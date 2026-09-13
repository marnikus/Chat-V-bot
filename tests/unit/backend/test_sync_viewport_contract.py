"""Pin viewport fallbacks/restoration through the existing session API."""

import asyncio
from unittest.mock import AsyncMock

import pytest

from backend.chat_parser import sync_conversation
from backend.chat_sync import SyncOptions, SyncSession
from tests.unit.backend.test_chat_sync_phases import FakeParser, FakeRepo, record


@pytest.mark.asyncio
@pytest.mark.parametrize("position, count, end", [
    (None, 0, 2), (4, 0, 7), (None, 5, 2), (4, 5, 5),
])
async def test_restored_state_reclamps_window_without_inventing_empty_state(position, count, end):
    parser = FakeParser([record(0)], count=count, chunk_size=3)
    session = SyncSession(parser, FakeRepo(), "Nick")
    session.old_top, session.position, session.count = 120, 2, 8
    prior = session.state = {"count": 8, "head": "before"}
    assert await session.restore_viewport(position) == end
    assert parser.restore_calls == [120]
    if count:
        assert (session.count, session.result.count, session.head_sig) == (5, 5, record(0)["fp"])
        assert session.result.backfill_pending is True
    else:
        assert session.state is prior
        assert session.count == 8
        assert session.result.backfill_pending is False


@pytest.mark.asyncio
async def test_failed_viewport_restore_still_reprobes_and_updates_window():
    parser = FakeParser([record(0)], count=2, chunk_size=5)
    parser.restore_scroll = AsyncMock(side_effect=RuntimeError("not scrollable"))
    session = SyncSession(parser, FakeRepo(), "Nick")
    assert await session.restore_viewport(0) == 2
    assert session.count == session.result.count == 2
    assert session.result.backfill_pending is True


@pytest.mark.asyncio
@pytest.mark.parametrize("fallback", [None, {"count": 3, "_settled": True,
                                            "scroll": {"atTop": True}}])
async def test_settle_exception_reprobes_and_only_trusts_settled_state(fallback):
    parser = FakeParser([record(i) for i in range(3)])
    initial = await parser.state()
    parser.state = AsyncMock(side_effect=[initial, fallback])
    parser.settle_after_top = AsyncMock(side_effect=RuntimeError("settle failed"))
    session = SyncSession(parser, FakeRepo(), "Nick", SyncOptions(backfill_older=True))
    assert await session.prepare() is True
    assert parser.state.await_count == 2
    assert parser.settle_after_top.await_args.kwargs == {
        "wait_ms": 300, "stable_polls": 3, "max_wait_s": 4.0, "minimum_count": 3,
    }
    assert session.count == 3
    assert session.result.backfilled is (fallback is not None)
    assert session.result.backfill_pending is (fallback is None)


@pytest.mark.asyncio
async def test_emptied_pane_fallback_recovers_original_count_without_marking_complete():
    parser = FakeParser([record(i) for i in range(3)])
    initial = await parser.state()
    parser.state = AsyncMock(side_effect=[initial, {"count": 0}, initial])
    parser.settle_after_top = AsyncMock(return_value={"count": 0, "scroll": {"atTop": False}})
    session = SyncSession(parser, FakeRepo(), "Nick", SyncOptions(backfill_older=True))
    assert await session.prepare() is True
    assert parser.restore_calls == [250]
    assert (session.count, session.before_count, session.result.count) == (3, 3, 3)
    assert (session.result.backfilled, session.result.backfill_pending) == (False, True)
    assert session.head_sig == record(0)["fp"]
    assert session.restored_top is None


@pytest.mark.asyncio
@pytest.mark.parametrize("top, expected", [(None, []), (85, [85])])
async def test_restore_if_needed_restores_only_the_recorded_position(top, expected):
    parser = FakeParser()
    session = SyncSession(parser, FakeRepo(), "Nick")
    session.restored_top = top
    await session.restore_if_needed()
    assert parser.restore_calls == expected


@pytest.mark.asyncio
async def test_final_restore_failure_is_logged_but_not_cancellation(caplog):
    parser = FakeParser()
    session = SyncSession(parser, FakeRepo(), "Nick")
    session.restored_top = 85
    parser.restore_scroll = AsyncMock(side_effect=RuntimeError("detached"))
    with caplog.at_level("DEBUG", logger="chatbot"):
        await session.restore_if_needed()
    assert "could not restore scroll position for Nick" in caplog.text
    parser.restore_scroll.side_effect = asyncio.CancelledError
    with pytest.raises(asyncio.CancelledError):
        await session.restore_if_needed()
    with pytest.raises(asyncio.CancelledError):
        await session.restore_viewport()


@pytest.mark.asyncio
async def test_zero_original_top_does_not_add_a_final_restore():
    parser = FakeParser([record(0)], state_extra={"scroll": {"top": 0, "height": 100}})
    result = await sync_conversation(parser, FakeRepo(), "Nick", backfill_older=True)
    assert result.backfilled is True
    assert parser.restore_calls == []


@pytest.mark.asyncio
async def test_unchanged_fast_path_does_not_add_restore_or_cursor_writes():
    msg = record(0)
    parser = FakeParser([msg])
    repo = FakeRepo(cursor={"bootstrapped": True, "dom_count": 1,
                            "head_sig": msg["fp"], "tail_sig": msg["fp"]})
    result = await sync_conversation(parser, repo, "Nick", backfill_older=True)
    assert (result.reason, result.backfilled) == ("unchanged", True)
    assert parser.restore_calls == parser.slice_calls == repo.calls_of("append") == []
