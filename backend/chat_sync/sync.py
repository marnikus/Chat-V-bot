"""`run_sync` — the orchestrator that wires the phases together.

The one entry point the package exposes for actually *doing* a sync:
`backend.chat_parser.sync_conversation()` forwards its keyword arguments here.
It composes a :class:`SyncSession` and drives the phases in order
(prepare → empty/unchanged short-circuits → read → align → restore → finish).
"""

from __future__ import annotations

from typing import Optional

from stores.history_models import SyncResult

from .aligner import DeltaAligner
from .constants import MODE_UNCHANGED
from .options import SyncOptions
from .reader import ChunkReader
from .session import SyncSession


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
