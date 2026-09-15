"""Row projection — message and person rows → UI items.

Part of the `history_query` family (facade: `backend/history_query.py`,
Round H step H-B2b). This file owns the pure mapping from DB rows to the
shapes the frontend expects. No SQL, no branching on request text — only
field renames, defaults, and the media-vanished guard.

Design: docs/archive/2026-09-14-round-h/AREA_H_FINAL_VALIDATION_2026-09-14.md §6.1
"""

from __future__ import annotations

import json
import os
from typing import Optional

# output keys, source key, default, as_int — alias pairs share one source
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

_FIELD_SPECS_TAIL = (
    (("time", "ts_display"), "ts_display", "", False),
    (("ts_resolved",), "ts_resolved", "", False),
    (("day",), "day", "", False),
    (("occ",), "occ", 0, True),
)


def _apply_specs(data: dict, specs) -> dict:
    out = {}
    for keys, source, default, as_int in specs:
        value = data.get(source) or default
        for key in keys:
            out[key] = int(value) if as_int else value
    return out


def _item_media(data: dict) -> dict | None:
    if not data.get("media_id"):
        return None
    path = data.get("cache_path") or ""
    state = data.get("media_state") or "pending"
    if path and not os.path.exists(path):
        state = "missing"
        path = ""
    return {"id": data.get("media_id"), "url": data.get("media_url"),
            "kind": data.get("media_kind") or data.get("kind"),
            "state": state, "path": path}


def _stat_int(data: dict, key: str) -> int:
    return int(data.get(key) or 0)


def _my_nicks(row) -> list:
    try:
        return json.loads(dict(row).get("my_nicks") or "[]")
    except Exception:  # noqa: BLE001
        return []


async def _day_bounds(db, pid: int) -> tuple[str, str, int]:
    row = await db.fetchone(
        "SELECT MIN(day) AS first_day, MAX(day) AS last_day, "
        "COUNT(DISTINCT day) AS days FROM messages WHERE person_id=? "
        "AND deleted_at=''", (pid,))
    if not row:
        return "", "", 0
    return (row["first_day"] or ""), (row["last_day"] or ""), int(row["days"] or 0)


def _person_item(row, my_nicks: list) -> dict:
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
