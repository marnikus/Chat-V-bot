"""Characterize archive writes before extracting the persistence boundary."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.chat_parser import sync_conversation
from backend.chat_sync import SyncOptions, SyncSession, merge_live
from stores.history_db import HistoryDB
from stores.history_models import MAX_LIVE_ITEMS, SyncResult
from stores.history_repo import HistoryRepo
from tests.unit.backend.test_chat_sync_phases import FakeParser, FakeRepo, NOW, record


@pytest.fixture
def session():
    parser = FakeParser([record(i) for i in range(4)], chunk_size=2)
    repo = FakeRepo(repairable=True, last_ord=17)
    return SyncSession(parser, repo, "Nick", SyncOptions(
        now=NOW, my_nick="Me", media=object(), max_messages=2))


@pytest.mark.asyncio
async def test_partial_cursor_preserves_head_and_never_promises_tail(session):
    await session.prepare()
    session.position = 1
    session.scanned = 1
    session.result.stopped = True
    await session.finish()
    write = session.repo.calls_of("append")[-1]
    assert write == {
        "nick": "Nick", "count": 0, "my_nick": "Me", "now": NOW,
        "dom_count": 1, "head_sig": record(0)["fp"], "tail_sig": "",
        "head_any": "", "tail_any": "",
    }
    assert session.result.reason == "stopped"
    assert session.result.scanned == 1
    assert session.complete is False


@pytest.mark.asyncio
async def test_gap_uses_archive_tail_and_precedes_first_chunk(session):
    await session.prepare()
    await session.record_cap_gap()
    await session.persister.stream_chunk([record(2)], 2, first=True)
    assert session.repo.calls_of("record_gap") == [{
        "person_id": 7, "after_ord": 17, "reason": "capped",
        "detail": "only the newest 2 messages were collected",
    }]
    assert session.repo.names.index("record_gap") < session.repo.names.index("append")
    write = session.repo.calls_of("append")[0]
    assert (write["align"], write["expect_idx"]) == (False, 2)
    assert session.result.gap is True
    assert session.result.added == 1


@pytest.mark.asyncio
async def test_failed_recovery_logs_without_destroying_existing_counts(session, caplog):
    session.result.media_repaired = 3
    session.result.media_requeued = 2
    session.repo.recover_media = AsyncMock(side_effect=RuntimeError("offline"))
    with caplog.at_level("DEBUG", logger="chatbot"):
        await session.persister.recover([record(0)], requeue_failed=True)
    assert (session.result.media_repaired, session.result.media_requeued) == (3, 2)
    assert "media recovery for Nick failed: offline" in caplog.text
    assert session.repo.recover_media.await_args.kwargs["requeue_failed"] is True


@pytest.mark.asyncio
async def test_empty_tail_does_not_recover_any_records(session):
    session.parser._count = 0
    await session.persister.repair_tail()
    assert session.parser.slice_calls == []
    assert session.repo.calls_of("recover_media") == []


@pytest.mark.asyncio
async def test_failed_tail_probe_is_logged_and_contained(session, caplog):
    session.parser.state = AsyncMock(side_effect=RuntimeError("page gone"))
    with caplog.at_level("DEBUG", logger="chatbot"):
        await session.persister.repair_tail()
    assert "tail media recovery for Nick failed: page gone" in caplog.text
    assert session.repo.calls_of("recover_media") == []


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["touch", "mark_backfilled", "recover", "repair_tail"])
async def test_cancellation_is_not_swallowed_by_best_effort_writes(session, operation):
    cases = {
        "touch": ("append", {}, (0,)),
        "mark_backfilled": ("mark_backfilled", {"why": "test"}, ()),
        "recover": ("recover_media", {"requeue_failed": True}, ([record(0)],)),
        "repair_tail": ("has_repairable_media", {}, ()),
    }
    method, kwargs, args = cases[operation]
    setattr(session.repo, method, AsyncMock(side_effect=asyncio.CancelledError))
    with pytest.raises(asyncio.CancelledError):
        await getattr(session.persister, operation)(*args, **kwargs)


@pytest.mark.asyncio
async def test_append_failure_is_not_a_successful_sync(session):
    session.repo.append = AsyncMock(side_effect=RuntimeError("database locked"))
    with pytest.raises(RuntimeError, match="database locked"):
        await session.persister.write_batch([record(0)])
    assert session.result.added == 0


def test_live_results_exclude_prepend_and_invalid_ordinals_and_keep_identity():
    kept = {"ord": "12", "text": "new"}
    result = SyncResult()
    merge_live(result, SimpleNamespace(records=[
        {"ord": 9}, {"ord": 10}, {"ord": "invalid"}, {"ord": None}, kept,
    ]), baseline=10)
    assert result.records == [kept]
    assert result.records[0] is kept
    merge_live(result, SimpleNamespace(), baseline=10)
    assert result.records == [kept]


def test_live_results_are_bounded_across_chunks():
    prior = [{"ord": i + 1} for i in range(MAX_LIVE_ITEMS - 1)]
    result = SyncResult(records=prior.copy())
    merge_live(result, SimpleNamespace(records=[
        {"ord": MAX_LIVE_ITEMS}, {"ord": MAX_LIVE_ITEMS + 1},
    ]))
    assert result.records == prior + [{"ord": MAX_LIVE_ITEMS}]
    merge_live(result, SimpleNamespace(records=[{"ord": MAX_LIVE_ITEMS + 2}]))
    assert len(result.records) == MAX_LIVE_ITEMS


@pytest.mark.asyncio
async def test_partial_sync_then_retry_preserves_real_sqlite_archive(tmp_path):
    db = HistoryDB(str(tmp_path / "world.db"))
    await db.init()
    repo = HistoryRepo(db)
    parser = FakeParser([record(i) for i in range(4)], chunk_size=2)
    stopped = False

    def progress(done, total):
        nonlocal stopped
        assert (done, total) == (2, 4)
        stopped = True

    try:
        partial = await sync_conversation(
            parser, repo, "Nick", now=NOW, should_stop=lambda: stopped,
            on_progress=progress, my_nick="Me", require_private=True, verify_partner=True)
        person = await repo.get_person("Nick")
        cursor = await repo.get_cursor(person["id"])
        assert (partial.added, partial.reason, person["message_count"]) == (2, "stopped", 2)
        assert (cursor["dom_count"], cursor["tail_sig"]) == (2, "")
        finished = await sync_conversation(parser, repo, "Nick", now=NOW, my_nick="Me")
        person = await repo.get_person("Nick")
        assert (finished.added, person["message_count"]) == (2, 4)
        unchanged = await sync_conversation(parser, repo, "Nick", now=NOW, my_nick="Me")
        assert (unchanged.reason, unchanged.added) == ("unchanged", 0)
    finally:
        await db.close()
