"""Helpers for LabelAssignments — predicates and id allocation.

Part of label_assignments family (H-C5 MI lift). Pure functions, no owner
access, ≤150 LOC.
"""

from __future__ import annotations

from stores.label_rules import normalize_id, normalize_name, normalize_nick


def is_valid_name(name: str) -> bool:
    return bool(normalize_name(name))


def is_valid_nick(nick: str) -> bool:
    return bool(normalize_nick(nick))


def is_valid_id(label_id: str) -> bool:
    return bool(normalize_id(label_id))


def is_unique_name(defs: list[dict], name: str, exclude: dict | None = None) -> bool:
    clean = normalize_name(name).casefold()
    if not clean:
        return False
    return not any(d is not exclude and d["name"].casefold() == clean for d in defs)


def is_known_label(defs: list[dict], label_id: str) -> bool:
    wanted = normalize_id(label_id)
    return any(d["id"] == wanted for d in defs)


def is_assigned(current: list[str], wanted: str) -> bool:
    return wanted in current


def is_same_assignment(current: list[str], kept: list[str]) -> bool:
    return kept == current


def has_assignments(assign: dict, nick: str) -> bool:
    return nick in assign


def is_dict_snapshot(snapshot) -> bool:
    return isinstance(snapshot, dict)


def coerce_next_id(snapshot) -> int:
    try:
        return int(snapshot.get("next_id") or 0)
    except (TypeError, ValueError):
        return 0


def next_label_id(defs: list[dict], next_id: int) -> tuple[str, int]:
    used = {d["id"] for d in defs}
    candidate_id = max(next_id, len(defs))
    while True:
        candidate_id += 1
        candidate = f"lbl_{candidate_id}"
        if candidate not in used:
            return candidate, candidate_id


def unassign(data: dict, wanted: str) -> None:
    for nick in list(data["assign"]):
        kept = [i for i in data["assign"][nick] if i != wanted]
        if kept:
            data["assign"][nick] = kept
        else:
            data["assign"].pop(nick, None)


def unfilter(data: dict, wanted: str) -> None:
    data["filter"]["include"] = [i for i in data["filter"]["include"] if i != wanted]
    data["filter"]["exclude"] = [i for i in data["filter"]["exclude"] if i != wanted]
