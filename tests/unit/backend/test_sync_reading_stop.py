"""RULE 7 regressions: test-first correction, separate from the file move."""

import asyncio

import pytest

from backend.chat_parser import sync_conversation
from tests.unit.backend.test_chat_sync_phases import FakeParser, FakeRepo, record


@pytest.mark.asyncio
@pytest.mark.parametrize("stop_on_attempt", [1, 4])
async def test_stop_during_empty_slice_is_not_no_new(stop_on_attempt):
    parser = FakeParser([record(0)], empty_reads=99)
    repo = FakeRepo()
    result = await sync_conversation(
        parser, repo, "Nick",
        should_stop=lambda: len(parser.slice_calls) >= stop_on_attempt)
    assert len(parser.slice_calls) == stop_on_attempt
    assert (result.stopped, result.reason, result.added) == (True, "stopped", 0)
    cursor = repo.calls_of("append")[-1]
    assert (cursor["count"], cursor["dom_count"], cursor["tail_sig"]) == (0, 0, "")


@pytest.mark.asyncio
@pytest.mark.parametrize("empty_reads, written", [(99, 0), (0, 1)])
async def test_stop_interrupts_retry_and_configured_pacing(monkeypatch, empty_reads, written):
    entered = asyncio.Event()
    real_sleep = asyncio.sleep
    stopped = False

    async def observed_sleep(delay):
        entered.set()
        await real_sleep(delay)

    parser = FakeParser([record(0), record(1)], chunk_size=1,
                        chunk_pause_ms=5000, empty_reads=empty_reads)
    repo = FakeRepo()
    monkeypatch.setattr(asyncio, "sleep", observed_sleep)
    task = asyncio.create_task(sync_conversation(
        parser, repo, "Nick", should_stop=lambda: stopped))
    try:
        await asyncio.wait_for(entered.wait(), 1)
        stopped = True
        # A 20ms cooperative slice should finish comfortably inside 400ms;
        # the old 800ms retry ladder / 5-second pacing sleep cannot pass.
        result = await asyncio.wait_for(task, 0.4)
    finally:
        if not task.done():
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
    assert (result.stopped, result.reason, result.added) == (True, "stopped", written)
    assert parser.slice_calls == [(0, 1)]
    cursor = repo.calls_of("append")[-1]
    assert (cursor["dom_count"], cursor["tail_sig"]) == (written, "")


@pytest.mark.asyncio
async def test_stop_on_completed_final_slice_keeps_chunk_but_reports_stopped():
    parser, repo = FakeParser([record(0)], chunk_size=1), FakeRepo()
    result = await sync_conversation(
        parser, repo, "Nick", should_stop=lambda: bool(parser.slice_calls))
    assert (result.added, result.scanned) == (1, 1)
    assert (result.stopped, result.reason) == (True, "stopped")
    assert [c["count"] for c in repo.calls_of("append")] == [1, 0]
    assert repo.calls_of("append")[-1]["tail_sig"] == ""


@pytest.mark.asyncio
async def test_external_cancel_of_cooperative_pacing_still_propagates(monkeypatch):
    entered = asyncio.Event()

    async def pending_sleep(delay):
        entered.set()
        await asyncio.Future()

    parser = FakeParser([record(0), record(1)], chunk_size=1, chunk_pause_ms=5000)
    repo = FakeRepo()
    monkeypatch.setattr(asyncio, "sleep", pending_sleep)
    task = asyncio.create_task(sync_conversation(
        parser, repo, "Nick", should_stop=lambda: False))
    try:
        await asyncio.wait_for(entered.wait(), 1)
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert parser.slice_calls == [(0, 1)]
    assert [c["count"] for c in repo.calls_of("append")] == [1]
