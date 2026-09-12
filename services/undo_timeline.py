"""TimelineCommit — writing the ONE global undo timeline (AREA C split).

`services/undo_service.py` keeps the timeline state machine (push / undo /
redo / projections); this collaborator owns what happens when the timeline
is written:

* `commit` stamps the entry identity (`seq`), splits the ONE line by
  ownership (app half → `config/undo.json`, world half → the active world's
  `undo_history` table) and erases the rows whose undo step just left it;
* `spawn` runs the async half of a step (the trash purge, an archive
  command) and logs a task that dies — a task that dies silently is what let
  a locked world keep a person deleted while the log said “archive restored”
  (bug 2026-09-11).

The timeline POINTER and the failure rewind (`rewind_after_failure`) stay on
`UndoService`, which owns the state machine; no `rewind` lives here.

Imports point down only: stdlib, `core.events` and nothing that imports this
file (the host is duck-typed, like `services/undo_support.py` does it).
"""

from __future__ import annotations

import asyncio
import copy
import logging
from typing import Optional


log = logging.getLogger("chatbot")


def _archive_token(entry) -> str:
    """The token of an archive entry — the rows a delete is keeping hidden."""
    if not isinstance(entry, dict) or entry.get("kind") != "archive":
        return ""
    value = entry.get("value")
    if not isinstance(value, dict):
        return ""
    return str(value.get("token") or "")


class TimelineCommit:
    """Persist the ONE timeline and erase what its dropped steps hid."""

    def __init__(self, host):
        self._host = host

    # ── the commit ───────────────────────────────────────────────
    def commit(self, history: list, index: int,
               purge_dropped: bool = True) -> None:
        """Persist the ONE timeline split by ownership (app vs world).

        `purge_dropped` erases the rows kept alive by archive entries that
        just left the timeline (the cap, or a new edit truncating the redo
        branch): once nothing can reach them, they are erased for good.
        A world CHANGE passes False — the old world's rows are not this
        world's to erase, and the old world sweeps them when it reopens.
        """
        host = self._host
        dropped = self._dropped_tokens(history) if purge_dropped else []
        self._stamp_seq(history)
        host._timeline = history
        host._h_index = index
        host._seq_next = self._next_seq(history)
        self._store_timeline(history, index)
        self._purge_tokens(dropped)

    def _next_seq(self, history: list) -> int:
        """One past the highest seq the timeline already carries."""
        return max([e["seq"] for e in history
                    if isinstance(e, dict) and isinstance(e.get("seq"), int)],
                   default=0) + 1

    def _stamp_seq(self, history: list) -> None:
        """Give every entry the identity the merge keys off (seq)."""
        for entry in history:
            if isinstance(entry, dict) and (
                    not isinstance(entry.get("seq"), int)
                    or entry["seq"] <= 0):
                entry["seq"] = self._host._next_seq()

    def _store_timeline(self, history: list, index: int) -> None:
        """Write the app half to config.json and the world half to the world."""
        host = self._host
        service = host._archive
        if service is None or not getattr(service.db, "is_open", False):
            host._config.set_state(
                undo_history=copy.deepcopy(history),
                undo_history_index=index)
            return
        app_entries, world_entries = host._world_store.split(history)
        host._config.set_state(undo_history=copy.deepcopy(app_entries),
                               undo_history_index=index)
        host._world_store.schedule_save(world_entries)

    def _dropped_tokens(self, history: list) -> list:
        """The archive tokens whose undo entry just left the timeline."""
        keep = {_archive_token(entry) for entry in history}
        seen = {_archive_token(entry) for entry in (self._host._timeline or [])}
        return sorted(token for token in seen - keep if token)

    def _purge_tokens(self, tokens: list) -> None:
        """Erase what the dropped steps were hiding (best effort, async).

        A step that leaves the timeline takes its data with it: past the undo
        memory there is no restore, so the rows are erased for good and the
        log says how many.
        """
        service = self._host._archive
        if service is None or not tokens:
            return

        async def work():
            erased = await service.purge_tokens(list(tokens))
            if erased.get("persons") or erased.get("messages"):
                self._host._log(
                    f"🔥 {erased['messages']} hidden message(s) and "
                    f"{erased['persons']} removed person(s) erased — their "
                    "undo step left the history", "warn")

        self.spawn("trash purge", work())

    # ── async steps ──────────────────────────────────────────────
    def spawn(self, scope: str, coro) -> bool:
        """Run the async half of a step; a dying task is never silent."""
        task = self._schedule_task(coro)
        if task is None:
            return False
        task.add_done_callback(lambda done: self._crash_log(scope, done))
        return True

    @staticmethod
    def _schedule_task(coro) -> Optional[asyncio.Task]:
        """Run `coro` now; None when there is no loop to run it on."""
        try:
            return asyncio.ensure_future(coro)
        except RuntimeError:
            coro.close()
            return None

    @staticmethod
    def _crash_log(scope: str, task) -> None:
        """A background step that dies must never do so silently."""
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            log.warning("%s failed: %s", scope, exc)
