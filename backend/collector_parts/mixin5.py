"""Collector mixin 5 (<150)."""
import asyncio, json, logging
from datetime import datetime
from typing import Optional

log = logging.getLogger("chatbot")

class CollectorMixin5:
    def state_payload(self) -> dict:
        return {
            "state": self._state,
            "text": self._text,
            "nick": self._nick,
            "my_nick": self.my_nick,
            "detected_my_nick": self._detected_my_nick,
            "added": self._added,
            "total": self._total,
            "throttled": self._throttled,
            "backfill_pending": self._backfill_pending,
            "error": self._error,
            "warning": self._warning,
            "self_heals": self._self_heals,
            "agent": self._agent,
            "sync_reason": self._last_sync_reason,
            "sync_added": self._last_sync_added,
            "sync_count": self._last_sync_count,
            "media_repaired": self._last_media_repaired,
            "media_requeued": self._last_media_requeued,
            "last_probe": self._last_probe,
            "paused": self._paused,
            "running": self._running,
            "enabled": self.enabled,
            "interval_ms": self.next_interval_ms(),
            "settings": self.settings(),
        }

    def _no_new_text(self) -> str:
        p = self._last_probe or {}
        return (f"No new messages (count {p.get('count')}, "
                f"participants {p.get('participants')}, "
                f"panes {p.get('panes')}, "
                f"pane {p.get('pane_source') or 'n/a'})")

    def _set(self, state: str, text: str) -> str:
        self._state = state
        self._text = text
        self._emit()
        return state

    def _emit(self) -> None:
        payload = self.state_payload()
        signature = (payload["state"], payload["text"], payload["nick"],
                     payload["added"], payload["total"], payload["throttled"],
                     payload["backfill_pending"], payload["sync_reason"],
                     payload["sync_added"], payload["sync_count"],
                     payload["media_repaired"], payload["media_requeued"],
                     payload["error"], payload["warning"])
        if signature == self._last_emitted:
            return                                   # never spam the UI
        self._last_emitted = signature
        try:
            self.status_changed.emit(json.dumps(payload, ensure_ascii=False))
        except Exception as e:                       # noqa: BLE001
            log.debug("status emit failed: %s", e)
