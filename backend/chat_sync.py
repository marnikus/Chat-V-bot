"""Compatibility exports for conversation synchronization.

Implementation lives in backend.sync: session composes admission/completion,
viewport, planning, reading and persistence. Imports point into that package;
its phases never import this facade. Legacy callers keep their existing names.
"""

from backend.sync.persistence import SyncPersister as SyncPersister, merge_live as merge_live
from backend.sync.planning import (
    MODE_EMPTY as MODE_EMPTY,
    MODE_UNCHANGED as MODE_UNCHANGED,
    MODE_DELTA as MODE_DELTA,
    MODE_FULL as MODE_FULL,
    ReadPlan as ReadPlan,
    SyncOptions as SyncOptions,
    SyncPlanner as SyncPlanner,
)
from backend.sync.reading import (
    ChunkReader as ChunkReader,
    DeltaAligner as DeltaAligner,
    SLICE_RETRIES as SLICE_RETRIES,
)
from backend.sync.session import (
    SyncSession as SyncSession,
    SyncResult as SyncResult,
    run_sync as run_sync,
)

__all__ = [
    "MODE_EMPTY", "MODE_UNCHANGED", "MODE_DELTA", "MODE_FULL", "SLICE_RETRIES",
    "SyncOptions", "ReadPlan", "SyncPlanner", "SyncPersister", "ChunkReader",
    "DeltaAligner", "SyncSession", "SyncResult", "merge_live", "run_sync",
]
