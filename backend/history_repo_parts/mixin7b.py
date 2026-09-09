"""History repo 7b deletes b (<150)."""
import asyncio, json, logging, re
from datetime import datetime
from typing import Optional

class HistoryRepoMixin7b:
    async def deleted_count(self, nick: str = "") -> int:
        if nick:
            person = await self.get_person(nick)
            if not person:
                return 0
            return int(await self.db.scalar(
                "SELECT COUNT(*) FROM messages WHERE person_id=? AND "
                "deleted_at<>''", (int(person["id"]),), 0))
        return int(await self.db.scalar(
            "SELECT COUNT(*) FROM messages WHERE deleted_at<>''", (), 0))

    async def purge_deleted(self, nick: str = "") -> int:
        """Erase hidden rows for good — the ONLY path that removes bytes."""
        params: tuple = ()
        sql = "DELETE FROM messages WHERE deleted_at<>''"
        person = None
        if nick:
            person = await self.get_person(nick)
            if not person:
                return 0
            sql += " AND person_id=?"
            params = (int(person["id"]),)
        before = await self.deleted_count(nick)
        await self.db.execute(sql, params)
        await self.db.commit()
        if person:
            await self._recount(int(person["id"]))
        return before

    async def delete_person(self, nick: str, hard: bool = False,
                            token: str = "") -> bool:
        """Remove a person WITH their history.

        Soft (the default) tombstones the person and hides every message
        under one token, so a single Ctrl+Z brings both halves back. Like a
        history clear, the hidden rows lose their identity and the
        collection markers reset, so a re-visit re-collects from scratch
        (Bug 3, 2026-09-08). `hard` erases the rows — used only by an
        explicit purge.
        """
        person = await self.get_person(nick)
        if not person:
            return False
        pid = int(person["id"])
        if hard:
            await self.db.execute("DELETE FROM messages WHERE person_id=?", (pid,))
            await self.db.execute("DELETE FROM cursors WHERE person_id=?", (pid,))
            await self.db.execute("DELETE FROM gaps WHERE person_id=?", (pid,))
            await self.db.execute("DELETE FROM persons WHERE id=?", (pid,))
        else:
            stamp = token or self.new_op_token()
            await self.db.execute(
                "UPDATE messages SET deleted_at=?, dup_key='' WHERE "
                "person_id=? AND deleted_at=''", (stamp, pid))
            await self.db.execute(
                "UPDATE persons SET deleted_at=? WHERE id=?", (stamp, pid))
        await self.db.commit()
        if not hard:
            await self._recount(pid)
            await self.reset_cursor(nick)
        return True

    async def restore_person(self, nick: str, token: str = "") -> bool:
        person = await self.get_person(nick)
        if not person:
            return False
        pid = int(person["id"])
        stamp = token or (person.get("deleted_at") or "")
        if stamp:
            await self._restore_rows(pid, str(stamp))
        await self.db.execute("UPDATE persons SET deleted_at=NULL WHERE id=?",
                              (pid,))
        await self.db.commit()
        await self._resequence(pid)
        await self._recount(pid)
        return True

    async def merge_persons(self, from_nick: str, into_nick: str) -> int:
        """Fold one nick's archive into another. Returns the rows moved."""
        source = await self.get_person(from_nick)
        target = await self.get_person(into_nick)
        if not source or not target or source["id"] == target["id"]:
            return 0
        src, dst = int(source["id"]), int(target["id"])
        moved = 0
        rows = await self.db.fetchall(
            "SELECT id FROM messages WHERE person_id=? ORDER BY ord", (src,))
        for row in rows:
            cur = await self.db.execute(
                "UPDATE OR IGNORE messages SET person_id=? WHERE id=?",
                (dst, int(row[0])))
            moved += int(cur.rowcount or 0)
        await self.db.execute("DELETE FROM messages WHERE person_id=?", (src,))
        await self.db.execute("UPDATE gaps SET person_id=? WHERE person_id=?",
                              (dst, src))
        await self.db.execute("DELETE FROM cursors WHERE person_id=?", (src,))
        nicks = list(dict.fromkeys(list(target.get("my_nicks") or []) +
                                   list(source.get("my_nicks") or [])))
        await self.db.execute("UPDATE persons SET my_nicks=? WHERE id=?",
                              (json.dumps(nicks, ensure_ascii=False), dst))
        await self.db.execute("DELETE FROM persons WHERE id=?", (src,))
        await self.db.commit()
        await self._resequence(dst)
        await self._recount(dst)
        return moved

    async def _resequence(self, person_id: int) -> None:
        rows = await self.db.fetchall(
            "SELECT id FROM messages WHERE person_id=? "
            "ORDER BY day, ts_display, ord, id", (person_id,))
        for index, row in enumerate(rows, start=1):
            await self.db.execute("UPDATE messages SET ord=? WHERE id=?",
                                  (index, int(row[0])))
        await self.db.commit()
