"""Undo/redo of the COMMAND kinds — entries that carry an edit, not a snapshot.

`stack` and `grid` entries ARE the state, so walking onto one restores it
(`snapshots.py`). The four COMMAND kinds (`people`, `labels`, `archive`,
`dbconn`) carry `{before, after}` or an op description, so applying one means
running the edit in the given direction — and the direction matters: undo
applies `before`, redo applies `after`.

`CommandsMixin` owns three of the four; `dbconn` is big enough for its own
leaf (`dbconn.py`). Two rules make this file what it is:

* **A refusal is an error, never a success.** When a half is missing
  (`after=None`) or the store is not attached, `apply_command` returns `False`
  and the caller (`walking.py`) answers `Err(...)` — and
  `rewind_after_failure` puts the pointer back where `Ctrl+Z` finds the entry
  again, so the next key press retries the same command instead of skipping a
  state the database never reached.
* **Archive commands verify themselves.** `_apply_archive_command` spawns ONE
  task (`services/undo_archive.py`) that applies the command, reads the
  database back and reports what the rows now show. Announcing success from
  the *intent* is what let a locked database keep a person deleted while the
  log said "archive restored" (bug 2026-09-11), which is also why `_log_command`
  stays quiet for archive entries: they report themselves later, with the
  database state they actually produced.

Extracted unchanged from `services/undo_service.py` (god-class round, step 7).
See `docs/archive/2026-09-13-god-classes/STEP7_UNDO_SERVICE_DESIGN_2026-09-13.md`.
"""

from __future__ import annotations

import json
from typing import Optional

from core.events import LabelsChanged, PeopleChanged, UndoHistoryChanged
from services.undo_archive import ArchiveCommands

from .entries import _position_of


def _apply_people_command(host, value: dict, forward: bool) -> bool:
    """Restore / re-apply the people-list snapshot the entry carries."""
    rows = value.get("after" if forward else "before")
    if rows is None or host._people is None:
        return False
    host._timeline_commit.spawn("people restore", host._people.apply(rows))
    return True


def _apply_labels_command(host, value: dict, forward: bool) -> bool:
    """Restore / re-apply the label snapshot the entry carries."""
    snapshot = value.get("after" if forward else "before")
    if not isinstance(snapshot, dict) or host._labels is None:
        return False
    host._labels.restore(snapshot)
    host._bus.emit(LabelsChanged(
        payload=json.dumps(host._labels.state(), ensure_ascii=False)))
    # labels can hide people from the queue: the # column changes
    host._bus.emit(PeopleChanged(reason="labels"))
    return True


def _log_command(host, entry: dict, forward: bool) -> None:
    """Announce a command entry; archive ones report themselves later,
    with the database state they actually produced."""
    kind = entry.get("kind")
    if kind == "archive":
        return
    host._log(f"{'↪ Redo' if forward else '↩ Undo'} — "
              + host.UNDO_LABELS.get(kind, kind + " restored"), "info")


class CommandsMixin:
    """Apply a command entry in either direction, and rewind when it refuses."""

    def apply_command(self, entry, forward: bool) -> bool:
        """Apply one command entry forward (redo) or backward (undo)."""
        kind = entry.get("kind")
        value = entry.get("value")
        if not isinstance(value, dict):
            return False
        if kind == "people":
            return _apply_people_command(self, value, forward)
        if kind == "labels":
            return _apply_labels_command(self, value, forward)
        if kind == "archive":
            return self._apply_archive_command(value, forward, entry)
        if kind == "dbconn":
            return self._apply_db_command(value, forward)
        return False

    def _apply_archive_command(self, value: dict, forward: bool,
                               entry: Optional[dict] = None) -> bool:
        """Reverse / re-apply a message, chat or person deletion (soft).

        The work is ONE self-verifying task (`services/undo_archive.py`):
        it applies the command, reads the database back, reports what the
        rows now show — and, when it cannot, says so and leaves the entry
        where Ctrl+Z finds it again. Announcing success from the *intent* is
        what let a locked database keep a person deleted while the log said
        “archive restored” (bug 2026-09-11).
        """
        if str(value.get("op") or "") not in ArchiveCommands.OPS:
            return False
        if self._archive is None and self._people is None:
            return False
        return self._timeline_commit.spawn("archive undo",
                           self._archive_commands.run(entry, value, forward))

    def rewind_after_failure(self, entry: Optional[dict],
                             forward: bool) -> None:
        """A command that could not be applied stays where Ctrl+Z finds it.

        A failed undo puts the pointer back ON the entry and a failed redo
        puts it back IN FRONT of it, so the next key press tries the same
        command again instead of skipping a state the database never reached.
        """
        if not isinstance(entry, dict):
            return
        history, index = self.history()
        at = _position_of(history, entry)
        if at < 0:
            return
        target = max(0, min(at - 1 if forward else at, len(history) - 1))
        if target != index:
            self.set_history(history, target)
            self._bus.emit(UndoHistoryChanged())
