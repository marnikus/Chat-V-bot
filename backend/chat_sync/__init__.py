"""The conversation-sync algorithm, in phases.

`backend.chat_parser` owns the *probes* (one state probe, one range probe, one
drain) and the private-chat gate. This package owns the *decision*: what to
read given what the archive already holds, and what to write back.

    run_sync(parser, repo, nick, options)                    ← sync.py
      ├─ SyncSession.prepare()      probe → install → gate → viewport → cursor
      ├─ SyncPlanner.plan()         (state, cursor, options) → ReadPlan  [pure]
      ├─ ChunkReader.read()         paced, retrying, stop-aware range reads
      ├─ DeltaAligner.apply()       what appeared ABOVE what we stored
      ├─ SyncPersister.*            every repo.write, in one place
      └─ SyncSession.finish()       final cursor, totals, reason

Layout (one responsibility per module, imports flow top-down):

    constants → options → plan → merge ─┬─→ session → sync
                                        └── persister / reader / aligner (leaves)

`reader`, `aligner` and `persister` reference `SyncSession` only in string type
hints, so they never import `session` back — the session owns its
collaborators. The public names below are the frozen seam
`backend.chat_parser` and the sync tests import, so this `__init__` re-exports
them verbatim (RULE 18 §18.2: the split must not change the call surface).

Why the phases are objects and not functions: they share one mutable
`SyncSession` (the page state can change *during* a read — a virtualised pane
that loses its nodes mid-read updates the count and the signatures, and the
final cursor write must reflect what was actually read, not what we hoped for).
"""

from __future__ import annotations

from .aligner import DeltaAligner
from .constants import (MODE_DELTA, MODE_EMPTY, MODE_FULL, MODE_UNCHANGED,
                        SLICE_RETRIES, _MAX_QUIET_RETRIES)
from .merge import merge_live
from .options import SyncOptions
from .persister import SyncPersister
from .plan import ReadPlan, SyncPlanner
from .reader import ChunkReader
from .session import SyncSession
from .sync import run_sync

__all__ = [
    "ChunkReader",
    "DeltaAligner",
    "MODE_DELTA",
    "MODE_EMPTY",
    "MODE_FULL",
    "MODE_UNCHANGED",
    "ReadPlan",
    "SLICE_RETRIES",
    "SyncOptions",
    "SyncPersister",
    "SyncPlanner",
    "SyncSession",
    "merge_live",
    "run_sync",
]
