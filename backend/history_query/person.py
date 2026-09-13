"""Person-row and message-item projections for the read path.

The module functions here map one database row to the UI shape — they are
deliberately NOT methods, because `HistoryQuery` is already over its size
budget and these mappings are pure projections.
"""

import os


def _person_item(row, my_nicks: list) -> dict:
    """One person row, as the Full User Database shows it.

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


#: (output keys, row column, default, as_int) — the message-row → UI-item
#: field map. Alias pairs share one source (`dir`/`direction`,
#: `from`/`from_nick`, `time`/`ts_display`) so the legacy and current
#: spellings can never disagree. The spec rows are in exact output order:
#: the UI contract pins both key set and order (backend_api_snapshot.json).
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
#: the fields that follow the `media` block in the output dict
_FIELD_SPECS_TAIL = (
    (("time", "ts_display"), "ts_display", "", False),
    (("ts_resolved",), "ts_resolved", "", False),
    (("day",), "day", "", False),
    (("occ",), "occ", 0, True),
)


def _apply_specs(data: dict, specs) -> dict:
    """One ordered group of the UI item: coalesce-empty + int casts."""
    out = {}
    for keys, source, default, as_int in specs:
        value = data.get(source) or default
        for key in keys:
            out[key] = int(value) if as_int else value
    return out


def _stat_int(data: dict, key: str) -> int:
    return int(data.get(key) or 0)


async def _day_bounds(db, pid: int) -> tuple[str, str, int]:
    """(first_day, last_day, distinct days) over visible messages."""
    row = await db.fetchone(
        "SELECT MIN(day) AS first_day, MAX(day) AS last_day, "
        "COUNT(DISTINCT day) AS days FROM messages WHERE person_id=? "
        "AND deleted_at=''", (pid,))
    if not row:
        return "", "", 0
    return (row["first_day"] or "", row["last_day"] or "",
            int(row["days"] or 0))


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
            "state": state,
            "path": path}
