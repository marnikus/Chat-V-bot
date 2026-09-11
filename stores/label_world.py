"""LabelWorldSync — moving the payload between memory and the world's tables.

Extracted from `stores/label_store.py` by the AREA B2 split (design §2.5).
One world = one database: loading another file must swap the labels, the
assignments and the filter together, and a mutation made while a panel is open
has to reach the `labels` / `label_assigns` tables through the Qt loop the
bridge handed us. That scheduling dance — `scheduler(coro)`, the re-entrant
guard, the flush on a world switch — is the whole of this file.
    """

from __future__ import annotations

import logging

import asyncio
import json
from datetime import datetime

from stores.label_rules import DEFAULT_COLOR, FILTER_KEY

log = logging.getLogger("chatbot")


def _defs_from_rows(rows) -> list[dict]:
    """Label defs straight from the `labels` table, in row order."""
    return [{"id": str(r["id"]), "name": str(r["name"] or ""),
             "color": str(r["color"] or DEFAULT_COLOR),
             "created_at": str(r["created_at"] or "")} for r in rows]


def _assign_from_pairs(pairs, known: set) -> dict[str, list[str]]:
    """Nick → label ids from `label_assigns`; unknown ids dropped."""
    assign: dict[str, list[str]] = {}
    for nick, label_id in pairs:
        if label_id in known:
            assign.setdefault(str(nick), []).append(str(label_id))
    return assign


def _filter_from_raw(raw_filter) -> dict:
    """The include/exclude filter from its stored JSON (corrupt → empty)."""
    filter_state = {"include": [], "exclude": []}
    if not raw_filter:
        return filter_state
    try:
        data = json.loads(str(raw_filter))
    except (TypeError, ValueError):
        return filter_state
    if isinstance(data, dict):
        filter_state = {"include": [str(i) for i in
                                    data.get("include") or []],
                        "exclude": [str(i) for i in
                                    data.get("exclude") or []]}
    return filter_state


async def _next_id_from_db(db) -> int:
    """labels_next_id from schema_meta; corrupt meta must not brick the load."""
    try:
        return int(await db.scalar(
            "SELECT value FROM schema_meta WHERE key='labels_next_id'",
            (), 0))
    except (TypeError, ValueError):
        return 0


class LabelWorldSync:
    """Writes the dirty payload through to whichever `HistoryDB` is bound.

    The bound database is read off the aggregate at call time, so a world
    switch can never leave this object writing to the previous file.
"""

    def __init__(self, owner) -> None:
        self._owner = owner

    def set_scheduler(self, scheduler) -> None:
        self._owner._scheduler = scheduler

    async def load_from_db(self, db) -> dict:
        """Read one world's labels out of `db` into memory (the switch path)."""
        self._owner._db = db
        self._owner._dirty = False
        rows = await db.fetchdicts("SELECT id, name, color, created_at "
                                   "FROM labels ORDER BY rowid")
        defs = _defs_from_rows(rows)
        known = {d["id"] for d in defs}
        pairs = await db.fetchall("SELECT nick, label_id FROM label_assigns "
                                  "ORDER BY rowid")
        raw_filter = await db.scalar(
            "SELECT value FROM app_settings WHERE key=?", (FILTER_KEY,), "")
        self._owner._memory = {
            "defs": defs,
            "assign": _assign_from_pairs(pairs, known),
            "filter": _filter_from_raw(raw_filter),
            "next_id": await _next_id_from_db(db),
        }
        return self._owner._normalized()

    async def flush_to_db(self) -> None:
        """Write the dirty in-memory state into the bound world's tables."""
        if self._owner._db is None or not self._owner._dirty:
            return
        db = self._owner._db
        data = self._owner._normalized()
        stamp = datetime.now().isoformat(timespec="seconds")
        await db.execute("DELETE FROM labels")
        for label in data["defs"]:
            await db.execute(
                "INSERT INTO labels(id, name, color, created_at) "
                "VALUES(?,?,?,?)",
                (label["id"], label["name"], label["color"],
                 label["created_at"]))
        await db.execute("DELETE FROM label_assigns")
        for nick, ids in data["assign"].items():
            for label_id in ids:
                await db.execute(
                    "INSERT OR IGNORE INTO label_assigns(nick, label_id) "
                    "VALUES(?,?)", (nick, label_id))
        await db.execute(
            "INSERT INTO app_settings(key, value, updated_at) VALUES(?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, "
            "updated_at=excluded.updated_at",
            (FILTER_KEY, json.dumps(data["filter"]), stamp))
        await db.execute(
            "INSERT INTO schema_meta(key, value) VALUES('labels_next_id',?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (str(int(data["next_id"])),))
        await db.commit()
        self._owner._dirty = False

    def _schedule_flush(self) -> None:
        if self._owner._db is None:
            return
        self._owner._dirty = True
        if self._owner._scheduler is None:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return                          # flushed on switch/close instead
        # the scheduler (the bridge) starts the coroutine on the live loop
        try:
            self._owner._scheduler(self._guarded_flush())
        except Exception as exc:            # noqa: BLE001
            log.warning("cannot schedule label flush: %s", exc)

    async def _guarded_flush(self) -> None:
        try:
            await self.flush_to_db()
        except Exception as exc:            # noqa: BLE001
            log.warning("label write-through failed: %s", exc)
