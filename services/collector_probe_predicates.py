"""Collector probe predicates — extracted from collector_probe (H-C5 split)

≤100 LOC.
"""

from __future__ import annotations


def _is_state_ok(state: dict) -> bool:
    return bool(state.get("ok", True))


def _is_private_tab(state: dict) -> bool:
    return state.get("tab") == "private"


def _has_partner_nick(nick: str) -> bool:
    return bool(nick)


def _is_group_tab(participants: int, require_two: bool) -> bool:
    return require_two and participants > 0 and participants != 2


def _is_single_out_author(outs: list, nick: str) -> bool:
    singles = [o for o in outs if o]
    return len(singles) == 1 and singles[0].lower() != nick.lower()


def _is_saved_nick_stale(saved: str, detected: str, outs: list) -> bool:
    if not saved or not detected:
        return False
    if detected.lower() == saved.lower():
        return False
    return saved.lower() not in {o.lower() for o in outs if o}
