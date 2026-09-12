"""The conversation-sync algorithm, in phases.

`backend.chat_parser` owns the *probes* (one state probe, one range probe,
one drain) and the private-chat gate. This package owns the *decision*: what
to read given what the archive already holds, and what to write back.

    run_sync(parser, repo, nick, options)
      ├─ SyncSession.prepare()      probe → install → gate → viewport → cursor
      ├─ SyncPlanner.plan()         (state, cursor, options) → ReadPlan      [pure]
      ├─ ChunkReader.read()         paced, retrying, stop-aware range reads
      ├─ DeltaAligner.apply()       what appeared ABOVE what we stored
      ├─ SyncPersister.*            every repo.write, in one place
      └─ SyncSession.finish()       final cursor, totals, reason

One file per phase, so each fits one read (RULE 18):

    options.py   SyncOptions — the eleven optional knobs, immutable
    plan.py      MODE_*, ReadPlan, SyncPlanner — the pure decision
    session.py   SyncSession + merge_live — the state the phases share
    persist.py   SyncPersister — every repo.write, in one place
    reader.py    ChunkReader — the paced, retrying chunk loop
    align.py     DeltaAligner — where the re-read continues the archive

Why the phases are objects and not functions: they share one mutable
`SyncSession` (the page state can change *during* a read — a virtualised pane
that loses its nodes mid-read updates the count and the signatures, and the
final cursor write must reflect what was actually read, not what we hoped
for).

The split is internal: `backend.chat_parser.sync_conversation()` keeps its
exact 14-parameter signature and delegates here, so `services/collector_service`
and the `COLLECT_HISTORY` block are untouched (plan §7.3.1).
"""

from __future__ import annotations

from typing import Optional

from backend.chat_sync.align import DeltaAligner
from backend.chat_sync.options import SyncOptions
from backend.chat_sync.plan import (MODE_DELTA, MODE_EMPTY, MODE_FULL,
                                    MODE_UNCHANGED, ReadPlan, SyncPlanner)
from backend.chat_sync.persist import SyncPersister
from backend.chat_sync.reader import SLICE_RETRIES, ChunkReader
from backend.chat_sync.session import SyncSession, merge_live
from stores.history_models import SyncResult

__all__ = ["MODE_DELTA", "MODE_EMPTY", "MODE_FULL", "MODE_UNCHANGED",
           "SLICE_RETRIES", "ChunkReader", "DeltaAligner", "ReadPlan",
           "SyncOptions", "SyncPersister", "SyncPlanner", "SyncSession",
           "merge_live", "run_sync"]


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
