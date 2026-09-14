"""What happens to a whole conversation, not to one row.

The lifecycle half of `stores/history_repo.py`: the collector's rename when a
nick's case or spacing changed (only after the two histories proved to be the
same conversation), the per-person sync cursor the collector reads and moves,
and the trash — soft-delete/restore/purge with an operation token, deleting or
restoring a person, and merging one person into another.

H-C4: restore ladder (_restore_rows) moved to `history_repo_restore.py` (≤200),
cursor ladder (_recount, _after_write, _touch_cursor, _last_ord, _resequence)
moved to `history_repo_cursor.py` (≤200). This file keeps phase orchestration.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime

from stores.history_repo_cursor import CursorLadder
from stores.history_repo_restore import RestoreLadder, _hidden_row_key as _restore_hidden_key, _sig_or
from stores.history_requests import WriteContext

log = logging.getLogger("chatbot")


def _hidden_row_key(row: dict) -> str:
    return _restore_hidden_key(row)


async def _delete_hidden(owner, nick: str, person) -> None:
    if not nick:
        await owner.db.execute("DELETE FROM messages WHERE deleted_at<>''")
        await _erase_tombstones(owner)
        return
    await owner.db.execute("DELETE FROM messages WHERE deleted_at<>'' AND person_id=?", (int(person["id"]),))
    if person.get("deleted_at"):
        await _erase_person(owner, int(person["id"]))


async def _erase_person(owner, pid: int) -> None:
    for table in ("messages", "cursors", "gaps"):
        await owner.db.execute(f"DELETE FROM {table} WHERE person_id=?", (pid,))
    await owner.db.execute("DELETE FROM persons WHERE id=?", (pid,))


async def _erase_tombstones(owner) -> None:
    for table in ("messages", "cursors", "gaps"):
        await owner.db.execute(
            f"DELETE FROM {table} WHERE person_id IN (SELECT id FROM persons WHERE deleted_at<>'')"
        )
    await owner.db.execute("DELETE FROM persons WHERE deleted_at<>''")


class PersonLifecycle:
    """What happens to a whole conversation, not to one row."""

    def __init__(self, owner):
        self._owner = owner
        self._restore = RestoreLadder(owner)
        self._cursor = CursorLadder(owner)

    async def get_cursor(self, person_id: int) -> dict:
        row = await self._owner.db.fetchone("SELECT * FROM cursors WHERE person_id=?", (person_id,))
        if not row:
            return {
                "person_id": person_id,
                "last_ord": 0,
                "dom_count": 0,
                "head_sig": "",
                "tail_sig": "",
                "head_any": "",
                "tail_any": "",
                "tail_fps": [],
                "tail_keys": [],
                "bootstrapped": False,
                "full_scan_complete": False,
                "full_scan_at": "",
            }
        data = dict(row)
        try:
            data["tail_fps"] = json.loads(data.get("tail_fps") or "[]")
        except Exception:  # noqa: BLE001
            data["tail_fps"] = []
        try:
            data["tail_keys"] = json.loads(data.get("tail_keys") or "[]")
        except Exception:  # noqa: BLE001
            data["tail_keys"] = []
        data["bootstrapped"] = bool(data.get("bootstrapped"))
        data["full_scan_complete"] = bool(data.get("full_scan_complete"))
        return data

    async def reset_cursor(self, nick: str) -> None:
        person_id = await self._owner.ensure_person(nick)
        await self._owner.db.execute(
            "INSERT INTO cursors(person_id, last_ord, dom_count, head_sig, tail_sig, head_any, tail_any, tail_fps, tail_keys, bootstrapped, full_scan_complete, full_scan_at, updated_at) "
            "VALUES(?,?,0,'','','','','[]','[]',0,0,'',?) ON CONFLICT(person_id) DO UPDATE SET dom_count=0, head_sig='', tail_sig='', head_any='', tail_any='', tail_fps='[]', tail_keys='[]', bootstrapped=0, full_scan_complete=0, full_scan_at='', updated_at=excluded.updated_at",
            (person_id, await self._last_ord(person_id), datetime.now().isoformat(timespec="seconds")),
        )
        await self._owner.db.commit()

    async def _last_ord(self, person_id: int) -> int:
        return await self._cursor._last_ord(person_id)

    async def mark_backfilled(self, nick_or_id) -> None:
        person_id = (
            int(nick_or_id) if isinstance(nick_or_id, int) else await self._owner.ensure_person(str(nick_or_id))
        )
        stamp = datetime.now().isoformat(timespec="seconds")
        await self._owner.db.execute(
            "INSERT INTO cursors(person_id, last_ord, dom_count, head_sig, tail_sig, head_any, tail_any, tail_fps, tail_keys, bootstrapped, full_scan_complete, full_scan_at, updated_at) "
            "VALUES(?,0,0,'','','','','[]','[]',0,1,?,?) ON CONFLICT(person_id) DO UPDATE SET full_scan_complete=1, full_scan_at=excluded.full_scan_at, updated_at=excluded.updated_at",
            (person_id, stamp, stamp),
        )
        await self._owner.db.commit()

    async def soft_delete_message(self, nick: str, message_id: int, token: str = "") -> str:
        person = await self._owner.get_person(nick)
        if not person:
            return ""
        stamp = token or self._owner.new_op_token()
        cur = await self._owner.db.execute(
            "UPDATE messages SET deleted_at=? WHERE id=? AND person_id=? AND deleted_at=''",
            (stamp, int(message_id), int(person["id"])),
        )
        if not cur.rowcount:
            await self._owner.db.commit()
            return ""
        await self._owner.db.commit()
        await self._owner._recount(int(person["id"]))
        return stamp

    async def soft_delete_history(self, nick: str, token: str = "") -> str:
        person = await self._owner.get_person(nick)
        if not person:
            return ""
        stamp = token or self._owner.new_op_token()
        cur = await self._owner.db.execute(
            "UPDATE messages SET deleted_at=?, dup_key='' WHERE person_id=? AND deleted_at=''",
            (stamp, int(person["id"])),
        )
        hidden = int(cur.rowcount or 0)
        await self._owner.db.commit()
        if not hidden:
            return ""
        await self._owner._recount(int(person["id"]))
        await self.reset_cursor(nick)
        return stamp

    async def restore_deleted(self, nick: str, token: str) -> int:
        person = await self._owner.get_person(nick)
        if not person or not token:
            return 0
        restored = await self._restore_rows(int(person["id"]), str(token))
        if restored:
            await self._resequence(int(person["id"]))
            await self._owner._recount(int(person["id"]))
        return restored

    async def _restore_rows(self, person_id: int, token: str) -> int:
        return await self._restore._restore_rows(person_id, token)

    async def _restore_one_row(self, row, token: str, alive: set) -> bool:
        return await self._restore._restore_one_row(row, token, alive)

    async def deleted_count(self, nick: str = "") -> int:
        if nick:
            person = await self._owner.get_person(nick)
            if not person:
                return 0
            return int(
                await self._owner.db.scalar(
                    "SELECT COUNT(*) FROM messages WHERE person_id=? AND deleted_at<>''",
                    (int(person["id"]),),
                    0,
                )
            )
        return int(await self._owner.db.scalar("SELECT COUNT(*) FROM messages WHERE deleted_at<>''", (), 0))

    async def purge_deleted(self, nick: str = "") -> int:
        person = None
        if nick:
            person = await self._owner.get_person(nick)
            if not person:
                return 0
        before = await self.deleted_count(nick)
        await _delete_hidden(self._owner, nick, person)
        await self._owner.db.commit()
        if person:
            await self._owner._recount(int(person["id"]))
        return before

    async def delete_person(self, nick: str, hard: bool = False, token: str = "") -> bool:
        person = await self._owner.get_person(nick)
        if not person:
            return False
        pid = int(person["id"])
        if hard:
            await _erase_person(self._owner, pid)
        else:
            stamp = token or self._owner.new_op_token()
            await self._owner.db.execute(
                "UPDATE messages SET deleted_at=?, dup_key='' WHERE person_id=? AND deleted_at=''",
                (stamp, pid),
            )
            await self._owner.db.execute("UPDATE persons SET deleted_at=? WHERE id=?", (stamp, pid))
        await self._owner.db.commit()
        if not hard:
            await self._owner._recount(pid)
            await self.reset_cursor(nick)
        return True

    async def restore_person(self, nick: str, token: str = "") -> bool:
        person = await self._owner.get_person(nick)
        if not person:
            return False
        pid = int(person["id"])
        stamp = token or (person.get("deleted_at") or "")
        restored = 0
        if stamp:
            restored = await self._restore_rows(pid, str(stamp))
        if token and str(token) != str(person.get("deleted_at") or "") and not restored:
            return False
        await self._owner.db.execute("UPDATE persons SET deleted_at=NULL WHERE id=?", (pid,))
        await self._owner.db.commit()
        await self._resequence(pid)
        await self._owner._recount(pid)
        return True

    async def merge_persons(self, from_nick: str, into_nick: str) -> int:
        source = await self._owner.get_person(from_nick)
        target = await self._owner.get_person(into_nick)
        if not source or not target or source["id"] == target["id"]:
            return 0
        src, dst = int(source["id"]), int(target["id"])
        moved = 0
        rows = await self._owner.db.fetchall(
            "SELECT id FROM messages WHERE person_id=? ORDER BY ord", (src,)
        )
        for row in rows:
            cur = await self._owner.db.execute(
                "UPDATE OR IGNORE messages SET person_id=? WHERE id=?", (dst, int(row[0]))
            )
            moved += int(cur.rowcount or 0)
        await self._owner.db.execute("DELETE FROM messages WHERE person_id=?", (src,))
        await self._owner.db.execute("UPDATE gaps SET person_id=? WHERE person_id=?", (dst, src))
        await self._owner.db.execute("DELETE FROM cursors WHERE person_id=?", (src,))
        nicks = list(dict.fromkeys(list(target.get("my_nicks") or []) + list(source.get("my_nicks") or [])))
        await self._owner.db.execute(
            "UPDATE persons SET my_nicks=? WHERE id=?", (json.dumps(nicks, ensure_ascii=False), dst)
        )
        await self._owner.db.execute("DELETE FROM persons WHERE id=?", (src,))
        await self._owner.db.commit()
        await self._resequence(dst)
        await self._owner._recount(dst)
        return moved

    async def _resequence(self, person_id: int) -> None:
        return await self._cursor._resequence(person_id)

    async def _after_write(self, ctx: WriteContext) -> None:
        return await self._cursor._after_write(ctx)

    async def _recount(self, person_id: int, my_nick: str = "") -> None:
        return await self._cursor._recount(person_id, my_nick)

    async def _touch_cursor(self, ctx: WriteContext) -> None:
        return await self._cursor._touch_cursor(ctx)
