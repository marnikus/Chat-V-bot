"""Typed private-chat gate — RULE 15 / I-13 (Area A extraction).

The public entry remains chat_parser.verify_private. Precedence is frozen:
not_private → no_partner → title_mismatch → self_chat → no_author_data →
strangers. No Qt, browser acquisition or database I/O occurs in this module.
Design: docs/archive/2026-09-19-area-a-integration/AREA_A_TRANSFER_2026-09-19.md.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from backend import chat_text
from backend.parser_requests import PrivateQuery
from backend.probe_results import PaneAuthors, TabState

_norm = chat_text.norm


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


_distinct = chat_text.distinct
_authors_from_items = chat_text.authors_from_items


def title_matches(title: str, nick: str) -> bool:
    """Step 2: does the active tab title name this person?"""
    want, have = _norm(nick), _norm(title)
    if not want or not have:
        return False
    return want in have


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
    def read(cls, state: TabState, nick: str, my_nick: str) -> "_GateNames":
        clean = chat_text.clean
        return cls(target=clean(nick),
                   partner=clean(state.partner),
                   title=state.title or state.partner,
                   me_cfg=clean(my_nick),
                   me_state=clean(state.me))

    @property
    def effective_me(self) -> str:
        # Preserve configured-nick precedence. Other checks also consider
        # the pane's current nick to accommodate a user rename.
        return self.me_cfg or self.me_state

    def refuse(self, reason: str, detail: str) -> "PrivateCheck":
        return PrivateCheck(False, reason, detail, self.me_cfg, self.partner)


def _is_self_chat(names: _GateNames) -> bool:
    """Writing to your own chat can look like a perfect conversation."""
    effective = names.effective_me
    return bool(effective and _norm(effective) == _norm(names.target)
                and (not names.me_state
                     or _norm(names.me_state) == _norm(names.target)))


def _split_authors(everyone, names: _GateNames) -> tuple:
    """Some pages report only one flat `authors` list — guess the sides."""
    effective = _norm(names.effective_me)
    inbound_exclusion = effective or _norm(names.target)
    ins = [a for a in everyone if _norm(a) != inbound_exclusion]
    outs = [a for a in everyone if _norm(a) == effective]
    return ins, outs


def _authors_of(authors: PaneAuthors, items,
                names: _GateNames) -> Optional[tuple]:
    """Author evidence from pushed items, split lists, or a flat report."""
    if items is not None:
        return _authors_from_items(items)
    if not authors.reported:
        return None
    if authors.split:
        return list(authors.inbound), list(authors.outbound)
    return _split_authors(authors.everyone, names)


def _foreign_authors(outs, names: _GateNames) -> tuple:
    """Who wrote outbound lines that is neither me nor my partner.

    "Me" is often undetectable — the page does not always label my own
    messages — so a single outbound author is taken to be me (that is the
    `me` the caller reports back); more than one, and we cannot tell, so all
    of them count as strangers.
    """
    me = names.me_cfg or names.me_state or (outs[0] if len(outs) == 1 else "")
    if me:
        known = {_norm(me), _norm(names.me_state), _norm(names.target)}
        return me, [a for a in outs if _norm(a) not in known]
    return me, list(outs) if len(outs) > 1 else []


def judge_private(state: TabState, nick: str, my_nick: str = "",
                   query: PrivateQuery = PrivateQuery()) -> PrivateCheck:
    """The gate. `ok` is False unless BOTH steps pass.

    RULE 15: this is the only place the private-chat decision is made, and it
    runs before a single record is written. Each guard keeps its own reason
    code because the run panel shows them to the user verbatim.
    """
    names = _GateNames.read(state, nick, my_nick)
    # The guard ORDER is part of the contract: the run panel shows whichever
    # reason fired first, so not_private → no_partner → title → self_chat →
    # authors must stay in that sequence.
    refusal = _tab_gate(state, names, query.require_private)
    if refusal is not None:
        return refusal
    refusal = _partner_gate(names)
    if refusal is not None:
        return refusal
    refusal = _title_gate(names)
    if refusal is not None:
        return refusal

    # ── step 1: exactly two nicks ─────────────────────────────────
    authors = _authors_of(state.authors, query.items, names)
    if authors is None:
        return names.refuse("no_author_data",
                            "this page cannot tell me who wrote what")
    return _strangers_verdict(authors, names)


def _tab_gate(state: TabState, names, require_private: bool):
    """The tab-is-private guard; None when the tab passes it."""
    if require_private and state.tab != "private":
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


# Preserve the historical public/serialization home, not just import aliases.
# Old pickles and API inspection resolve these names through chat_parser.
PrivateCheck.__module__ = "backend.chat_parser"
title_matches.__module__ = "backend.chat_parser"
