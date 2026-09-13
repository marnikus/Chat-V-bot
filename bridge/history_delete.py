"""HistoryBridge deletion slots -- all reversible (RULE 12).

Split out of `bridge/history_bridge` in round H (H1) as a MIXIN, for the
same reason as the media slots: QWebChannel exposes one object, so every
`@Slot` name below is part of the wire contract and the class identity must
survive the split.

Everything here is undoable except a HARD delete, which is terminal by
design and says so in its log line. The people-table snapshots taken either
side of a removal are what let one Ctrl+Z restore both the person and their
messages; they are only recorded when BOTH snapshots exist, since a
half-known before/after would restore the archive into a shape that never
existed.

Imports point one way: `history_bridge` imports this; this imports only Qt,
`core` and the standard library.
"""

from __future__ import annotations

import json
import logging

from PySide6.QtCore import Slot

from core.events import LogMessage

log = logging.getLogger("chatbot")


def _record_person_deletion(ctx, nick, hard, token, snapshots):
    """Log a completed deletion and, when soft, make it undoable.

    A hard delete is terminal: the label is forgotten and nothing is pushed,
    because there is no state left to restore. A soft delete pushes the
    people rows either side of the removal so Ctrl+Z can put the person back
    as well as their messages -- but only when both snapshots exist, since a
    half-known before/after would restore the archive into a shape that
    never existed.
    """
    if hard:
        ctx.label_store.forget(nick)
        ctx.bus.emit(LogMessage(
            message=f"🔥 “{nick}” erased permanently (not undoable)",
            level="warn"))
        return
    entry = {"op": "delete_person", "nick": nick, "token": token}
    before, after = snapshots
    if before is not None and after is not None:
        entry["people"] = {"before": before, "after": after}
    ctx.undo.push("archive", entry)
    ctx.bus.emit(LogMessage(
        message=f"🗑 “{nick}” and their history removed — "
                "Ctrl+Z restores both", level="warn"))

def _message_id(raw) -> int:
    """A message id as a positive int, or 0 when the argument is unusable.

    Ids arrive from QWebChannel as strings and a malformed one must refuse
    the delete rather than address row 0. Zero is the single "no" value, so
    callers test it once instead of distinguishing bad text from a bad
    number.
    """
    try:
        mid = int(str(raw or "0").strip() or 0)
    except (TypeError, ValueError):
        return 0
    return mid if mid > 0 else 0


class HistoryDeleteMixin:
    """Reversible removals from the archive, plus the people-table sync."""

    @Slot(str, bool, result=bool)
    def history_delete_person(self, nick, hard=False):
        clean = self._nick_for("history_delete_person", nick)
        if not clean:
            return False

        async def work():
            archive = self.ctx.archive
            repo = archive.repo
            token = repo.new_op_token()
            people_before = await self._people_snapshot()
            ok = await repo.delete_person(clean, hard=bool(hard),
                                          token=token)
            if people_before is not None:
                try:
                    await self.ctx.memory.delete_user(clean)
                except Exception as exc:                  # noqa: BLE001
                    log.debug("people row for %s not removed: %s",
                              clean, exc)
            people_after = await self._people_snapshot()
            if ok:
                _record_person_deletion(
                    self.ctx, clean, bool(hard), token,
                    (people_before, people_after))
            self.userdb_changed.emit(json.dumps(
                {"action": "deleted", "nick": clean, "hard": bool(hard),
                 "ok": ok}, ensure_ascii=False))
            self._refresh_people()
        self._run_async("history_delete_person", work())
        return True
    @Slot(str, result=bool)
    def history_clear_person(self, nick):
        clean = self._nick_for("history_clear_person", nick)
        if not clean:
            return False

        async def work():
            archive = self.ctx.archive
            repo = archive.repo
            token = await repo.soft_delete_history(clean)
            if not token:
                if await repo.get_person(clean):
                    await repo.reset_cursor(clean)
                self.ctx.bus.emit(LogMessage(
                    message=f"ℹ “{clean}” has no messages to clear",
                    level="info"))
            else:
                self.ctx.undo.push("archive", {
                    "op": "clear_history", "nick": clean, "token": token})
                self.ctx.bus.emit(LogMessage(
                    message=f"🧹 History of “{clean}” cleared — the person "
                            "stays in the database and the chat is "
                            "re-collected from scratch (Ctrl+Z restores "
                            "the messages)", level="warn"))
            collector = getattr(archive, "collector", None)
            if collector is not None:
                try:
                    collector.person_cleared(clean)
                except Exception:                      # noqa: BLE001
                    pass
            self.userdb_changed.emit(json.dumps(
                {"action": "cleared", "nick": clean, "ok": bool(token)},
                ensure_ascii=False))
        self._run_async("history_clear_person", work())
        return True
    @Slot(str, str, result=bool)
    def history_delete_message(self, nick, message_id):
        mid = _message_id(message_id)
        clean = self._nick_for("history_delete_message", nick) if mid else ""
        if not clean:
            return False

        async def work():
            token = await self.ctx.archive.repo.soft_delete_message(clean,
                                                                    mid)
            if not token:
                self.ctx.bus.emit(LogMessage(
                    message="⚠ That message is already gone", level="warn"))
                return
            self.ctx.undo.push("archive", {
                "op": "delete_message", "nick": clean, "token": token,
                "message_id": mid})
            self.ctx.bus.emit(LogMessage(
                message=f"🗑 One message removed from “{clean}” "
                        "(Ctrl+Z restores it)", level="info"))
            self.userdb_changed.emit(json.dumps(
                {"action": "message_deleted", "nick": clean, "id": mid},
                ensure_ascii=False))
        self._run_async("history_delete_message", work())
        return True
    @Slot(str, result=bool)
    def history_purge_deleted(self, nick):
        if self.ctx.archive is None:
            return False

        async def work():
            gone = await self.ctx.archive.repo.purge_deleted(
                " ".join(str(nick or "").split()).strip())
            self.ctx.bus.emit(LogMessage(
                message=f"🔥 {gone} hidden message(s) erased permanently",
                level="warn"))
            self.userdb_changed.emit(json.dumps(
                {"action": "purged", "nick": nick, "count": gone},
                ensure_ascii=False))
        self._run_async("history_purge_deleted", work())
        return True
    @Slot(str, result=bool)
    def history_restore_person(self, nick):
        if self.ctx.archive is None:
            return False

        async def work():
            ok = await self.ctx.archive.repo.restore_person(nick)
            self.userdb_changed.emit(json.dumps(
                {"action": "restored", "nick": nick, "ok": ok},
                ensure_ascii=False))
            self._refresh_people()
        self._run_async("history_restore_person", work())
        return True
    @Slot(str, str, result=bool)
    def history_merge(self, from_nick, into_nick):
        if self.ctx.archive is None:
            return False

        async def work():
            moved = await self.ctx.archive.repo.merge_persons(from_nick,
                                                              into_nick)
            self.userdb_changed.emit(json.dumps(
                {"action": "merged", "nick": into_nick, "from": from_nick,
                 "moved": moved}, ensure_ascii=False))
        self._run_async("history_merge", work())
        return True
    async def _people_snapshot(self):
        if self.ctx.memory is None:
            return None
        try:
            return await self.ctx.people.rows()
        except Exception as exc:                         # noqa: BLE001
            log.debug("people snapshot unavailable: %s", exc)
            return None
    def _refresh_people(self) -> None:
        from core.events import PeopleChanged
        self.ctx.bus.emit(PeopleChanged(reason="archive"))
