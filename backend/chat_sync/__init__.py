"""The conversation-sync algorithm, in phases.

`backend.chat_parser` owns the *probes* (one state probe, one range probe, one
drain) and the private-chat gate. This package owns the *decision*: what to
read given what the archive already holds, and what to write back.

    run_sync(parser, repo, nick, options)
      ├─ SyncSession.prepare()      probe → install → gate → viewport → cursor
      ├─ SyncPlanner.plan()         (state, cursor, options) → ReadPlan      [pure]
      ├─ ChunkReader.read()         paced, retrying, stop-aware range reads
      ├─ DeltaAligner.apply()       what appeared ABOVE what we stored
      ├─ SyncPersister.*            every repo.write, in one place
      └─ SyncSession.finish()       final cursor, totals, reason

## What each module owns, and which way the imports go

| Module | Owns | Imports from this package |
|---|---|---|
| `modes.py` | the four read modes, the retry budget | — |
| `options.py` | `SyncOptions`, `ReadPlan` — pure data | `modes` |
| `planner.py` | `SyncPlanner.plan()`, `merge_live` — pure decision | `modes`, `options` |
| `persist.py` | `SyncPersister` — every `repo.*` write | — (session arrives as a param) |
| `read.py` | `ChunkReader`, `DeltaAligner` — the page reads | `modes` |
| `session.py` | `SyncSession` — shared state + opening/closing phases | `options`, `persist`, `planner` |
| `run.py` | `run_sync` — the sequence, and nothing else | all of the above |

Imports only ever point *down* that table. No module imports `__init__`, so the
front door can re-export everything without a cycle.

## Why this is a package (Round G, step G1)

It was one 807-line module at maintainability index **11.4** — half the
next-worst file in the repository and a sixth of the project mean. It could not
be split until step G0 taught the AREA D snapshot to walk into packages and to
treat a symbol defined in a submodule as still *owned* by the package
(`tools/metrics/dump_public_api.py::owns`). Design and the empty-diff proof:
`docs/archive/2026-09-13-round-g/AREA_D_DECISION_2026-09-13.md` and
`CHAT_SYNC_SPLIT_2026-09-13.md`.

**The rule that keeps the contract:** this `__init__` re-exports the module's
previous public surface verbatim. `owns()` makes a submodule symbol count as
owned; it does not make an un-exported one appear. Split the file, keep the
front door.

The split is internal in the other direction too:
`backend.chat_parser.sync_conversation()` keeps its exact 14-parameter
signature and delegates here, so `services/collector_service` and the
`COLLECT_HISTORY` block are untouched.
"""

from __future__ import annotations

from backend.chat_sync.modes import (MODE_DELTA, MODE_EMPTY, MODE_FULL,
                                     MODE_UNCHANGED, SLICE_RETRIES)
from backend.chat_sync.options import ReadPlan, SyncOptions
from backend.chat_sync.persist import SyncPersister
from backend.chat_sync.planner import SyncPlanner, merge_live
from backend.chat_sync.read import ChunkReader, DeltaAligner
from backend.chat_sync.run import run_sync
from backend.chat_sync.session import SyncSession

__all__ = [
    "MODE_DELTA", "MODE_EMPTY", "MODE_FULL", "MODE_UNCHANGED",
    "SLICE_RETRIES", "ChunkReader", "DeltaAligner", "ReadPlan",
    "SyncOptions", "SyncPersister", "SyncPlanner", "SyncSession",
    "merge_live", "run_sync",
]
