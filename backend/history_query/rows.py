"""One database row → one UI item.

Owns the row-shaping helpers: the person item for the Full User Database, the
field-spec tables that fix key order and defaults, the media sub-object, and
the day-bounds probe. Pure except `_day_bounds`, which takes the db it reads.
"""

from __future__ import annotations

import os

def _person_item(row, my_nicks: list) -> dict:
    """

from __future__ import annotations
One person row, as the Full User Database shows it.

    A module function rather than a method: the mapping is a pure projection
    of one row, and `HistoryQuery` is already over its size budget.
    """
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
_FIELD_SPECS = (
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
_FIELD_SPECS_TAIL = (
    (("time", "ts_display"), "ts_display", "", False),
    (("ts_resolved",), "ts_resolved", "", False),
    (("day",), "day", "", False),
    (("occ",), "occ", 0, True),
)


def _apply_specs(data: dict, specs) -> dict:
    """One group of the UI item, coalesced and aliased per a field spec."""
    out = {}
    for keys, source, default, as_int in specs:
        value = data.get(source) or default
        for key in keys:
            out[key] = int(value) if as_int else value
    return out


def _item_media(data: dict) -> dict | None:
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


def _stat_int(data: dict, key: str) -> int:
    """One counter of a person row, tolerating NULL/absent."""
    return int(data.get(key) or 0)


async def _day_bounds(db, pid: int) -> tuple[str, str, int]:
    """(first_day, last_day, distinct days) over the visible messages.

    Module-level on purpose: `HistoryQuery` is already at the RULE 16
    method cap (enforced by tests/test_rule16_new_code.py through
    tools/metrics/rule16_gate.py), and this is a pure read over a db
    handle — it needs nothing from the instance.
    """
    row = await db.fetchone(
        "SELECT MIN(day) AS first_day, MAX(day) AS last_day, "
        "COUNT(DISTINCT day) AS days FROM messages WHERE person_id=? "
        "AND deleted_at=''", (pid,))
    if not row:
        return "", "", 0
    return (row["first_day"] or ""), (row["last_day"] or ""), int(row["days"] or 0)
