"""Cursor and recount — extracted from PersonLifecycle (H-C4).

One named responsibility: cursor and recount ladder.
Keeps lifecycle orchestration, moves cursor logic here.

Design: AREA_C H-C4 — helper named by responsibility, ≤200 LOC.
"""

from __future__ import annotations

import json
import logging
from dataclasses import replace
from datetime import datetime

from stores.history_repo_identity import TAIL_FP_LIMIT
from stores.history_requests import WriteContext

log = logging.getLogger("chatbot")


def _sig_or(current: dict, key: str, value):
    return current.get(key, "") if value is None else value


class CursorLadder:
    def __init__(self, owner):
        self._owner = owner

    async def _last_ord(self, person_id: int) -> int:
        return int(await self._owner.db.scalar("SELECT MAX(ord) FROM messages WHERE person_id=?", (person_id,), 0))

    async def _resequence(self, person_id: int) -> None:
        rows = await self._owner.db.fetchall(
            "SELECT id FROM messages WHERE person_id=? ORDER BY day, ts_display, ord, id", (person_id,)
        )
        for index, row in enumerate(rows, start=1):
            await self._owner.db.execute("UPDATE messages SET ord=? WHERE id=?", (index, int(row[0])))
        await self._owner.db.commit()

    async def _recount(self, person_id: int, my_nick: str = "") -> None:
        row = await self._owner.db.fetchone(
            "SELECT COUNT(*) AS n, SUM(direction='in') AS ins, SUM(direction='out') AS outs, "
            "SUM(media_id IS NOT NULL) AS media, MIN(ts_resolved) AS first_ts, MAX(ts_resolved) AS last_ts, "
            "(SELECT MAX(ord) FROM messages WHERE person_id=?) AS last_ord FROM messages WHERE person_id=? AND deleted_at=''",
            (person_id, person_id),
        )
        person = await self._owner.get_person_by_id(person_id) or {}
        nicks = list(person.get("my_nicks") or [])
        clean = self._owner.normalise_nick(my_nick)
        if clean and clean not in nicks:
            nicks.append(clean)
        await self._owner.db.execute(
            "UPDATE persons SET message_count=?, in_count=?, out_count=?, media_count=?, last_ord=?, my_nicks=?, "
            "first_seen=COALESCE(?, first_seen), last_seen=COALESCE(?, last_seen) WHERE id=?",
            (
                int(row["n"] or 0),
                int(row["ins"] or 0),
                int(row["outs"] or 0),
                int(row["media"] or 0),
                int(row["last_ord"] or 0),
                json.dumps(nicks, ensure_ascii=False),
                row["first_ts"],
                row["last_ts"],
                person_id,
            ),
        )
        await self._owner.db.commit()

    async def _after_write(self, ctx: WriteContext) -> None:
        person_id = ctx.person_id
        await self._recount(person_id, ctx.my_nick)
        tail = [
            r
            for r in await self._owner.db.fetchall(
                "SELECT fp, dup_key FROM (SELECT fp, dup_key, ord FROM messages WHERE person_id=? ORDER BY ord DESC LIMIT ?) ORDER BY ord",
                (person_id, TAIL_FP_LIMIT),
            )
        ]
        tail_fps = [r[0] for r in tail]
        tail_keys = [r[1] for r in tail]
        current = await self._owner.get_cursor(person_id)
        flag = current["bootstrapped"] if ctx.bootstrapped is None else ctx.bootstrapped
        await self._owner.db.execute(
            "INSERT INTO cursors(person_id, last_ord, dom_count, head_sig, tail_sig, head_any, tail_any, tail_fps, tail_keys, bootstrapped, full_scan_complete, full_scan_at, updated_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,0,'',?) ON CONFLICT(person_id) DO UPDATE SET last_ord=excluded.last_ord, dom_count=excluded.dom_count, "
            "head_sig=excluded.head_sig, tail_sig=excluded.tail_sig, head_any=excluded.head_any, tail_any=excluded.tail_any, "
            "tail_fps=excluded.tail_fps, tail_keys=excluded.tail_keys, bootstrapped=excluded.bootstrapped, updated_at=excluded.updated_at",
            (
                person_id,
                await self._last_ord(person_id),
                ctx.dom_count or current.get("dom_count") or 0,
                _sig_or(current, "head_sig", ctx.head_sig),
                _sig_or(current, "tail_sig", ctx.tail_sig),
                _sig_or(current, "head_any", ctx.head_any),
                _sig_or(current, "tail_any", ctx.tail_any),
                json.dumps(tail_fps),
                json.dumps(tail_keys),
                1 if flag else 0,
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
        await self._owner.db.commit()

    async def _touch_cursor(self, ctx: WriteContext) -> None:
        if not ctx.dom_count and ctx.head_sig is None and ctx.tail_sig is None:
            return
        await self._after_write(replace(ctx, my_nick="", bootstrapped=None))
