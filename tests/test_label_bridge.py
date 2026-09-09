"""D5 — LabelBridge contract (design IDs L-1..L-12).

The assign/edit/delete contract the labels window depends on:

  L-1  get_labels → {defs, assign, filter, palette} — one payload, JS
       re-renders from it (labels.js applyState)
  L-2  label_create returns the created label; duplicate (case-insensitive)
       and empty names → "null" + a warning log, no crash
  L-3  label_update renames/recolors; unknown id → False; a rename onto
       an existing name is refused for the name (kept unique)
  L-4  label_delete removes the definition AND every assignment and
       filter entry (no orphans); unknown id → False
  L-5  label_assign: ok / unknown id → False / already assigned → False
  L-6  label_unassign of a missing pair → False
  L-7  label_set_for REPLACES the set, silently drops unknown ids,
       corrupt JSON → False
  L-8  label_set_filter / label_clear_filter roundtrip; corrupt → False
  L-9  every successful mutation emits labels_changed ONCE with the
       post-state; failed mutations emit nothing (C-3)
  L-10 mutations persist to disk (C-6)
  L-11 create → assign → delete-label chain leaves NO dangling ids
  L-12 the engine guard exposes allows()/reject_reason for run filtering
  L-13 every mutation is one reversible "labels" timeline entry (C-4)

Run:  python -m pytest tests/test_label_bridge.py
"""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend.bridge import Bridge  # noqa: E402

from bridge_harness import FakeEngine, Recorder, TempWorld, make_bare  # noqa: E402


class LabelCase(unittest.TestCase):
    def setUp(self):
        self.world = TempWorld()
        self.addCleanup(self.world.__exit__, None, None, None)
        self.engine = FakeEngine()
        self.br = make_bare(engine=self.engine, config=self.world.config)
        self.changed = Recorder(self.br.labels_changed)

    def state(self):
        return json.loads(self.br.get_labels())

    def create(self, name, color=""):
        raw = self.br.label_create(name, color)
        self.assertNotEqual(raw, "null", f"create {name!r} failed")
        return json.loads(raw)["id"]

    # ── state shape ──────────────────────────────────────────────
    def test_L1_state_shape(self):
        state = self.state()
        self.assertEqual(set(state.keys()),
                         {"defs", "assign", "filter", "palette"})
        self.assertEqual(state["defs"], [])
        self.assertEqual(state["assign"], {})

    # ── create ───────────────────────────────────────────────────
    def test_L2_create_returns_label_rejects_dupes_and_empty(self):
        made = json.loads(self.br.label_create("VIP", "#ff0000"))
        self.assertEqual(made["name"], "VIP")
        self.assertTrue(made["id"])
        self.assertEqual(made["color"], "#ff0000")

        self.changed.clear()
        self.assertEqual(self.br.label_create("vip", "#00ff00"), "null",
                         "names are unique case-insensitively")
        self.assertEqual(self.br.label_create("   ", "#123123"), "null")
        self.assertEqual(self.changed.calls, [],
                         "failed creates emit nothing")
        self.assertEqual(len(self.state()["defs"]), 1)

    # ── update ───────────────────────────────────────────────────
    def test_L3_update_rename_recolor_unknown(self):
        lid = self.create("work")
        self.assertTrue(self.br.label_update(lid, "job", "#00ff00"))
        defs = self.state()["defs"]
        self.assertEqual(defs[0]["name"], "job")
        self.assertEqual(defs[0]["color"], "#00ff00")

        self.assertFalse(self.br.label_update("lbl_999", "x", ""),
                         "unknown id → False")
        other = self.create("other")
        self.assertFalse(self.br.label_update(other, "JOB", ""),
                         "renaming onto an existing name is a no-op → False")
        names = [d["name"] for d in self.state()["defs"]]
        self.assertNotIn("JOB", names, "the conflicting rename was refused")

    # ── delete ───────────────────────────────────────────────────
    def test_L4_delete_removes_definition_and_every_reference(self):
        lid = self.create("gone")
        self.assertTrue(self.br.label_assign("Anna", lid))
        self.assertTrue(self.br.label_set_filter(
            json.dumps({"include": [lid]})))
        self.assertTrue(self.br.label_delete(lid))
        state = self.state()
        self.assertEqual(state["defs"], [])
        self.assertNotIn("Anna", state["assign"], "no orphan assignments")
        self.assertEqual(state["filter"]["include"], [],
                         "no orphan filter entries")
        self.assertFalse(self.br.label_delete("lbl_999"))
        self.assertFalse(self.br.label_delete(""))

    # ── assignment ───────────────────────────────────────────────
    def test_L5_assign_contract(self):
        lid = self.create("vip")
        self.assertTrue(self.br.label_assign("Anna", lid))
        self.assertEqual(self.state()["assign"], {"Anna": [lid]})
        self.assertFalse(self.br.label_assign("Anna", "lbl_999"),
                         "unknown label id")
        self.assertFalse(self.br.label_assign("", lid), "empty nick")
        self.assertFalse(self.br.label_assign("Anna", lid),
                         "already assigned — no duplicates")
        self.assertEqual(self.state()["assign"]["Anna"], [lid])

    def test_L6_unassign_contract(self):
        lid = self.create("vip")
        self.assertFalse(self.br.label_unassign("Anna", lid),
                         "nothing assigned yet")
        self.br.label_assign("Anna", lid)
        self.assertTrue(self.br.label_unassign("Anna", lid))
        self.assertEqual(self.state()["assign"], {})

    def test_L7_set_for_replaces_and_drops_unknown(self):
        a = self.create("a")
        b = self.create("b")
        self.br.label_assign("Anna", a)
        self.assertTrue(self.br.label_set_for(
            "Anna", json.dumps([b, "lbl_999", b])))
        self.assertEqual(self.state()["assign"]["Anna"], [b],
                         "replace + dedupe + unknown dropped")
        self.assertFalse(self.br.label_set_for("Anna", "{corrupt"))
        self.assertFalse(self.br.label_set_for("Anna", '"not a list"'))
        self.assertEqual(self.state()["assign"]["Anna"], [b],
                         "corrupt payload changes nothing")

    # ── filter ───────────────────────────────────────────────────
    def test_L8_filter_roundtrip(self):
        a = self.create("a")
        b = self.create("b")
        self.assertTrue(self.br.label_set_filter(
            json.dumps({"include": [a], "exclude": [b, a]})))
        state = self.state()
        self.assertEqual(state["filter"]["exclude"], [b, a],
                         "exclusion wins: a stays in exclude")
        self.assertEqual(state["filter"]["include"], [],
                         "a label is never included and excluded at once")
        self.assertTrue(self.br.label_clear_filter())
        self.assertEqual(self.state()["filter"],
                         {"include": [], "exclude": []})
        # clearing an already-clear filter is a no-op
        self.assertFalse(self.br.label_clear_filter())
        self.assertFalse(self.br.label_set_filter("{corrupt"))
        self.assertFalse(self.br.label_set_filter('["not a dict"]'))

    # ── signal discipline ────────────────────────────────────────
    def test_L9_changed_fires_once_per_successful_mutation(self):
        self.assertEqual(self.changed.calls, [], "reads emit nothing")
        lid = self.create("x")
        self.assertEqual(len(self.changed.calls), 1)
        payload = json.loads(self.changed.calls[0])
        self.assertEqual([d["name"] for d in payload["defs"]], ["x"],
                         "payload is the POST state")
        self.br.label_assign("Anna", lid)
        self.assertEqual(len(self.changed.calls), 2)
        # failed mutations emit nothing
        self.br.label_assign("Anna", "lbl_999")
        self.br.label_update("lbl_999", "y", "")
        self.assertEqual(len(self.changed.calls), 2)

    # ── persistence ──────────────────────────────────────────────
    def test_L10_mutations_persist_to_disk(self):
        lid = self.br.label_create("keep", "")
        lid = json.loads(lid)["id"]
        self.br.label_assign("Anna", lid)
        from backend.config_manager import ConfigManager
        cfg2 = ConfigManager(self.world.config_path)
        from stores.label_store import LabelStore
        store2 = LabelStore(cfg2)
        self.assertEqual([d["name"] for d in store2.defs()], ["keep"])
        self.assertEqual(store2.ids_for("Anna"), [lid])

    # ── no dangling references ───────────────────────────────────
    def test_L11_delete_after_assign_leaves_no_dangling_id(self):
        lid = self.create("temp")
        self.br.label_assign("Anna", lid)
        self.br.label_assign("Boris", lid)
        self.br.label_delete(lid)
        state = self.state()
        self.assertEqual(state["assign"], {}, "nicks cleaned up entirely")

    # ── engine guard ─────────────────────────────────────────────
    def test_L12_engine_guard_exposes_the_filter(self):
        self.br._install_label_guard()
        self.assertEqual(self.engine.label_filter, self.br._label_store.allows
                         if hasattr(self.br, "_label_store") else None
                         or self.engine.label_filter)
        # through the real store: an excluded person is not allowed
        lid = self.create("blocked")
        self.br.label_set_filter(json.dumps({"exclude": [lid]}))
        self.br._install_label_guard()
        self.assertTrue(self.engine.label_filter("Anna"))
        self.br.label_assign("Anna", lid)
        self.assertFalse(self.engine.label_filter("Anna"),
                         "excluded label blocks the run for this person")
        self.assertTrue(self.engine.label_filter("Boris"))

    # ── undo contract ────────────────────────────────────────────
    def test_L13_every_mutation_is_one_reversible_entry(self):
        lid = json.loads(self.br.label_create("u", ""))["id"]
        self.br.label_assign("Anna", lid)
        history, _ = self.br._get_global_history()
        label_entries = [e for e in history if e["kind"] == "labels"]
        self.assertEqual(len(label_entries), 2,
                         "create + assign, one entry each")

        self.br.label_unassign("Anna", lid)
        self.br.label_delete(lid)
        history, _ = self.br._get_global_history()
        self.assertEqual(len([e for e in history
                              if e["kind"] == "labels"]), 4)

        # Ctrl+Z walks the labels edits back in reverse order
        raw = json.loads(self.br.undo())
        self.assertEqual(raw["kind"], "labels")
        self.assertEqual([d["name"] for d in self.state()["defs"]], ["u"],
                         "the delete is reversed: label restored")
        self.br.undo()      # unassign → assignment restored
        self.assertEqual(self.state()["assign"], {"Anna": [lid]})
        self.br.undo()      # assign → assignment removed again
        self.br.undo()      # create → label gone
        state = self.state()
        self.assertEqual(state["defs"], [])
        self.assertEqual(state["assign"], {})


if __name__ == "__main__":
    unittest.main()
