"""Person labels: the store, the bridge slots, the undo timeline and the
label filter that keeps an "ignored" person out of an automated run.

What a user was promised (see the feature spec and
docs/PERSON_LABELS_AND_DB_MANAGEMENT_DESIGN_2026-09-07.md):

  * labels are free text with a colour, created and deleted by the user;
  * one person can carry several labels;
  * the ✕ on a pill removes the label FROM THAT PERSON ONLY — deleting a
    label everywhere happens in the Label Manager;
  * labels can filter: "include selected" (only these) and "exclude
    selected" (never these, e.g. ignore "Rude" while auto-messaging);
  * everything is stored in config.json and everything is undoable
    through the ONE global timeline (RULE 12).

Per AGENT_RULES RULE 8 this runs the REAL shipped modules.

Run with:  python3 tests/test_person_labels.py
"""

import asyncio
import json
import os
import sys
import tempfile
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QObject  # noqa: E402

from backend.action_engine import ActionEngine  # noqa: E402
from backend.bridge import Bridge  # noqa: E402
from backend.config_manager import ConfigManager  # noqa: E402
from backend.label_store import PALETTE, LabelStore  # noqa: E402


def make_config():
    tmp = tempfile.mkdtemp()
    return ConfigManager(os.path.join(tmp, "config.json"))


def make_bridge():
    """A Bridge with a throwaway config and no Qt plumbing to start."""
    cfg = make_config()
    br = Bridge.__new__(Bridge)
    QObject.__init__(br)
    br._config = cfg
    br._memory = None
    br._history = None        # _archive is a property over _history
    br._engine = types.SimpleNamespace(load_stack=lambda _b: None)
    return br, cfg


# ═════════════════════════════════════════════════════════════════
# the store
# ═════════════════════════════════════════════════════════════════
class TestLabelStore(unittest.TestCase):
    def setUp(self):
        self.store = LabelStore(make_config())

    def test_a_label_is_created_with_a_name_and_a_colour(self):
        made = self.store.create("Rude", "#ff3b30")
        self.assertEqual(made["name"], "Rude")
        self.assertEqual(made["color"], "#ff3b30")
        self.assertTrue(made["id"])

    def test_a_label_without_a_colour_gets_one_from_the_palette(self):
        made = self.store.create("Nice")
        self.assertIn(made["color"], PALETTE)

    def test_a_nameless_label_is_refused(self):
        self.assertIsNone(self.store.create("   "))
        self.assertEqual(self.store.defs(), [])

    def test_names_are_unique_regardless_of_case(self):
        self.store.create("Rude")
        self.assertIsNone(self.store.create("rude"))
        self.assertEqual(len(self.store.defs()), 1)

    def test_ids_are_never_reused(self):
        first = self.store.create("A")["id"]
        self.store.delete(first)
        second = self.store.create("B")["id"]
        self.assertNotEqual(first, second)

    def test_a_person_can_carry_several_labels(self):
        rude = self.store.create("Rude")["id"]
        short = self.store.create("Short answering")["id"]
        self.store.assign("Nick", rude)
        self.store.assign("Nick", short)
        self.assertEqual(self.store.ids_for("Nick"), [rude, short])

    def test_assigning_twice_changes_nothing(self):
        rude = self.store.create("Rude")["id"]
        self.assertTrue(self.store.assign("Nick", rude))
        self.assertFalse(self.store.assign("Nick", rude))
        self.assertEqual(self.store.ids_for("Nick"), [rude])

    def test_unassign_only_touches_that_person(self):
        rude = self.store.create("Rude")["id"]
        self.store.assign("Nick", rude)
        self.store.assign("Other", rude)
        self.store.unassign("Nick", rude)
        self.assertEqual(self.store.ids_for("Nick"), [])
        self.assertEqual(self.store.ids_for("Other"), [rude],
                         "removing a pill must not touch anybody else")
        self.assertIsNotNone(self.store.by_id(rude),
                             "the label itself must still exist")

    def test_deleting_a_label_removes_it_from_everybody(self):
        rude = self.store.create("Rude")["id"]
        self.store.assign("Nick", rude)
        self.store.assign("Other", rude)
        self.store.set_filter(exclude=[rude])
        self.assertTrue(self.store.delete(rude))
        self.assertEqual(self.store.ids_for("Nick"), [])
        self.assertEqual(self.store.ids_for("Other"), [])
        self.assertFalse(self.store.filter_active,
                         "a deleted label must leave the filter too")

    def test_recolouring_keeps_the_assignments(self):
        rude = self.store.create("Rude", "#ff3b30")["id"]
        self.store.assign("Nick", rude)
        self.store.update(rude, color="#0a84ff")
        self.assertEqual(self.store.by_id(rude)["color"], "#0a84ff")
        self.assertEqual(self.store.ids_for("Nick"), [rude])

    def test_an_unknown_colour_falls_back_instead_of_being_stored(self):
        made = self.store.create("X", "javascript:alert(1)")
        self.assertIn(made["color"], PALETTE)

    def test_set_for_replaces_the_whole_set(self):
        a = self.store.create("A")["id"]
        b = self.store.create("B")["id"]
        self.store.set_for("Nick", [a, b])
        self.assertEqual(self.store.ids_for("Nick"), [a, b])
        self.store.set_for("Nick", [b])
        self.assertEqual(self.store.ids_for("Nick"), [b])

    def test_labels_survive_a_reload_of_the_config(self):
        cfg = make_config()
        store = LabelStore(cfg)
        rude = store.create("Rude", "#ff3b30")["id"]
        store.assign("Nick", rude)
        again = LabelStore(ConfigManager(cfg._path))
        self.assertEqual([d["name"] for d in again.defs()], ["Rude"])
        self.assertEqual(again.ids_for("Nick"), [rude])


class TestLabelFilter(unittest.TestCase):
    def setUp(self):
        self.store = LabelStore(make_config())
        self.rude = self.store.create("Rude")["id"]
        self.vip = self.store.create("VIP")["id"]
        self.store.assign("Rudy", self.rude)
        self.store.assign("Vicky", self.vip)
        self.store.assign("Both", self.rude)
        self.store.assign("Both", self.vip)

    def test_without_a_filter_everybody_passes(self):
        for nick in ("Rudy", "Vicky", "Nobody"):
            self.assertTrue(self.store.allows(nick))

    def test_exclude_skips_only_the_labelled_people(self):
        self.store.set_filter(exclude=[self.rude])
        self.assertFalse(self.store.allows("Rudy"))
        self.assertTrue(self.store.allows("Vicky"))
        self.assertTrue(self.store.allows("Nobody"))

    def test_include_is_a_whitelist(self):
        self.store.set_filter(include=[self.vip])
        self.assertTrue(self.store.allows("Vicky"))
        self.assertFalse(self.store.allows("Rudy"))
        self.assertFalse(self.store.allows("Nobody"))

    def test_exclusion_wins_over_inclusion(self):
        self.store.set_filter(include=[self.vip], exclude=[self.rude])
        self.assertFalse(self.store.allows("Both"),
                         "an ignored person stays ignored")

    def test_the_reason_names_the_label_so_the_log_can_explain_itself(self):
        self.store.set_filter(exclude=[self.rude])
        self.assertIn("Rude", self.store.reject_reason("Rudy"))

    def test_clearing_the_filter_lets_everybody_through_again(self):
        self.store.set_filter(exclude=[self.rude])
        self.store.clear_filter()
        self.assertTrue(self.store.allows("Rudy"))
        self.assertFalse(self.store.filter_active)


# ═════════════════════════════════════════════════════════════════
# the run queue honours the filter
# ═════════════════════════════════════════════════════════════════
class Person:
    def __init__(self, nick, messaged=False):
        self.nick = nick
        self.messaged = messaged
        self.gender = "female"
        self.registered = True
        self.anonymous = False
        self.guest = False
        self.first_seen = "2026-01-01 00:00:00"
        self.last_messaged = ""


class TestQueueHonoursLabels(unittest.TestCase):
    def setUp(self):
        self.engine = ActionEngine.__new__(ActionEngine)
        self.engine.label_filter = None
        self.engine.label_reason = None
        self.engine.blocks = []
        self.engine.criteria = types.SimpleNamespace(
            evaluate=lambda *_a, **_k: types.SimpleNamespace(passed=True))
        self.store = LabelStore(make_config())
        self.rude = self.store.create("Rude")["id"]
        self.store.assign("Rudy", self.rude)

    def test_filter_by_labels_drops_an_ignored_person(self):
        self.engine.label_filter = self.store.allows
        self.store.set_filter(exclude=[self.rude])
        people = [Person("Rudy"), Person("Vicky")]
        kept = self.engine.filter_by_labels(people)
        self.assertEqual([p.nick for p in kept], ["Vicky"])

    def test_without_a_filter_nobody_is_dropped(self):
        self.engine.label_filter = self.store.allows
        people = [Person("Rudy"), Person("Vicky")]
        self.assertEqual(len(self.engine.filter_by_labels(people)), 2)

    def test_a_broken_filter_fails_open(self):
        """A bug in the label code must never silence the whole queue."""
        def boom(_nick):
            raise RuntimeError("nope")
        self.engine.label_filter = boom
        people = [Person("Rudy"), Person("Vicky")]
        self.assertEqual(len(self.engine.filter_by_labels(people)), 2)


# ═════════════════════════════════════════════════════════════════
# the bridge slots + the one global undo timeline
# ═════════════════════════════════════════════════════════════════
class TestLabelBridge(unittest.TestCase):
    def setUp(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.br, self.cfg = make_bridge()
        self.events = []
        self.br.labels_changed.connect(
            lambda payload: self.events.append(json.loads(payload)))

    def tearDown(self):
        self.loop.close()
        asyncio.set_event_loop(None)

    def ids(self):
        return [d["id"] for d in self.br.label_store.defs()]

    def test_create_returns_the_label_and_tells_the_ui(self):
        raw = self.br.label_create("Rude", "#ff3b30")
        made = json.loads(raw)
        self.assertEqual(made["name"], "Rude")
        self.assertTrue(self.events, "labels_changed must fire")
        self.assertEqual(self.events[-1]["defs"][0]["name"], "Rude")

    def test_get_labels_returns_defs_assignments_and_filter(self):
        rude = json.loads(self.br.label_create("Rude", ""))["id"]
        self.br.label_assign("Nick", rude)
        state = json.loads(self.br.get_labels())
        self.assertEqual(state["assign"]["Nick"], [rude])
        self.assertIn("filter", state)
        self.assertIn("palette", state)

    def test_the_palette_has_the_twenty_preset_colours(self):
        state = json.loads(self.br.get_labels())
        self.assertEqual(len(state["palette"]), 20)

    def test_every_label_action_is_one_undo_step(self):
        rude = json.loads(self.br.label_create("Rude", ""))["id"]
        self.br.label_assign("Nick", rude)
        history, index = self.br._get_global_history()
        self.assertEqual([e["kind"] for e in history], ["labels", "labels"])
        self.assertEqual(index, 1)

    def test_undo_takes_the_label_off_the_person_only(self):
        rude = json.loads(self.br.label_create("Rude", ""))["id"]
        self.br.label_assign("Nick", rude)
        result = json.loads(self.br.undo())
        self.assertEqual(result["kind"], "labels")
        self.assertEqual(self.br.label_store.ids_for("Nick"), [])
        self.assertIsNotNone(self.br.label_store.by_id(rude),
                             "undoing an assignment must keep the label")

    def test_undo_brings_a_deleted_label_back_with_its_people(self):
        rude = json.loads(self.br.label_create("Rude", ""))["id"]
        self.br.label_assign("Nick", rude)
        self.br.label_delete(rude)
        self.assertEqual(self.br.label_store.defs(), [])
        self.br.undo()
        self.assertEqual([d["id"] for d in self.br.label_store.defs()], [rude])
        self.assertEqual(self.br.label_store.ids_for("Nick"), [rude])

    def test_redo_puts_the_change_back(self):
        rude = json.loads(self.br.label_create("Rude", ""))["id"]
        self.br.label_delete(rude)
        self.br.undo()
        self.br.redo()
        self.assertEqual(self.br.label_store.defs(), [])

    def test_a_no_op_is_not_recorded(self):
        rude = json.loads(self.br.label_create("Rude", ""))["id"]
        self.br.label_assign("Nick", rude)
        before = len(self.br._get_global_history()[0])
        self.br.label_assign("Nick", rude)          # already assigned
        self.assertEqual(len(self.br._get_global_history()[0]), before)

    def test_the_filter_is_stored_and_undoable(self):
        rude = json.loads(self.br.label_create("Rude", ""))["id"]
        self.br.label_set_filter(json.dumps({"exclude": [rude]}))
        self.assertTrue(self.br.label_store.filter_active)
        self.br.undo()
        self.assertFalse(self.br.label_store.filter_active)

    def test_labels_share_the_timeline_with_the_other_panels(self):
        """One Ctrl+Z crosses panels — there is only one history (RULE 12)."""
        self.br.push_global_history("stack", json.dumps([]))
        self.br.push_global_history(
            "stack", json.dumps([{"type": "delay", "enabled": True}]))
        rude = json.loads(self.br.label_create("Rude", ""))["id"]
        self.assertTrue(rude)
        kinds = [e["kind"] for e in self.br._get_global_history()[0]]
        self.assertEqual(kinds, ["stack", "stack", "labels"])
        self.assertEqual(json.loads(self.br.undo())["kind"], "labels")
        self.assertEqual(json.loads(self.br.undo())["kind"], "stack",
                         "one Ctrl+Z walks straight into the stack history")

    def test_labels_are_persisted_in_the_config(self):
        self.br.label_create("Rude", "#ff3b30")
        stored = self.cfg.get("labels", default={})
        self.assertTrue(stored.get("defs"), "labels must live in config.json")

    def test_the_engine_gets_a_label_guard_installed(self):
        engine = types.SimpleNamespace(load_stack=lambda _b: None)
        self.br._engine = engine
        self.br._install_label_guard()
        rude = json.loads(self.br.label_create("Rude", ""))["id"]
        self.br.label_assign("Rudy", rude)
        self.br.label_set_filter(json.dumps({"exclude": [rude]}))
        self.assertFalse(engine.label_filter("Rudy"))
        self.assertTrue(engine.label_filter("Someone else"))


class TestLabelsReachTheTables(unittest.TestCase):
    """Both tables must draw the same pills — the payloads carry them."""

    def setUp(self):
        self.br, _cfg = make_bridge()

    def test_the_bridge_maps_nicks_to_their_labels(self):
        rude = json.loads(self.br.label_create("Rude", "#ff3b30"))["id"]
        self.br.label_assign("Nick", rude)
        got = self.br._labels_for_nicks(["Nick", "Other"])
        self.assertEqual(got["Nick"][0]["name"], "Rude")
        self.assertEqual(got.get("Other", []), [])

    def test_the_map_carries_the_colour_the_ui_paints_with(self):
        rude = json.loads(self.br.label_create("Rude", "#ff3b30"))["id"]
        self.assertTrue(rude)
        self.br.label_assign("Nick", "  " + rude + " ")
        got = self.br._labels_for_nicks(["Nick"])
        self.assertEqual(got["Nick"][0]["color"], "#ff3b30")


class TestUiWiring(unittest.TestCase):
    """The shipped UI must actually contain the Label Manager."""

    @classmethod
    def setUpClass(cls):
        base = os.path.join(os.path.dirname(__file__), "..", "ui")
        with open(os.path.join(base, "index.html"), encoding="utf-8") as fh:
            cls.html = fh.read()
        with open(os.path.join(base, "js", "labels.js"), encoding="utf-8") as fh:
            cls.js = fh.read()
        with open(os.path.join(base, "css", "labels.css"), encoding="utf-8") as fh:
            cls.css = fh.read()

    def test_the_label_manager_is_a_normal_grid_window(self):
        self.assertIn('data-window="labels"', self.html)
        self.assertIn('id="winLabels"', self.html)
        self.assertIn("win-title", self.html)

    def test_it_has_all_four_sections(self):
        for anchor in ("labelActiveList", "labelNameInput", "labelColorBtn",
                       "labelAddBtn", "labelFilterList", "labelIncludeBtn",
                       "labelExcludeBtn", "labelPersonSelect",
                       "labelAssignList", "labelAssignBtn"):
            self.assertIn(anchor, self.html, anchor + " is missing")

    def test_the_person_dropdown_says_select_person(self):
        self.assertIn("Select person", self.js)

    def test_a_pill_has_a_remove_button_scoped_to_the_person(self):
        self.assertIn("label-pill-x", self.js)
        self.assertIn("label-pill-x", self.css)
        self.assertIn("unassign", self.js)

    def test_deleting_everywhere_lives_in_the_manager_only(self):
        self.assertIn("label_delete", self.js)
        with open(os.path.join(os.path.dirname(__file__), "..", "ui", "js",
                               "user-table.js"), encoding="utf-8") as fh:
            table = fh.read()
        self.assertNotIn("label_delete", table,
                         "a table row must never delete a label globally")


if __name__ == "__main__":
    unittest.main(verbosity=2)
