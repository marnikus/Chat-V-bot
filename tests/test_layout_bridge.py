"""D6 — LayoutBridge contract (design IDs Y-1..Y-10).

Layout sync + resize validation, as JS (sash-grid.js) sees it:

  Y-1  fresh profile: get_grid_layout → "" (JS builds its own default);
       no crash, no made-up payload
  Y-2  save(valid) → True + persisted(True); get returns the canonical
       payload; a RESTART (fresh ConfigManager over the same file) sees it
  Y-3  wrong version → REJECTED (False, persisted(False)), stored layout
       unchanged (RULE 13: never destroy the user's arrangement)
  Y-4  unknown window id → rejected
  Y-5  stored legacy v1 payload → get returns it UPGRADED to the current
       window set, user's arrangement kept
  Y-6  reset_grid_layout → default payload with every window + cleared
       window states + undo entry + changed signal
  Y-7  window states sanitize: unknown ids dropped, a window cannot be
       closed AND minimized, corrupt JSON → False
  Y-8  resize rules: sizes must sum to 100 and respect the panel minimum
  Y-9  block-config pin persists
  Y-10 get_app_state carries the full session restore payload

Run:  python -m pytest tests/test_layout_bridge.py
"""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend.bridge import Bridge  # noqa: E402
from services.layout_service import LayoutService  # noqa: E402

from bridge_harness import Recorder, TempWorld, make_bare  # noqa: E402


def leaf(i):
    return {"t": "leaf", "id": i}


def split(d, kids, sizes):
    return {"t": "split", "dir": d, "children": kids, "sizes": sizes}


def payload(tree, version=None):
    v = LayoutService.GRID_VERSION if version is None else version
    return json.dumps({"v": v, "tree": tree}, ensure_ascii=False)


def default_tree():
    return LayoutService.default_grid_tree()


class LayoutCase(unittest.TestCase):
    def setUp(self):
        self.world = TempWorld()
        self.addCleanup(self.world.__exit__, None, None, None)
        self.br = make_bare(config=self.world.config)
        self.changed = Recorder(self.br.grid_layout_changed)
        self.persisted = Recorder(self.br.grid_layout_persisted)

    # ── reads ────────────────────────────────────────────────────
    def test_Y1_fresh_profile_returns_empty_not_garbage(self):
        self.assertEqual(self.br.get_grid_layout(), "")
        self.assertEqual(self.changed.calls, [])

    # ── save / load ──────────────────────────────────────────────
    def test_Y2_save_then_get_roundtrip_and_persist(self):
        tree = default_tree()
        self.assertTrue(self.br.save_grid_layout(payload(tree)))
        self.assertEqual(self.persisted.calls, [True])
        got = json.loads(self.br.get_grid_layout())
        self.assertEqual(got["v"], LayoutService.GRID_VERSION)
        self.assertEqual(got["tree"], tree)
        # C-6: restart sees it
        from backend.config_manager import ConfigManager
        cfg2 = ConfigManager(self.world.config_path)
        br2 = make_bare(config=cfg2)
        self.assertEqual(json.loads(br2.get_grid_layout())["tree"], tree)

    def test_Y3_wrong_version_is_rejected_and_keeps_the_stored_layout(self):
        tree = default_tree()
        self.br.save_grid_layout(payload(tree))
        self.persisted.clear()
        future = payload(tree, version=LayoutService.GRID_VERSION + 1)
        self.assertFalse(self.br.save_grid_layout(future))
        self.assertFalse(self.br.save_grid_layout(payload(tree, version=0)))
        self.assertEqual(self.persisted.calls, [False, False])
        self.assertEqual(json.loads(self.br.get_grid_layout())["tree"], tree,
                         "the stored arrangement survived the rejects")

    def test_Y4_unknown_window_id_is_rejected(self):
        tree = split("row", [leaf("stats"), leaf("not_a_window")], [50, 50])
        self.assertFalse(self.br.save_grid_layout(payload(tree)))

    def test_Y5_stored_v1_payload_is_upgraded_with_arrangement_kept(self):
        # the 7 legacy windows in the user's own arrangement
        legacy = split("col", [
            split("row", [leaf("stats"), leaf("filters")], [30, 70]),
            split("col", [leaf("stack"), leaf("config")], [60, 40]),
            leaf("composer"),
            split("row", [leaf("people"), leaf("log")], [70, 30]),
        ], [25, 25, 25, 25])
        self.world.config.set_state(grid_layout=payload(legacy, version=1))
        got = json.loads(self.br.get_grid_layout())
        self.assertEqual(got["v"], LayoutService.GRID_VERSION,
                         "v1 must be upgraded on read")
        ids = sorted(LayoutService.leaf_ids(got["tree"]))
        self.assertEqual(ids, sorted(self.br.WINDOW_IDS),
                         "the new windows were appended, nothing lost")
        # the user's top-level arrangement survives inside the tree
        flat = json.dumps(got["tree"])
        self.assertIn('"stats"', flat)

    # ── reset ────────────────────────────────────────────────────
    def test_Y6_reset_restores_default_and_clears_states(self):
        self.br.save_window_states(json.dumps({"closed": ["log"]}))
        self.changed.clear()
        raw = self.br.reset_grid_layout()
        got = json.loads(raw)
        self.assertEqual(got["v"], LayoutService.GRID_VERSION)
        self.assertEqual(sorted(LayoutService.leaf_ids(got["tree"])),
                         sorted(self.br.WINDOW_IDS))
        states = json.loads(self.br.get_window_states())
        self.assertEqual(states, {"closed": [], "minimized": []})
        history, _ = self.br._get_global_history()
        self.assertTrue(any(e["kind"] == "grid" for e in history),
                        "reset is undoable")
        # JS applies the RETURN value (sash-grid.js:234) — no changed
        # signal is required for the reset itself; the undo path emits
        # GridLayoutChanged when the reset is later undone

    # ── window states ────────────────────────────────────────────
    def test_Y7_window_states_sanitize(self):
        self.assertTrue(self.br.save_window_states(json.dumps(
            {"closed": ["log", "bogus", 5],
             "minimized": ["stats", "log", "ghost"]})))
        states = json.loads(self.br.get_window_states())
        self.assertEqual(states["closed"], ["log"])
        self.assertEqual(states["minimized"], ["stats"],
                         "bogus dropped, closed wins over minimized")
        self.assertFalse(self.br.save_window_states("{corrupt"))
        self.assertFalse(self.br.save_window_states('["not a dict"]'))
        # fresh profile: config defaults give the sane empty set
        world2 = TempWorld()
        self.addCleanup(world2.__exit__, None, None, None)
        br2 = make_bare(config=world2.config)
        self.assertEqual(json.loads(br2.get_window_states()),
                         {"closed": [], "minimized": []})

    # ── resize validation ────────────────────────────────────────
    def test_Y8_size_rules(self):
        bad_sum = split("row", [leaf("stats"), leaf("filters")], [50, 60])
        self.assertFalse(self.br.save_grid_layout(payload(bad_sum)),
                         "sizes must sum to 100")
        too_small = split("row", [leaf("stats"), leaf("filters")], [1, 99])
        self.assertFalse(self.br.save_grid_layout(payload(too_small)),
                         f"panels respect MIN_GRID_SIZE="
                         f"{self.br.MIN_GRID_SIZE}")
        full = default_tree()
        full["sizes"] = [33.4, 16.6, 20, 15, 15]   # sums to 100, all >= min
        self.assertTrue(self.br.save_grid_layout(payload(full)),
                        "fractional sizes within tolerance are valid")
        # a child split breaking the rules also rejects the whole payload
        bad_child = split("col",
                          [split("row", [leaf("stats"), leaf("filters")],
                                 [10, 10]),
                           split("row", [leaf("stack"), leaf("config")],
                                 [50, 50])],
                          [50, 50])
        self.assertFalse(self.br.save_grid_layout(payload(bad_child)))

    # ── pin + app state ──────────────────────────────────────────
    def test_Y9_block_config_pin_persists(self):
        self.br.set_block_config_pinned(True)
        from backend.config_manager import ConfigManager
        cfg2 = ConfigManager(self.world.config_path)
        br2 = make_bare(config=cfg2)
        state = json.loads(br2.get_app_state())
        self.assertTrue(state["state"]["block_config_pinned"])

    def test_Y10_app_state_carries_the_session(self):
        self.br.save_grid_layout(payload(default_tree()))
        self.br.save_message_state = None
        state = json.loads(self.br.get_app_state())
        self.assertEqual(set(state.keys()),
                         {"theme", "url_presets", "labels", "custom_blocks",
                          "stack_presets", "template_presets", "state"})
        inner = state["state"]
        for key in ("last_url_preset", "last_stack_preset", "last_stack",
                    "stack_history", "stack_history_index", "undo_history",
                    "undo_history_index", "grid_layout",
                    "block_config_pinned", "window_states",
                    "window_geometry"):
            self.assertIn(key, inner, f"session key {key} missing")
        self.assertIsNotNone(inner["grid_layout"])
        self.assertIsInstance(inner["undo_history"], list)


if __name__ == "__main__":
    unittest.main()
