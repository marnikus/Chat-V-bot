"""D3 — UndoBridge contract (design IDs U-1..U-13).

The one global timeline, as seen from JS (ui/js/app.js):

  U-1  get_undo_history → {"history": [...], "index": int}; `history`
       is the key app.js reads (Array.isArray(state.history))
  U-2  push_global_history accepts ONLY the frontend-owned kinds
       "stack" and "grid"; corrupt payloads → False; server-owned kinds
       (people/labels/…) → False so edits are never double-recorded
  U-3  undo() on an empty timeline → "null", no raise
  U-4  redo() at the tip → "null", no raise
  U-5  undo() of a stack edit APPLIES the previous entry to the engine
       and returns {kind, value, index}; a sole entry cannot be undone
       (state 0 = initial state, matching app.js `canUndo = index > 0`)
  U-6  redo() re-applies the undone entry and returns it
  U-7  mixed kinds share ONE timeline and one pointer (interleaved
       stack/grid undo walks back in exact push order)
  U-8  undo_stack / undo_grid_layout are PROJECTIONS: they run the one
       global undo but return "null" unless the undone entry is theirs
  U-9  push_stack_history/save_stack_history/get_stack_history roundtrip
       (frontend bulk restore after reload)
  U-10 save_stack_history clamps a bad index instead of corrupting
  U-11 history_changed fires on push/undo/redo — never on a no-op

Run:  python -m pytest tests/test_undo_bridge.py
"""

import asyncio
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend.bridge import Bridge  # noqa: E402
from services.layout_service import LayoutService  # noqa: E402

from bridge_harness import (FakeEngine, Recorder, TempWorld,  # noqa: E402
                            blocks, make_bare, rec, seed)


def sj(*ids):
    return json.dumps(blocks(*ids))


def grid_payload(tree=None):
    tree = tree or LayoutService.default_grid_tree()
    return json.dumps({"v": LayoutService.GRID_VERSION, "tree": tree},
                      ensure_ascii=False, separators=(",", ":"))


class UndoCase(unittest.TestCase):
    def setUp(self):
        self.world = TempWorld()
        self.addCleanup(self.world.__exit__, None, None, None)
        self.engine = FakeEngine()
        self.br = make_bare(engine=self.engine, config=self.world.config)
        self.changed = Recorder(self.br.history_changed)

    def hist(self):
        raw = json.loads(self.br.get_undo_history())
        return raw["history"], raw["index"]

    # ── timeline read ────────────────────────────────────────────
    def test_U1_get_undo_history_shape(self):
        raw = json.loads(self.br.get_undo_history())
        self.assertEqual(set(raw.keys()), {"history", "index"})
        self.assertIsInstance(raw["history"], list)
        self.assertIsInstance(raw["index"], int)
        self.assertEqual(raw["history"], [])
        self.assertEqual(raw["index"], -1)

    def test_U1b_index_tracks_tip_after_push(self):
        self.br.push_global_history("stack", sj("PAUSE"))
        history, index = self.hist()
        self.assertEqual(len(history), 1)
        self.assertEqual(index, 0, "index must point at the tip")
        self.assertEqual(history[0]["kind"], "stack")
        self.assertEqual(history[0]["value"], blocks("PAUSE"))

    # ── push contract ────────────────────────────────────────────
    def test_U2_stack_push_accepted(self):
        self.assertTrue(self.br.push_global_history("stack", sj("PAUSE")))
        history, _ = self.hist()
        self.assertEqual([e["kind"] for e in history], ["stack"])

    def test_U2b_corrupt_or_nonlist_stack_payload_rejected(self):
        before, _ = self.hist()
        self.assertFalse(self.br.push_global_history("stack", "{bad"))
        self.assertFalse(self.br.push_global_history("stack", '{"a":1}'))
        history, _ = self.hist()
        self.assertEqual(history, before, "timeline unchanged on rejects")
        # "" coerces to "[]" like every stack slot: pushing the emptied
        # stack is a legitimate (undoable) edit
        self.assertTrue(self.br.push_global_history("stack", ""))
        history, _ = self.hist()
        self.assertEqual(history[-1]["value"], [])

    def test_U2c_server_owned_kinds_are_rejected(self):
        # people/labels/archive/dbconn entries are recorded SERVER-side
        # (PeopleBridge etc.); the frontend mirror must not double-record
        for kind in ("people", "labels", "archive", "dbconn"):
            self.assertFalse(self.br.push_global_history(kind, "{}"),
                             f"{kind} must not be frontend-pushed")
        history, _ = self.hist()
        self.assertEqual(history, [])

    def test_U2d_grid_push_canonicalizes_and_persists(self):
        ok = self.br.push_global_history("grid", grid_payload())
        self.assertTrue(ok)
        history, _ = self.hist()
        self.assertEqual([e["kind"] for e in history], ["grid"])
        # the canonical payload is what gets persisted for restart
        stored = self.world.config.get_state("grid_layout")
        self.assertEqual(json.loads(stored)["v"], LayoutService.GRID_VERSION)

    def test_U2e_corrupt_grid_payload_rejected(self):
        self.assertFalse(self.br.push_global_history("grid", "{bad"))
        self.assertFalse(self.br.push_global_history("grid", ""))
        history, _ = self.hist()
        self.assertEqual(history, [])

    # ── undo / redo on empty ─────────────────────────────────────
    def test_U3_undo_empty_is_null(self):
        self.assertEqual(self.br.undo(), "null")
        self.assertEqual(self.changed.calls, [], "no signal on a no-op")

    def test_U4_redo_empty_is_null(self):
        self.assertEqual(self.br.redo(), "null")

    # ── undo / redo semantics ────────────────────────────────────
    def test_U5_undo_applies_previous_stack(self):
        self.br.push_global_history("stack", sj("A"))
        self.br.push_global_history("stack", sj("B"))
        raw = self.br.undo()
        result = json.loads(raw)
        self.assertEqual(result["kind"], "stack")
        self.assertEqual(result["value"], blocks("A"))
        self.assertEqual(result["index"], 0)
        self.assertEqual(self.engine.stack, blocks("A"),
                         "undo must restore the previous stack to the engine")
        # a sole entry cannot be undone (state 0 = initial state)
        self.assertEqual(self.br.undo(), "null")

    def test_U6_redo_reapplies(self):
        self.br.push_global_history("stack", sj("A"))
        self.br.push_global_history("stack", sj("B"))
        self.br.undo()
        raw = self.br.redo()
        result = json.loads(raw)
        self.assertEqual(result["kind"], "stack")
        self.assertEqual(result["value"], blocks("B"))
        self.assertEqual(self.engine.stack, blocks("B"))
        self.assertEqual(self.br.redo(), "null", "redo at tip is a no-op")

    def test_U7_mixed_kinds_share_one_timeline(self):
        # undo reports the state being RESTORED (the entry at the new
        # pointer) — JS applies raw.value to the UI
        self.br.push_global_history("stack", sj("A"))
        self.br.push_global_history("grid", grid_payload())
        raw = self.br.undo()          # 1 → 0: restores the stack state
        result = json.loads(raw)
        self.assertEqual(result["kind"], "stack")
        self.assertEqual(result["value"], blocks("A"))
        self.assertEqual(self.br.undo(), "null", "state 0 is the initial")
        raw = self.br.redo()          # 0 → 1: re-applies the grid entry
        result = json.loads(raw)
        self.assertEqual(result["kind"], "grid", "redo walks forward")

    def test_U8_per_surface_slots_are_projections(self):
        self.br.push_global_history("grid", grid_payload())
        self.br.push_global_history("grid", grid_payload())
        # the stack slot RUNS the global undo but reports "null" — the
        # undone entry is not a stack entry
        self.assertEqual(self.br.undo_stack(), "null")
        _, index = self.hist()
        self.assertEqual(index, 0, "the global pointer still moved")
        # the grid projection reports the same global undo
        self.br.redo()
        raw = self.br.undo_grid_layout()
        self.assertNotEqual(raw, "null")
        result = json.loads(raw)
        self.assertIn("tree", result, "payload shape for JS")

    def test_U8b_stack_projection_returns_value_when_kind_matches(self):
        self.br.push_global_history("stack", sj("A"))
        self.br.push_global_history("stack", sj("B"))
        raw = self.br.undo_stack()
        self.assertEqual(json.loads(raw), blocks("A"))

    # ── legacy bulk save/restore slots ───────────────────────────
    def test_U9_stack_history_roundtrip(self):
        self.br.push_stack_history(sj("A"))
        self.br.push_stack_history(sj("B"))
        raw = json.loads(self.br.get_stack_history())
        self.assertEqual([e for e in raw["history"]], [blocks("A"),
                                                       blocks("B")])
        # frontend sends the full projection back after a reload
        self.br.save_stack_history(json.dumps([blocks("A"), blocks("B")]), 0)
        raw = json.loads(self.br.get_stack_history())
        self.assertEqual(raw["history"], [blocks("A"), blocks("B")])
        self.assertEqual(raw["index"], 0)

    def test_U10_save_stack_history_survives_garbage(self):
        self.br.save_stack_history("{bad", 0)
        self.br.save_stack_history('{"not":"a list"}', 0)
        raw = json.loads(self.br.get_stack_history())
        self.assertEqual(raw["history"], [], "garbage must not corrupt")

    def test_U10b_index_clamped_into_range(self):
        self.br.save_stack_history(json.dumps([blocks("A")]), 99)
        raw = json.loads(self.br.get_stack_history())
        self.assertEqual(raw["index"], 0, "index clamped into range")

    # ── signal discipline ────────────────────────────────────────
    def test_U11_history_changed_fires_on_push_undo_redo_only(self):
        self.br.push_global_history("stack", sj("A"))
        self.assertEqual(len(self.changed.calls), 1)
        self.br.undo()                    # sole entry → no-op
        self.assertEqual(len(self.changed.calls), 1,
                         "no-op undo must not fire the signal")
        self.br.push_global_history("stack", sj("B"))
        self.assertEqual(len(self.changed.calls), 2)
        self.br.undo()
        self.assertEqual(len(self.changed.calls), 3)
        self.br.redo()
        self.assertEqual(len(self.changed.calls), 4)


class PeopleUndoPath(unittest.TestCase):
    """U-8 interplay with the server-side people commands (C-4)."""

    def setUp(self):
        self.world = TempWorld()
        self.addCleanup(self.world.__exit__, None, None, None)
        self.engine = FakeEngine()
        self.br = make_bare(engine=self.engine, config=self.world.config)

    def test_people_command_undo_restores_rows(self):
        async def go():
            from backend.user_memory import UserMemory
            mem = UserMemory(self.world.path("users.db"))
            await mem.init()
            self.br._memory = mem
            await seed(mem, rec("Anna"), rec("Bella"))
            rows = await self.br._people_rows()
            self.assertEqual(len(rows), 2)
            after = [r for r in rows if r["nick"] != "Anna"]
            ok = self.br._push_global("people", {"before": rows,
                                                 "after": after})
            self.assertTrue(ok)
            raw = self.br.undo()
            result = json.loads(raw)
            self.assertEqual(result["kind"], "people")
            self.assertTrue(any(r["nick"] == "Anna" for r in result["value"]),
                            "undo returns the BEFORE rows")
            await asyncio.sleep(0.05)     # let apply() land
            names = {u.nick for u in await mem.get_all()}
            # the BEFORE half re-inserted Anna through the people service
            self.assertIn("Anna", names)
            await mem.close()
        asyncio.run(go())


if __name__ == "__main__":
    unittest.main()
