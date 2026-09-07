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

from backend import chat_agent_js
from backend.chat_parser import (ChatParser, _signature, sync_conversation,
                                 verify_private)
from backend.history_repo import HistoryRepo
from backend.user_memory import UserMemory, UserRecord

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
    "auto_backfill": True,       # scroll to top once per person for full history
    "backfill_wait_s": 2.0,
}

MAX_PROBE_PENALTY = 4.0


class Collector(QObject):
    """Non-blocking background monitor of the active conversation."""

    status_changed = Signal(str)        # json state payload
    history_appended = Signal(str)      # json {nick, items, added, total}
    people_changed = Signal(str)        # json {nick, kind, source}

    def __init__(self, cdp, repo: HistoryRepo, parser: ChatParser,
                 media=None, settings: Optional[dict] = None,
                 lease=None, memory=None, parent=None):
        super().__init__(parent)
        self.cdp = cdp
        self.repo = repo
        self.parser = parser
        self.media = media
        self.lease = lease
        self.memory = memory
        self._settings = dict(DEFAULTS)
        self.configure(**(settings or {}))
        self.now = datetime.now

        self._state = CollectorState.DISCONNECTED
        self._text = ""
        self._nick = ""
        self._verified = False      # the two-step gate passed for _nick
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
        self._force_backfill = False
        self._backfill_pending = False
        self._detected_my_nick = ""

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
        if int(state.get("agent") or 0) < chat_agent_js.AGENT_VERSION:
            # No agent, or one that predates the pane-scoped parser: an old
            # agent cannot tell us who wrote what, so it may not be trusted.
            await self.parser.install()
            self._self_heals += 1
            state = await self.parser.state()
        self._agent = int(state.get("agent") or 0)
        self._error = ""

        if not state.get("ok", True):
            return self._refuse(CollectorState.NOT_PRIVATE,
                                "Not in private tab now")
        if state.get("tab") != "private":
            return self._refuse(CollectorState.NOT_PRIVATE,
                                "Not in private tab now")
        participants = int(state.get("participants") or 0)
        if self._settings["require_two_participants"] and participants != 2:
            return self._refuse(
                CollectorState.GROUP_TAB,
                f"Group tab ({participants} people) — not collected")

        nick = " ".join(str(state.get("partner") or "").split()).strip()
        if not nick:
            return self._refuse(CollectorState.NOT_PRIVATE,
                                "Not in private tab now")

        # My Nick is optional for the archive: in a verified two-person chat
        # the single outbound author IS me, so we adopt it for this session
        # (it is not persisted to config.json unless the user saves it).
        detected_me = " ".join(str(state.get("me") or "").split()).strip()
        if not detected_me:
            outs = [str(o or "").strip() for o in
                    (state.get("out_authors") or [])]
            singles = [o for o in outs if o]
            if len(singles) == 1 and singles[0].lower() != nick.lower():
                detected_me = singles[0]
        if not self.my_nick and detected_me:
            self.configure(my_nick=detected_me)
            self._detected_my_nick = detected_me

        my_nick = self.my_nick or detected_me
        if my_nick and nick.lower() == my_nick.lower():
            return self._refuse(CollectorState.NOT_PRIVATE,
                                "Partner is ambiguous (same as My Nick)")

        # A verified private tab (active tab = private, 2 participants, title
        # names the partner) is enough to create the person in BOTH stores.
        # The author gate below protects the message rows from a mixed pane;
        # the People row itself is safe even before that check passes.
        person_id = await self.repo.ensure_person(nick)
        await self._remember_partner(nick, state)

        # ── the two-step gate ─────────────────────────────────────
        check = verify_private(state, nick, self.my_nick)
        if not check.ok:
            self._nick = nick
            return self._refuse(*self._gate_status(check, nick))
        self._verified = True
        if check.me and not self._detected_my_nick:
            self._detected_my_nick = check.me

        self._warning = ("" if self.my_nick else
                         "My Nick is not known yet — the archive will use "
                         "the single outbound author as 'me'")
        if nick != self._nick:
            self._nick = nick
            self._added = 0

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
        full_scan_complete = bool(cursor.get("full_scan_complete"))
        want_backfill = ((bool(self._settings.get("auto_backfill", True))
                          and not full_scan_complete
                          and not self._backfill_pending)
                         or self._force_backfill)
        self._force_backfill = False
        self._set(CollectorState.BOOTSTRAPPING if bootstrap
                  else CollectorState.COLLECTING,
                  f"Collecting from {nick}…")

        result = await self._sync(nick, my_nick, bootstrap,
                                  backfill_older=want_backfill)
        self._backfill_pending = bool(result.backfill_pending)
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

    async def _sync(self, nick: str, my_nick: str, bootstrap: bool,
                    backfill_older: bool = False):
        cap = int(self._settings["max_bootstrap"] or 0) if bootstrap else 0
        kwargs = dict(my_nick=my_nick,
                      require_private=bool(self._settings["require_private"]),
                      verify_partner=True,
                      max_messages=cap or None,
                      backfill_older=backfill_older,
                      backfill_wait_s=float(self._settings.get("backfill_wait_s", 2.0)),
                      now=self.now())
        if self.lease is not None:
            async with self.lease.low():
                return await sync_conversation(self.parser, self.repo, nick,
                                               **kwargs)
        return await sync_conversation(self.parser, self.repo, nick, **kwargs)

    async def _remember_partner(self, nick: str, state: Optional[dict] = None) -> str:
        """Make sure the partner exists in BOTH the archive and the People list.

        The archive person is created by `HistoryRepo.ensure_person` regardless
        of whether any message lines were written yet; the People Memory row is
        only added when this app owns a UserMemory (production does, tests may
        not). Nothing is marked messaged — appearing in a private chat is not
        the same as having been messaged by an action run.
        """
        clean = self.repo.normalise_nick(nick)
        await self.repo.ensure_person(clean)
        if self.memory is None:
            return "archive_only"
        try:
            existing = await self.memory.get_user(clean)
            if existing:
                # refresh last_seen without touching the messaged flag
                await self.memory.upsert_user(
                    UserRecord(nick=clean,
                               gender=existing.gender,
                               registered=existing.registered,
                               anonymous=existing.anonymous,
                               guest=existing.guest,
                               messaged=existing.messaged,
                               message_count=existing.message_count,
                               last_messaged=existing.last_messaged,
                               notes=existing.notes))
                return "known"
            result = await self.memory.upsert_user(UserRecord(nick=clean))
            if result == "new":
                self._notify_people(clean, "new")
            return result
        except Exception as e:                       # noqa: BLE001
            log.warning("cannot add %s to the People list: %s", clean, e)
            return "error"

    def _notify_people(self, nick: str, kind: str) -> None:
        try:
            self.people_changed.emit(json.dumps(
                {"nick": nick, "kind": kind, "source": "collector"},
                ensure_ascii=False))
        except Exception as e:                       # noqa: BLE001
            log.debug("people_changed emit failed: %s", e)

    async def backfill_older(self) -> str:
        """Force one scroll-to-top full-history pass for the current person."""
        if not self._nick:
            return self._state
        try:
            await self.repo.reset_cursor(self._nick)
        except Exception as e:                        # noqa: BLE001
            self._error = str(e)
            return self._set(CollectorState.ERROR, f"Backfill failed: {e}")
        self._set(CollectorState.COLLECTING,
                  f"Backfilling older messages from {self._nick}…")
        self._force_backfill = True
        self._backfill_pending = False
        return await self.tick()

    # ── the gate helpers ─────────────────────────────────────────
    def _refuse(self, state: str, text: str) -> str:
        """Refuse to save: the push channel is disarmed with the tick."""
        self._verified = False
        return self._set(state, text)

    @staticmethod
    def _gate_status(check, nick: str) -> tuple:
        """Turn a failed PrivateCheck into (state, status text)."""
        if check.reason == "strangers":
            shown = ", ".join(check.strangers[:3])
            if len(check.strangers) > 3:
                shown += "…"
            return (CollectorState.GROUP_TAB,
                    f"Not a private chat — {shown} write here too "
                    f"(nothing saved for {nick})")
        if check.reason == "title_mismatch":
            return (CollectorState.NOT_PRIVATE,
                    f"Tab does not match “{nick}” — nothing saved")
        if check.reason == "self_chat":
            return (CollectorState.NOT_PRIVATE,
                    "Partner is ambiguous (same as My Nick)")
        if check.reason == "no_author_data":
            return (CollectorState.NOT_PRIVATE,
                    "Cannot verify this chat yet — nothing saved")
        return (CollectorState.NOT_PRIVATE, "Not in private tab now")

    # ── the live push channel ────────────────────────────────────
    async def handle_push(self, payload) -> int:
        """Store what the in-page observer pushed. Never raises."""
        if not self._nick or not self.enabled or self._paused:
            return 0
        data = self._payload(payload)
        items = self._records(data)
        if not items:
            return 0
        if not self._verified:
            # No tick has verified this conversation (or the last one
            # refused it): the observer may be describing another pane.
            return 0
        check = verify_private(
            {"tab": data.get("tab") or "private",
             "partner": data.get("partner") or self._nick,
             "title": data.get("title") or data.get("partner") or "",
             "me": data.get("me") or ""},
            self._nick, self.my_nick, items=items)
        if not check.ok:
            self._refuse(*self._gate_status(check, self._nick))
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
            "detected_my_nick": self._detected_my_nick,
            "added": self._added,
            "total": self._total,
            "throttled": self._throttled,
            "backfill_pending": self._backfill_pending,
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
                     payload["backfill_pending"], payload["error"],
                     payload["warning"])
        if signature == self._last_emitted:
            return                                   # never spam the UI
        self._last_emitted = signature
        try:
            self.status_changed.emit(json.dumps(payload, ensure_ascii=False))
        except Exception as e:                       # noqa: BLE001
            log.debug("status emit failed: %s", e)
