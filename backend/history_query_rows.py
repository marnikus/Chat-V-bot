"""Row → payload projection for the archive read path.

Part of the `history_*` read family (facade: `backend/history_query.py`,
Round J step J-2). Everything here takes a database row — or a small bundle
of them — and returns the exact JSON shape the two windows render:

* `person_item` / `apply_specs` — the Full User Database's row → item map,
  including the alias pairs (``dir``/``direction``, ``from``/``from_nick``)
  that the UI contract pins, and the media block;
* `item` — one message row as the history window's item, key order intact;
* `item_media` — the joined media block, with the "cached row whose file
  vanished reports itself missing rather than rendering a dead path" rule;
* `stat_int` / `day_bounds` — the header counters;
* `clamp`, `my_nicks`, `person_row` — the three small helpers the facade's
  own query methods share.

Why a module and not methods: these are pure functions over data (one of
them, `day_bounds`, over a db handle), the facade is at the wire/query
surface, and the projection is exactly the part mutation testing found
under-tested once — `tests/test_person_item.py` pinned it key by key, and it
moves with the functions (Round H Area B design §2b).
"""

from __future__ import annotations

import json
import os
from typing import Optional

DEFAULT_LIMIT = 50
MAX_LIMIT = 500


def clamp(limit: Optional[int]) -> int:
    """A page limit inside `1 … MAX_LIMIT`, with the default for garbage.

    `None`, a string and a negative all have a defined answer here because
    the value arrives from a JSON payload a human may have edited.
    """
    try:
        value = int(limit or DEFAULT_LIMIT)
    except (TypeError, ValueError):
        value = DEFAULT_LIMIT
    return max(1, min(MAX_LIMIT, value))


def my_nicks(row) -> list:
    """The stored identity list of a person row, defensively.

    `my_nicks` is `TEXT NOT NULL DEFAULT '[]'`, so a falsy value means a
    hand-emptied string or a row that never carried the column; both read as
    "no identities" rather than raising. The ``or "[]"`` spelling is pinned
    as an *equivalent mutant* by `tests/test_history_query_gaps.py` — see the
    argument there before "simplifying" it.
    """
    try:
        return json.loads(dict(row).get("my_nicks") or "[]")
    except Exception:                                 # noqa: BLE001
        return []


async def person_row(db, nick: str):
    """The `persons` row for a nick, whitespace-collapsed, or None."""
    return await db.fetchone(
        "SELECT * FROM persons WHERE nick=?",
        (" ".join(str(nick or "").split()).strip(),))


def person_item(row, my_nicks: list) -> dict:
    """One person row, as the Full User Database shows it."""
    data = dict(row)
    return {
        "id": int(data["id"]),
        "nick": data["nick"],
        "message_count": int(data.get("message_count") or 0),
        "in_count": int(data.get("in_count") or 0),
        "out_count": int(data.get("out_count") or 0),
        "media_count": int(data.get("media_count") or 0),
        "first_seen": data.get("first_seen") or "",
        "last_seen": data.get("last_seen") or "",
        "my_nicks": my_nicks,
        "deleted": bool(data.get("deleted_at")),
    }


#: (output keys, source key, default, as_int) — the row→UI-item field map.
#: Alias pairs share one source so the legacy and current spellings can never
#: disagree (UI contract; see backend_api_snapshot.json).
FIELD_SPECS = (
    (("id",), "id", 0, True),
    (("ord",), "ord", 0, True),
    (("fp",), "fp", "", False),
    (("dir", "direction"), "direction", "in", False),
    (("from", "from_nick"), "from_nick", "", False),
    (("my_nick",), "my_nick", "", False),
    (("kind",), "kind", "text", False),
    (("text",), "text", "", False),
)
#: The fields after `media`, which the UI contract places between `text` and
#: `time` — two tables so that position survives the loop.
FIELD_SPECS_TAIL = (
    (("time", "ts_display"), "ts_display", "", False),
    (("ts_resolved",), "ts_resolved", "", False),
    (("day",), "day", "", False),
    (("occ",), "occ", 0, True),
)


def apply_specs(data: dict, specs) -> dict:
    """One group of the UI item, coalesced and aliased per a field spec."""
    out = {}
    for keys, source, default, as_int in specs:
        value = data.get(source) or default
        for key in keys:
            out[key] = int(value) if as_int else value
    return out


def item_media(data: dict) -> dict | None:
    """The joined media block for one message row, or None."""
    if not data.get("media_id"):
        return None
    path = data.get("cache_path") or ""
    state = data.get("media_state") or "pending"
    # A cached row whose file vanished must not render as a broken
    # <img> from a dead local path: report it as missing so the UI
    # shows a "click to restore" marker instead.
    if path and not os.path.exists(path):
        state = "missing"
        path = ""
    return {"id": data.get("media_id"), "url": data.get("media_url"),
            "kind": data.get("media_kind") or data.get("kind"),
            "state": state, "path": path}


def item(row) -> dict:
    """One archive row as the UI item, key order and defaults intact."""
    data = dict(row)
    out = apply_specs(data, FIELD_SPECS)
    out["media"] = item_media(data)
    out.update(apply_specs(data, FIELD_SPECS_TAIL))
    return out


def stat_int(data: dict, key: str) -> int:
    """One counter of a person row, tolerating NULL/absent."""
    return int(data.get(key) or 0)


async def day_bounds(db, pid: int) -> tuple[str, str, int]:
    """(first_day, last_day, distinct days) over the visible messages."""
    row = await db.fetchone(
        "SELECT MIN(day) AS first_day, MAX(day) AS last_day, "
        "COUNT(DISTINCT day) AS days FROM messages WHERE person_id=? "
        "AND deleted_at=''", (pid,))
    if not row:
        return "", "", 0
    return ((row["first_day"] or ""), (row["last_day"] or ""),
            int(row["days"] or 0))
