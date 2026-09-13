"""Characterize session admission and completion before steps 6–7 move them."""

import asyncio
from unittest.mock import AsyncMock

import pytest

from backend.chat_parser import sync_conversation
from backend.chat_sync import SyncOptions, SyncSession
from stores.history_models import SyncResult
from tests.unit.backend.test_chat_sync_phases import FakeParser, FakeRepo, NOW, record


@pytest.mark.asyncio
@pytest.mark.parametrize("state, reason", [
    ({"ok": False, "reason": "lost pane"}, "lost pane"),
    ({"ok": False, "reason": ""}, "no_agent"),
    ({"tab": "main"}, "not_private"),
    ({"partner": "Other"}, "partner_mismatch"),
    ({"title": "Other"}, "title_mismatch"),
    ({"in_authors": ["Nick", "Stranger"]}, "strangers"),
])
async def test_admission_refusal_precedes_scroll_and_any_archive_access(state, reason):
    parser, repo = FakeParser([record(0)], state_extra=state), FakeRepo()
    result = await sync_conversation(
        parser, repo, "Nick", now=NOW, my_nick="Me", require_private=True,
        verify_partner=True, backfill_older=True)
    assert (result.ok, result.reason, result.added) == (False, reason, 0)
    assert repo.calls == []
    assert parser.scroll_to_top_calls == 0
    assert parser.slice_calls == parser.restore_calls == []


@pytest.mark.asyncio
async def test_backfill_runs_gate_viewport_archive_restore_and_finish_in_order(monkeypatch):
    events = []
    parser = FakeParser([record(0), record(1)], chunk_size=10)
    repo = FakeRepo(repairable=True)

    def trace(obj, method, label):
        original = getattr(obj, method)

        async def invoke(*args, **kwargs):
            name = label
            if method == "append":
                name = "write" if args[1] else "cursor_write"
            events.append(name)
            return await original(*args, **kwargs)

        monkeypatch.setattr(obj, method, invoke)

    for method in ("state", "scroll_to_top", "settle_after_top", "slice", "restore_scroll"):
        trace(parser, method, method)
    for method in ("ensure_person", "get_cursor", "get_person_by_id", "append",
                   "recover_media", "has_repairable_media", "mark_backfilled"):
        trace(repo, method, method)
    result = await sync_conversation(
        parser, repo, "Nick", now=NOW, my_nick="Me", require_private=True,
        verify_partner=True, backfill_older=True, media=object())
    assert result.ok and result.backfilled
    assert events == [
        "state", "scroll_to_top", "settle_after_top", "ensure_person", "get_cursor",
        "get_person_by_id", "slice", "write", "recover_media", "restore_scroll",
        "has_repairable_media", "state", "slice", "recover_media", "mark_backfilled",
        "cursor_write", "get_person_by_id",
    ]
    assert repo.calls_of("append")[-1]["tail_sig"] == record(1)["fp"]


@pytest.mark.asyncio
@pytest.mark.parametrize("stopped, pending, mark", [
    (False, False, True), (True, False, False), (False, True, False),
])
async def test_finish_preserves_supplied_result_and_backfill_marker_rules(stopped, pending, mark):
    result = SyncResult(ok=True, reason="existing", backfilled=True,
                        stopped=stopped, backfill_pending=pending)
    repo = FakeRepo(person={"message_count": 19})
    session = SyncSession(FakeParser(), repo, "Nick", SyncOptions(now=NOW), result)
    session.count, session.position, session.scanned = 3, 3, 2
    session.head_sig, session.tail_sig = "h", "t"
    assert await session.person_total() == 19
    await session.finish()
    assert session.result is result
    assert (result.reason, result.total, result.scanned) == ("existing", 19, 2)
    assert bool(repo.calls_of("mark_backfilled")) is mark
    assert session.complete is (not stopped)
    cursor = repo.calls_of("append")[-1]
    assert cursor["tail_sig"] == ("" if stopped else "t")


@pytest.mark.asyncio
@pytest.mark.parametrize("owner, method", [
    ("parser", "state"), ("parser", "scroll_to_top"), ("parser", "settle_after_top"),
    ("repo", "ensure_person"), ("repo", "get_cursor"), ("repo", "get_person_by_id"),
])
async def test_prepare_cancellation_propagates_without_final_cursor(owner, method):
    parser, repo = FakeParser([record(0)]), FakeRepo()
    setattr({"parser": parser, "repo": repo}[owner], method,
            AsyncMock(side_effect=asyncio.CancelledError))
    with pytest.raises(asyncio.CancelledError):
        await sync_conversation(parser, repo, "Nick", backfill_older=True)
    assert repo.calls_of("append") == []
    assert repo.calls_of("mark_backfilled") == []


def test_sessions_do_not_share_mutable_defaults_or_supplied_result():
    first = SyncSession(FakeParser(), FakeRepo(), "A")
    second = SyncSession(FakeParser(), FakeRepo(), "B")
    first.state["count"] = 5
    first.collected.append(record(0))
    first.result.chunks.append({"from": 0, "to": 1})
    assert second.state == second.cursor == {}
    assert second.collected == second.result.chunks == []
    assert first.persister is not second.persister
    assert (first.result.nick, second.result.nick) == ("A", "B")
