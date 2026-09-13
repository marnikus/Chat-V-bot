"""The collector's status vocabulary and emit plumbing.

`StatusMixin` owns the single status payload the UI reads, the dedup that
stops it from spamming, and the two side signals (the collector log and the
people-changed notice). Nothing here decides state — it only renders and
emits what the other phases set.
"""

import json
import logging
from typing import Optional

log = logging.getLogger("chatbot")


class StatusMixin:
    def _log(self, message: str, level: str = "info",
             nick: Optional[str] = None) -> None:
        """One line for the Collector window's own log.

        Kept deliberately separate from `log.debug`: this is user-facing
        (parsing history / trying to identify the nick), not a stack trace.
        """
        try:
            payload = {
                "ts": self.now().strftime("%H:%M:%S"),
                "level": str(level or "info"),
                "message": str(message or ""),
                "nick": nick or self._nick or "",
            }
            self.collector_log.emit(json.dumps(payload, ensure_ascii=False))
        except Exception as e:                       # noqa: BLE001
            log.debug("collector_log emit failed: %s", e)

    def _notify_people(self, nick: str, kind: str) -> None:
        try:
            self.people_changed.emit(json.dumps(
                {"nick": nick, "kind": kind, "source": "collector"},
                ensure_ascii=False))
        except Exception as e:                       # noqa: BLE001
            log.debug("people_changed emit failed: %s", e)

    # ── status ───────────────────────────────────────────────────
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
