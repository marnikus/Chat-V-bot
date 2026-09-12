"""CollectorBridge — the passive collector window + My Nick.

The collector itself lives inside the archive service
(services/collector_service.py) and keeps its Qt signals; this bridge
wires them (at attach_history time, when the archive exists) and adds
the panel's @Slot controls.
"""

from __future__ import annotations

import json
import logging

from PySide6.QtCore import QObject, Signal, Slot

from core.events import LogMessage, MyNickChanged

log = logging.getLogger("chatbot")


class CollectorBridge(QObject):
    collector_status = Signal(str)           # JSON collector state payload
    collector_log = Signal(str)              # JSON {ts, level, message, nick}
    history_appended = Signal(str)           # JSON {nick, items, added}
    my_nick_changed = Signal(str)            # the configured "my nick"

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        ctx.bus.subscribe(MyNickChanged,
                          lambda e: self.my_nick_changed.emit(e.nick))

    def attach_archive(self, service) -> None:
        """Wire the archive's collector signals (called by attach_history)."""
        if service is None:
            return
        try:
            service.collector.status_changed.connect(self.collector_status.emit)
            service.collector.collector_log.connect(self.collector_log.emit)
            service.collector.history_appended.connect(
                self.history_appended.emit)
            # a private chat with an unknown partner creates a People row
            service.collector.people_changed.connect(
                lambda *_a: self._refresh_people())
        except Exception as exc:                         # noqa: BLE001
            log.warning("collector signals not connected: %s", exc)

    def _refresh_people(self) -> None:
        from core.events import PeopleChanged
        self.ctx.bus.emit(PeopleChanged(reason="collector"))

    def _run_async(self, scope: str, coro) -> None:
        async def guarded():
            try:
                await coro
            except Exception as exc:                     # noqa: BLE001
                log.warning("collector %s failed: %s", scope, exc)
        try:
            import asyncio
            asyncio.ensure_future(guarded())
        except RuntimeError:
            coro.close()

    # ── the collector window ─────────────────────────────────────
    @Slot(result=str)
    def collector_state(self):
        if self.ctx.archive is None:
            return json.dumps({"state": "off",
                               "text": "Archive not running",
                               "settings": {}, "paused": False})
        return json.dumps(self.ctx.archive.collector.state_payload(),
                          ensure_ascii=False)

    @Slot(str)
    def collector_set(self, settings_json):
        """Apply and persist collector settings from the panel."""
        if self.ctx.archive is None:
            return
        try:
            patch = json.loads(settings_json or "{}")
        except (TypeError, ValueError):
            return
        if not isinstance(patch, dict):
            return
        applied = self.ctx.archive.collector.configure(**patch)
        stored = self.ctx.config.get_copy("collector", default={})
        if not isinstance(stored, dict):
            stored = {}
        stored.update({k: v for k, v in applied.items()})
        self.ctx.config.set("collector", stored)
        self.ctx.config.save()
        self.collector_status.emit(json.dumps(
            self.ctx.archive.collector.state_payload(),
            ensure_ascii=False))

    @Slot(str)
    def collector_command(self, command):
        """pause / resume / start / stop / tick — anything else is ignored."""
        if self.ctx.archive is None:
            return
        collector = self.ctx.archive.collector
        action = str(command or "").strip().lower()
        if not self._run_collector_action(action, collector):
            return
        self.collector_status.emit(json.dumps(collector.state_payload(),
                                              ensure_ascii=False))

    def _run_collector_action(self, action: str, collector) -> bool:
        """Dispatch one collector verb (named-bound-method table)."""
        simple = {"pause": collector.pause, "resume": collector.resume,
                  "stop": collector.stop}
        if action in simple:
            simple[action]()
            return True
        if action == "start":
            collector.start()
            self.ctx.archive.start()
            return True
        if action == "tick":
            self._run_async("collector_tick", collector.tick())
            return True
        if action in ("backfill_older", "backfill"):
            self._run_async("collector_backfill", collector.backfill_older())
            return True
        return False

    # ── My Nick (pinned header) ──────────────────────────────────
    @Slot(result=str)
    def get_my_nick(self):
        value = self.ctx.config.get("collector", "my_nick", default="")
        return str(value or "")

    @Slot(str)
    def set_my_nick(self, nick):
        clean = " ".join(str(nick or "").split()).strip()
        self._store_my_nick(clean)
        if self.ctx.archive is not None:
            self.ctx.archive.set_my_nick(clean)
        self._announce_my_nick(clean)

    def _store_my_nick(self, clean: str) -> None:
        """Persist the nick (collector section) + the 10-entry recents list."""
        stored = self.ctx.config.get_copy("collector", default={})
        if not isinstance(stored, dict):
            stored = {}
        stored["my_nick"] = clean
        self.ctx.config.set("collector", stored)
        recent = [n for n in
                  (self.ctx.config.get_state("my_nick_recent", []) or [])
                  if isinstance(n, str) and n and n != clean]
        if clean:
            recent.insert(0, clean)
        self.ctx.config.set_state(my_nick_recent=recent[:10])

    def _announce_my_nick(self, clean: str) -> None:
        """The pinned header + bus fan-out (string pinned)."""
        self.my_nick_changed.emit(clean)
        self.ctx.bus.emit(MyNickChanged(nick=clean))
        self.ctx.bus.emit(LogMessage(
            message=f"👤 My Nick set to “{clean}”" if clean else
                    "👤 My Nick cleared", level="info"))
