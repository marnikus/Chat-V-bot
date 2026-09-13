"""The entry point: the six phases in order.

Owns: `run_sync`. This is the only module that knows the *sequence*; every
phase it calls is defined elsewhere in the package, which is what keeps the
sequence readable in one screen.
"""

from __future__ import annotations

from typing import Optional

from backend.chat_sync.modes import MODE_UNCHANGED
from backend.chat_sync.options import SyncOptions
from backend.chat_sync.read import ChunkReader, DeltaAligner
from backend.chat_sync.session import SyncSession
from stores.history_models import SyncResult


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
