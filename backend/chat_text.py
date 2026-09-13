"""The tiny text helpers the conversation reader shares.

A leaf module on purpose: `backend.chat_parser` (the probes + the private-chat
gate) and `backend.chat_sync` (the sync algorithm) both need these, and one
must not import the other at module level. Keeping them here instead of
duplicating them is what lets `chat_parser` re-export the same functions it
always did — `_signature`, `_norm`, `_payload`, … stay importable from
`backend.chat_parser`, so no caller has to change.

Nothing here touches CDP, the database or Qt: pure, total functions that never
raise on hostile page input (the page can answer with anything).
"""

from __future__ import annotations

import json
from typing import Any, Iterable, Optional


def clean(value: Any) -> str:
    """Collapse whitespace and strip — how a nick is compared everywhere."""
    return " ".join(str(value or "").split()).strip()


def signature(value) -> str:
    """Flatten a probe field (list of fingerprints, or a scalar) to the
    string the cursor stores.

    `str(value or "")` deliberately collapses every falsy scalar — including
    `0` and `""` — to the empty string, which reads as "no signature stored",
    i.e. "read again next tick". That is the safe direction: a missing
    signature costs one extra read, a wrong one loses messages.
    """
    if isinstance(value, (list, tuple)):
        return "|".join(str(v) for v in value)
    return str(value or "")


def norm(nick: Any) -> str:
    """Case/whitespace-insensitive nick comparison (site nicks are sloppy)."""
    return clean(nick).lower()


def distinct(names: Optional[Iterable]) -> list:
    """De-duplicate while keeping page order; drop blanks."""
    out: list[str] = []
    for name in names or []:
        value = clean(name)
        if value and value not in out:
            out.append(value)
    return out


def authors_from_items(items) -> tuple:
    """Split a batch of records into (inbound nicks, outbound nicks).

    Accepts `MessageRecord`s and the agent's raw dicts — the gate runs on
    whichever shape the caller has to hand.
    """
    ins, outs = [], []
    for item in items or []:
        pair = _direction_and_nick(item)
        if pair is None:
            continue
        direction, nick = pair
        (outs if direction == "out" else ins).append(nick)
    return distinct(ins), distinct(outs)


def _direction_and_nick(item):
    """(direction, nick) for one record, or None if it is neither shape.

    Dicts carry two spellings of each field because the in-page agent and the
    stored model disagree; `dir`/`from` is the agent's, `direction`/`from_nick`
    the model's. Direction defaults to "in" — an unmarked message is inbound.
    """
    from stores.history_models import MessageRecord      # local: avoid an
    if isinstance(item, MessageRecord):                  # import cycle risk
        return item.direction, item.from_nick
    if isinstance(item, dict):
        return (item.get("dir") or item.get("direction") or "in",
                item.get("from") or item.get("from_nick") or "")
    return None


def payload(result) -> list:
    """Agent probes answer with a bare list or a `{ok, items}` envelope.

    Unwrapping is total: a string is parsed, a non-list `items` and anything
    else yields `[]`. (Iterating the envelope dict used to yield its KEYS and
    silently drop every record — see
    docs/archive/2026-09-07-labels-and-collector/MESSAGE_HISTORY_BUGS_DESIGN_2026-09-07.md.)
    """
    if result is None:
        return []
    if isinstance(result, str):
        try:
            result = json.loads(result)
        except (TypeError, ValueError):
            return []
    if isinstance(result, dict):
        items = result.get("items")
        return list(items) if isinstance(items, (list, tuple)) else []
    if isinstance(result, list):
        return result
    return []


def as_dict(value) -> dict:
    """A probe answer is JSON text, a dict, or garbage — the caller always
    gets a dict (and never an exception)."""
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            return {}
    return value if isinstance(value, dict) else {}
