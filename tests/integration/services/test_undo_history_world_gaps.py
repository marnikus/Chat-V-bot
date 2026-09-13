"""The undo-family seams no test reached (Round G step 5, plan §1e).

`test_services_undo.py` pins the timeline contract and
`test_services_undo_gaps.py` the `undo_db` seams — but four surfaces stayed
unexercised after Round F measured them (§8.12.5, §8.15.8):

* `undo_history._migrated_entry` — **no test at all** of the seq-preserving
  legacy rebuild, the function whose dropped-seq bug pushed every app entry
  ahead of the world entries and issued duplicate seqs;
* `undo_world.restart_world`'s three failure paths — a queue that refuses to
  follow the world, an undo sync that explodes, and a my-nick emit that dies
  inside its `except: pass`; plus `_schedule_world_undo_save`, which no test
  ever called, and `sync_world_state`'s malformed-entry skip;
* `undo_apply`'s eight attributed uncovered lines — the json fallback, the
  equality (non-identity) position match, the labels refusal, the archive
  command's two refusals, the rewind non-dict guard and redo's
  cannot-re-apply `Err`;
* the two `undo_service` delegate bodies and `attach`'s dbs/memory slots.

RULE 8: every test asserts behavior, not line execution — a reverted fix (a
dropped seq, a swallowed continuation, a missing refusal) fails here.

Run with:  python3 tests/integration/services/test_undo_history_world_gaps.py
"""

import asyncio
import os
import sys
import unittest
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import services.undo_apply as undo_apply                     # noqa: E402
from core.events import (EventBus, LabelsChanged, MyNickChanged,  # noqa: E402
                         PeopleChanged, UndoHistoryChanged, UserDbChanged)
from services.undo_apply import ApplyCommand                 # noqa: E402
from services.undo_service import UndoService                # noqa: E402
from services.undo_world import WorldSync, restart_world     # noqa: E402
from services.wiring_requests import RestartDeps, UndoDeps   # noqa: E402


class FakeConfig:
    """The two methods UndoService/WorldSync touch on a config store."""

    def __init__(self, state=None):
        self._state = state or {}
        self.writes = []

    def get_state(self, key, default=None):
        return self._state.get(key, default)

    def set_state(self, **kw):
        self.writes.append(kw)


def make_service(config=None):
    return UndoService(config or FakeConfig())


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class TestMigratedEntry(unittest.TestCase):
    """`undo_history._migrated_entry` through the real service delegate."""

    def setUp(self):
        self.svc = make_service()

    def test_a_positive_seq_is_preserved_verbatim(self):
        entry = self.svc._migrated_entry({"seq": 7}, "grid", {"a": 1})
        self.assertEqual(entry["seq"], 7,
                         "seq is the merge identity — it must survive")
        self.assertEqual(entry["kind"], "grid")
        self.assertEqual(entry["value"], {"a": 1})

    def test_a_missing_seq_is_not_invented(self):
        entry = self.svc._migrated_entry({}, "grid", {"a": 1})
        self.assertNotIn("seq", entry,
                         "a fresh seq here would collide with world seqs")

    def test_a_non_int_seq_is_dropped(self):
        entry = self.svc._migrated_entry({"seq": "7"}, "grid", {})
        self.assertNotIn("seq", entry)

    def test_a_non_positive_seq_is_dropped(self):
        for bad in (0, -3):
            entry = self.svc._migrated_entry({"seq": bad}, "grid", {})
            self.assertNotIn("seq", entry, f"seq={bad} is not an identity")

    def test_the_rebuild_is_a_plain_history_entry_otherwise(self):
        entry = self.svc._migrated_entry({"seq": 2}, "stack", [{"x": 1}])
        fresh = UndoService._history_entry("stack", [{"x": 1}])
        fresh["seq"] = 2
        self.assertEqual(entry, fresh)


class TestAttachSlotsAndCleanHistory(unittest.TestCase):
    """The two `attach` slots and `_clean_history`'s non-list guard."""

    def test_attach_fills_exactly_the_slots_that_are_set(self):
        svc = make_service()
        dbs, memory = object(), object()
        svc.attach(UndoDeps(dbs=dbs, memory=memory))
        self.assertIs(svc._dbs, dbs)
        self.assertIs(svc._memory, memory)
        self.assertIsNone(svc._archive, "unset fields must not be touched")
        self.assertIsNone(svc._people)

    def test_clean_history_of_a_non_list_is_empty(self):
        self.assertEqual(UndoService._clean_history("not a list"), [])


class TestRestartWorldFailurePaths(unittest.TestCase):
    """A restart warns and CONTINUES — the broadcast is the contract."""

    def _deps(self, memory, undo, archive, bus=None, labels=None):
        return RestartDeps(memory=memory, archive=archive, labels=labels,
                           undo=undo, bus=bus or EventBus())

    @staticmethod
    def _archive(my_nick="Ana", boom_nick=False):
        class A:
            db = SimpleNamespace(path="/tmp/g5_world.db")

            @property
            def mine(self):
                return my_nick

            @property
            def my_nick(self):
                if boom_nick:
                    raise RuntimeError("archive is mid-rebuild")
                return my_nick
        return A()

    def _announced(self, bus):
        seen = []
        for kind in (PeopleChanged, UserDbChanged, LabelsChanged):
            bus.subscribe(kind, lambda event, k=kind: seen.append(k.__name__))
        return seen

    def test_a_refusing_queue_warns_and_the_world_still_goes_live(self):
        bus = EventBus()
        seen = self._announced(bus)
        switched = []

        class Memory:
            db_path = "/tmp/g5_OTHER.db"      # differs → switch_db must run

            async def switch_db(self, path):
                switched.append(path)
                raise RuntimeError("queue is locked")

        with self.assertLogs("chatbot", level="WARNING") as cm:
            run(restart_world(self._deps(Memory(), None, self._archive(),
                                         bus=bus), "load"))
        self.assertEqual(switched, ["/tmp/g5_world.db"],
                         "the switch must have been attempted")
        self.assertIn("PeopleChanged", seen,
                      "the world must still be announced live")
        self.assertIn("UserDbChanged", seen)
        self.assertTrue(any("queue did not follow" in m for m in cm.output))

    def test_an_exploding_undo_sync_warns_and_continues(self):
        bus = EventBus()
        seen = self._announced(bus)

        class Undo:
            async def sync_world_state(self):
                raise RuntimeError("timeline store is gone")

        class Memory:
            db_path = "/tmp/g5_world.db"      # equal → no switch attempt

            async def switch_db(self, path):
                raise AssertionError("must not be called")

        with self.assertLogs("chatbot", level="WARNING") as cm:
            run(restart_world(self._deps(Memory(), Undo(), self._archive(),
                                         bus=bus), "create"))
        self.assertIn("PeopleChanged", seen)
        self.assertTrue(any("world undo sync failed" in m for m in cm.output))

    def test_a_dying_my_nick_emit_is_swallowed(self):
        bus = EventBus()
        seen = self._announced(bus)
        nicks = []
        bus.subscribe(MyNickChanged, lambda event: nicks.append(event.nick))

        class Memory:
            db_path = "/tmp/g5_world.db"

            async def switch_db(self, path):
                raise AssertionError("must not be called")

        with self.assertLogs("chatbot", level="INFO") as cm:
            run(restart_world(self._deps(
                Memory(), None, self._archive(boom_nick=True), bus=bus),
                "delete"))
        self.assertEqual(nicks, [], "the broken nick never reaches the bus")
        self.assertIn("PeopleChanged", seen,
                      "the announcement happened BEFORE the failing emit")
        self.assertTrue(any("is live" in m for m in cm.output),
                      "the final log line must still run")


class TestWorldSyncSeams(unittest.TestCase):
    """`_schedule_world_undo_save` (both layers) and the malformed skip."""

    def test_the_projection_forwards_to_the_world_store(self):
        saved = []
        owner = SimpleNamespace(
            _world_store=SimpleNamespace(schedule_save=saved.extend))
        WorldSync(owner)._schedule_world_undo_save([{"seq": 1}])
        self.assertEqual(saved, [{"seq": 1}])

    def test_the_service_delegate_reaches_the_same_store(self):
        svc = make_service()
        saved = []
        svc._world_store = SimpleNamespace(schedule_save=saved.extend)
        svc._schedule_world_undo_save([{"seq": 9}])
        self.assertEqual(saved, [{"seq": 9}])

    def test_sync_world_state_skips_malformed_app_entries(self):
        committed = []
        events = []
        raw = ["junk", {"kind": 42}, {"kind": "grid", "seq": 3, "value": {}}]
        world = [{"kind": "people", "seq": 5, "value": {}}]

        class Store:
            async def settle(self):
                return None

            async def load(self):
                return world

        owner = SimpleNamespace(
            _world_store=Store(),
            _archive=None,
            _config=FakeConfig({"undo_history": raw}),
            WORLD_UNDO_KINDS=UndoService.WORLD_UNDO_KINDS,
            _timeline_commit=SimpleNamespace(
                commit=lambda merged, idx, purge_dropped:
                    committed.append((merged, idx, purge_dropped))),
            _bus=SimpleNamespace(emit=events.append),
        )
        result = run(WorldSync(owner).sync_world_state())
        self.assertTrue(result.is_ok)
        self.assertEqual(len(committed), 1)
        merged, idx, purge = committed[0]
        self.assertEqual([e["kind"] for e in merged], ["grid", "people"],
                         "junk and the non-str kind are dropped, seq sorts")
        self.assertEqual(idx, len(merged) - 1)
        self.assertFalse(purge)
        self.assertTrue(any(isinstance(e, UndoHistoryChanged) for e in events))


class TestUndoApplyRefusals(unittest.TestCase):
    """The eight attributed lines of `undo_apply.py`."""

    def test_values_equal_falls_back_to_plain_equality(self):
        # json.dumps raises on sets — the fallback must still answer.
        self.assertTrue(undo_apply._values_equal({1, 2}, {1, 2}))
        self.assertFalse(undo_apply._values_equal({1, 2}, {3}))

    def test_position_of_finds_an_equal_non_identical_entry(self):
        entry = {"kind": "grid", "value": {"x": 1}}
        history = [entry]
        twin = {"kind": "grid", "value": {"x": 1}}
        self.assertEqual(undo_apply._position_of(history, twin), 0)
        self.assertEqual(undo_apply._position_of(history, entry), 0)
        self.assertEqual(
            undo_apply._position_of(history, {"kind": "stack", "value": {}}),
            -1)

    def test_labels_refuse_a_non_dict_snapshot(self):
        self.assertFalse(
            undo_apply._apply_labels_command(None, {"before": "nope"}, False))

    def test_archive_refuses_an_unknown_op(self):
        ac = ApplyCommand(SimpleNamespace())
        self.assertFalse(ac._apply_archive_command({"op": "bogus"}, False))

    def test_archive_refuses_when_nothing_is_wired(self):
        ac = ApplyCommand(SimpleNamespace(_archive=None, _people=None))
        self.assertFalse(
            ac._apply_archive_command({"op": "delete_person"}, False))

    def test_rewind_of_a_non_dict_entry_returns_quietly(self):
        owner = SimpleNamespace(history=lambda: (_ for _ in ()).throw(
            AssertionError("must not read the timeline")))
        ApplyCommand(owner).rewind_after_failure(None, False)

    def test_redo_of_a_command_that_cannot_reapply_is_an_err(self):
        calls = []
        entry = {"kind": "archive", "value": {"op": "delete_person"}}
        owner = SimpleNamespace(
            history=lambda: ([{"kind": "grid"}, entry], 0),
            COMMAND_KINDS=UndoService.COMMAND_KINDS,
            apply_command=lambda e, forward: calls.append((e, forward)) and False,
            set_history=lambda *a: calls.append("moved"),
        )
        result = ApplyCommand(owner).redo()
        self.assertTrue(result.is_err)
        self.assertEqual(result.code, "nothing_to_redo")
        self.assertIn("cannot re-apply archive", result.detail)
        self.assertEqual(calls, [(entry, True)],
                         "the pointer must NOT move on a refused redo")


if __name__ == "__main__":
    unittest.main()
