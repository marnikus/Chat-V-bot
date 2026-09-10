"""services/undo_service — the ONE global timeline: push / undo / redo / sync.

Contract (docs/archive/2026-09-09-test-suite/SERVICES_TEST_DESIGN_2026-09-09.md §2.1):

* entries are tagged ``{kind, value}`` with a monotonic ``seq``;
* a push of the SAME value at the tip is a NO-OP (dedupe) — grid/stack
  autosaves must not grow the timeline with duplicates;
* a push after an undo truncates the redo branch (commit semantics);
* timeline is capped at MAX_STACK_HISTORY;
* app-level entries persist in config; world-bound entries (people/labels/
  archive/dbconn) persist in the active world's ``undo_history`` table;
* undo/redo of command entries applies before/after; failure is a typed
  ``Err`` — never a fake success.

Run with:  python3 tests/integration/services/test_services_undo.py
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

from backend.config_manager import ConfigManager, MAX_STACK_HISTORY  # noqa: E402
from core.events import (EventBus, StackLoaded, UndoHistoryChanged,  # noqa: E402
                         PeopleChanged)
from services.layout_service import LayoutService  # noqa: E402
from services.run import normalize_blocks  # noqa: E402
from services.undo_service import UndoService  # noqa: E402

BLOCK_A = [{"block_id": "PAUSE", "pause_ms": 5}]
BLOCK_B = [{"block_id": "CLICK_MAIN_TAB"}]
BLOCK_A_CLEAN = normalize_blocks(BLOCK_A)
BLOCK_B_CLEAN = normalize_blocks(BLOCK_B)
#: opaque-but-realistic grid payloads (dedupe compares the VALUE, so a
#: valid layout is not required — but migration paths validate, so there
#: GRID_FULL is used)
GRID_X = '{"v":3,"tree":{"t":"leaf","id":"stats"}}'
GRID_Y = '{"v":3,"tree":{"t":"leaf","id":"log"}}'
GRID_FULL = LayoutService.default_payload()


def _variant_tree():
    """A second VALID full layout (different split sizes)."""
    tree = LayoutService.default_grid_tree()
    tree["sizes"][0] -= 5
    tree["sizes"][1] += 5
    return tree


GRID_FULL_B = LayoutService.canonical_grid_payload(
    json.dumps({"v": 3, "tree": _variant_tree()}))[0]


class FakeArchive:
    """Stands in for HistoryService: config-backed world undo surface."""

    def __init__(self, open_=True, world=None):
        self.db = types.SimpleNamespace(is_open=open_, path="/fake/world.db")
        self._world = list(world or [])
        self.saved = []
        self.loads = 0

    async def save_world_undo(self, entries):
        self.saved.append(entries)

    async def load_world_undo(self):
        self.loads += 1
        return list(self._world)


class UndoCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.cfg = ConfigManager(os.path.join(self._tmp.name, "config.json"))
        self.bus = EventBus()
        self.changed = []
        self.bus.subscribe(UndoHistoryChanged,
                           lambda e: self.changed.append(e))
        self.undo = UndoService(config=self.cfg, bus=self.bus)

    def tearDown(self):
        self._tmp.cleanup()

    def engine(self):
        engine = types.SimpleNamespace(loads=[], load_stack=lambda b: engine.loads.append(b))
        return engine


class TestPush(UndoCase):
    def test_push_appends_and_returns_ok(self):
        result = self.undo.push("stack", BLOCK_A)
        self.assertTrue(result.is_ok)
        history, index = result.value
        self.assertEqual(len(history), 1)
        self.assertEqual(index, 0)
        self.assertEqual(history[0]["kind"], "stack")
        self.assertEqual(history[0]["value"], BLOCK_A)
        self.assertEqual(history[0]["seq"], 1)

    def test_push_unknown_kind_is_err(self):
        result = self.undo.push("nonsense", {})
        self.assertTrue(result.is_err)
        self.assertEqual(result.code, "unknown_kind")
        history, _ = self.undo.history()
        self.assertEqual(history, [])

    def test_push_identical_tip_value_is_a_noop(self):
        """THE BUG: same grid payload pushed twice must stay one entry."""
        self.undo.push("grid", GRID_X)
        result = self.undo.push("grid", GRID_X)
        self.assertTrue(result.is_ok)
        history, index = result.value
        self.assertEqual(len(history), 1, "duplicate entries on identical push")
        self.assertEqual(index, 0)
        self.assertEqual(result.value[0][0]["seq"], 1)

    def test_push_different_value_appends(self):
        self.undo.push("grid", GRID_X)
        result = self.undo.push("grid", GRID_Y)
        history, index = result.value
        self.assertEqual(len(history), 2)
        self.assertEqual(index, 1)

    def test_push_after_undo_truncates_the_redo_branch(self):
        """THE BUG: re-committing the SAME value after an undo must truncate
        the redo tail and stay at the same position — not duplicate."""
        self.undo.push("grid", GRID_X)
        self.undo.push("grid", GRID_Y)
        self.undo.undo()                      # back to GRID_X
        result = self.undo.push("grid", GRID_X)
        self.assertTrue(result.is_ok)
        history, index = result.value
        self.assertEqual([e["value"] for e in history], [GRID_X],
                         "redo tail must be dropped on re-commit of same value")
        self.assertEqual(index, 0)

    def test_push_after_undo_different_value_truncates(self):
        self.undo.push("grid", GRID_X)
        self.undo.push("grid", GRID_Y)
        self.undo.undo()
        result = self.undo.push("grid", GRID_Z_DEFAULT())
        history, index = result.value
        self.assertEqual([e["value"] for e in history],
                         [GRID_X, GRID_Z_DEFAULT()])
        self.assertEqual(index, 1)

    def test_cap_is_enforced(self):
        for i in range(MAX_STACK_HISTORY + 5):
            self.undo.push("stack", [{"block_id": "PAUSE", "i": i}])
        history, index = self.undo.history()
        self.assertEqual(len(history), MAX_STACK_HISTORY)
        self.assertEqual(index, MAX_STACK_HISTORY - 1)
        # the 5 oldest entries fell off the front
        self.assertEqual(history[0]["value"][0]["i"], 5)
        self.assertEqual(history[-1]["value"][0]["i"],
                         MAX_STACK_HISTORY + 4)

    def test_unknown_kind_pushes_nothing(self):
        self.undo.push("people", {"before": [], "after": []})
        history, _ = self.undo.history()
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["kind"], "people")
        result = self.undo.push("zzz", {})
        self.assertTrue(result.is_err)

    def test_push_emits_history_changed(self):
        self.undo.push("stack", BLOCK_A)
        self.assertEqual(len(self.changed), 1)
        self.undo.push("stack", BLOCK_B)
        self.assertEqual(len(self.changed), 2)

    def test_push_identical_still_emits_nothing_new(self):
        self.undo.push("grid", GRID_X)
        self.undo.push("grid", GRID_X)
        # no change → no extra event (event count stays 1)
        self.assertEqual(len(self.changed), 1)


def GRID_Z_DEFAULT():
    """A third distinct layout (a valid leaf tree)."""
    return '{"v":3,"tree":{"t":"leaf","id":"stack"}}'


class TestUndoRedoCommands(UndoCase):
    def test_undo_empty_timeline(self):
        result = self.undo.undo()
        self.assertTrue(result.is_err)
        self.assertEqual(result.code, "nothing_to_undo")

    def test_undo_first_snapshot_entry(self):
        self.undo.push("stack", BLOCK_A)
        result = self.undo.undo()
        self.assertTrue(result.is_err)
        self.assertEqual(result.code, "nothing_to_undo")

    def test_redo_at_tip(self):
        self.undo.push("stack", BLOCK_A)
        result = self.undo.redo()
        self.assertTrue(result.is_err)
        self.assertEqual(result.code, "nothing_to_redo")

    def test_undo_stack_applies_previous_state(self):
        engine = self.engine()
        self.undo.attach(engine=engine)
        self.undo.push("stack", BLOCK_A)
        self.undo.push("stack", BLOCK_B)
        result = self.undo.undo()
        self.assertTrue(result.is_ok)
        self.assertEqual(result.value["kind"], "stack")
        self.assertEqual(result.value["index"], 0)
        self.assertEqual(engine.loads[-1], BLOCK_A_CLEAN,
                         "undo must load the PREVIOUS stack")
        self.assertEqual(self.cfg.get_state("last_stack"), BLOCK_A_CLEAN)

    def test_redoing_a_stack_takes_it_forward_again(self):
        engine = self.engine()
        self.undo.attach(engine=engine)
        self.undo.push("stack", BLOCK_A)
        self.undo.push("stack", BLOCK_B)
        self.undo.undo()
        result = self.undo.redo()
        self.assertTrue(result.is_ok)
        self.assertEqual(result.value["index"], 1)
        self.assertEqual(engine.loads[-1], BLOCK_B_CLEAN)

    def test_undo_emits_stack_loaded_for_entries(self):
        engine = self.engine()
        self.undo.attach(engine=engine)
        loaded = []
        self.bus.subscribe(StackLoaded, lambda e: loaded.append(e))
        self.undo.push("stack", BLOCK_A)
        self.undo.push("stack", BLOCK_B)
        self.undo.undo()
        self.assertEqual(len(loaded), 1)
        payload = json.loads(loaded[0].payload)
        self.assertEqual(payload[0]["block_id"], "PAUSE")


class TestWorldSplit(UndoCase):
    def test_world_entries_go_to_the_world_table(self):
        archive = FakeArchive(open_=True)
        self.undo.attach(archive=archive)

        async def go():
            self.undo.push("people", {"before": [], "after": [{"nick": "A"}]})
            self.undo.push("stack", BLOCK_A)
            if self.undo._undo_pendings:
                await asyncio.gather(*list(self.undo._undo_pendings),
                                     return_exceptions=True)

        asyncio.run(go())
        self.assertTrue(archive.saved, "world entries must be persisted")
        for save in archive.saved:
            self.assertEqual([e["kind"] for e in save], ["people"],
                             "only world-bound entries go to the world table")
        saved_kinds = [e.get("kind") for e in self.cfg.get_state(
            "undo_history", [])]
        self.assertEqual(saved_kinds, ["stack"],
                         "config keeps the app half only")

    def test_sync_merges_app_and_world_by_seq(self):
        archive = FakeArchive(
            open_=True,
            world=[{"seq": 2, "kind": "people",
                    "value": {"before": [], "after": []}},
                   {"seq": 4, "kind": "labels",
                    "value": {"before": {}, "after": {}}}])
        self.undo.attach(archive=archive)
        self.cfg.set_state(undo_history=[
            {"seq": 1, "kind": "stack", "value": BLOCK_A},
            {"seq": 3, "kind": "grid", "value": GRID_X}])
        result = asyncio.run(self.undo.sync_world_state())
        self.assertTrue(result.is_ok)
        history, index = self.undo.history()
        kinds = [e["kind"] for e in history]
        self.assertEqual(kinds, ["stack", "people", "grid", "labels"])
        self.assertEqual(index, len(history) - 1, "sync parks at the tip")
        self.assertTrue(all(e.get("seq") for e in history))

    def test_sync_with_no_archive_keeps_config_only(self):
        self.undo.attach(archive=None)
        self.cfg.set_state(undo_history=[
            {"seq": 1, "kind": "stack", "value": BLOCK_A}])
        result = asyncio.run(self.undo.sync_world_state())
        self.assertTrue(result.is_ok)
        history, _ = self.undo.history()
        self.assertEqual([e["kind"] for e in history], ["stack"])

    def test_startup_path_keeps_the_app_world_interleaving(self):
        """THE BUG: after a restart `history()` runs first (migrate), and the
        merged timeline must still interleave app and world entries by seq —
        not push all app entries ahead of the world ones."""
        archive = FakeArchive(
            open_=True,
            world=[{"seq": 2, "kind": "people",
                    "value": {"before": [], "after": []}}])
        self.undo.attach(archive=archive)
        self.cfg.set_state(undo_history=[
            {"seq": 1, "kind": "stack", "value": BLOCK_A},
            {"seq": 3, "kind": "grid", "value": GRID_FULL}])

        async def go():
            history, _ = self.undo.history()   # the migrate path runs first
            self.assertTrue(all(e.get("seq") for e in history),
                            "migration must not drop seq")
            await self.undo.sync_world_state()

        asyncio.run(go())
        history, _ = self.undo.history()
        self.assertEqual([e["kind"] for e in history],
                         ["stack", "people", "grid"],
                         "interleaving must survive a restart")
        self.assertEqual([e["seq"] for e in history], [1, 2, 3])


class TestCommandKinds(UndoCase):
    def test_apply_command_unknown_kind(self):
        self.assertFalse(self.undo.apply_command(
            {"kind": "nope", "value": {}}, forward=True))

    def test_apply_command_malformed_value(self):
        self.assertFalse(self.undo.apply_command(
            {"kind": "people", "value": "nope"}, forward=True))

    def test_undo_people_without_people_wired_is_err(self):
        self.undo.push("people", {"before": [{"nick": "A"}],
                                  "after": []})
        result = self.undo.undo()
        self.assertTrue(result.is_err)
        self.assertEqual(result.code, "nothing_to_undo")
        self.assertEqual(self.undo.history()[1], 0,
                         "a failed reversal must not move the pointer")

    def test_redo_people_without_people_wired_is_err(self):
        self.undo.push("people", {"before": [{"nick": "A"}],
                                  "after": []})
        self.undo.undo()  # fails -> pointer still at 0
        result = self.undo.redo()
        self.assertTrue(result.is_err)
        self.assertEqual(result.code, "nothing_to_redo")


class TestProjections(UndoCase):
    def test_stack_projection_keeps_order_and_maps_index(self):
        self.undo.push("stack", BLOCK_A)
        self.undo.push("grid", GRID_X)
        self.undo.push("stack", BLOCK_B)
        stacks, index = self.undo.stack_projection()
        self.assertEqual(stacks, [BLOCK_A_CLEAN, BLOCK_B_CLEAN],
                         "stack snapshots are normalized on the way in")
        self.assertEqual(index, 1)
        self.undo.undo()           # back to BLOCK_A (stack at global 1)
        stacks, index = self.undo.stack_projection()
        self.assertEqual(index, 0)

    def test_kind_projection_filters_one_kind(self):
        self.undo.push("stack", BLOCK_A)
        self.undo.push("grid", GRID_X)
        grids, index = self.undo.kind_projection("grid")
        self.assertEqual(grids, [GRID_X])
        self.assertEqual(index, 0)

    def test_set_stack_projection_normalizes_and_clamps(self):
        self.undo.set_stack_projection(
            [[{"block_id": "PAUSE", "use_panel_filters": True}], []],
            index=99)
        history, index = self.undo.history()
        self.assertEqual(len(history), 2)
        self.assertEqual(index, 1, "index must be clamped")
        self.assertNotIn("use_panel_filters", history[0]["value"][0])
        self.assertEqual(history[0]["value"][0]["enabled"], True)


class TestMigration(UndoCase):
    def test_legacy_stack_history_migrates(self):
        self.cfg.set_state(stack_history=[BLOCK_A, BLOCK_B])
        self.cfg.set_state(stack_history_index=1)
        history, index = self.undo.history()
        self.assertEqual([e["kind"] for e in history], ["stack", "stack"])
        self.assertEqual(index, 1)
        # the migrated timeline is written back into the global store
        self.assertEqual(len(self.cfg.get_state("undo_history", [])), 2)

    def test_legacy_grid_layout_history_migrates_to_canonical(self):
        self.cfg.set_state(grid_layout_history=[GRID_FULL])
        self.cfg.set_state(grid_layout=GRID_FULL)
        history, index = self.undo.history()
        self.assertEqual([e["kind"] for e in history], ["grid"])
        self.assertEqual(index, 0)
        self.assertEqual(self.cfg.get_state("grid_layout"), GRID_FULL)

    def test_raw_undo_history_is_reused(self):
        raw = [{"kind": "stack", "value": BLOCK_A},
               {"kind": "grid", "value": GRID_FULL, "seq": 7}]
        self.cfg.set_state(undo_history=raw)
        self.cfg.set_state(undo_history_index=1)
        history, index = self.undo.history()
        self.assertEqual(len(history), 2)
        self.assertEqual(index, 1)
        self.assertEqual(history[1]["seq"], 7)
        self.assertEqual(json.loads(history[1]["value"])["v"], 3)

    def test_migration_caps_and_indexes(self):
        items = []
        for i in range(MAX_STACK_HISTORY + 3):
            items.append([{"block_id": "P", "i": i}])
        self.cfg.set_state(stack_history=items)
        self.cfg.set_state(stack_history_index=len(items) - 1)
        history, index = self.undo.history()
        self.assertEqual(len(history), MAX_STACK_HISTORY)
        self.assertEqual(index, MAX_STACK_HISTORY - 1)


class TestSeqManagement(UndoCase):
    def test_commit_assigns_missing_seqs(self):
        self.undo.set_history(
            [{"kind": "stack", "value": BLOCK_A},
             {"kind": "grid", "value": GRID_Y}], index=1)
        history, _ = self.undo.history()
        seqs = [e["seq"] for e in history]
        self.assertEqual(seqs, [1, 2])
        next_seq = self.undo._seq_next
        self.undo.push("stack", [{"block_id": "WAIT_PAGE_LOAD"}])
        history, _ = self.undo.history()
        self.assertEqual(history[-1]["seq"], next_seq)

    def test_seq_stays_monotonic_after_overflow(self):
        for i in range(MAX_STACK_HISTORY + 2):
            self.undo.push("stack", [{"block_id": "P", "n": i}])
        history, _ = self.undo.history()
        seqs = [e["seq"] for e in history]
        self.assertEqual(seqs, sorted(seqs))
        self.assertTrue(all(s > 0 for s in seqs))


class TestPeopleIntegration(unittest.IsolatedAsyncioTestCase):
    """undo/redo of a people command against a REAL queue store."""

    async def asyncSetUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        from stores.user_memory import UserMemory
        self.memory = UserMemory(os.path.join(self._tmp.name, "users.db"))
        await self.memory.init()
        from services.people_service import PeopleService
        self.people = PeopleService(memory=self.memory, bus=EventBus())
        self.cfg = ConfigManager(os.path.join(self._tmp.name, "config.json"))
        self.undo = UndoService(config=self.cfg)
        self.undo.attach(people=self.people, archive=None)
        self.people.attach(undo=self.undo)

    async def asyncTearDown(self):
        await self.memory.close()
        self._tmp.cleanup()

    async def seed(self, nick):
        from stores.user_memory import UserRecord
        if not await self.memory.get_user(nick):
            await self.memory.upsert_user(UserRecord(nick=nick))

    async def test_undo_restores_people_command(self):
        await self.seed("Anna")
        before = await self.people.rows()
        result = await self.people.delete_one("Anna")
        self.assertEqual(result.value, 1)
        history, index = self.undo.history()
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["kind"], "people")
        self.assertEqual(index, 0)

        raw = self.undo.undo()
        self.assertTrue(raw.is_ok)
        self.assertEqual(raw.value["kind"], "people")
        await asyncio.sleep(0.05)   # let the scheduled apply land
        names = {u.nick for u in await self.memory.get_all()}
        self.assertIn("Anna", names, "undo must restore the deleted row")
        self.assertEqual(raw.value["value"], before)

    async def test_redo_reapplies_people_command(self):
        await self.seed("Anna")
        await self.people.delete_one("Anna")
        self.undo.undo()
        await asyncio.sleep(0.05)
        raw = self.undo.redo()
        self.assertTrue(raw.is_ok)
        await asyncio.sleep(0.05)
        names = {u.nick for u in await self.memory.get_all()}
        self.assertNotIn("Anna", names, "redo must re-delete the row")


if __name__ == "__main__":
    unittest.main(verbosity=2)
