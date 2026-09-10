"""services/people_service — snapshot → mutate → undo entry → announce.

Contract (docs/archive/2026-09-09-test-suite/SERVICES_TEST_DESIGN_2026-09-09.md §2.4): every mutation
returns ``Result``; domain failures are typed, outcomes are announced on the
EventBus (PeopleChanged / UsersDeleted / LogMessage). Queue order comes from
the engine (fallback: get_queue), labels are joined at read time.

Run with:  python3 tests/integration/services/test_services_people.py
"""

import asyncio
import json
import os
import sys
import tempfile
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))

from core.events import EventBus, LogMessage, PeopleChanged, UsersDeleted  # noqa: E402
from services.people_service import PeopleService, people_row  # noqa: E402
from stores.user_memory import UserMemory, UserRecord  # noqa: E402


def rec(nick, messaged=False, gender="female", first_seen="2026-09-01T10:00",
        message_count=0):
    return UserRecord(nick=nick, gender=gender, messaged=messaged,
                      first_seen=first_seen, message_count=message_count)


class FakeEngine:
    def __init__(self, order=None, error=None):
        self.order = order
        self.error = error
        self.calls = 0

    def queue_order(self, users):
        self.calls += 1
        if self.error:
            raise self.error
        return [getattr(u, "nick", "") for u in users] if self.order is None \
            else self.order


class FakeLabels:
    def __init__(self, mapping=None, error=None):
        self.mapping = mapping or {}
        self.error = error

    def labels_map(self, nicks):
        if self.error:
            raise self.error
        return {n: list(self.mapping.get(n, [])) for n in nicks}


class FakeUndo:
    def __init__(self):
        self.pushes = []

    def push(self, kind, value):
        self.pushes.append((kind, value))
        return types.SimpleNamespace(is_ok=True, value=([], 0))


class PeopleCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.memory = UserMemory(os.path.join(self._tmp.name, "users.db"))
        await self.memory.init()
        self.bus = EventBus()
        self.people_events = []
        self.deleted_events = []
        self.logs = []
        self.bus.subscribe(PeopleChanged, lambda e: self.people_events.append(e))
        self.bus.subscribe(UsersDeleted, lambda e: self.deleted_events.append(e))
        self.bus.subscribe(LogMessage, lambda e: self.logs.append((e.message, e.level)))
        self.undo = FakeUndo()
        self.engine = FakeEngine()
        self.labels = FakeLabels()
        self.service = PeopleService(memory=self.memory, engine=self.engine,
                                     labels=self.labels, undo=self.undo,
                                     bus=self.bus)

    async def asyncTearDown(self):
        await self.memory.close()
        self._tmp.cleanup()

    async def seed(self, *users):
        for u in users:
            await self.memory.upsert_user(u)


class TestSnapshots(PeopleCase):
    async def test_rows_expose_every_column(self):
        await self.seed(rec("Anna", gender="female"))
        rows = await self.service.rows()
        self.assertEqual(len(rows), 1)
        row = rows[0]
        for key in ("nick", "gender", "registered", "anonymous", "guest",
                    "first_seen", "last_seen", "messaged", "message_count",
                    "last_messaged", "notes"):
            self.assertIn(key, row, key)
        self.assertEqual(rows[0]["nick"], "Anna")
        self.assertIsInstance(rows[0]["messaged"], bool)

    async def test_payload_orders_via_engine_and_joins_labels(self):
        await self.seed(rec("Anna", first_seen="2026-09-02"),
                        rec("Bob", first_seen="2026-09-01"))
        self.engine.order = ["Bob", "Anna"]
        self.labels.mapping = {"Anna": [7], "Bob": []}
        result = await self.service.payload()
        self.assertTrue(result.is_ok)
        payload = result.value
        by_nick = {u["nick"]: u for u in payload["users"]}
        self.assertEqual(by_nick["Bob"]["order"], 1)
        self.assertEqual(by_nick["Anna"]["order"], 2)
        self.assertEqual(by_nick["Anna"]["labels"], [7])
        self.assertEqual(by_nick["Bob"]["labels"], [])
        self.assertTrue(payload["stats"], "stats come from memory")

    async def test_payload_falls_back_to_queue_when_engine_raises(self):
        await self.seed(rec("Anna", first_seen="2026-09-02"),
                        rec("Bob", first_seen="2026-09-01"))
        self.engine.error = RuntimeError("no engine")
        result = await self.service.payload()
        self.assertTrue(result.is_ok, "engine failure must not fail the payload")
        payload = result.value
        # get_queue sorts first_seen DESC → Anna (newer) first
        self.assertEqual(payload["users"][0]["nick"], "Anna")

    async def test_payload_empty_people(self):
        result = await self.service.payload()
        self.assertTrue(result.is_ok)
        self.assertEqual(result.value["users"], [])

    async def test_labels_for_nicks_fails_open(self):
        self.service._labels = None
        self.assertEqual(self.service.labels_for_nicks(["Anna"]), {})
        self.service._labels = FakeLabels(error=RuntimeError("labels broke"))
        self.assertEqual(self.service.labels_for_nicks(["Anna"]), {})


class TestDeleteOne(PeopleCase):
    async def test_empty_nick_is_typed_err(self):
        for nick in ("", "   "):
            result = await self.service.delete_one(nick)
            self.assertTrue(result.is_err)
            self.assertEqual(result.code, "empty_nick")
            self.assertTrue(any(lvl == "warn" for _, lvl in self.logs))

    async def test_unknown_nick_is_ok_zero_no_undo(self):
        result = await self.service.delete_one("Ghost")
        self.assertTrue(result.is_ok)
        self.assertEqual(result.value, 0)
        self.assertEqual(self.undo.pushes, [], "no change → no undo entry")
        self.assertTrue(any(e.reason == "noop" for e in self.people_events))

    async def test_success_deletes_and_announces(self):
        await self.seed(rec("Anna"))
        result = await self.service.delete_one("Anna")
        self.assertTrue(result.is_ok)
        self.assertEqual(result.value, 1)
        self.assertEqual(len(await self.memory.get_all()), 0)
        self.assertEqual(len(self.deleted_events), 1)
        self.assertEqual(self.deleted_events[0].count, 1)
        self.assertEqual(json.loads(self.deleted_events[0].nicks_json), ["Anna"])
        self.assertTrue(any(e.reason == "deleted" for e in self.people_events))
        self.assertEqual(len(self.undo.pushes), 1)
        self.assertEqual(self.undo.pushes[0][0], "people")
        before, after = self.undo.pushes[0][1]["before"], self.undo.pushes[0][1]["after"]
        self.assertEqual(len(before), 1)
        self.assertEqual(after, [])

    async def test_delete_failure_is_typed_err(self):
        await self.seed(rec("Anna"))
        async def boom(_nick):
            raise RuntimeError("disk full")
        self.memory.delete_user = boom
        result = await self.service.delete_one("Anna")
        self.assertTrue(result.is_err)
        self.assertEqual(result.code, "delete_failed")
        self.assertTrue(any(e.reason == "error" for e in self.people_events))
        self.assertEqual(self.undo.pushes, [])


class TestDeleteMany(PeopleCase):
    async def test_empty_selection_is_err(self):
        result = await self.service.delete_many([])
        self.assertTrue(result.is_err)
        self.assertEqual(result.code, "empty_selection")

    async def test_mixed_known_and_unknown_counts(self):
        await self.seed(rec("Anna"), rec("Bob"))
        result = await self.service.delete_many(["Anna", "Ghost"])
        self.assertTrue(result.is_ok)
        self.assertEqual(result.value, 1, "only the existing person is deleted")
        self.assertEqual(len(await self.memory.get_all()), 1)
        self.assertEqual(len(self.undo.pushes), 1)

    async def test_nothing_deleted_pushes_no_entry(self):
        await self.seed(rec("Anna"))
        result = await self.service.delete_many(["Ghost"])
        self.assertEqual(result.value, 0)
        self.assertEqual(self.undo.pushes, [])


class TestStatus(PeopleCase):
    async def test_toggle_true_then_false(self):
        await self.seed(rec("Anna", messaged=False))
        ok = await self.service.set_messaged("Anna", True)
        self.assertEqual(ok.value, True)
        row = await self.memory.get_user("Anna")
        self.assertTrue(row.messaged)
        ok = await self.service.set_messaged("Anna", False)
        self.assertEqual(ok.value, True)
        row = await self.memory.get_user("Anna")
        self.assertFalse(row.messaged)
        self.assertEqual(len(self.undo.pushes), 2)
        self.assertTrue(any(e.reason == "marked" for e in self.people_events))

    async def test_unknown_nick_is_ok_false_no_event(self):
        before = len(self.people_events)
        result = await self.service.set_messaged("Ghost", True)
        self.assertEqual(result.value, False)
        self.assertEqual(len(self.people_events), before)
        self.assertEqual(self.undo.pushes, [])

    async def test_update_failure_is_typed_err(self):
        await self.seed(rec("Anna"))
        async def boom(_nick, _flag):
            raise RuntimeError("locked")
        self.memory.set_messaged = boom
        result = await self.service.set_messaged("Anna", True)
        self.assertTrue(result.is_err)
        self.assertEqual(result.code, "update_failed")

    async def test_reset_messaged(self):
        await self.seed(rec("Anna"), rec("Bob"))
        await self.memory.set_messaged("Anna", True)
        result = await self.service.reset_messaged()
        self.assertTrue(result.is_ok)
        # the store resets EVERY row (rowcount semantics, not "changed" rows)
        self.assertEqual(result.value, 2)
        for nick in ("Anna", "Bob"):
            row = await self.memory.get_user(nick)
            self.assertFalse(row.messaged)
            self.assertIsNone(row.last_messaged)
        self.assertTrue(any(e.reason == "reset" for e in self.people_events))
        self.assertEqual(len(self.undo.pushes), 1)

    async def test_reset_when_nothing_marked_still_ok(self):
        await self.seed(rec("Bob"))
        result = await self.service.reset_messaged()
        self.assertEqual(result.value, 1, "the one row is reset (already-new)")
        self.assertEqual(self.undo.pushes, [])


class TestClearAndApply(PeopleCase):
    async def test_clear_all(self):
        await self.seed(rec("Anna"), rec("Bob"))
        result = await self.service.clear_all()
        self.assertTrue(result.is_ok)
        self.assertEqual(result.value, 2)
        self.assertEqual(await self.memory.get_all(), [])
        deleted = self.deleted_events[-1]
        self.assertEqual(deleted.count, 2)
        self.assertEqual(json.loads(deleted.nicks_json), [])
        self.assertTrue(any(e.reason == "cleared" for e in self.people_events))

    async def test_apply_restores_a_snapshot(self):
        await self.seed(rec("Anna", message_count=4))
        await self.memory.set_messaged("Anna", True)
        snapshot = await self.service.rows()
        await self.service.clear_all()
        result = await self.service.apply(snapshot)
        self.assertTrue(result.is_ok)
        self.assertEqual(result.value, 1)
        rows = await self.service.rows()
        self.assertEqual(rows[0]["nick"], "Anna")
        self.assertTrue(rows[0]["messaged"])
        self.assertTrue(any(e.reason == "restored" for e in self.people_events))

    async def test_apply_ignores_blank_rows(self):
        result = await self.service.apply([{"nick": "  "}, {"nick": "Zed"}])
        self.assertEqual(result.value, 1)
        rows = await self.service.rows()
        self.assertEqual([r["nick"] for r in rows], ["Zed"])

    async def test_apply_failure_is_typed_err(self):
        async def boom(_rows):
            raise RuntimeError("readonly")
        self.memory.replace_all = boom
        result = await self.service.apply([{"nick": "Zed"}])
        self.assertTrue(result.is_err)
        self.assertEqual(result.code, "restore_failed")


class TestWiring(PeopleCase):
    async def test_attach_rewires_dependencies(self):
        memory2 = UserMemory(os.path.join(self._tmp.name, "users2.db"))
        await memory2.init()
        bus2 = EventBus()
        self.service.attach(memory=memory2, bus=bus2)
        self.assertIs(self.service._memory, memory2)
        self.assertIs(self.service._bus, bus2)
        events = []
        bus2.subscribe(PeopleChanged, lambda e: events.append(e))
        await self.service.clear_all()
        self.assertEqual(len(events), 1)
        await memory2.close()

    def test_people_row_serialises_ints_and_bools(self):
        row = people_row(UserRecord(nick="N", gender="male", registered=True,
                                    message_count=2))
        self.assertIsInstance(row["registered"], bool)
        self.assertIsInstance(row["message_count"], int)
        self.assertIsInstance(row["messaged"], bool)


if __name__ == "__main__":
    unittest.main(verbosity=2)
