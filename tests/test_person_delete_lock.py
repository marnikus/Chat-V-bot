"""Regression: queue write failures must not poison the shared archive world."""

import asyncio
import sqlite3

import pytest
import pytest_asyncio

from stores.history_db import HistoryDB
from stores.history_repo import HistoryRepo
from stores.user_memory import UserMemory, UserRecord


@pytest_asyncio.fixture
async def world(tmp_path):
    archive = await HistoryDB(str(tmp_path / "world.db")).init()
    memory = UserMemory(archive.path)
    await memory.init()
    repo = HistoryRepo(archive)
    await repo.ensure_person("Partner")
    await memory.upsert_user(UserRecord("Partner"))
    await archive.execute("PRAGMA busy_timeout=50")
    try:
        yield archive, repo, memory
    finally:
        await memory._db.rollback()
        await memory.close()
        await archive.close()


async def assert_archive_writable(world):
    archive, repo, memory = world
    assert not memory._db.in_transaction, "failed queue write leaked a transaction"
    assert await repo.delete_person("Partner", token="test-delete")
    assert await repo.restore_person("Partner", token="test-delete")
    assert not archive.conn.in_transaction


@pytest.mark.asyncio
async def test_failed_upsert_does_not_lock_person_delete_or_restore(world):
    archive, _, memory = world
    await archive.execute("CREATE TRIGGER reject_update BEFORE UPDATE ON users "
                          "BEGIN SELECT RAISE(ABORT, 'rejected update'); END")
    await archive.commit()
    with pytest.raises(sqlite3.IntegrityError, match="rejected update"):
        await memory.upsert_user(UserRecord("Partner"))
    await assert_archive_writable(world)
    assert (await memory.get_user("Partner")).nick == "Partner"


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["DELETE", "INSERT"])
async def test_replacement_failure_rolls_back_entire_queue(world, operation):
    archive, _, memory = world
    await archive.execute(f"CREATE TRIGGER reject_replace BEFORE {operation} ON users "
                          "BEGIN SELECT RAISE(ABORT, 'rejected replacement'); END")
    await archive.commit()
    with pytest.raises(sqlite3.IntegrityError, match="rejected replacement"):
        await memory.replace_all([{"nick": "Another"}])
    await assert_archive_writable(world)
    assert [u.nick for u in await memory.get_all()] == ["Partner"]


@pytest.mark.asyncio
async def test_cancelled_replacement_rolls_back_before_another_writer(world, monkeypatch):
    _, _, memory = world
    deleted = asyncio.Event()
    original = memory._db.execute

    async def pause_after_delete(sql, *args):
        result = await original(sql, *args)
        if sql == "DELETE FROM users":
            deleted.set()
            await asyncio.Event().wait()
        return result

    monkeypatch.setattr(memory._db, "execute", pause_after_delete)
    task = asyncio.create_task(memory.replace_all([{"nick": "Another"}]))
    await asyncio.wait_for(deleted.wait(), 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await assert_archive_writable(world)
    assert [u.nick for u in await memory.get_all()] == ["Partner"]
    assert await memory.upsert_user(UserRecord("Later")) == "new"


@pytest.mark.asyncio
async def test_discovery_cannot_enter_a_partly_replaced_queue(world, monkeypatch):
    _, _, memory = world
    deleted, release, started, attempted = (asyncio.Event() for _ in range(4))
    original = memory._db.execute

    async def paused_execute(sql, *args):
        if asyncio.current_task().get_name() == "concurrent-discovery":
            attempted.set()
        result = await original(sql, *args)
        if sql == "DELETE FROM users":
            deleted.set()
            await release.wait()
        return result

    async def discover():
        started.set()
        return await memory.upsert_user(UserRecord("Partner"))

    monkeypatch.setattr(memory._db, "execute", paused_execute)
    replacing = asyncio.create_task(memory.replace_all([{"nick": "Partner"}, {"nick": "Other"}]))
    await asyncio.wait_for(deleted.wait(), 2)
    discovery = asyncio.create_task(discover(), name="concurrent-discovery")
    try:
        await asyncio.wait_for(started.wait(), 2)
        assert not attempted.is_set(), "discovery entered another writer's uncommitted DELETE"
    finally:
        release.set()
        results = await asyncio.gather(replacing, discovery, return_exceptions=True)
    assert results == [2, "known"]
    assert {u.nick for u in await memory.get_all()} == {"Partner", "Other"}
    await assert_archive_writable(world)


@pytest.mark.asyncio
async def test_upsert_only_ignores_nick_conflicts_not_invalid_rows(world):
    _, _, memory = world
    with pytest.raises(sqlite3.IntegrityError):
        await memory.upsert_user(UserRecord(None))
    await assert_archive_writable(world)


@pytest.mark.asyncio
async def test_concurrent_discovery_and_restore_preserve_existing_flags(world):
    _, _, memory = world
    row = {"nick": "Partner", "messaged": True, "message_count": 7,
           "notes": "keep", "first_seen": "2020-01-01", "last_messaged": "2020-01-02"}
    for _ in range(10):
        await asyncio.gather(memory.replace_all([row]),
                             memory.upsert_user(UserRecord("Partner")),
                             memory.upsert_user(UserRecord("Partner")))
        user = await memory.get_user("Partner")
        assert (user.messaged, user.message_count, user.notes) == (True, 7, "keep")
        assert user.first_seen == "2020-01-01"
        await assert_archive_writable(world)


@pytest.mark.asyncio
@pytest.mark.parametrize("method,args,operation", [
    ("mark_messaged", ("Partner",), "UPDATE"),
    ("set_messaged", ("Partner", True), "UPDATE"),
    ("reset_messaged", (), "UPDATE"),
    ("delete_user", ("Partner",), "DELETE"),
    ("delete_users", (["Partner"],), "DELETE"),
    ("clear_all", (), "DELETE"),
])
async def test_all_queue_mutators_release_failed_transactions(world, method, args, operation):
    archive, _, memory = world
    await archive.execute(f"CREATE TRIGGER reject_write BEFORE {operation} ON users "
                          "BEGIN SELECT RAISE(ABORT, 'rejected write'); END")
    await archive.commit()
    with pytest.raises(sqlite3.IntegrityError, match="rejected write"):
        await getattr(memory, method)(*args)
    await assert_archive_writable(world)
    assert await memory.get_user("Partner")


@pytest.mark.asyncio
async def test_unopened_store_reports_a_clear_failure_without_creating_a_file(tmp_path):
    path = tmp_path / "unopened.db"
    memory = UserMemory(str(path))
    with pytest.raises(RuntimeError, match="not open"):
        await memory.upsert_user(UserRecord("Partner"))
    assert not path.exists()


@pytest.mark.asyncio
async def test_archive_write_waits_for_read_cursor_after_queue_commit(world, monkeypatch):
    archive, _, memory = world
    opened, release, started, attempted = (asyncio.Event() for _ in range(4))
    original = archive.conn.execute

    async def paused_execute(sql, *args):
        if asyncio.current_task().get_name() == "archive-writer":
            attempted.set()
        cursor = await original(sql, *args)
        if sql == "SELECT * FROM persons":
            opened.set()
            await release.wait()
        return cursor

    async def write():
        started.set()
        await archive.execute("UPDATE persons SET message_count=0 WHERE nick='Partner'")
        await archive.commit()

    monkeypatch.setattr(archive.conn, "execute", paused_execute)
    reader = asyncio.create_task(archive.fetchone("SELECT * FROM persons"))
    await asyncio.wait_for(opened.wait(), 2)
    await memory.upsert_user(UserRecord("Other"))  # advances the WAL snapshot
    writer = asyncio.create_task(write(), name="archive-writer")
    try:
        await asyncio.wait_for(started.wait(), 2)
        assert not attempted.is_set(), "write entered SQLite with a stale read cursor alive"
    finally:
        release.set()
        results = await asyncio.gather(reader, writer, return_exceptions=True)
        await archive.conn.rollback()
    assert not any(isinstance(result, BaseException) for result in results)
    await assert_archive_writable(world)


@pytest.mark.asyncio
async def test_cancelling_cursor_acquisition_still_closes_it(world, monkeypatch):
    archive, _, memory = world
    opened, release, closed = (asyncio.Event() for _ in range(3))
    original = archive.conn.execute

    async def delayed_execute(sql, *args):
        cursor = await original(sql, *args)
        if sql == "SELECT * FROM persons":
            close = cursor.close

            async def record_close():
                await close()
                closed.set()

            cursor.close = record_close
            opened.set()
            await release.wait()
        return cursor

    monkeypatch.setattr(archive.conn, "execute", delayed_execute)
    reader = asyncio.create_task(archive.fetchone("SELECT * FROM persons"))
    await asyncio.wait_for(opened.wait(), 2)
    await memory.upsert_user(UserRecord("Other"))
    reader.cancel()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await reader
    assert closed.is_set(), "cancelled acquisition abandoned the live cursor"
    await assert_archive_writable(world)
