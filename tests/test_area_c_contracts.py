"""Behavioral contracts written before Area C extraction; no helper-class mocks."""

import asyncio
import copy
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio

from core.events import EventBus, LogMessage
from services.collector_service import Collector, CollectorState
from services.history import HistoryService
from services.layout_service import LayoutService
from services.undo_service import UndoService
from backend.chat_parser import ChatParser
from backend.config_manager import ConfigManager
from stores.history_db import HistoryDB
from stores.history_repo import HistoryRepo
from test_chat_parser_delta import FakePage, raw


class Config:
    def __init__(self, **state):
        self.state = copy.deepcopy(state)

    def get_state(self, key, default=None):
        return copy.deepcopy(self.state.get(key, default))

    def set_state(self, **state):
        self.state.update(copy.deepcopy(state))


@pytest.mark.parametrize(
    "kind,value,accepted",
    [
        ("stack", [], True),
        ("stack", {}, False),
        ("grid", LayoutService.default_payload(), True),
        ("grid", "bad", False),
        ("grid", {}, False),
        ("people", {"before": [], "after": []}, True),
        ("people", {"before": [], "after": {}}, False),
        ("people", [], False),
        ("labels", {}, True),
        ("archive", {}, True),
        ("dbconn", {}, True),
        ("labels", [], False),
        ("unknown", {}, False),
    ],
)
def test_modern_migration_validates_entries_and_preserves_identity(
    kind, value, accepted
):
    cfg = Config(
        undo_history=[None, {"kind": kind, "value": value, "seq": 27}],
        undo_history_index=99,
    )
    service = UndoService(cfg)
    history, index = service.migrate_global_history()
    assert index == (0 if accepted else -1)
    assert len(history) == int(accepted)
    if accepted:
        assert history[0]["seq"] == 27
        assert history[0]["kind"] == kind
        if isinstance(value, (dict, list)):
            assert history[0]["value"] == value
            assert history[0]["value"] is not value


@pytest.mark.parametrize(
    "index,expected", [(None, 0), ("bad", 0), (-8, -1), (55, 0), (0, 0)]
)
def test_modern_migration_clamps_index(index, expected):
    service = UndoService(
        Config(undo_history=[{"kind": "stack", "value": []}], undo_history_index=index)
    )
    assert service.migrate_global_history()[1] == expected


def test_legacy_grid_migration_deduplicates_and_canonicalizes():
    grid = LayoutService.default_payload()
    cfg = Config(
        stack_history=[None, []],
        grid_layout_history=[None, "broken", grid],
        grid_layout=grid,
        stack_history_index=0,
    )
    history, index = UndoService(cfg).migrate_global_history()
    assert [e["kind"] for e in history] == ["stack", "grid"]
    assert index == 1
    assert cfg.state["grid_layout"] == history[-1]["value"]
    assert cfg.state["undo_history"] == history


def test_same_value_push_after_undo_persists_branch_truncation():
    service = UndoService(Config())
    service.push("stack", [{"block_id": "PAUSE", "enabled": True}])
    service.push("stack", [{"block_id": "CLICK_SEND", "enabled": True}])
    assert service.undo().is_ok
    service.push("stack", [{"block_id": "PAUSE", "enabled": True}])
    assert len(service.history()[0]) == 1
    assert service.redo().is_err


@pytest.mark.asyncio
async def test_world_merge_orders_sequences_and_persists_only_its_half():
    cfg = Config(
        undo_history=[
            {"kind": "stack", "value": [], "seq": 4},
            {"kind": "people", "value": {}, "seq": 1},
        ]
    )
    world = [{"kind": "labels", "value": {}, "seq": 2}]
    archive = SimpleNamespace(
        db=SimpleNamespace(is_open=True),
        load_world_undo=AsyncMock(return_value=world),
        save_world_undo=AsyncMock(),
    )
    undo = UndoService(cfg, archive=archive)
    assert (await undo.sync_world_state()).is_ok
    await asyncio.gather(*list(undo._undo_pendings))
    assert [e["seq"] for e in undo.history()[0]] == [2, 4]
    assert [e["kind"] for e in cfg.state["undo_history"]] == ["stack"]
    archive.save_world_undo.assert_awaited_once_with(world)
    assert undo._undo_pendings == []


@pytest.mark.asyncio
async def test_world_io_failure_is_reported_without_losing_app_timeline(caplog):
    cfg = Config(undo_history=[{"kind": "stack", "value": [], "seq": 3}])
    archive = SimpleNamespace(
        db=SimpleNamespace(is_open=True),
        load_world_undo=AsyncMock(side_effect=OSError("load")),
        save_world_undo=AsyncMock(side_effect=OSError("save")),
    )
    undo = UndoService(cfg, archive=archive)
    assert (await undo.sync_world_state()).is_ok
    await asyncio.gather(*list(undo._undo_pendings))
    assert undo.history()[0][0]["seq"] == 3
    assert "world undo load failed" in caplog.text
    assert "world undo save failed" in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "op,forward,method",
    [
        ("delete_message", True, "soft_delete_message"),
        ("clear_history", True, "soft_delete_history"),
        ("delete_person", True, "delete_person"),
        ("delete_person", False, "restore_person"),
        ("clear_history", False, "restore_deleted"),
    ],
)
async def test_archive_commands_call_correct_direction(op, forward, method):
    repo = SimpleNamespace(
        **{
            name: AsyncMock()
            for name in (
                "soft_delete_message",
                "soft_delete_history",
                "delete_person",
                "restore_person",
                "restore_deleted",
            )
        }
    )
    undo = UndoService(Config(), archive=SimpleNamespace(repo=repo))
    tasks = []
    undo._schedule = lambda coro: tasks.append(asyncio.create_task(coro))
    assert undo.apply_command(
        {
            "kind": "archive",
            "value": {"op": op, "nick": "N", "message_id": 12, "token": "t"},
        },
        forward,
    )
    await asyncio.gather(*tasks)
    getattr(repo, method).assert_awaited_once()
    assert getattr(repo, method).await_args.args[0] == "N"
    assert sum(m.await_count for m in vars(repo).values()) == 1


@pytest_asyncio.fixture
async def collector(tmp_path):
    db = HistoryDB(str(tmp_path / "world.db"))
    await db.init()
    page = FakePage([raw("hello", idx=0)])
    page.is_connected = True
    col = Collector(
        page,
        HistoryRepo(db),
        ChatParser(page, chunk_pause_ms=0),
        settings={"my_nick": "Me", "auto_backfill": False},
    )
    try:
        yield col
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_collector_idle_drains_media_and_retains_totals(collector):
    assert await collector.tick() == CollectorState.COLLECTED
    media = SimpleNamespace(process_pending=AsyncMock(), evict_if_needed=AsyncMock())
    collector.media = media
    assert await collector.tick() == CollectorState.NO_NEW
    media.process_pending.assert_awaited_once()
    media.evict_if_needed.assert_awaited_once()
    assert collector.state_payload()["sync_reason"] == "unchanged_cursor"
    assert collector._total == 1
    assert collector._added == 0


@pytest.mark.asyncio
async def test_collector_media_failure_does_not_break_idle(collector):
    await collector.tick()
    collector.media = SimpleNamespace(
        process_pending=AsyncMock(side_effect=OSError()), evict_if_needed=AsyncMock()
    )
    assert await collector.tick() == CollectorState.NO_NEW
    collector.media.evict_if_needed.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "patch,expected",
    [
        ({"ok": False}, CollectorState.NOT_PRIVATE),
        ({"tab": "room"}, CollectorState.NOT_PRIVATE),
        ({"participants": 3}, CollectorState.GROUP_TAB),
        ({"partner": ""}, CollectorState.NOT_PRIVATE),
        ({"partner": "Me"}, CollectorState.NOT_PRIVATE),
        ({"in_authors": ["Stranger"]}, CollectorState.GROUP_TAB),
    ],
)
async def test_collector_refusal_disarms_previously_verified_push(
    collector, patch, expected
):
    await collector.tick()
    state = await collector.parser.state()
    state.update(patch)
    collector.parser.state = AsyncMock(return_value=state)
    assert await collector.tick() == expected
    assert not collector._verified
    assert await collector.handle_push({"items": [raw("late")], "partner": "Nick"}) == 0
    assert (await collector.repo.get_person("Nick"))["message_count"] == 1


@pytest.mark.asyncio
async def test_collector_busy_guard_prevents_overlapping_reads(collector):
    entered, release = asyncio.Event(), asyncio.Event()
    original = collector.parser.state

    async def blocked():
        entered.set()
        await release.wait()
        return await original()

    collector.parser.state = AsyncMock(side_effect=blocked)
    task = asyncio.create_task(collector.tick())
    await entered.wait()
    assert await collector.tick() == collector.state
    assert collector.parser.state.await_count == 1
    release.set()
    await task
    assert not collector._busy


@pytest_asyncio.fixture
async def history_service(tmp_path):
    cfg = ConfigManager(str(tmp_path / "config.json"))
    cfg.set(
        "history", "media", {"cache_dir": str(tmp_path / "media"), "enabled": False}
    )
    service = HistoryService(
        SimpleNamespace(), config=cfg, db_path=str(tmp_path / "one.db")
    )
    await service.init()
    try:
        yield service
    finally:
        await service.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("fmt", ["json", "csv", "text", "unknown"])
async def test_export_format_contract(history_service, fmt):
    page = {
        "items": [{"time": "12:00", "from": "Л", "text": 'hello, "world"'}],
        "total": 1,
    }
    history_service.query.page = AsyncMock(return_value=page)
    result = await history_service.export_chat("Л", fmt)
    history_service.query.page.assert_awaited_once_with("Л", limit=500)
    if fmt == "text":
        assert result == '[12:00] Л: hello, "world"'
    elif fmt == "csv":
        assert (
            result
            == "time,from,text\n"
            + json.dumps(["12:00", "Л", 'hello, "world"'], ensure_ascii=False)[1:-1]
        )
    else:
        assert json.loads(result) == page


@pytest.mark.asyncio
async def test_history_page_enriches_query_without_losing_pagination(history_service):
    history_service.query.page = AsyncMock(return_value={"items": [], "next": 9})
    history_service.query.person_stats = AsyncMock(return_value={"messages": 4})
    history_service.collector.configure(my_nick="Me")
    assert await history_service.page("N", limit=7) == {
        "items": [],
        "next": 9,
        "stats": {"messages": 4},
        "my_nick": "Me",
    }
    history_service.query.page.assert_awaited_once_with("N", limit=7)


@pytest.mark.asyncio
async def test_world_undo_filters_malformed_rows_and_round_trips(history_service):
    entries = [{"seq": 5, "kind": "people", "value": {"before": [], "after": []}}]
    await history_service.save_world_undo([None, {}, *entries])
    assert await history_service.load_world_undo() == entries
    await history_service.db.execute(
        "INSERT INTO undo_history(seq,kind,value,created_at) VALUES(6,'labels','bad','')"
    )
    await history_service.db.commit()
    assert await history_service.load_world_undo() == entries
    await history_service.save_world_undo([])
    assert await history_service.load_world_undo() == []


@pytest.mark.asyncio
async def test_install_migration_failures_do_not_mark_completed(
    history_service, caplog
):
    service = history_service
    service._labels = SimpleNamespace(flush_to_db=AsyncMock())
    service.get_meta_flag = AsyncMock(return_value=False)
    service.set_meta_flag = AsyncMock()
    service._import_config_labels = AsyncMock(side_effect=RuntimeError("labels"))
    service._rehome_undo_entries = AsyncMock(side_effect=RuntimeError("undo"))
    service.config.set_state(db_recent=["/does/not/exist", service.db.path])
    report = await service.migrate_install()
    assert report == {
        "queue_merged": False,
        "labels_imported": False,
        "recent_pruned": True,
        "undo_rehomed": False,
    }
    service.set_meta_flag.assert_not_awaited()
    assert "label import" in caplog.text and "undo re-home" in caplog.text


@pytest.mark.asyncio
async def test_switch_rebinds_every_consumer_and_keeps_gate_disarmed(
    history_service, tmp_path
):
    service = history_service
    service.collector._verified = True
    service.collector._nick = "Old"
    await service.switch_db(str(tmp_path / "two.db"))
    assert service.repo.db is service.query.db is service.media.db is service.db
    assert not service.collector._verified
    assert service.collector._nick == ""
    assert service.media.cache_dir == str(tmp_path / "media" / "two")


@pytest.mark.parametrize("service_class", ["cdp", "people", "undo"])
def test_status_forwarding_preserves_message_and_level(service_class):
    from services.cdp_service import CdpService
    from services.people_service import PeopleService

    bus = EventBus()
    events = []
    bus.subscribe(LogMessage, events.append)
    service = {
        "cdp": lambda: CdpService(None, bus=bus),
        "people": lambda: PeopleService(None, bus=bus),
        "undo": lambda: UndoService(Config(), bus=bus),
    }[service_class]()
    service._log("A message", "warn")
    assert [(e.message, e.level) for e in events] == [("A message", "warn")]
