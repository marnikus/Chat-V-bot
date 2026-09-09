"""D2 — StackBridge contract (design IDs S-1..S-15).

Wire behaviours pinned here (docs/plans/BRIDGE_TESTS_DESIGN_2026-09-09.md):

  S-1  run_stack(valid) loads the engine and starts a run
  S-2  run_stack(corrupt json) touches nothing, raises nothing
  S-3  stop/pause/resume reach the engine
  S-4  composer text roundtrips and is handed to the engine
  S-5  criteria roundtrip through the criteria object
  S-6  save_stack_preset stores, emits, overwrites by name (no dupes)
  S-7  load_stack_preset(missing) → "null" (the JS sentinel), no raise
  S-8  load_stack_preset(existing) → blocks + stack_loaded signal + engine
  S-9  delete_stack_preset removes + emits; missing name is a safe no-op
  S-10 snapshot_stack persists the last-session stack only (no 2nd undo)
  S-11 template CRUD mirrors stack CRUD (save/load/list/delete/signals)
  S-12 custom block CRUD with persistence
  S-13 engine run signals are forwarded (step/complete)
  S-14 stack history pushes land in the shared undo timeline
  S-15 preset_list_updated payload always includes the new entry

Run:  python -m pytest tests/test_stack_bridge_contract.py
"""

import asyncio
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend.bridge import Bridge  # noqa: E402
from bridge.stack_bridge import StackBridge  # noqa: E402

from bridge_harness import (FakeEngine, Recorder, TempWorld,  # noqa: E402
                            blocks, make_bare)


def stack_json(*ids):
    return json.dumps(blocks(*ids))


class StackCase(unittest.TestCase):
    """Real Router (bare) + real config/presets on a temp dir."""

    def setUp(self):
        self.world = TempWorld()
        self.addCleanup(self.world.__exit__, None, None, None)
        self.engine = FakeEngine()
        self.br = make_bare(engine=self.engine, config=self.world.config)
        self.presets = Recorder(self.br.preset_list_updated)
        self.templates = Recorder(self.br.template_list_updated)
        self.custom = Recorder(self.br.custom_blocks_updated)
        self.stack_loaded = Recorder(self.br.stack_loaded)
        self.template_loaded = Recorder(self.br.template_loaded)

    # ── run control ──────────────────────────────────────────────
    def test_S1_run_stack_loads_engine_and_runs(self):
        self.br.run_stack(stack_json("PAUSE", "PAUSE"))
        loaded = [c for c in self.engine.calls if c[0] == "load_stack"]
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0][1], blocks("PAUSE", "PAUSE"))
        self.assertEqual(self.world.config.get_state("last_stack"),
                         blocks("PAUSE", "PAUSE"),
                         "last-session stack must be snapshot for restart")
        self.assertEqual(self.world.config.get_state("last_stack_preset"), "")

    def test_S1b_run_stack_cleans_retired_and_private_keys(self):
        payload = json.dumps([{"block_id": "PAUSE", "unknown_future_key": 1,
                               "_private": 2, "enabled": None}])
        self.br.run_stack(payload)
        loaded = [c for c in self.engine.calls if c[0] == "load_stack"][0][1]
        # retired + underscore keys are stripped, `enabled` backfilled;
        # unknown future keys survive (forward compat)
        self.assertEqual(loaded,
                         [{"block_id": "PAUSE", "unknown_future_key": 1,
                           "enabled": True}])

    def test_S2_run_stack_corrupt_json_is_safe(self):
        self.br.run_stack("{not json")
        self.assertEqual(self.engine.calls, [], "engine must not be touched")
        self.br.run_stack('{"not":"a list"}')
        self.assertEqual(self.engine.calls, [], "non-list payload rejected")

    def test_S3_stop_pause_resume_reach_engine(self):
        self.br.stop_stack()
        self.br.pause_stack()
        self.br.resume_stack()
        self.assertEqual([c[0] for c in self.engine.calls],
                         ["stop", "pause", "resume"])

    # ── composer / criteria ──────────────────────────────────────
    def test_S4_composer_roundtrip_and_engine_handoff(self):
        self.br.save_message("hello world")
        self.assertEqual(self.br.get_message(), "hello world")
        self.assertEqual(self.engine.composer_text, "hello world",
                         "engine must receive the text to type")

    def test_S5_criteria_roundtrip(self):
        class FakeCriteria:
            def __init__(self):
                self.stored = None

            def load_json(self, j):
                self.stored = json.loads(j)

            def to_json(self):
                return json.dumps(self.stored or {})

        crit = FakeCriteria()
        self.br._criteria = crit            # write-through onto the context
        self.br.save_criteria('{"gender":["female"]}')
        self.assertEqual(crit.stored, {"gender": ["female"]})
        self.assertEqual(json.loads(self.br.get_criteria()),
                         {"gender": ["female"]})

    # ── stack presets ────────────────────────────────────────────
    def test_S6_save_preset_stores_emits_and_overwrites(self):
        self.br.save_stack_preset("daily", stack_json("PAUSE"))
        listed = json.loads(self.br.list_stack_presets())
        self.assertEqual([p["name"] for p in listed], ["daily"])

        self.presets.clear()
        self.br.save_stack_preset("daily", stack_json("PAUSE", "PAUSE"))
        listed = json.loads(self.br.list_stack_presets())
        self.assertEqual(len(listed), 1, "same name must overwrite, not dup")
        self.assertEqual(listed[0]["blocks"], 2, "new payload stored")
        # the emitted signal payload already contains the new entry (S-15)
        self.assertEqual(len(self.presets.calls), 1)
        emitted = json.loads(self.presets.calls[0])
        self.assertEqual([p["name"] for p in emitted], ["daily"])

    def test_S6b_save_preset_bad_payload_is_rejected(self):
        self.br.save_stack_preset("bad", "{oops")
        self.assertEqual(json.loads(self.br.list_stack_presets()), [])
        self.br.save_stack_preset("bad", '{"not":"a list"}')
        self.assertEqual(json.loads(self.br.list_stack_presets()), [])

    def test_S7_load_missing_preset_returns_null_sentinel(self):
        self.assertEqual(self.br.load_stack_preset("ghost"), "null")

    def test_S8_load_existing_preset_loads_engine_and_signals(self):
        self.br.save_stack_preset("daily", stack_json("PAUSE", "PAUSE"))
        payload = self.br.load_stack_preset("daily")
        self.assertEqual(json.loads(payload), blocks("PAUSE", "PAUSE"))
        self.assertEqual(self.stack_loaded.calls, [("daily", payload)])
        loaded = [c for c in self.engine.calls if c[0] == "load_stack"]
        self.assertEqual(loaded[-1][1], blocks("PAUSE", "PAUSE"))
        # the loaded preset becomes the named last-session snapshot
        self.assertEqual(self.world.config.get_state("last_stack_preset"),
                         "daily")

    def test_S9_delete_preset(self):
        self.br.save_stack_preset("daily", stack_json("PAUSE"))
        self.br.delete_stack_preset("daily")
        self.assertEqual(json.loads(self.br.list_stack_presets()), [])
        self.assertEqual(len(self.presets.calls), 2, "delete re-emits list")
        # missing name: safe, no signal
        self.presets.clear()
        self.br.delete_stack_preset("ghost")
        self.assertEqual(self.presets.calls, [])

    def test_S10_snapshot_persists_without_second_undo_entry(self):
        self.br.run_stack(stack_json("PAUSE"))      # creates undo tip
        hist_before = self.br._get_global_history()[0]
        self.br.snapshot_stack(stack_json("SNAPSHOT_ONLY"))
        self.assertEqual(self.world.config.get_state("last_stack"),
                         blocks("SNAPSHOT_ONLY"))
        hist_after = self.br._get_global_history()[0]
        self.assertEqual(len(hist_after), len(hist_before),
                         "snapshot must not add an undo entry")

    # ── templates ────────────────────────────────────────────────
    def test_S11_template_crud_mirrors_stack_crud(self):
        self.br.save_template_preset("intro", "Hi {nick}!")
        listed = json.loads(self.br.list_template_presets())
        self.assertEqual([t["name"] for t in listed], ["intro"])
        self.assertEqual(len(self.templates.calls), 1)

        body = self.br.load_template_preset("intro")
        self.assertEqual(body, "Hi {nick}!")
        self.assertEqual(self.template_loaded.calls, [("intro", "Hi {nick}!")])

        self.assertEqual(self.br.load_template_preset("ghost"), "")
        self.templates.clear()
        self.br.delete_template_preset("intro")
        self.assertEqual(json.loads(self.br.list_template_presets()), [])
        self.assertEqual(len(self.templates.calls), 1)
        self.br.delete_template_preset("ghost")     # safe no-op
        self.assertEqual(len(self.templates.calls), 1)

    # ── custom blocks ────────────────────────────────────────────
    def test_S12_custom_block_crud_persists(self):
        blk = {"block_id": "CUSTOM_FIND", "params": {"selector": ".a"}}
        self.br.save_custom_block("myfind", json.dumps(blk))
        listed = json.loads(self.br.list_custom_blocks())
        self.assertEqual([b["name"] for b in listed], ["myfind"])
        self.assertEqual(listed[0]["block"], blk)

        # persisted: a fresh ConfigManager over the same dir sees it
        from backend.config_manager import ConfigManager
        cfg2 = ConfigManager(self.world.config_path)
        self.assertEqual([b["name"] for b in cfg2.blocks.all()], ["myfind"])

        self.br.save_custom_block("", json.dumps(blk))       # empty name
        self.assertEqual(len(json.loads(self.br.list_custom_blocks())), 1)
        self.br.save_custom_block("x", "{bad")               # corrupt
        self.assertEqual(len(json.loads(self.br.list_custom_blocks())), 1)

        self.br.delete_custom_block("myfind")
        self.assertEqual(json.loads(self.br.list_custom_blocks()), [])
        self.br.delete_custom_block("ghost")                 # safe no-op

    # ── engine signals ───────────────────────────────────────────
    def test_S13_engine_signals_are_forwarded(self):
        step = Recorder(self.br.step_started)
        done = Recorder(self.br.stack_complete)
        bridge = self.br._bridge(StackBridge)
        # a Qt-signal engine (like ActionEngine) gets connected in __init__
        from PySide6.QtCore import QObject, Signal

        class QtEngine(QObject):
            step_started = Signal(int, str, str)
            step_complete = Signal(str, str)
            stack_complete = Signal()

        eng = QtEngine()
        self.br._engine = eng                     # re-wire: new __init__?
        bridge._connect_engine(eng)
        eng.step_started.emit(0, "PAUSE", "Anna")
        eng.step_complete.emit("PAUSE", "ok")
        eng.stack_complete.emit()
        self.assertEqual(step.calls, [(0, "PAUSE", "Anna")])
        self.assertEqual(done.calls, [()])

    # ── stack history / undo timeline ────────────────────────────
    def test_S14_preset_save_and_load_push_stack_history(self):
        self.br.save_stack_preset("daily", stack_json("PAUSE"))
        history, index = self.br._get_global_history()
        self.assertTrue(any(e["kind"] == "stack" for e in history),
                        "preset save must be undoable")

        self.br.run_stack(stack_json("PAUSE", "PAUSE", "PAUSE"))
        self.br.load_stack_preset("daily")
        history, index = self.br._get_global_history()
        stack_entries = [e for e in history if e["kind"] == "stack"]
        self.assertGreaterEqual(len(stack_entries), 2)
        # the tip is the loaded preset, NOT the previous run stack (the
        # previous stack is preserved below it for ↩)
        self.assertEqual(stack_entries[-1]["value"], blocks("PAUSE"))

    def test_S14b_projection_slots_roundtrip(self):
        self.br._push_history(blocks("PAUSE"))
        hist, idx = self.br._get_history()
        self.assertEqual(hist[-1], blocks("PAUSE"))
        self.br._set_history(hist[:-1], idx - 1)
        hist2, idx2 = self.br._get_history()
        self.assertEqual(len(hist2), len(hist) - 1)


if __name__ == "__main__":
    unittest.main()
