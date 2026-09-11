"""One world, one writer's turn — and the undo that must prove itself.

Reproduces the bug report of 2026-09-11 against the REAL stack: the real
`UserMemory` queue and the real `HistoryService` archive on ONE world file
(two connections), the real `Bridge`, the real global timeline.

Two things are pinned here:

1. **The gate** (`stores/world_lock.py`): a second connection's write waits
   for the first one's transaction instead of dying with
   `database is locked`, while a read never waits and the turn is given back
   on every path (`commit`, a failed statement, `close`).
2. **A verified undo**: “archive restored” may only be said after the rows
   say so. A refused command must log an ERROR, leave the database untouched,
   put the People half back, and keep the entry where Ctrl+Z finds it again.

Run with:  python3 tests/test_world_write_gate.py
"""

import asyncio
import json
import os
import sqlite3
import sys
import tempfile
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtCore import QObject  # noqa: E402

from backend.bridge import Bridge  # noqa: E402
from backend.config_manager import ConfigManager  # noqa: E402
from backend.history_query import PersonPageRequest  # noqa: E402
from core.events import LogMessage  # noqa: E402
from core.result import Err  # noqa: E402
from services.history import HistoryService  # noqa: E402
from services.undo_archive import (ArchiveCommands, _disagrees,  # noqa: E402
                                   _outcome, _person_verdict, _reason,
                                   _rows, _row_verdict, _state)
from stores import world_lock  # noqa: E402
from stores.user_memory import UserMemory, UserRecord  # noqa: E402

from test_chat_parser_delta import FakePage, raw  # noqa: E402


class ConnectedPage(FakePage):
    is_connected = True


async def settle(times=40, step=0.02):
    """Let the scheduled tasks of one undo finish."""
    for _ in range(times):
        await asyncio.sleep(step)


async def wait_until(predicate, timeout=6.0, step=0.05):
    """Poll until `predicate()` is true — retries back off on real time."""
    waited = 0.0
    while waited < timeout:
        if predicate():
            return True
        await asyncio.sleep(step)
        waited += step
    return predicate()


# ═════════════════════════════════════════════════════════════════
# the gate itself
# ═════════════════════════════════════════════════════════════════
class TestGateUnit(unittest.IsolatedAsyncioTestCase):
    async def test_classifies_writes_and_locks(self):
        self.assertTrue(world_lock.is_write_sql("INSERT INTO users(nick) …"))
        self.assertTrue(world_lock.is_write_sql("  update users SET a=1"))
        self.assertTrue(world_lock.is_write_sql("DELETE FROM messages"))
        self.assertFalse(world_lock.is_write_sql("SELECT * FROM users"))
        self.assertTrue(world_lock.is_locked_error(
            sqlite3.OperationalError("database is locked")))
        self.assertTrue(world_lock.is_locked_error(
            sqlite3.OperationalError("database is busy")))
        self.assertFalse(world_lock.is_locked_error(ValueError("nope")))

    async def test_one_gate_per_file_and_two_per_two_files(self):
        first = world_lock.gate_for("/tmp/a/world.db")
        self.assertIs(first, world_lock.gate_for("/tmp/a/./world.db"))
        self.assertIsNot(first, world_lock.gate_for("/tmp/b/world.db"))

    async def test_the_same_token_may_enter_twice(self):
        gate = world_lock.WorldGate("same")
        token = object()
        self.assertTrue(await gate.enter(token))
        self.assertTrue(await gate.enter(token), "a re-entrant take must not "
                                                 "wait for itself")
        self.assertTrue(gate.busy)
        gate.leave(token)
        self.assertTrue(gate.busy, "one level of two is still a hold")
        gate.leave(token)
        self.assertFalse(gate.busy)
        self.assertIsNone(gate.holder)

    async def test_a_second_token_waits_and_a_read_does_not(self):
        gate = world_lock.WorldGate("wait")
        first, second = object(), object()
        await gate.enter(first)
        waiter = asyncio.ensure_future(gate.enter(second))
        await asyncio.sleep(0.05)
        self.assertFalse(waiter.done(), "the second connection must wait")
        gate.leave(first)
        self.assertTrue(await asyncio.wait_for(waiter, 1.0))
        gate.leave(second)

    async def test_a_gate_that_never_frees_fails_open(self):
        gate = world_lock.WorldGate("stuck")
        await gate.enter(object())
        original = world_lock.WAIT_S
        world_lock.WAIT_S = 0.05
        try:
            self.assertFalse(await gate.enter(object()),
                             "a stuck turn must not hang the caller forever")
        finally:
            world_lock.WAIT_S = original
        self.assertTrue(gate.busy, "the stuck holder keeps its turn")

    async def test_retry_locked_retries_only_locked_errors(self):
        calls = {"locked": 0, "other": 0}

        async def flaky_locked():
            calls["locked"] += 1
            if calls["locked"] < 3:
                raise sqlite3.OperationalError("database is locked")
            return "ok"

        async def always_broken():
            calls["other"] += 1
            raise ValueError("not a lock")

        self.assertEqual(await world_lock.retry_locked(flaky_locked,
                                                       attempts=5, delay=0),
                         "ok")
        self.assertEqual(calls["locked"], 3)
        with self.assertRaises(ValueError):
            await world_lock.retry_locked(always_broken, attempts=3, delay=0)
        self.assertEqual(calls["other"], 1, "other errors must not be retried")


class TestArchiveFacts(unittest.IsolatedAsyncioTestCase):
    """The pure helpers decide what the log may say — pin them directly."""

    def test_the_snapshot_half_is_read_the_way_the_entry_stores_it(self):
        value = {"people": {"before": [{"nick": "A"}],
                            "after": [{"nick": "B"}]}}
        self.assertEqual(_rows(value, True), [{"nick": "B"}])
        self.assertEqual(_rows(value, False), [{"nick": "A"}])
        self.assertIsNone(_rows({}, True), "an entry without a snapshot")
        self.assertIsNone(_rows({"people": {"after": "nope"}}, True))

    async def test_the_read_back_is_skipped_when_there_is_nothing_to_ask(self):
        self.assertIsNone(await _state(None, "Nick"), "no archive wired")
        self.assertIsNone(await _state(object(), ""), "no nick to ask about")

    def test_the_read_back_decides_whether_a_command_disagrees(self):
        self.assertEqual(_disagrees("delete_person", False, None, None), "")
        self.assertEqual(_disagrees("delete_person", False, None,
                                    {"missing": True}),
                         "the person is not in this database")
        self.assertEqual(_person_verdict(False, {"deleted": False}), "")
        self.assertEqual(_person_verdict(False, {"deleted": True}),
                         "the person is still deleted")
        self.assertEqual(_person_verdict(True, {"deleted": False}),
                         "the person was not deleted")
        self.assertEqual(_row_verdict(True, {"hidden": 1}, {"hidden": 1}),
                         "the messages are still visible")
        self.assertEqual(_row_verdict(False, {"hidden": 1}, {"hidden": 1}),
                         "the messages did not come back")
        self.assertEqual(_row_verdict(True, {"hidden": 1}, {"hidden": 2}), "")
        self.assertEqual(_row_verdict(False, {"hidden": 2}, {"hidden": 1}), "")

    def test_the_success_line_uses_the_verified_state(self):
        self.assertIn("People list only",
                      _outcome("delete_person", False, None))
        self.assertEqual(_outcome("delete_person", False, {"messages": 4}),
                         "is back in the database (4 message(s))")
        self.assertEqual(_outcome("delete_person", True, {"hidden": 2}),
                         "is hidden again (2 message(s) hidden)")
        self.assertEqual(_outcome("clear_history", True, {"hidden": 3}),
                         "history hidden (3 message(s))")
        self.assertEqual(_outcome("clear_history", False, {"messages": 3}),
                         "history restored (3 message(s))")
        self.assertEqual(_outcome("delete_message", False, {}),
                         "message restored")

    async def test_a_cancelled_command_is_never_reported_as_done(self):
        """Cancellation propagates instead of turning into a success log."""
        bus = types.SimpleNamespace(emit=lambda *a, **k: None)
        logged = []
        service = types.SimpleNamespace(
            _archive=None, _bus=bus, _log=lambda *a, **k: logged.append(a))

        async def slow_apply(rows):
            await asyncio.sleep(0.5)
            return None

        service._people = types.SimpleNamespace(apply=slow_apply)
        commands = ArchiveCommands(service)
        value = {"op": "delete_person", "nick": "X",
                 "people": {"before": [{"nick": "X"}]}}
        task = asyncio.ensure_future(commands.run(None, value, False))
        await asyncio.sleep(0.05)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(logged, [], "a cancelled command says nothing")

    def test_a_reason_is_one_short_line(self):
        self.assertEqual(_reason(ValueError("a\n  b ")), "a b")
        self.assertEqual(_reason(None), "NoneType")


# ═════════════════════════════════════════════════════════════════
# the real stack: queue + archive on ONE world file
# ═════════════════════════════════════════════════════════════════
class WorldCase(unittest.IsolatedAsyncioTestCase):
    """The app's own wiring: UserMemory and HistoryService share the file."""

    async def asyncSetUp(self):
        self.dir = tempfile.mkdtemp()
        self.world = os.path.join(self.dir, "v.db")
        self.cfg = ConfigManager(os.path.join(self.dir, "config.json"))
        self.memory = UserMemory(self.world)
        await self.memory.init()
        self.page = ConnectedPage([])
        self.service = HistoryService(cdp=self.page, config=self.cfg,
                                      db_path=self.world, memory=self.memory)
        await self.service.init()
        self.service.collector.configure(my_nick="Me")
        br = Bridge.__new__(Bridge)
        QObject.__init__(br)
        br._config = self.cfg
        br._engine = types.SimpleNamespace(load_stack=lambda _b: None)
        br._memory = self.memory
        br._presets = None
        br.attach_history(self.service)
        self.bridge = br
        self.logs = []
        self.ctx = br._ensure_ctx()[0]
        self.ctx.bus.subscribe(LogMessage, lambda e: self.logs.append(e))

    async def asyncTearDown(self):
        await self.service.close()
        await self.memory.close()

    async def seed(self, nick="Mloni", count=4):
        self.page.partner = nick
        self.page.messages = [raw(f"m{i}", from_nick=nick, idx=i)
                              for i in range(count)]
        await self.service.collector.tick()
        await self.memory.upsert_user(UserRecord(nick=nick))

    async def db_nicks(self):
        page = await self.service.query.list_persons(PersonPageRequest(limit=50))
        return [item["nick"] for item in page["items"]]

    async def no_sqlite_waiter(self):
        """Strict SQLite: a held write lock FAILS at once, never waits.

        The app's real failure (`database is locked` on the undo path) is the
        case SQLite refuses to wait out, so the tests must run without the
        connection-level busy handler that would otherwise paper over a
        missing turn.
        """
        for db in (self.service.db, self.memory._db):
            await db.execute("PRAGMA busy_timeout=0")
            await db.commit()                 # a write statement holds a turn

    async def visible(self, nick="Mloni"):
        page = await self.service.query.page(nick, limit=100)
        return [item["text"] for item in page["items"]]

    def messages(self, level=None):
        return [e.message for e in self.logs
                if level is None or e.level == level]


class TestTwoConnectionsShareTheWorld(WorldCase):
    async def test_a_slow_queue_commit_never_locks_the_archive_out(self):
        """THE BUG: the queue rewrites the list while the undo restores rows.

        A commit that takes its time (Google Drive, a big table) used to make
        the archive's UPDATE fail instantly with `database is locked` — the
        WAL “already read, cannot upgrade” case, which no busy_timeout can
        wait out. The gate makes the second connection wait instead.
        """
        await self.seed(count=4)
        await self.no_sqlite_waiter()
        for i in range(60):
            await self.memory.upsert_user(UserRecord(nick=f"P{i}"))
        repo = self.service.repo
        token = repo.new_op_token()
        await repo.delete_person("Mloni", hard=False, token=token)
        rows = [{"nick": u.nick, "gender": u.gender, "messaged": u.messaged,
                 "first_seen": u.first_seen, "last_seen": u.last_seen}
                for u in await self.memory.get_all()]

        timeline = []
        real_commit = self.memory._db.commit
        real_restore = repo.restore_person

        async def slow_commit():
            await asyncio.sleep(0.3)
            await real_commit()
            timeline.append("queue committed")

        async def timed_restore(nick, token=""):
            answer = await real_restore(nick, token=token)
            timeline.append("archive restored")
            return answer

        self.memory._db.commit = slow_commit
        repo.restore_person = timed_restore
        try:
            results = await asyncio.gather(
                self.memory.replace_all(rows),
                repo.restore_person("Mloni", token=token),
                return_exceptions=True)
        finally:
            self.memory._db.commit = real_commit
            repo.restore_person = real_restore
        self.assertEqual(timeline, ["queue committed", "archive restored"],
                         "the archive write must wait for the open "
                         "transaction, not run beside it")
        self.assertEqual([r for r in results if isinstance(r, Exception)], [],
                         "two connections must not fight over the file")
        self.assertIn("Mloni", await self.db_nicks())
        self.assertEqual(len(await self.visible()), 4)
        self.assertFalse(self.service.db.turn.held,
                         "the writer's turn must be given back")

    async def test_world_write_hands_the_world_back_on_a_timeout(self):
        """The fail-open path must still release a turn it never took."""
        gate = world_lock.gate_for(self.world)
        holder = object()
        await gate.enter(holder)
        original = world_lock.WAIT_S
        world_lock.WAIT_S = 0.05
        try:
            async with world_lock.world_write(self.world, object()) as held:
                self.assertFalse(held, "the turn was not available")
        finally:
            world_lock.WAIT_S = original
            gate.leave(holder)
        self.assertFalse(gate.busy)

    async def test_busy_timeout_never_breaks_an_open_database(self):
        await world_lock.apply_busy_timeout(object(), "nowhere.db")
        self.assertTrue(self.service.db.is_open, "a failed PRAGMA is a warning")

    async def test_both_writers_at_once_leave_a_consistent_world(self):
        """Ctrl+Z fires the queue restore and the archive restore together."""
        await self.seed(count=4)
        await self.no_sqlite_waiter()
        for i in range(20):
            await self.memory.upsert_user(UserRecord(nick=f"P{i}"))
        repo = self.service.repo
        token = repo.new_op_token()
        await repo.delete_person("Mloni", hard=False, token=token)
        rows = [{"nick": u.nick, "gender": u.gender, "messaged": u.messaged,
                 "first_seen": u.first_seen, "last_seen": u.last_seen}
                for u in await self.memory.get_all()]
        results = await asyncio.gather(
            self.memory.replace_all(rows),
            repo.restore_person("Mloni", token=token),
            return_exceptions=True)
        self.assertEqual([r for r in results if isinstance(r, Exception)], [])
        self.assertIn("Mloni", await self.db_nicks())
        self.assertEqual(len(await self.visible()), 4)

    async def test_the_queue_write_waits_for_the_archive_transaction(self):
        await self.seed(count=2)
        await self.no_sqlite_waiter()
        db = self.service.db
        await db.turn.begin()
        waiting = asyncio.ensure_future(
            self.memory.upsert_user(UserRecord(nick="Late")))
        await asyncio.sleep(0.1)
        self.assertFalse(waiting.done(), "the queue must queue up")
        await db.commit()
        await asyncio.wait_for(waiting, 2.0)
        self.assertIsNotNone(await self.memory.get_user("Late"))

    async def test_a_failed_statement_gives_the_turn_back(self):
        await self.seed(count=1)
        with self.assertRaises(sqlite3.OperationalError):
            await self.service.db.execute("UPDATE no_such_table SET x=1")
        self.assertFalse(self.service.db.turn.held)
        self.assertFalse(world_lock.gate_for(self.world).busy)


class TestUndoProvesItself(WorldCase):
    async def test_delete_then_undo_restores_person_and_history(self):
        await self.seed(count=4)
        self.assertTrue(self.bridge.history_delete_person("Mloni", False))
        await settle()
        self.assertNotIn("Mloni", await self.db_nicks())
        self.assertNotIn("Mloni", [u.nick for u in await self.memory.get_all()])

        raw_result = self.bridge.undo()
        await settle()
        self.assertNotEqual(raw_result, "null")
        self.assertIn("Mloni", await self.db_nicks(),
                      "undo must put the person back in the database")
        self.assertEqual(len(await self.visible()), 4,
                         "…with the whole conversation")
        self.assertIn("Mloni", [u.nick for u in await self.memory.get_all()])
        self.assertTrue(any("is back in the database" in m
                            for m in self.messages()),
                        f"the log must state the verified state: {self.logs}")

    async def test_redo_hides_them_again_and_says_so(self):
        await self.seed(count=4)
        self.bridge.history_delete_person("Mloni", False)
        await settle()
        self.bridge.undo()
        await settle()
        self.bridge.redo()
        await settle()
        self.assertNotIn("Mloni", await self.db_nicks())
        self.assertEqual(await self.visible(), [])
        self.assertTrue(any("is hidden again" in m for m in self.messages()),
                        f"the log must state the verified state: {self.logs}")

    async def test_clear_history_undo_reports_the_messages_it_restored(self):
        await self.seed(count=3)
        self.assertTrue(self.bridge.history_clear_person("Mloni"))
        await settle()
        self.assertEqual(await self.visible(), [])
        self.assertIn("Mloni", await self.db_nicks(),
                      "clearing keeps the person")
        self.bridge.undo()
        await settle()
        self.assertEqual(len(await self.visible()), 3)
        self.assertTrue(any("history restored" in m for m in self.messages()))

        self.bridge.redo()                      # … and hiding them again
        await settle()
        self.assertEqual(await self.visible(), [])
        self.assertTrue(any("history hidden (3 message(s))" in m
                            for m in self.messages()),
                        f"the redo must report the hidden count: {self.logs}")

    async def test_a_refused_undo_reports_and_stays_retryable(self):
        """A locked database must NOT be reported as a restored person."""
        await self.seed(count=4)
        self.bridge.history_delete_person("Mloni", False)
        await settle()
        repo = self.service.repo
        original = repo.restore_person
        attempts = {"n": 0}

        async def locked(nick, token=""):
            attempts["n"] += 1
            raise sqlite3.OperationalError("database is locked")

        repo.restore_person = locked
        try:
            self.bridge.undo()
            await wait_until(lambda: any("Undo failed" in e.message
                                         for e in self.logs))
        finally:
            repo.restore_person = original

        self.assertGreater(attempts["n"], 1, "a lock must be retried")
        self.assertNotIn("Mloni", await self.db_nicks(),
                         "a failed undo must not pretend it worked")
        self.assertFalse(any("is back in the database" in m
                             for m in self.messages()),
                         "no success may be claimed")
        self.assertTrue(any(e.level == "error" and "Undo failed" in e.message
                            for e in self.logs),
                        "a failed undo must be an ERROR, not a success")
        self.assertNotIn("Mloni", [u.nick for u in await self.memory.get_all()],
                         "the People half must follow the archive back")

        # the timeline kept the entry: pressing Ctrl+Z again really retries
        before = len(self.logs)
        self.bridge.undo()
        await settle()
        self.assertIn("Mloni", await self.db_nicks())
        self.assertEqual(len(await self.visible()), 4)
        self.assertTrue(any("is back in the database" in e.message
                            for e in self.logs[before:]))

    async def test_the_db_window_is_told_about_every_change(self):
        """The Full User Database refreshes itself — delete and undo."""
        seen = []
        self.bridge.userdb_changed.connect(
            lambda payload: seen.append(json.loads(payload)))
        await self.seed(count=2)
        self.assertTrue(self.bridge.history_delete_person("Mloni", False))
        await settle()
        self.bridge.undo()
        await settle()
        actions = [payload.get("action") for payload in seen]
        self.assertIn("deleted", actions)
        self.assertIn("undo", actions)
        undo_event = next(p for p in seen if p.get("action") == "undo")
        self.assertTrue(undo_event.get("verified"),
                        "the refresh must follow the verified state")


    async def test_a_refused_people_half_stops_the_command(self):
        """If the list half cannot land, the archive half must not run."""
        await self.seed(count=3)
        self.bridge.history_delete_person("Mloni", False)
        await settle()
        undo = self.ctx.undo
        people = undo._people
        real = people.apply

        async def refuse(rows):
            return Err("restore_failed", "boom")

        people.apply = refuse
        try:
            self.bridge.undo()
            await wait_until(lambda: any("Undo failed" in e.message
                                         for e in self.logs))
        finally:
            people.apply = real
        self.assertTrue(any("the people list refused it" in e.message
                            for e in self.logs),
                        f"the reason must reach the user: {self.logs}")
        self.assertNotIn("Mloni", await self.db_nicks(),
                         "the archive half must not run when the list failed")
        self.assertNotIn("Mloni", [u.nick for u in await self.memory.get_all()],
                         "the failed list half is put back (RULE 14)")

    async def test_a_people_only_entry_says_there_is_no_archive(self):
        """No archive running: the log may not claim a database restore."""
        await self.seed(count=2)
        undo = self.ctx.undo
        rows = [{"nick": u.nick, "message_count": u.message_count}
                for u in await self.memory.get_all() if u.nick != "Mloni"]
        undo.push("archive", {"op": "delete_person", "nick": "Mloni",
                              "people": {"before": rows, "after": rows}})
        archive, undo._archive = undo._archive, None
        try:
            self.bridge.undo()
            await wait_until(lambda: any("People list only" in e.message
                                         for e in self.logs))
        finally:
            undo._archive = archive
        self.assertTrue(any("People list only" in e.message for e in self.logs),
                        f"the report must match the wiring: {self.logs}")


class TestEmptyTrash(WorldCase):
    """The only irreversible action asks for a click, and it is honest."""

    async def test_a_soft_delete_stays_reversible_until_the_trash_is_emptied(self):
        await self.seed(count=3)
        self.bridge.history_delete_person("Mloni", False)
        await settle()
        self.assertIsNotNone(await self.service.repo.get_person("Mloni"),
                             "a soft delete keeps the tombstone")

        self.bridge.undo()                       # still fully reversible …
        await settle()
        self.assertIn("Mloni", await self.db_nicks())
        self.assertEqual(len(await self.visible()), 3)

        self.bridge.history_delete_person("Mloni", False)
        await settle()
        self.assertTrue(self.bridge.history_purge_deleted(""))   # … until now
        await settle()
        self.assertIsNone(await self.service.repo.get_person("Mloni"),
                          "the emptied trash leaves no row behind")
        self.assertNotIn("Mloni", await self.db_nicks())

    async def test_undo_after_a_purge_reports_the_failure(self):
        """Ctrl+Z on an erased person must never claim a restore."""
        await self.seed(count=3)
        self.bridge.history_delete_person("Mloni", False)
        await settle()
        self.bridge.history_purge_deleted("")
        await settle()
        before = len(self.logs)

        self.bridge.undo()
        await wait_until(lambda: any("Undo failed" in e.message
                                     for e in self.logs[before:]))
        self.assertTrue(any(e.level == "error" and "Undo failed" in e.message
                            for e in self.logs[before:]),
                        "an undo that cannot restore must say so")
        self.assertFalse(any("is back in the database" in e.message
                             for e in self.logs[before:]))
        self.assertNotIn("Mloni", await self.db_nicks())
        self.assertNotIn("Mloni", [u.nick for u in await self.memory.get_all()],
                         "the people list must not hold someone the "
                         "database does not have (RULE 14)")


if __name__ == "__main__":
    unittest.main(verbosity=2)
