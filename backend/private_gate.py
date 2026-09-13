"""The two-step private-chat gate (bug report of 2026-09-07).

Split out of backend/chat_parser.py in Round H (step H5). chat_parser.py was
441 lines doing two unrelated jobs: driving the page (ChatParser, scrolling,
settling, sync_conversation) and DECIDING whether what was read may be saved.
This module is the decision, and it touches no page and no repo — it is pure
functions over already-extracted nicks and titles, which is why it tests and
reads independently.

STEP 1  the conversation must contain exactly two nicks: mine and the
        partner's. A third author means this is not a private chat.
STEP 2  the ACTIVE tab title must name that same partner.

Both must pass before a single line may be written to that person's history.
Everything that saves goes through `verify_private()`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

from backend import chat_text

log = logging.getLogger("chatbot")

_norm = chat_text.norm
_distinct = chat_text.distinct
_authors_from_items = chat_text.authors_from_items


@dataclass
class PrivateCheck:
    ok: bool = True
    reason: str = "ok"          # ok|not_private|no_partner|title_mismatch|
    #                             self_chat|strangers|no_author_data
    detail: str = ""            # human text for the status window
    me: str = ""                # my nick, detected when it was not configured
    partner: str = ""           # the nick the page says we are talking to
    strangers: list = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.ok)


def title_matches(title: str, nick: str) -> bool:
    """Step 2: does the active tab title name this person?"""
    want, have = _norm(nick), _norm(title)
    if not want or not have:
        return False
    return have == want or want in have


@dataclass(frozen=True)
class _GateNames:
    """The five nicks the gate compares, each normalised exactly once.

    The page hands these over in whatever shape its DOM had them — padded,
    doubled spaces, non-strings — and every comparison below (and every
    message shown to the user) must use the same collapse, or a nick that
    reads fine to a human refuses its own chat.
    """

    target: str = ""          # the person we think we are collecting
    partner: str = ""         # the nick the page says we are talking to
    title: str = ""           # the raw ACTIVE TAB title
    me_cfg: str = ""          # My Nick from the settings
    me_state: str = ""        # the pane's own user list

    @classmethod
    def read(cls, state: dict, nick: str, my_nick: str) -> "_GateNames":
        clean = chat_text.clean
        return cls(target=clean(nick),
                   partner=clean(state.get("partner")),
                   title=str(state.get("title") or state.get("partner") or ""),
                   me_cfg=clean(my_nick),
                   me_state=clean(state.get("me")))

    @property
    def effective_me(self) -> str:
        # the pane's own user list is the authoritative "me": a configured My
        # Nick can go stale when the user renames themselves on the site, and
        # the stale value must not make this gate refuse the chat (2026-09-08)
        return self.me_cfg or self.me_state

    def refuse(self, reason: str, detail: str) -> "PrivateCheck":
        return PrivateCheck(False, reason, detail, self.me_cfg, self.partner)


def _is_self_chat(names: _GateNames) -> bool:
    """Writing to your own chat can look like a perfect conversation."""
    effective = names.effective_me
    return bool(effective and _norm(effective) == _norm(names.target)
                and (not names.me_state
                     or _norm(names.me_state) == _norm(names.target)))


def _split_authors(state: dict, names: _GateNames) -> tuple:
    """Some pages report only one flat `authors` list — guess the sides."""
    everyone = _distinct(state.get("authors"))
    ins = [a for a in everyone
           if _norm(a) != _norm(names.effective_me or names.target)]
    outs = [a for a in everyone if _norm(a) == _norm(names.effective_me)]
    return ins, outs


def _authors_of(state: dict, items, names: _GateNames) -> Optional[tuple]:
    """Step 1's raw material: (inbound, outbound) authors, or None when the
    page cannot tell who wrote what."""
    if items is not None:
        return _authors_from_items(items)
    if not ("in_authors" in state or "out_authors" in state
            or "authors" in state):
        return None
    ins = _distinct(state.get("in_authors"))
    outs = _distinct(state.get("out_authors"))
    return (ins, outs) if (ins or outs) else _split_authors(state, names)


def _foreign_authors(outs, names: _GateNames) -> tuple:
    """Who wrote outbound lines that is neither me nor my partner.

    "Me" is often undetectable — the page does not always label my own
    messages — so a single outbound author is taken to be me (that is the
    `me` the caller reports back); more than one, and we cannot tell, so all
    of them count as strangers.
    """
    me = names.me_cfg or names.me_state or (outs[0] if len(outs) == 1 else "")
    if me:
        return me, [a for a in outs
                    if _norm(a) != _norm(me)
                    and _norm(a) != _norm(names.me_state)
                    and _norm(a) != _norm(names.target)]
    return me, list(outs) if len(outs) > 1 else []


def verify_private(state: dict, nick: str, my_nick: str = "",
                   items=None, require_private: bool = True) -> PrivateCheck:
    """The gate. `ok` is False unless BOTH steps pass.

    RULE 15: this is the only place the private-chat decision is made, and it
    runs before a single record is written. Each guard keeps its own reason
    code because the run panel shows them to the user verbatim.
    """
    state = state if isinstance(state, dict) else {}
    names = _GateNames.read(state, nick, my_nick)
    # The guard ORDER is part of the contract: the run panel shows whichever
    # reason fired first, so not_private → no_partner → title → self_chat →
    # authors must stay in that sequence.
    refusal = _tab_gate(state, names, require_private)
    if refusal is not None:
        return refusal
    refusal = _partner_gate(names)
    if refusal is not None:
        return refusal
    refusal = _title_gate(names)
    if refusal is not None:
        return refusal

    # ── step 1: exactly two nicks ─────────────────────────────────
    authors = _authors_of(state, items, names)
    if authors is None:
        return names.refuse("no_author_data",
                            "this page cannot tell me who wrote what")
    return _strangers_verdict(authors, names)


def _tab_gate(state: dict, names, require_private: bool):
    """The tab-is-private guard; None when the tab passes it."""
    if require_private and str(state.get("tab") or "") != "private":
        return names.refuse("not_private",
                            "the active tab is not a private chat")
    return None


def _partner_gate(names):
    """The tab-names-a-person guard; None when a partner is present."""
    if not names.target or not names.partner:
        return names.refuse("no_partner",
                            "the active tab does not name a person")
    return None


def _title_gate(names):
    """The tab-title guard and the self-chat guard, in their pinned order."""
    # ── step 2: the tab title ─────────────────────────────────────
    if not title_matches(names.title, names.target):
        return names.refuse(
            "title_mismatch",
            f"the active tab is “{chat_text.clean(names.title)}”, "
            f"not “{names.target}”")
    if _is_self_chat(names):
        return names.refuse("self_chat", "the partner is my own nick")
    return None


def _strangers_verdict(authors, names) -> PrivateCheck:
    """Who else writes here: ok when only the two of us do."""
    ins, outs = authors
    me, foreign = _foreign_authors(outs, names)
    strangers = _distinct([a for a in ins
                           if _norm(a) != _norm(names.target)] + foreign)
    if not strangers:
        return PrivateCheck(True, "ok", "", me, names.partner, [])
    shown = ", ".join(strangers[:3]) + ("…" if len(strangers) > 3 else "")
    return PrivateCheck(False, "strangers",
                        f"other people write here: {shown}",
                        me, names.partner, strangers)
