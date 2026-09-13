"""Pin read/alignment and cancellation semantics before moving their owners."""

import asyncio

import pytest

from backend.chat_parser import sync_conversation
from backend.chat_sync import DeltaAligner
from stores.history_models import MessageRecord
from tests.unit.backend.test_chat_sync_phases import FakeParser, FakeRepo, record


def test_alignment_requires_real_overlap_and_preserves_older_records():
    records = [MessageRecord.from_dict(record(i)) for i in range(3)]
    assert DeltaAligner.split([], {}) == []
    assert DeltaAligner.split(records, {"tail_keys": ["unrelated"]}) == []
    assert DeltaAligner.split(records, {}) == []
    # Prefix includes the matched tail; the repository de-duplicates known rows.
    assert DeltaAligner.split(records, {"tail_keys": [r.dup_key for r in records]}) == records
    older = DeltaAligner.split(records, {"tail_keys": [records[0].dup_key]})
    assert older == records[:1]
    assert older[0] is records[0]


@pytest.mark.asyncio
async def test_cancellation_during_slice_propagates_without_any_archive_write():
    entered, exited = asyncio.Event(), asyncio.Event()

    class PendingParser(FakeParser):
        async def slice(self, start, end):
            entered.set()
            try:
                await asyncio.Future()
            finally:
                exited.set()

    repo = FakeRepo()
    task = asyncio.create_task(sync_conversation(PendingParser([record(0)]), repo, "Nick"))
    try:
        await asyncio.wait_for(entered.wait(), 1)
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert exited.is_set()
    assert repo.calls_of("append") == []
    assert repo.calls_of("mark_backfilled") == []


@pytest.mark.asyncio
async def test_cancellation_during_write_does_not_forge_final_cursor():
    entered, exited = asyncio.Event(), asyncio.Event()

    class PendingRepo(FakeRepo):
        async def append(self, nick, records, **kwargs):
            self._note("pending_append", count=len(records))
            entered.set()
            try:
                await asyncio.Future()
            finally:
                exited.set()

    parser, repo = FakeParser([record(0)]), PendingRepo()
    task = asyncio.create_task(sync_conversation(parser, repo, "Nick"))
    try:
        await asyncio.wait_for(entered.wait(), 1)
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert exited.is_set()
    assert repo.calls_of("pending_append") == [{"count": 1}]
    assert repo.calls_of("append") == []


@pytest.mark.asyncio
@pytest.mark.parametrize("empty_reads, written", [(99, 0), (0, 1)])
async def test_cancellation_during_retry_or_pacing_propagates(monkeypatch, empty_reads, written):
    entered, exited = asyncio.Event(), asyncio.Event()

    async def blocking_sleep(delay):
        assert delay > 0
        entered.set()
        try:
            await asyncio.Future()
        finally:
            exited.set()

    parser = FakeParser([record(0), record(1)], chunk_size=1,
                        chunk_pause_ms=5000, empty_reads=empty_reads)
    repo = FakeRepo()
    monkeypatch.setattr(asyncio, "sleep", blocking_sleep)
    task = asyncio.create_task(sync_conversation(parser, repo, "Nick"))
    try:
        await asyncio.wait_for(entered.wait(), 1)
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert exited.is_set()
    assert parser.slice_calls == [(0, 1)]
    assert [c["count"] for c in repo.calls_of("append")] == ([1] if written else [])
