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

from core.events import EventBus, PeopleChanged, UsersDeleted
from services.wiring_requests import PeopleDeps  # noqa: F401  (re-exported)
from core.result import Err, Ok, Result
from services.service_log import emit_log

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

    def __init__(self, deps: PeopleDeps):
        # The world collaborators travel as one `PeopleDeps` (Round G step 4).
        self._memory = deps.memory
        self._engine = deps.engine
        self._labels = deps.labels
        self._undo = deps.undo
        self._bus = deps.bus or EventBus()

    # ── wiring (main.py / attach_history) ────────────────────────
    def attach(self, deps: PeopleDeps) -> None:
        """Re-wire: only the deps fields that are set replace the current."""
        if deps.memory is not None:
            self._memory = deps.memory
        if deps.engine is not None:
            self._engine = deps.engine
        if deps.labels is not None:
            self._labels = deps.labels
        if deps.undo is not None:
            self._undo = deps.undo
        if deps.bus is not None:
            self._bus = deps.bus

    # ── helpers ──────────────────────────────────────────────────
    def _log(self, message: str, level: str = "info") -> None:
        emit_log(self._bus, message, level)

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

    async def apply(self, rows: list, forward: bool = False) -> Result[int]:
        """Restore the people list to a snapshot (undo/redo of a people
        entry, or an archive delete that carried the queue row).

        This is the ONLY line a people undo writes: `undo_apply._log_command`
        does not announce the intent for a kind that reports itself
        (SYSTEM_OF_RECORD I-22), so the arrow here has to carry the direction —
        `forward` is a redo re-applying the entry's "after" snapshot.
        """
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
        self._log(f"{'↪' if forward else '↩'} People list restored — "
                  f"{count} person(s)", "info")
        self._bus.emit(PeopleChanged(reason="restored"))
        return Ok(count)
