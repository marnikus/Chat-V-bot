"""The passive private-chat collector.

A supervisor that watches the active tab without ever blocking the UI. One
cheap heartbeat probe per tick tells it what the page is showing; only when
something actually changed does it read message nodes, and even then in
paced chunks through the shared CDP lease at LOW priority.

Statuses are the vocabulary the feature request asked for:

    Collecting …            work in progress
    Collected N …           new lines were archived
    No new messages         the conversation is idle
    Not in private tab now  the active tab is a room, a group, or nothing

Decision D-3: an Action-Stack run does NOT pause collection — it throttles
it, so the archive stays complete while runs keep priority on the socket.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from typing import Optional

from PySide6.QtCore import QObject, Signal

from backend.chat_parser import ChatParser, _signature, sync_conversation
from backend.history_repo import HistoryRepo

log = logging.getLogger("chatbot")


class CollectorState:
    DISCONNECTED = "disconnected"
    OFF = "off"
    PAUSED = "paused"
    NOT_PRIVATE = "not_private"
    GROUP_TAB = "group_tab"
    BOOTSTRAPPING = "bootstrapping"
    COLLECTING = "collecting"
    COLLECTED = "collected"
    NO_NEW = "no_new"
    ERROR = "error"


IDLE_STATES = {CollectorState.DISCONNECTED, CollectorState.OFF,
               CollectorState.PAUSED, CollectorState.NOT_PRIVATE,
               CollectorState.GROUP_TAB, CollectorState.NO_NEW,
               CollectorState.ERROR}

DEFAULTS = {
    "enabled": True,
    "my_nick": "",
    "heartbeat_ms": 1500,
    "idle_heartbeat_ms": 5000,
    "throttle_factor": 4,
    "require_two_participants": True,
    "require_private": True,
    "chunk_size": 80,
    "chunk_pause_ms": 40,
    "download_media": True,
    "max_bootstrap": 0,          # 0 = no cap
}

MAX_PROBE_PENALTY = 4.0


class Collector(QObject):
    """Non-blocking background monitor of the active conversation."""

    status_changed = Signal(str)        # json state payload
    history_appended = Signal(str)      # json {nick, items, added, total}

    def __init__(self, cdp, repo: HistoryRepo, parser: ChatParser,
                 media=None, settings: Optional[dict] = None,
                 lease=None, parent=None):
        super().__init__(parent)
        self.cdp = cdp
        self.repo = repo
        self.parser = parser
        self.media = media
        self.lease = lease
        self._settings = dict(DEFAULTS)
        self.configure(**(settings or {}))
        self.now = datetime.now

        self._state = CollectorState.DISCONNECTED
        self._text = ""
        self._nick = ""
        self._added = 0
        self._total = 0
        self._error = ""
        self._warning = ""
        self._agent = 0
        self._self_heals = 0
        self._throttled = False
        self._paused = False
        self._running = True
        self._probe_penalty = 1.0
        self._last_emitted: tuple = ()
        self._stop_event: Optional[asyncio.Event] = None
        self._busy = False

    # ── settings ─────────────────────────────────────────────────
    def configure(self, **kwargs) -> dict:
        for key, value in (kwargs or {}).items():
            if key not in DEFAULTS:
                continue                       # unknown keys are ignored
            if isinstance(DEFAULTS[key], bool):
                self._settings[key] = bool(value)
            elif isinstance(DEFAULTS[key], int):
                try:
                    self._settings[key] = int(value)
                except (TypeError, ValueError):
                    pass
            else:
                self._settings[key] = str(value or "")
        self.parser.chunk_size = max(1, int(self._settings["chunk_size"]))
        self.parser.chunk_pause_ms = max(0, int(self._settings["chunk_pause_ms"]))
        return self.settings()

    def settings(self) -> dict:
        return dict(self._settings)

    @property
    def my_nick(self) -> str:
        return self._settings.get("my_nick", "")

    @property
    def enabled(self) -> bool:
        return bool(self._settings.get("enabled", True))

    @property
    def running(self) -> bool:
        return self._running

    @property
    def paused(self) -> bool:
        return self._paused

    @property
    def state(self) -> str:
        return self._state

    # ── lifecycle ────────────────────────────────────────────────
    def start(self) -> None:
        self._running = True
        self._paused = False
        if self._stop_event:
            self._stop_event.clear()

    def stop(self) -> None:
        self._running = False
        if self._stop_event:
            self._stop_event.set()

    def pause(self) -> None:
        self._paused = True

    def resume(self) -> None:
        self._paused = False

    def on_run_started(self) -> None:
        """An Action-Stack run began: keep collecting, but stay out of its way."""
        self._throttled = True
        self._emit()

    def on_run_finished(self) -> None:
        self._throttled = False
        self._emit()

    def note_probe_duration(self, seconds: float) -> None:
        """Back off when the page answers slowly (a busy or huge chat)."""
        try:
            value = float(seconds)
        except (TypeError, ValueError):
            return
        self._probe_penalty = max(1.0, min(MAX_PROBE_PENALTY, value / 0.1))

    def next_interval_ms(self) -> int:
        base = int(self._settings["idle_heartbeat_ms" if self._state in
                                  IDLE_STATES else "heartbeat_ms"])
        interval = base * self._probe_penalty
        if self._throttled:
            interval *= max(1, int(self._settings["throttle_factor"]))
        return int(interval)

    async def run(self) -> None:
        """The heartbeat loop. Exits promptly when `stop()` is called."""
        self._stop_event = asyncio.Event()
        self.start()
        while self._running:
            try:
                await self.tick()
            except Exception as e:                    # noqa: BLE001
                log.warning("collector tick failed: %s", e)
            if not self._running:
                break
            try:
                await asyncio.wait_for(self._stop_event.wait(),
                                       timeout=self.next_interval_ms() / 1000.0)
            except asyncio.TimeoutError:
                pass

    # ── the heartbeat ────────────────────────────────────────────
    async def tick(self) -> str:
        if not self._running:
            return self._set(CollectorState.OFF, "Collector stopped")
        if not self.enabled:
            return self._set(CollectorState.OFF, "Collector is off")
        if self._paused:
            return self._set(CollectorState.PAUSED, "Paused")
        if not getattr(self.cdp, "is_connected", False):
            return self._set(CollectorState.DISCONNECTED, "Not connected")
        if self._busy:
            return self._state
        self._busy = True
        started = self.now()
        try:
            return await self._tick()
        except Exception as e:                        # noqa: BLE001
            self._error = str(e)
            return self._set(CollectorState.ERROR, f"Collector error: {e}")
        finally:
            self._busy = False
            try:
                self.note_probe_duration(
                    (self.now() - started).total_seconds())
            except Exception:                         # noqa: BLE001
                pass

    async def _tick(self) -> str:
        state = await self.parser.state()
        if not int(state.get("agent") or 0):
            await self.parser.install()
            self._self_heals += 1
            state = await self.parser.state()
        self._agent = int(state.get("agent") or 0)
        self._error = ""

        if not state.get("ok", True):
            return self._set(CollectorState.NOT_PRIVATE,
                             "Not in private tab now")
        if state.get("tab") != "private":
            return self._set(CollectorState.NOT_PRIVATE,
                             "Not in private tab now")
        participants = int(state.get("participants") or 0)
        if self._settings["require_two_participants"] and participants != 2:
            return self._set(CollectorState.GROUP_TAB,
                             f"Group tab ({participants} people) — not collected")

        nick = " ".join(str(state.get("partner") or "").split()).strip()
        if not nick:
            return self._set(CollectorState.NOT_PRIVATE,
                             "Not in private tab now")
        my_nick = self.my_nick or " ".join(
            str(state.get("me") or "").split()).strip()
        if my_nick and nick.lower() == my_nick.lower():
            return self._set(CollectorState.NOT_PRIVATE,
                             "Partner is ambiguous (same as My Nick)")

        self._warning = ("" if self.my_nick else
                         "My Nick is not set — set it in the header so the "
                         "archive knows who 'me' is")
        if nick != self._nick:
            self._nick = nick
            self._added = 0

        person_id = await self.repo.ensure_person(nick)
        cursor = await self.repo.get_cursor(person_id)
        head_sig = _signature(state.get("head"))
        tail_sig = _signature(state.get("tail"))
        count = int(state.get("count") or 0)
        unchanged = (cursor["bootstrapped"] and count == cursor["dom_count"]
                     and tail_sig and tail_sig == cursor["tail_sig"]
                     and head_sig == cursor["head_sig"])
        person = await self.repo.get_person_by_id(person_id) or {}
        self._total = int(person.get("message_count") or 0)
        if unchanged:
            self._added = 0
            return self._set(CollectorState.NO_NEW, "No new messages")

        bootstrap = not cursor["bootstrapped"]
        self._set(CollectorState.BOOTSTRAPPING if bootstrap
                  else CollectorState.COLLECTING,
                  f"Collecting from {nick}…")

        result = await self._sync(nick, my_nick, bootstrap)
        self._added = result.added
        self._total = result.total
        if self.media is not None and self._settings["download_media"]:
            try:
                await self.media.process_pending()
                await self.media.evict_if_needed()
            except Exception as e:                    # noqa: BLE001
                log.debug("media caching skipped: %s", e)

        suffix = " (throttled — a run is active)" if self._throttled else ""
        if result.added:
            self._notify_appended(nick, [], result.added, result.total)
            return self._set(CollectorState.COLLECTED,
                             f"Collected {result.added} new "
                             f"message{'s' if result.added != 1 else ''} "
                             f"from {nick}{suffix}")
        if not result.ok:
            return self._set(CollectorState.NOT_PRIVATE,
                             "Not in private tab now")
        return self._set(CollectorState.NO_NEW, "No new messages")

    async def _sync(self, nick: str, my_nick: str, bootstrap: bool):
        cap = int(self._settings["max_bootstrap"] or 0) if bootstrap else 0
        kwargs = dict(my_nick=my_nick,
                      require_private=bool(self._settings["require_private"]),
                      verify_partner=True,
                      max_messages=cap or None,
                      now=self.now())
        if self.lease is not None:
            async with self.lease.low():
                return await sync_conversation(self.parser, self.repo, nick,
                                               **kwargs)
        return await sync_conversation(self.parser, self.repo, nick, **kwargs)

    # ── the live push channel ────────────────────────────────────
    async def handle_push(self, payload) -> int:
        """Store what the in-page observer pushed. Never raises."""
        if not self._nick or not self.enabled or self._paused:
            return 0
        items = self._records(payload)
        if not items:
            return 0
        try:
            result = await self.repo.append(self._nick, items,
                                            my_nick=self.my_nick,
                                            align=False, now=self.now())
        except Exception as e:                        # noqa: BLE001
            log.warning("push append failed: %s", e)
            return 0
        if result.added:
            self._added = result.added
            self._total = result.total
            self._notify_appended(self._nick, items, result.added,
                                  result.total)
            self._set(CollectorState.COLLECTED,
                      f"Collected {result.added} new "
                      f"message{'s' if result.added != 1 else ''} "
                      f"from {self._nick}")
        return result.added

    @staticmethod
    def _records(payload) -> list:
        data = payload
        if isinstance(data, (bytes, bytearray)):
            data = data.decode("utf-8", "replace")
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except (TypeError, ValueError):
                return []
        if isinstance(data, dict):
            data = data.get("items")
        if not isinstance(data, list):
            return []
        return [item for item in data if isinstance(item, dict)]

    def _notify_appended(self, nick: str, items: list, added: int,
                         total: int) -> None:
        try:
            self.history_appended.emit(json.dumps(
                {"nick": nick, "my_nick": self.my_nick, "items": items,
                 "added": added, "total": total}, ensure_ascii=False))
        except Exception as e:                        # noqa: BLE001
            log.debug("history_appended emit failed: %s", e)

    # ── status ───────────────────────────────────────────────────
    def state_payload(self) -> dict:
        return {
            "state": self._state,
            "text": self._text,
            "nick": self._nick,
            "my_nick": self.my_nick,
            "added": self._added,
            "total": self._total,
            "throttled": self._throttled,
            "error": self._error,
            "warning": self._warning,
            "self_heals": self._self_heals,
            "agent": self._agent,
            "paused": self._paused,
            "running": self._running,
            "enabled": self.enabled,
            "interval_ms": self.next_interval_ms(),
            "settings": self.settings(),
        }

    def _set(self, state: str, text: str) -> str:
        self._state = state
        self._text = text
        self._emit()
        return state

    def _emit(self) -> None:
        payload = self.state_payload()
        signature = (payload["state"], payload["text"], payload["nick"],
                     payload["added"], payload["total"], payload["throttled"],
                     payload["error"], payload["warning"])
        if signature == self._last_emitted:
            return                                   # never spam the UI
        self._last_emitted = signature
        try:
            self.status_changed.emit(json.dumps(payload, ensure_ascii=False))
        except Exception as e:                       # noqa: BLE001
            log.debug("status emit failed: %s", e)
