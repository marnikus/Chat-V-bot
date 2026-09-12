"""The archive half of an undo entry — apply it, prove it, report it.

`services/undo_service.py` owns WHEN a command runs (the ONE global
timeline); this collaborator owns HOW: it applies both halves of an archive
entry (the People-list snapshot and the archive rows), reads the world back
and reports only what the rows now show.

It exists because of the bug of 2026-09-11. The old
`UndoService._apply_archive_command` *scheduled* its work and returned True,
so when the database answered `database is locked` the timeline moved, the
log said “↩ Undo — archive restored”, and the person stayed deleted forever —
the scheduled coroutine's exception had nowhere to go. An archive command is
now ONE task that must prove itself before it is allowed to say anything:

* **Who first, then the rows.** The People-list snapshot is applied before
  the archive write; if the archive half fails, the list half is put back, so
  the queue and the database can never disagree about who exists (RULE 14).
* **Read back before speaking.** The outcome line and the change event are
  built from `HistoryQuery.person_stats` *after* the write, never from the
  intent. An archive that is not running is the one case that reports
  “People list only”, because that is the truth.
* **A refusal is loud.** No success words, an ERROR line the user can see, a
  `UserDbChanged(action="failed")` so the list reloads from the truth, and
  the timeline pointer is put back so the next Ctrl+Z retries the entry.

Direction: `services/` → `stores/` (the write gate). No Qt, no `bridge.*`.
"""

from __future__ import annotations

import asyncio
import json
import logging
from functools import partial
from typing import Optional

from core.events import ArchiveUndoApplied, UserDbChanged
from stores.world_lock import retry_locked

log = logging.getLogger("chatbot")


# ── the settled facts of one command (pure helpers) ──────────────────

def _rows(value: dict, forward: bool):
    """The one People-list snapshot the entry carries, or None."""
    people = value.get("people")
    if not isinstance(people, dict):
        return None
    rows = people.get("after" if forward else "before")
    return rows if isinstance(rows, list) else None


async def _apply(archive, value: dict, forward: bool):
    """The one repository call the command means (safe to run again)."""
    repo = archive.repo
    op = str(value.get("op") or "")
    nick = str(value.get("nick") or "")
    token = str(value.get("token") or "")
    if op == "delete_person":
        if forward:
            return await repo.delete_person(nick, hard=False, token=token)
        return await repo.restore_person(nick, token=token)
    if op == "clear_history":
        if forward:
            return await repo.soft_delete_history(nick, token=token)
        return await repo.restore_deleted(nick, token)
    message_id = int(value.get("message_id") or 0)
    if forward:
        return await repo.soft_delete_message(nick, message_id, token=token)
    return await repo.restore_deleted(nick, token)


async def _state(archive, nick: str) -> Optional[dict]:
    """The database's own view of a person — the only proof that counts.

    None means “no archive to ask”: the app can run without one, and a
    People-only entry must still be undoable.
    """
    if archive is None or not nick:
        return None
    try:
        return await archive.query.person_stats(nick)
    except Exception as exc:                            # noqa: BLE001
        log.warning("archive state for %s unreadable: %s", nick, exc)
        return None


def _disagrees(op: str, forward: bool, before: Optional[dict],
               after: Optional[dict]) -> str:
    """'' when the read-back shows what the command promised."""
    if after is None:
        return ""                     # no archive wired: nothing to check
    if after.get("missing"):
        return "the person is not in this database"
    if op == "delete_person":
        return _person_verdict(forward, after)
    return _row_verdict(forward, before, after)


def _person_verdict(forward: bool, after: dict) -> str:
    """A person delete is proven by the tombstone flag itself."""
    if bool(after.get("deleted")) == forward:
        return ""
    return ("the person is still deleted" if not forward
            else "the person was not deleted")


def _row_verdict(forward: bool, before, after: dict) -> str:
    """A message/chat command is proven by the hidden count moving."""
    moved = int(after.get("hidden") or 0) - int((before or {}).get("hidden") or 0)
    if moved and (moved > 0) == bool(forward):
        return ""
    return ("the messages are still visible" if forward
            else "the messages did not come back")


def _refusal(result) -> str:
    """The human half of a `Result` refusal (`Err` carries code + detail)."""
    return (str(getattr(result, "detail", "") or "")
            or str(getattr(result, "code", "") or "") or "no reason given")


def _reason(exc) -> str:
    """A one-line, human-sized reason for a refused command."""
    text = " ".join(str(exc or "").split()) or exc.__class__.__name__
    return text[:160]


def _outcome(op: str, forward: bool, after: Optional[dict]) -> str:
    """The verified state, in the user's words."""
    if after is None:
        return "restored (no archive is running — People list only)"
    messages = int(after.get("messages") or 0)
    hidden = int(after.get("hidden") or 0)
    if op == "delete_person":
        return (f"is hidden again ({hidden} message(s) hidden)" if forward
                else f"is back in the database ({messages} message(s))")
    if op == "clear_history":
        return (f"history hidden ({hidden} message(s))" if forward
                else f"history restored ({messages} message(s))")
    return "message hidden again" if forward else "message restored"


# ── the task ─────────────────────────────────────────────────────────

class ArchiveCommands:
    """Apply / reverse the archive half of one undo entry, then verify it."""

    #: the operations an archive entry may carry (RULE 12 / RULE 14)
    OPS = ("delete_person", "clear_history", "delete_message")

    def __init__(self, host):
        """`host` is the `UndoService`: archive, people queue, bus, log."""
        self._host = host

    async def _apply(self, entry: Optional[dict], value: dict, forward: bool,
                     rows) -> bool:
        """Both halves under one error policy; False = refused, entry kept."""
        archive = self._host._archive
        try:
            await self._people_half(rows)
            await self._archive_half(archive, value, forward)
        except asyncio.CancelledError:
            raise
        except Exception as exc:                        # noqa: BLE001
            await self._refuse(entry, value, forward, _reason(exc))
            return False
        return True

    async def run(self, entry: Optional[dict], value: dict,
                  forward: bool) -> None:
        """Apply → verify → report ONE archive command (undo or redo)."""
        archive = self._host._archive
        nick = str(value.get("nick") or "")
        rows = _rows(value, forward)
        before = await _state(archive, nick)
        if not await self._apply(entry, value, forward, rows):
            return
        after = await _state(archive, nick)
        problem = _disagrees(str(value.get("op") or ""), forward, before,
                             after)
        if problem:
            await self._refuse(entry, value, forward, problem)
            return
        self._report(value, forward, after)

    async def _people_half(self, rows) -> None:
        """Apply the People half — first, so a failure costs nothing."""
        if rows is None or self._host._people is None:
            return
        result = await self._host._people.apply(rows)
        if result is not None and getattr(result, "is_err", False):
            raise RuntimeError("the people list refused it: "
                               + _refusal(result))

    async def _archive_half(self, archive, value: dict,
                            forward: bool) -> None:
        """Apply the archive half, retrying while the file stays locked."""
        if archive is None:
            return
        await retry_locked(partial(_apply, archive, value, forward))

    async def _refuse(self, entry, value: dict, forward: bool,
                      problem: str) -> None:
        """Report a refused command; leave the world and the timeline intact."""
        nick = str(value.get("nick") or "")
        key = "Ctrl+Y" if forward else "Ctrl+Z"
        self._host._log(
            f"❌ {'Redo' if forward else 'Undo'} failed — “{nick}” could not "
            f"be changed: {problem}. The database is unchanged; press {key} "
            "to try again.", "error")
        await self._put_people_back(value, forward)
        self._host.rewind_after_failure(entry, forward)
        self._host._bus.emit(UserDbChanged(payload=json.dumps(
            {"action": "failed", "op": str(value.get("op") or ""),
             "nick": nick}, ensure_ascii=False)))

    async def _put_people_back(self, value: dict, forward: bool) -> None:
        """Undo the People half so the list matches the untouched rows."""
        try:
            await self._people_half(_rows(value, not forward))
        except Exception as exc:                        # noqa: BLE001
            log.warning("people list could not be put back: %s", exc)

    def _report(self, value: dict, forward: bool,
                after: Optional[dict]) -> None:
        """Say what the database now shows, then let the windows refresh."""
        op = str(value.get("op") or "")
        nick = str(value.get("nick") or "")
        self._host._bus.emit(UserDbChanged(payload=json.dumps(
            {"action": "redo" if forward else "undo", "op": op, "nick": nick,
             "verified": True}, ensure_ascii=False)))
        self._host._log(f"{'↪' if forward else '↩'} "
                        f"{'Redo' if forward else 'Undo'} — “{nick}” "
                        + _outcome(op, forward, after), "info")
        self._host._bus.emit(ArchiveUndoApplied(forward=forward, op=op,
                                                nick=nick))
