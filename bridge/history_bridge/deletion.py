"""Removing things from the archive — all of it reversible (RULE 12).

`DeletionMixin` owns the three removals: a person with their history, a
conversation kept as a person, and ONE message. Each is a soft delete
stamped with an operation token, so the undo entry carries no message
bodies and Ctrl+Z is a single UPDATE (RULE 14: the archive is
append-only, a tombstone hides a row).
"""

from __future__ import annotations

import json
import logging

from PySide6.QtCore import Slot

from core.events import LogMessage

log = logging.getLogger("chatbot")


class DeletionMixin:
    # ── deleting from the archive (all reversible, RULE 12) ──────
    @Slot(str, bool, result=bool)
    def history_delete_person(self, nick, hard=False):
        clean = " ".join(str(nick or "").split()).strip()
        if not clean:
            return False
        if self.ctx.archive is None:
            self.history_error.emit("history_delete_person",
                                    "the message archive is not running")
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
            if ok and not hard:
                entry = {"op": "delete_person", "nick": clean,
                         "token": token}
                if people_before is not None and people_after is not None:
                    entry["people"] = {"before": people_before,
                                       "after": people_after}
                self.ctx.undo.push("archive", entry)
                self.ctx.bus.emit(LogMessage(
                    message=f"🗑 “{clean}” and their history removed — "
                            "Ctrl+Z restores both", level="warn"))
            elif ok and hard:
                self.ctx.label_store.forget(clean)
                self.ctx.bus.emit(LogMessage(
                    message=f"🔥 “{clean}” erased permanently "
                            "(not undoable)", level="warn"))
            self.userdb_changed.emit(json.dumps(
                {"action": "deleted", "nick": clean, "hard": bool(hard),
                 "ok": ok}, ensure_ascii=False))
            self._refresh_people()
        self._run_async("history_delete_person", work())
        return True

    @Slot(str, result=bool)
    def history_clear_person(self, nick):
        clean = " ".join(str(nick or "").split()).strip()
        if not clean:
            return False
        if self.ctx.archive is None:
            self.history_error.emit("history_clear_person",
                                    "the message archive is not running")
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
        clean = " ".join(str(nick or "").split()).strip()
        try:
            mid = int(str(message_id or "0").strip() or 0)
        except (TypeError, ValueError):
            mid = 0
        if not clean or mid <= 0:
            return False
        if self.ctx.archive is None:
            self.history_error.emit("history_delete_message",
                                    "the message archive is not running")
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
