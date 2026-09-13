"""The conversation-sync algorithm, in phases — the family seam.

`backend.chat_parser` owns the *probes* (one state probe, one range probe, one
drain) and the private-chat gate. This family owns the *decision*: what to
read given what the archive already holds, and what to write back.

    run_sync(parser, repo, nick, options)                    ← this file
      ├─ SyncSession.prepare()   probe → install → gate → viewport → cursor
      ├─ SyncPlanner.plan()      (state, cursor, options) → ReadPlan   [pure]
      ├─ ChunkReader.read()      paced, retrying, stop-aware range reads
      ├─ DeltaAligner.apply()    what appeared ABOVE what we stored
      ├─ SyncPersister.*         every repo.write, in one place
      └─ SyncSession.finish()    final cursor, totals, reason

Family map (import direction is one-way down the list, and nothing in the
family imports this seam, so it cannot close a cycle — the F1 `db_deletion_*`
pattern):

    chat_sync_options   SyncOptions — the eleven knobs of one sync
    chat_sync_plan      MODE_*, ReadPlan, SyncPlanner — the pure decision
    chat_sync_persist   merge_live, SyncPersister — every archive write
    chat_sync_read      SLICE_RETRIES, ChunkReader, DeltaAligner
    chat_sync_session   SyncViewport, SyncSession — the shared run state

The split is internal: `backend.chat_parser.sync_conversation()` keeps its
exact 14-parameter signature and delegates here, so `services/collector_service`
and the `COLLECT_HISTORY` block are untouched. Every public name this module
owned before the split is re-exported below, so existing import sites —
`chat_parser`'s seam, the phase tests, the plan tests — are unchanged.

Why the phases are objects and not functions: they share one mutable
`SyncSession` (the page state can change *during* a read — a virtualised pane
that loses its nodes mid-read updates the count and the signatures, and the
final cursor write must reflect what was actually read, not what we hoped for).

History: this file was 807 lines (MI 11.35, the worst in the repo) until the
AREA D freeze was lifted by owner ruling on 2026-09-13 and Round G step G2
split it into this family:
docs/archive/2026-09-13-round-g-write-gate/G2_CHAT_SYNC_SCROLL_PARSER_DESIGN_2026-09-13.md
"""

from __future__ import annotations

from typing import Optional

from backend.chat_sync_options import SyncOptions  # noqa: F401  (re-exported: the seam)
from backend.chat_sync_persist import SyncPersister, merge_live  # noqa: F401
from backend.chat_sync_plan import (  # noqa: F401
    MODE_DELTA, MODE_EMPTY, MODE_FULL, MODE_UNCHANGED, ReadPlan, SyncPlanner)
from backend.chat_sync_read import (  # noqa: F401
    SLICE_RETRIES, ChunkReader, DeltaAligner)
from backend.chat_sync_session import SyncSession  # noqa: F401
from stores.history_models import SyncResult

#: The seam contract — every name this module owned before the G2 split, so
#: `from backend.chat_sync import …` keeps working unchanged (the F1
#: `db_deletion.py` shim pattern; `__all__` is also what tells pylint these
#: re-exports are deliberate).
__all__ = [
    "MODE_DELTA", "MODE_EMPTY", "MODE_FULL", "MODE_UNCHANGED",
    "ChunkReader", "DeltaAligner", "ReadPlan", "SLICE_RETRIES",
    "SyncOptions", "SyncPersister", "SyncPlanner", "SyncSession",
    "merge_live", "run_sync",
]


async def run_sync(parser, repo, nick: str,
                   options: Optional[SyncOptions] = None, **legacy) -> SyncResult:
    """Bring the archive up to date with what the page currently shows.

    `backend.chat_parser.sync_conversation()` is the public entry point and
    forwards its keyword arguments; `options` is the typed seam new callers
    should use.
    """
    session = SyncSession(parser, repo, nick,
                          options or SyncOptions.from_kwargs(**legacy))
    if not await session.prepare():
        return session.result
    if session.plan.is_empty:
        await session.finish_empty()
        return session.result
    if session.plan.mode == MODE_UNCHANGED:
        session.result.reason = "unchanged"
        return session.result
    await session.record_cap_gap()
    await ChunkReader(session).read()
    await DeltaAligner().apply(session)
    await session.restore_if_needed()
    await session.persister.repair_tail()
    await session.finish()
    return session.result
