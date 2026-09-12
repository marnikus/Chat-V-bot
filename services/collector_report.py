"""Everything the collector says about itself, outward.

Owns the state payload the Radar window reads, the reset between people,
and the three emitters (`status_changed`, `collector_log`) plus the
pure payload shaping helpers. Built from the aggregate only; the state it
describes stays on `Collector`.
"""

from __future__ import annotations

import json
import logging

from typing import Optional

log = logging.getLogger("chatbot")


class Reporter:
    """One responsibility of `Collector`, built from it."""

    def __init__(self, owner):
        self._o = owner

    def reset_state(self) -> None:
        """Forget everything learned about the CURRENT conversation.

        Called when the archive database is swapped underneath us: the
        cursors, totals and the verified private-chat gate all describe the
        old file, and acting on them would attribute the next batch to a
        conversation this database has never seen (RULE 15 fails closed).
        """
        self._o._nick = ""
        self._o._text = ""
        self._o._verified = False
        self._o._added = 0
        self._o._total = 0
        self._o._error = ""
        self._o._warning = ""
        self._o._last_probe = {}
        self._o._last_sync_reason = ""
        self._o._last_sync_added = 0
        self._o._last_sync_count = 0
        self._o._backfill_pending = False
        self._o._force_backfill = False
        self._o._last_emitted = ()

    def _log(self, message: str, level: str = "info",
             nick: Optional[str] = None) -> None:
        """One line for the Collector window's own log.

        Kept deliberately separate from `log.debug`: this is user-facing
        (parsing history / trying to identify the nick), not a stack trace.
        """
        try:
            payload = {
                "ts": self._o.now().strftime("%H:%M:%S"),
                "level": str(level or "info"),
                "message": str(message or ""),
                "nick": nick or self._o._nick or "",
            }
            self._o.collector_log.emit(json.dumps(payload, ensure_ascii=False))
        except Exception as e:                       # noqa: BLE001
            log.debug("collector_log emit failed: %s", e)

    def _notify_people(self, nick: str, kind: str) -> None:
        try:
            self._o.people_changed.emit(json.dumps(
                {"nick": nick, "kind": kind, "source": "collector"},
                ensure_ascii=False))
        except Exception as e:                       # noqa: BLE001
            log.debug("people_changed emit failed: %s", e)

    @staticmethod
    def _payload(payload) -> dict:
        """Normalise whatever the page pushed into a dict."""
        data = payload
        if isinstance(data, (bytes, bytearray)):
            data = data.decode("utf-8", "replace")
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except (TypeError, ValueError):
                return {}
        if isinstance(data, list):
            return {"items": data}
        return data if isinstance(data, dict) else {}

    @classmethod
    def _records(cls, payload) -> list:
        data = payload if isinstance(payload, dict) else cls._payload(payload)
        items = data.get("items")
        if not isinstance(items, list):
            return []
        return [item for item in items if isinstance(item, dict)]

    # ── status ───────────────────────────────────────────────────
    def state_payload(self) -> dict:
        return {
            "state": self._o._state,
            "text": self._o._text,
            "nick": self._o._nick,
            "my_nick": self._o.my_nick,
            "detected_my_nick": self._o._detected_my_nick,
            "added": self._o._added,
            "total": self._o._total,
            "throttled": self._o._throttled,
            "backfill_pending": self._o._backfill_pending,
            "error": self._o._error,
            "warning": self._o._warning,
            "self_heals": self._o._self_heals,
            "agent": self._o._agent,
            "sync_reason": self._o._last_sync_reason,
            "sync_added": self._o._last_sync_added,
            "sync_count": self._o._last_sync_count,
            "media_repaired": self._o._last_media_repaired,
            "media_requeued": self._o._last_media_requeued,
            "last_probe": self._o._last_probe,
            "paused": self._o._paused,
            "running": self._o._running,
            "enabled": self._o.enabled,
            "interval_ms": self._o.next_interval_ms(),
            "settings": self._o.settings(),
        }

    def _no_new_text(self) -> str:
        p = self._o._last_probe or {}
        return (f"No new messages (count {p.get('count')}, "
                f"participants {p.get('participants')}, "
                f"panes {p.get('panes')}, "
                f"pane {p.get('pane_source') or 'n/a'})")

    def _set(self, state: str, text: str) -> str:
        self._o._state = state
        self._o._text = text
        self._o._emit()
        return state

    def _emit(self) -> None:
        payload = self._o.state_payload()
        signature = (payload["state"], payload["text"], payload["nick"],
                     payload["added"], payload["total"], payload["throttled"],
                     payload["backfill_pending"], payload["sync_reason"],
                     payload["sync_added"], payload["sync_count"],
                     payload["media_repaired"], payload["media_requeued"],
                     payload["error"], payload["warning"])
        if signature == self._o._last_emitted:
            return                                   # never spam the UI
        self._o._last_emitted = signature
        try:
            self._o.status_changed.emit(
                json.dumps(payload, ensure_ascii=False))
        except Exception as e:                       # noqa: BLE001
            log.debug("status emit failed: %s", e)
