"""services/undo_service — migration / projection / world-store contract.

test_services_undo.py pins push/undo/redo, the world split and the seq
management. This file pins the seams the AREA C refactor extracts
(docs/REFACTOR_2026-09-09_AREA_C_DESIGN.md §4):

  * migrate_global_history: the stored undo_history branch (per-kind
    validation, seq preservation, index clamping) and the legacy branch
    (stack_history / grid_layout_history / grid_layout, canonicalisation,
    cap, index rules, write-back);
  * the world-store seams through the public API: app/world split on
    commit, pending-save settlement, seq backfill, archive-closed fallback;
  * history() stack-block cleaning.

Every test drives the PUBLIC UndoService API — the refactor is only
allowed to move code, not to change these observables.

Run with:  python3 -m pytest tests/integration/services/test_undo_support_contract.py
"""

import json
import os
import sys
import tempfile
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))

from backend.config_manager import MAX_STACK_HISTORY  # noqa: E402
from backend.config_manager import ConfigManager  # noqa: E402
from core.events import EventBus  # noqa: E402
from services.layout_service import LayoutService  # noqa: E402
from services.undo_service import UndoService  # noqa: E402

STACK_A = [{"block_id": "PAUSE", "pause_ms": 5}]
STACK_B = [{"block_id": "CLICK_MAIN_TAB"}]
GRID_FULL = LayoutService.default_payload()
GRID_CANONICAL = LayoutService.canonical_grid_payload(GRID_FULL)[0]


class FakeArchive:
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


class UndoContractCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.cfg = ConfigManager(os.path.join(self._tmp.name, "config.json"))
        self.undo = UndoService(config=self.cfg, bus=EventBus())

    def tearDown(self):
        self._tmp.cleanup()


# ══════════════════════════════════════════════════════════════════
# migrate_global_history — the stored undo_history branch
# ══════════════════════════════════════════════════════════════════
class TestMigrateRawHistory(UndoContractCase):
    def seed(self, raw):
        self.cfg.set_state(undo_history=raw)

    def test_stack_entry_is_kept_with_seq(self):
        self.seed([{"kind": "stack", "value": STACK_A, "seq": 7}])
        history, index = self.undo.migrate_global_history()
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["kind"], "stack")
        self.assertEqual(history[0]["value"], STACK_A)
        self.assertEqual(history[0]["seq"], 7, "seq is the merge identity")
        # no undo_history_index stored → the UndoStore default (-1) wins
        self.assertEqual(index, -1)

    def test_grid_entry_is_canonicalised(self):
        self.seed([{"kind": "grid", "value": GRID_FULL}])
        history, index = self.undo.migrate_global_history()
        self.assertEqual(history[0]["kind"], "grid")
        self.assertEqual(history[0]["value"], GRID_CANONICAL)

    def test_invalid_grid_entry_is_dropped(self):
        self.seed([{"kind": "grid", "value": "{not json"}])
        history, index = self.undo.migrate_global_history()
        self.assertEqual(history, [])
        self.assertEqual(index, -1)

    def test_people_entry_requires_before_and_after_lists(self):
        self.seed([
            {"kind": "people", "value": {"before": [], "after": []}},
            {"kind": "people", "value": {"before": "no"}},
            {"kind": "people", "value": "not-a-dict"},
        ])
        history, index = self.undo.migrate_global_history()
        self.assertEqual([e["kind"] for e in history], ["people"])

    def test_world_command_kinds_are_kept(self):
        self.seed([
            {"kind": "labels", "value": {"defs": []}},
            {"kind": "archive", "value": {"op": "delete_person"}},
            {"kind": "dbconn", "value": {"op": "create"}},
        ])
        history, index = self.undo.migrate_global_history()
        self.assertEqual([e["kind"] for e in history],
                         ["labels", "archive", "dbconn"])

    def test_world_command_kind_with_non_dict_value_is_dropped(self):
        self.seed([{"kind": "labels", "value": ["x"]}])
        history, index = self.undo.migrate_global_history()
        self.assertEqual(history, [])

    def test_non_dict_entries_are_skipped(self):
        self.seed(["junk", None, 3, {"kind": "stack", "value": STACK_A}])
        history, index = self.undo.migrate_global_history()
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["kind"], "stack")

    def test_index_reads_and_clamps_the_stored_index(self):
        self.seed([{"kind": "stack", "value": STACK_A},
                   {"kind": "grid", "value": GRID_FULL}])
        self.cfg.set_state(undo_history_index=99)
        _, index = self.undo.migrate_global_history()
        self.assertEqual(index, 1)
        self.cfg.set_state(undo_history_index=-5)
        _, index = self.undo.migrate_global_history()
        self.assertEqual(index, -1)

    def test_index_defaults_to_start_when_nothing_stored(self):
        """Pre-refactor pinned behaviour: with entries but no stored
        undo_history_index, the UndoStore default (-1) is what the
        migration returns — the pointer sits at the timeline start."""
        self.seed([{"kind": "stack", "value": STACK_A},
                   {"kind": "stack", "value": STACK_B}])
        _, index = self.undo.migrate_global_history()
        self.assertEqual(index, -1)

    def test_returned_history_is_independent_of_config(self):
        self.seed([{"kind": "stack", "value": STACK_A}])
        history, _ = self.undo.migrate_global_history()
        history[0]["value"].append({"block_id": "X"})
        raw = self.cfg.get_state("undo_history")
        self.assertEqual(raw[0]["value"], STACK_A,
                         "the caller's copy must not mutate config state")


# ══════════════════════════════════════════════════════════════════
# migrate_global_history — the legacy branch
# ══════════════════════════════════════════════════════════════════
class TestMigrateLegacy(UndoContractCase):
    def test_legacy_stack_history_becomes_stack_entries(self):
        self.cfg.set_state(stack_history=[STACK_A, STACK_B])
        history, index = self.undo.migrate_global_history()
        self.assertEqual([e["kind"] for e in history], ["stack", "stack"])
        self.assertEqual(history[0]["value"], STACK_A)
        self.assertEqual(history[1]["value"], STACK_B)

    def test_legacy_grid_history_is_canonicalised_and_invalid_dropped(self):
        self.cfg.set_state(grid_layout_history=["{bad", GRID_FULL])
        history, index = self.undo.migrate_global_history()
        grids = [e["value"] for e in history if e["kind"] == "grid"]
        self.assertEqual(grids, [GRID_CANONICAL])

    def test_current_grid_layout_is_appended_when_different(self):
        self.cfg.set_state(grid_layout_history=[GRID_FULL])
        tree = LayoutService.default_grid_tree()
        tree["sizes"][0] -= 5
        tree["sizes"][1] += 5
        other = LayoutService.canonical_grid_payload(
            json.dumps({"v": 3, "tree": tree}))[0]
        self.cfg.set_state(grid_layout=other)
        history, index = self.undo.migrate_global_history()
        grids = [e["value"] for e in history if e["kind"] == "grid"]
        self.assertEqual(grids, [GRID_CANONICAL, other])
        # the canonical current layout is written back
        self.assertEqual(self.cfg.get_state("grid_layout"), other)

    def test_current_grid_layout_is_not_duplicated(self):
        self.cfg.set_state(grid_layout_history=[GRID_FULL])
        self.cfg.set_state(grid_layout=GRID_FULL)
        history, index = self.undo.migrate_global_history()
        grids = [e["value"] for e in history if e["kind"] == "grid"]
        self.assertEqual(grids, [GRID_CANONICAL])

    def test_migration_caps_history_at_max(self):
        stacks = [[{"block_id": "PAUSE", "pause_ms": i}]
                  for i in range(MAX_STACK_HISTORY + 5)]
        self.cfg.set_state(stack_history=stacks)
        history, index = self.undo.migrate_global_history()
        self.assertEqual(len(history), MAX_STACK_HISTORY)

    def test_grid_tail_pins_the_index_to_last(self):
        self.cfg.set_state(stack_history=[STACK_A, STACK_B])
        self.cfg.set_state(grid_layout=GRID_FULL)
        self.cfg.set_state(stack_history_index=0)
        history, index = self.undo.migrate_global_history()
        self.assertEqual(index, len(history) - 1)

    def test_legacy_index_is_clamped(self):
        self.cfg.set_state(stack_history=[STACK_A, STACK_B])
        self.cfg.set_state(stack_history_index=42)
        _, index = self.undo.migrate_global_history()
        self.assertEqual(index, 1)
        # the migration writes the unified history back, so the SECOND call
        # would take the raw branch — clear it to stay on the legacy path
        self.cfg.set_state(undo_history=[])
        self.cfg.set_state(stack_history_index=-9)
        _, index = self.undo.migrate_global_history()
        self.assertEqual(index, -1)

    def test_migration_writes_the_unified_history_back(self):
        self.cfg.set_state(stack_history=[STACK_A])
        history, index = self.undo.migrate_global_history()
        stored = self.cfg.get_state("undo_history")
        self.assertEqual(stored[0]["kind"], "stack")
        self.assertEqual(stored[0]["value"], STACK_A)
        self.assertEqual(self.cfg.get_state("undo_history_index"), index)

    def test_empty_everything_yields_empty_history(self):
        history, index = self.undo.migrate_global_history()
        self.assertEqual(history, [])
        self.assertEqual(index, -1)


# ══════════════════════════════════════════════════════════════════
# world-store seams (public API)
# ══════════════════════════════════════════════════════════════════
class TestWorldStoreSeams(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.cfg = ConfigManager(os.path.join(self._tmp.name, "config.json"))
        self.archive = FakeArchive()
        self.undo = UndoService(config=self.cfg, bus=EventBus(),
                                archive=self.archive)

    def tearDown(self):
        self._tmp.cleanup()

    async def test_commit_splits_app_and_world_entries(self):
        self.undo.set_history([
            {"kind": "stack", "value": STACK_A, "seq": 1},
            {"kind": "people", "value": {"before": [], "after": []},
             "seq": 2},
            {"kind": "grid", "value": GRID_CANONICAL, "seq": 3},
        ], 2)
        await self.undo.sync_world_state()   # settles the pending save
        app_stored = self.cfg.get_state("undo_history")
        self.assertEqual([e["kind"] for e in app_stored],
                         ["stack", "grid"],
                         "app kinds live in config, world kinds in the table")
        self.assertEqual(len(self.archive.saved), 1)
        self.assertEqual([e["kind"] for e in self.archive.saved[0]],
                         ["people"])

    async def test_commit_with_closed_archive_keeps_everything_in_config(self):
        self.undo.attach(archive=FakeArchive(open_=False))
        self.undo.set_history([
            {"kind": "stack", "value": STACK_A, "seq": 1},
            {"kind": "labels", "value": {"x": 1}, "seq": 2},
        ], 1)
        stored = self.cfg.get_state("undo_history")
        self.assertEqual([e["kind"] for e in stored], ["stack", "labels"])

    async def test_commit_backfills_missing_seqs(self):
        self.undo.set_history([
            {"kind": "stack", "value": STACK_A},
            {"kind": "grid", "value": GRID_CANONICAL, "seq": 0},
        ], 1)
        stored = self.cfg.get_state("undo_history")
        seqs = [e["seq"] for e in stored]
        self.assertTrue(all(isinstance(s, int) and s > 0 for s in seqs))

    async def test_sync_world_state_merges_by_seq(self):
        self.archive._world = [
            {"kind": "people", "value": {"before": [], "after": []},
             "seq": 5},
        ]
        self.cfg.set_state(undo_history=[
            {"kind": "stack", "value": STACK_A, "seq": 1},
            {"kind": "people", "value": {"before": ["x"], "after": []},
             "seq": 4},   # world table is the truth for world kinds
        ])
        await self.undo.sync_world_state()
        history, index = self.undo.history()
        self.assertEqual([e["kind"] for e in history], ["stack", "people"])
        self.assertEqual(history[1]["seq"], 5)

    async def test_sync_without_archive_keeps_config_only(self):
        self.cfg.set_state(undo_history=[
            {"kind": "stack", "value": STACK_A, "seq": 1},
        ])
        self.undo.attach(archive=None)
        await self.undo.sync_world_state()
        history, index = self.undo.history()
        self.assertEqual([e["kind"] for e in history], ["stack"])

    async def test_save_failure_is_reported_but_does_not_raise(self):
        async def boom(entries):
            raise RuntimeError("table gone")

        self.archive.save_world_undo = boom
        self.undo.set_history([
            {"kind": "people", "value": {"before": [], "after": []},
             "seq": 1},
        ], 0)
        await self.undo.sync_world_state()   # must settle without raising

    async def test_history_cleans_stack_blocks(self):
        self.cfg.set_state(undo_history=[
            {"kind": "stack",
             "value": [{"block_id": "PAUSE", "pause_ms": 5,
                        "use_panel_filters": True, "_x": 1}],
             "seq": 1},
        ])
        history, index = self.undo.history()
        self.assertEqual(history[0]["value"],
                         [{"block_id": "PAUSE", "pause_ms": 5,
                           "enabled": True}])

    async def test_commit_with_no_archive_writes_config_unchanged(self):
        self.undo.attach(archive=None)
        self.undo.set_history([
            {"kind": "stack", "value": STACK_A, "seq": 1},
        ], 0)
        stored = self.cfg.get_state("undo_history")
        self.assertEqual(stored[0]["value"], STACK_A)
        self.assertEqual(self.cfg.get_state("undo_history_index"), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
