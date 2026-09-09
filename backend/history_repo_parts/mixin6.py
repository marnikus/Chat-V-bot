"""History repo part 6 (<150)."""
import asyncio, json, logging, re
from datetime import datetime
from typing import Optional, Iterable, Sequence

class HistoryRepoMixin6:
    async def _all_person_keys(self, person_id: int) -> set:
        rows = await self.db.fetchall(
            "SELECT dup_key FROM messages WHERE person_id=? AND dup_key<>''",
            (person_id,))
        return {r[0] for r in rows}

    async def has_repairable_media(self, person_id: int,
                                   include_failed: bool = False,
                                   rescan_after_s: int = 600) -> bool:
        """Cheap heartbeat check: is there any media row worth a repair pass?

        ``include_failed`` is True only for the manual backfill (a known-bad
        download gets another chance there, not on every tick). A row the DOM
        could not supply a URL for is skipped for `rescan_after_s` seconds so
        a permanently unrepairable line (e.g. a deleted message) cannot make
        every heartbeat re-read the newest window. The manual backfill
        deliberately ignores that grace period: the top pass of the very
        same sync may have marked a row "scanned, not found" while the row's
        DOM record only returns after the viewport is restored.
        """
        if include_failed:
            clause = ("(media_id IS NULL AND (kind IN ('image','gif') "
                      "OR text='')) OR media_id IN "
                      "(SELECT id FROM media WHERE state IN "
                      "('failed','skipped'))")
            return bool(await self.db.scalar(
                f"SELECT COUNT(*) FROM messages WHERE person_id=? "
                f"AND deleted_at='' AND ({clause})", (person_id,), 0))
        cutoff = (datetime.now() -
                  timedelta(seconds=max(60, int(rescan_after_s)))
                  ).isoformat(timespec="seconds")
        clause = ("(media_id IS NULL AND (kind IN ('image','gif') "
                  "OR text='') AND (media_scan_at='' OR media_scan_at<?))")
        return bool(await self.db.scalar(
            f"SELECT COUNT(*) FROM messages WHERE person_id=? AND "
            f"deleted_at='' AND ({clause})",
            (person_id, cutoff), 0))


    async def _touch_cursor(self, person_id: int, dom_count: int,
                            head_sig: Optional[str],
                            tail_sig: Optional[str],
                            head_any: Optional[str] = None,
                            tail_any: Optional[str] = None) -> None:
        if not dom_count and head_sig is None and tail_sig is None:
            return
        await self._after_write(person_id, "", dom_count, head_sig, tail_sig,
                                bootstrapped=None, head_any=head_any,
                                tail_any=tail_any)

    async def _after_write(self, person_id: int, my_nick: str, dom_count: int,
                           head_sig: Optional[str], tail_sig: Optional[str],
                           bootstrapped: Optional[bool],
                           head_any: Optional[str] = None,
                           tail_any: Optional[str] = None) -> None:
        """Refresh counters and the resume cursor.

        `head_sig` / `tail_sig` (and their author-agnostic twins) of None
        mean "leave as is"; an empty string deliberately CLEARS the
        signature, which is how an interrupted read tells the next pass that
        it may not trust the shortcut.
        """
        await self._recount(person_id, my_nick)
        tail = [r for r in await self.db.fetchall(
            "SELECT fp, dup_key FROM (SELECT fp, dup_key, ord FROM messages "
            "WHERE person_id=? ORDER BY ord DESC LIMIT ?) ORDER BY ord",
            (person_id, TAIL_FP_LIMIT))]
        tail_fps = [r[0] for r in tail]
        tail_keys = [r[1] for r in tail]
        current = await self.get_cursor(person_id)
        flag = current["bootstrapped"] if bootstrapped is None else bootstrapped
        await self.db.execute(
            "INSERT INTO cursors(person_id, last_ord, dom_count, head_sig, "
            "tail_sig, head_any, tail_any, tail_fps, tail_keys, "
            "bootstrapped, full_scan_complete, full_scan_at, updated_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,0,'',?) "
            "ON CONFLICT(person_id) DO UPDATE SET last_ord=excluded.last_ord, "
            "dom_count=excluded.dom_count, head_sig=excluded.head_sig, "
            "tail_sig=excluded.tail_sig, head_any=excluded.head_any, "
            "tail_any=excluded.tail_any, tail_fps=excluded.tail_fps, "
            "tail_keys=excluded.tail_keys, "
            "bootstrapped=excluded.bootstrapped, updated_at=excluded.updated_at",
            (person_id, await self._last_ord(person_id),
             dom_count or current.get("dom_count") or 0,
             current.get("head_sig", "") if head_sig is None else head_sig,
             current.get("tail_sig", "") if tail_sig is None else tail_sig,
             current.get("head_any", "") if head_any is None else head_any,
             current.get("tail_any", "") if tail_any is None else tail_any,
             json.dumps(tail_fps), json.dumps(tail_keys), 1 if flag else 0,
             datetime.now().isoformat(timespec="seconds")))
        await self.db.commit()

    async def _recount(self, person_id: int, my_nick: str = "") -> None:
        # Counters describe what the user can SEE, so hidden (soft-deleted)
        # rows are excluded — while `last_ord` still spans every row so a
        # deletion can never make the next append reuse an ord.
        row = await self.db.fetchone(
            "SELECT COUNT(*) AS n, "
            "SUM(direction='in') AS ins, SUM(direction='out') AS outs, "
            "SUM(media_id IS NOT NULL) AS media, "
            "MIN(ts_resolved) AS first_ts, MAX(ts_resolved) AS last_ts, "
            "(SELECT MAX(ord) FROM messages WHERE person_id=?) AS last_ord "
            "FROM messages WHERE person_id=? AND deleted_at=''",
            (person_id, person_id))
        person = await self.get_person_by_id(person_id) or {}
        nicks = list(person.get("my_nicks") or [])
        clean = self.normalise_nick(my_nick)
        if clean and clean not in nicks:
            nicks.append(clean)
        await self.db.execute(
            "UPDATE persons SET message_count=?, in_count=?, out_count=?, "
            "media_count=?, last_ord=?, my_nicks=?, "
            "first_seen=COALESCE(?, first_seen), last_seen=COALESCE(?, last_seen) "
            "WHERE id=?",
            (int(row["n"] or 0), int(row["ins"] or 0), int(row["outs"] or 0),
             int(row["media"] or 0), int(row["last_ord"] or 0),
             json.dumps(nicks, ensure_ascii=False),
             row["first_ts"], row["last_ts"], person_id))
        await self.db.commit()
