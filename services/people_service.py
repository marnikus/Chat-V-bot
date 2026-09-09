"""PeopleService — the people queue's business logic.

Extracted from the bridge monolith (2026-09-09): snapshots, mutations,
undo entries and the users/stats payload the People table renders. Every
method returns ``Result``; domain failures are typed, not thrown.

Qt-free: outcomes are announced on the EventBus (PeopleChanged,
UsersDeleted, LogMessage); the PeopleBridge subscribes and forwards them
to JS signals.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from core.events import EventBus, LogMessage, PeopleChanged, UsersDeleted
from core.result import Err, Ok, Result

log = logging.getLogger("chatbot")


def people_row(u) -> dict:
    """Full serialisable row for one person (every DB column)."""
    return {"nick": u.nick, "gender": u.gender,
            "registered": bool(u.registered),
            "anonymous": bool(u.anonymous), "guest": bool(u.guest),
            "first_seen": u.first_seen or "", "last_seen": u.last_seen or "",
            "messaged": bool(u.messaged),
            "message_count": int(u.message_count or 0),
            "last_messaged": u.last_messaged, "notes": u.notes or ""}


class PeopleService:
    """Snapshot → mutate → undo-entry → announce, for the people queue."""

    def __init__(self, memory, engine=None, labels=None, undo=None,
                 bus: EventBus | None = None):
        self._memory = memory
        self._engine = engine
        self._labels = labels
        self._undo = undo
        self._bus = bus or EventBus()

    # ── wiring (main.py / attach_history) ────────────────────────
    def attach(self, memory=None, engine=None, labels=None, undo=None,
               bus=None) -> None:
        if memory is not None:
            self._memory = memory
        if engine is not None:
            self._engine = engine
        if labels is not None:
            self._labels = labels
        if undo is not None:
            self._undo = undo
        if bus is not None:
            self._bus = bus

    # ── helpers ──────────────────────────────────────────────────
    def _log(self, message: str, level: str = "info") -> None:
        self._bus.emit(LogMessage(message=message, level=level))

    def labels_for_nicks(self, nicks) -> dict:
        """nick → label ids, joined at read time (never stored per DB)."""
        if self._labels is None:
            return {}
        try:
            return self._labels.labels_map(nicks)
        except Exception as exc:                        # noqa: BLE001
            log.warning("labels unavailable: %s", exc)
            return {}

    # ── snapshots ────────────────────────────────────────────────
    async def rows(self) -> list[dict]:
        """Full snapshot of the people list (all columns)."""
        users = await self._memory.get_all()
        return [people_row(u) for u in users]

    async def payload(self) -> Result[dict]:
        """The users_updated + stats_updated payload in one Result.

        The '#' column (order) mirrors the queue a run would build right
        now; labels are joined from the (world-bound) label store.
        """
        try:
            return Ok(await self._build_payload())
        except Exception as exc:                        # noqa: BLE001
            log.warning("people payload failed: %s", exc)
            return Err("payload_failed", str(exc))

    async def _build_payload(self) -> dict:
        users = await self._memory.get_all()
        ranks: dict[str, int] = {}
        try:
            ordered = self._engine.queue_order(users)
            ranks = {nick: i + 1 for i, nick in enumerate(ordered)}
        except Exception:                               # noqa: BLE001
            queue = await self._memory.get_queue()
            ranks = {u.nick: i + 1 for i, u in enumerate(queue)}
        labels = self.labels_for_nicks([u.nick for u in users])
        return {
            "users": [{"nick": u.nick, "gender": u.gender,
                       "registered": u.registered, "anonymous": u.anonymous,
                       "guest": u.guest, "messaged": u.messaged,
                       "first_seen": u.first_seen,
                       "last_messaged": u.last_messaged,
                       "order": ranks.get(u.nick),
                       "labels": labels.get(u.nick, [])}
                      for u in users],
            "stats": await self._memory.get_stats(),
        }

    # ── undo integration ─────────────────────────────────────────
    async def _push_entry(self, before: list[dict], after: list[dict]) -> bool:
        """Record one people-list edit as ONE reversible timeline entry."""
        if before == after or self._undo is None:
            return False
        return bool(self._undo.push("people",
                                    {"before": before, "after": after}))

    # ── mutations (each: snapshot → mutate → undo → announce) ────
    async def delete_one(self, nick: str) -> Result[int]:
        clean = (nick or "").strip()
        if not clean:
            self._log("⚠ No nick given — nothing deleted", "warn")
            return Err("empty_nick", "no nick given")
        before = await self.rows()
        try:
            ok = await self._memory.delete_user(clean)
        except Exception as exc:                        # noqa: BLE001
            self._log(f"❌ Delete failed for “{clean}”: {exc}", "error")
            self._bus.emit(PeopleChanged(reason="error"))
            return Err("delete_failed", str(exc))
        if not ok:
            self._log(f"⚠ User “{clean}” not found", "warn")
            self._bus.emit(PeopleChanged(reason="noop"))
            return Ok(0)
        self._log(f"🗑 Deleted user “{clean}”", "warn")
        await self._push_entry(before, await self.rows())
        self._bus.emit(UsersDeleted(
            nicks_json=json.dumps([clean], ensure_ascii=False), count=1))
        self._bus.emit(PeopleChanged(reason="deleted", nicks=(clean,)))
        return Ok(1)

    async def delete_many(self, nicks: list) -> Result[int]:
        if not nicks:
            self._log("⚠ Nothing selected — nothing deleted", "warn")
            return Err("empty_selection", "nothing selected")
        before = await self.rows()
        try:
            count = await self._memory.delete_users(nicks)
        except Exception as exc:                        # noqa: BLE001
            self._log(f"❌ Delete failed: {exc}", "error")
            self._bus.emit(PeopleChanged(reason="error"))
            return Err("delete_failed", str(exc))
        if count:
            await self._push_entry(before, await self.rows())
        self._log(
            f"🗑 Deleted {count} selected user(s)"
            + (f": {', '.join(nicks[:5])}" + ("…" if len(nicks) > 5 else "")
               if count else ""), "warn")
        self._bus.emit(UsersDeleted(
            nicks_json=json.dumps(nicks, ensure_ascii=False), count=count))
        self._bus.emit(PeopleChanged(reason="deleted",
                                     nicks=tuple(nicks)))
        return Ok(count)

    async def set_messaged(self, nick: str, messaged: bool) -> Result[bool]:
        before = await self.rows()
        try:
            ok = await self._memory.set_messaged(nick, messaged)
        except Exception as exc:                        # noqa: BLE001
            self._log(f"❌ Update failed for “{nick}”: {exc}", "error")
            self._bus.emit(PeopleChanged(reason="error"))
            return Err("update_failed", str(exc))
        if ok:
            self._log(
                f"{'✅' if messaged else '↩'} “{nick}” marked as "
                f"{'messaged' if messaged else 'new'}", "info")
            await self._push_entry(before, await self.rows())
            self._bus.emit(PeopleChanged(reason="marked", nicks=(nick,)))
        return Ok(ok)

    async def reset_messaged(self) -> Result[int]:
        before = await self.rows()
        count = await self._memory.reset_messaged()
        self._log(f"🔄 Reset {count} users", "info")
        if count:
            await self._push_entry(before, await self.rows())
            self._bus.emit(PeopleChanged(reason="reset"))
        return Ok(count)

    async def clear_all(self) -> Result[int]:
        before = await self.rows()
        count = await self._memory.clear_all()
        self._log(f"🗑 Cleared {count} users", "warn")
        if count:
            await self._push_entry(before, await self.rows())
        self._bus.emit(UsersDeleted(nicks_json="[]", count=count))
        self._bus.emit(PeopleChanged(reason="cleared"))
        return Ok(count)

    async def apply(self, rows: list) -> Result[int]:
        """Restore the people list to a snapshot (undo/redo of a people
        entry, or an archive delete that carried the queue row)."""
        rows = [dict(r) for r in (rows or [])]
        try:
            count = await self._memory.replace_all(rows)
        except Exception as exc:                        # noqa: BLE001
            self._log(f"❌ People-list restore failed: {exc}", "error")
            return Err("restore_failed", str(exc))
        # the store reports how many rows actually landed (blank nicks are
        # skipped there) — report that, not the raw snapshot length
        count = int(count) if isinstance(count, int) else \
            sum(1 for r in rows if str(r.get("nick") or "").strip())
        self._log(f"↩ People list restored — {count} person(s)", "info")
        self._bus.emit(PeopleChanged(reason="restored"))
        return Ok(count)
