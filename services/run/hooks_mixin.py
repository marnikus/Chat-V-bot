"""Run hooks mixin — extracted from hooks.py (H-C5 split)

Person collection / rejection / nick expansion, ≤150 LOC.
"""

from __future__ import annotations

import json
import logging

from services.run.hooks_levels import norm_level

log = logging.getLogger("chatbot")


class RunHooksMixin:
    def report(self, message: str, level: str = "info") -> None:
        level = norm_level(level)
        self.debug_msg.emit(f"      {message}", level)
        if self._tracer is not None:
            self._tracer.note({"type": "detail", "level": level, "message": message, **self._ctx})

    async def person_collected(self, record, collected: list) -> None:
        try:
            await self._memory.upsert_user(record)
        except Exception as exc:
            log.warning("Live upsert failed for %s: %s", record.nick, exc)
        payload = {
            "nick": record.nick, "gender": record.gender,
            "registered": bool(record.registered), "anonymous": bool(record.anonymous),
            "guest": bool(record.guest), "messaged": bool(record.messaged),
            "collected": len(collected),
        }
        self.person_found.emit(json.dumps(payload, ensure_ascii=False))
        if self._tracer is not None:
            self._tracer.note({"type": "person_collected", **payload})

    async def unmessaged_nicks(self) -> set[str]:
        try:
            return {u.nick for u in await self._memory.get_all() if not u.messaged}
        except Exception as exc:
            log.warning("Un-messaged read failed (collecting instead): %s", exc)
            return set()

    def is_stopping(self) -> bool:
        return self._stop_requested

    async def person_rejected(self, record, reason: str) -> bool:
        try:
            deleter = getattr(self._memory, "delete_user", None)
            removed = bool(await deleter(record.nick)) if deleter else False
        except Exception as exc:
            log.warning("Purge failed for %s: %s", record.nick, exc)
            return False
        if not removed:
            return False
        payload = {"nick": record.nick, "reason": reason}
        self.person_removed.emit(json.dumps(payload, ensure_ascii=False))
        self.debug_msg.emit(f"      🗑 Removed “{record.nick}” — {reason}", "warn")
        if self._tracer is not None:
            self._tracer.note({"type": "person_purged", **payload})
        return True

    def note_selected(self, nick: str) -> None:
        if not nick:
            return
        self.selected_nick = nick
        if self._tracer is not None:
            self._tracer.note({"type": "nick_selected", "nick": nick})

    def _expand_nick_on_block(self, block, nick: str) -> dict:
        changed = {}
        for key, value in vars(block).items():
            if key.startswith("_") or not isinstance(value, str) or "{{nick}}" not in value:
                continue
            changed[key] = value
            setattr(block, key, value.replace("{{nick}}", nick))
        return changed

    @staticmethod
    def _restore_block_attrs(block, originals: dict) -> None:
        for key, value in originals.items():
            setattr(block, key, value)
