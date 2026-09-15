"""The two-step private-chat gate — the decision machinery.

Part of the `chat_parser` family (public entry point: `backend/chat_parser.py`,
Round J step J-7). The gate itself is a RULE 15 decision made before a single
record is written, and it has two steps (bug report of 2026-09-07):

STEP 1  the conversation must contain exactly two nicks: mine and the
        partner's. A third author means this is not a private chat.
STEP 2  the ACTIVE tab title must name that same partner.

What lives here is everything the verdict is computed from: the normalised
nick table (`_GateNames`), the author splitting (`_split_authors`,
`_authors_of`, `_foreign_authors`), the three ordered guards (`_tab_gate`,
`_partner_gate`, `_title_gate`) and the verdict (`_strangers_verdict`). What
stays in `backend/chat_parser.py` is the public half — `PrivateCheck`,
`title_matches` and `verify_private`, whose guard ORDER is part of the contract
because the run panel shows whichever reason fired first. The API snapshot pins
those three to that module, so this split moves the machinery and not the
public names.

`_check()` is the one seam that has to look back: `PrivateCheck` is defined in
`backend/chat_parser.py` (the snapshot's definition-site rule), and that module
imports this one, so the verdict object is built through a function-local
import. It is a sys.modules lookup by the time any gate runs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from backend import chat_text

#: the three text helpers this module normalises with — the same functions
#: `backend.chat_parser` re-exports, imported here so the gate does not have to
#: reach back for them.
_norm = chat_text.norm
_distinct = chat_text.distinct
_authors_from_items = chat_text.authors_from_items


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
        return _check(False, reason, detail, self.me_cfg, self.partner)


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
    # `title_matches` is a public symbol of backend.chat_parser — the API
    # snapshot records definition sites, not re-exports — so it is imported
    # here for the same reason `_check` imports `PrivateCheck` locally.
    from backend.chat_parser import title_matches

    # ── step 2: the tab title ─────────────────────────────────────
    if not title_matches(names.title, names.target):
        return names.refuse(
            "title_mismatch",
            f"the active tab is “{chat_text.clean(names.title)}”, "
            f"not “{names.target}”")
    if _is_self_chat(names):
        return names.refuse("self_chat", "the partner is my own nick")
    return None


def _strangers_verdict(authors, names):
    """Who else writes here: ok when only the two of us do."""
    ins, outs = authors
    me, foreign = _foreign_authors(outs, names)
    strangers = _distinct([a for a in ins
                           if _norm(a) != _norm(names.target)] + foreign)
    if not strangers:
        return _check(True, "ok", "", me, names.partner)
    shown = ", ".join(strangers[:3]) + ("…" if len(strangers) > 3 else "")
    return _check(False, "strangers",
                  f"other people write here: {shown}",
                  me, names.partner, strangers)

def _check(ok: bool, reason: str, detail: str, me: str, partner: str,
           strangers: Optional[list] = None):
    """Build the verdict object.

    `PrivateCheck` is a public symbol of `backend/chat_parser` — the API
    snapshot records definition sites, not re-exports — and that module
    imports this one, so the import is local on purpose.
    """
    from backend.chat_parser import PrivateCheck
    return PrivateCheck(ok, reason, detail, me, partner, strangers or [])
