"""Delete/undo/redo/clear via real services and slots, in ONE shared world."""

import asyncio
import json
import sqlite3
from types import SimpleNamespace

import pytest
import pytest_asyncio

from backend.config_manager import ConfigManager
from bridge.context import BridgeContext
from bridge.history_bridge import HistoryBridge
from core.events import ArchiveUndoApplied, PeopleChanged
from services.history import HistoryService
from stores.history_models import MessageRecord
from stores.user_memory import UserMemory, UserRecord


@pytest_asyncio.fixture
async def ui(tmp_path):
    config = ConfigManager(str(tmp_path / "config.json"))
    memory = UserMemory(str(tmp_path / "world.db"))
    await memory.init()
    archive = HistoryService(SimpleNamespace(is_connected=False), config,
                             db_path=memory.db_path, memory=memory)
    await archive.init()
    ctx = BridgeContext(config=config, memory=memory, archive=archive)
    bridge = HistoryBridge(ctx)
    changed, restored, people = asyncio.Queue(), asyncio.Queue(), asyncio.Queue()
    errors = []
    bridge.userdb_changed.connect(lambda data: changed.put_nowait(json.loads(data)))
    bridge.history_error.connect(lambda scope, detail: errors.append((scope, detail)))
    ctx.bus.subscribe(ArchiveUndoApplied, restored.put_nowait)
    ctx.bus.subscribe(PeopleChanged, lambda event: people.put_nowait(event)
                      if event.reason == "restored" else None)
    rows = [{"nick": f"Queue-{i:03d}"} for i in range(188)]
    rows.append({"nick": "Partner", "messaged": True, "message_count": 7, "notes": "keep"})
    await memory.replace_all(rows)
    await archive.repo.append("Partner", [
        MessageRecord(direction="in", from_nick="Partner", text=f"message {i}", ts_display=f"10:0{i}")
        for i in range(3)])
    try:
        yield SimpleNamespace(ctx=ctx, bridge=bridge, archive=archive, memory=memory,
                              changed=changed, restored=restored, people=people, errors=errors)
    finally:
        await ctx.undo._world_store.settle()
        await archive.close()
        await memory.close()


async def receive(queue):
    return await asyncio.wait_for(queue.get(), 5)


async def check_state(ui, deleted=False):
    await ui.ctx.undo._world_store.settle()
    assert ui.errors == []
    users = await ui.memory.get_all()
    assert len(users) == (188 if deleted else 189)
    assert bool(await ui.memory.get_user("Partner")) is not deleted
    person = await ui.archive.repo.get_person("Partner")
    assert bool(person["deleted_at"]) is deleted
    if not deleted:
        user = await ui.memory.get_user("Partner")
        assert (user.messaged, user.message_count, user.notes) == (True, 7, "keep")
    # A fresh connection sees durable rows, not a writer's uncommitted state.
    with sqlite3.connect(ui.memory.db_path, timeout=0) as observer:
        observer.execute("BEGIN IMMEDIATE")
        count = observer.execute("SELECT COUNT(*) FROM messages WHERE deleted_at=''").fetchone()[0]
        assert count == (0 if deleted else 3)
        observer.rollback()


async def timeline(ui, forward=False, with_people=True):
    result = ui.ctx.undo.redo() if forward else ui.ctx.undo.undo()
    assert result.is_ok
    assert (await receive(ui.restored)).forward is forward
    if with_people:
        await receive(ui.people)
    assert (await receive(ui.changed))["action"] == ("redo" if forward else "undo")


@pytest.mark.asyncio
@pytest.mark.parametrize("concurrent_discovery", [False, True])
async def test_repeated_delete_restore_and_clear_in_shared_world(ui, concurrent_discovery):
    async def discover():
        if concurrent_discovery:
            for _ in range(12):
                await ui.memory.upsert_user(UserRecord("Partner"))

    for _ in range(3):
        assert ui.bridge.history_delete_person("Partner")
        assert (await receive(ui.changed))["action"] == "deleted"
        await check_state(ui, deleted=True)
        # Discovery is active while the full 189-row snapshot is restored.
        await asyncio.gather(timeline(ui), discover())
        await check_state(ui)
        await timeline(ui, forward=True)
        await check_state(ui, deleted=True)
        await timeline(ui)
        await check_state(ui)
        assert ui.bridge.history_clear_person("Partner")
        assert (await receive(ui.changed))["action"] == "cleared"
        assert (await ui.archive.repo.get_person("Partner"))["message_count"] == 0
        await timeline(ui, with_people=False)
        await check_state(ui)
