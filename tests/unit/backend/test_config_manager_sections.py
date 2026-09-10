"""backend/config_manager — the section-owner table (AREA D task D3).

`ConfigManager` is a façade over seven stores. Before D3 both `get()` and
`set()` dispatched on *store identity* with a 5-branch `if/elif` chain, and
`set()` reached nesting 14 — the class of bug that lives in such a chain is
"a section that is not a dict any more" (a hand-edited file, or the arity
misuse `set("history", "enabled")` that the ledger records).

The design (docs/REFACTOR_2026-09-09_AREA_D_DESIGN.md §5) is one table:
section → owner, each owner with `read(rest, default)` / `write(rest, value)`
/ `snapshot()`. Adding a section is a new row, not a new `elif`.

Promises proven here (CF#8–17, continuing the ids of
`tests/unit/backend/test_config_manager_contract.py`):

  CF#8   `data()` serves EVERY documented section — defaults deep-merged
         under what the file holds — and stays JSON-valid when a section was
         clobbered into a scalar;
  CF#9   the routing table is total: every routed name has an owner, an
         unknown section lands in the settings store, `snapshot()` of the
         settings owner carries the merged view;
  CF#10  a scalar standing where a dict belongs: reads fall back to the
         default, writes repair the path instead of raising;
  CF#11  nested reads through the routed sections work (and cannot walk a
         list);
  CF#12  `named_*` routes: presets through the preset store, everything else
         through its owner — and never fabricates a dict for a list section;
  CF#13  `set_state` keeps its "flush the settings store too" quirk (load
         bearing for services/undo_service);
  CF#14  `get_state` falls back to DEFAULTS["state"], and the undo keys are
         read from the undo store;
  CF#15  `data()`'s state section carries the undo timeline;
  CF#16  `validate()` reports only the settings rules, whatever the other
         stores hold;
  CF#17  `to_dict()` is the same data as `data()`, ASCII-preserving JSON.

Run with:  python3 tests/unit/backend/test_config_manager_sections.py
"""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))))

from backend.config_manager import (DEFAULTS, MAX_STACK_HISTORY,  # noqa: E402
                                    ConfigManager)
from stores.settings_store import SETTINGS_DEFAULTS  # noqa: E402


class SectionsCase(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cfg_path = os.path.join(self.tmp.name, "config.json")
        self.cm = ConfigManager(self.cfg_path)
        self.addCleanup(self._quiet_save)
        self.conf_dir = os.path.join(self.tmp.name, "config")

    def _quiet_save(self):
        try:
            self.cm.save()
        except Exception:
            pass

    def write_settings(self, payload) -> None:
        """Put a file in place the way a hand-edit would, then re-read."""
        with open(os.path.join(self.conf_dir, "settings.json"), "w",
                  encoding="utf-8") as fh:
            json.dump(payload, fh)
        self.cm.settings.load()

    def read_file(self, name: str):
        with open(os.path.join(self.conf_dir, name), encoding="utf-8") as fh:
            return json.load(fh)


# ══════════════════════════════════════════════════════════════════
# CF#8 — `data()` is the whole app view, not just what happens to be saved
# ══════════════════════════════════════════════════════════════════
class TestDataCompleteness(SectionsCase):

    def test_fresh_install_reports_every_default_section(self):
        data = self.cm.data()
        for section in SETTINGS_DEFAULTS:
            with self.subTest(section=section):
                self.assertIn(section, data,
                              "`data()` is what `get_app_state` renders and "
                              "what `to_dict()` serialises: a section that "
                              "only exists as a `get()` fallback is invisible "
                              "to both")
        self.assertEqual(data["chrome"]["port"], 9222)
        self.assertEqual(data["history"]["media"]["max_file_mb"], 25)

    def test_stored_values_win_and_siblings_are_kept(self):
        self.cm.set("chrome", "port", 9999)
        data = self.cm.data()
        self.assertEqual(data["chrome"]["port"], 9999)
        self.assertEqual(data["chrome"]["host"], "127.0.0.1",
                         "the merge must be per key, not per section: a file "
                         "that stores one key may not hide its neighbours")

    def test_data_is_a_snapshot_the_caller_can_mutate(self):
        data = self.cm.data()
        data["chrome"]["port"] = 1
        data["state"]["undo_history"] = ["gone"]
        self.assertEqual(self.cm.get("chrome", "port"), 9222)
        self.assertEqual(self.cm.get_state("undo_history"), [])

    def test_a_scalar_clobbered_section_still_produces_valid_json(self):
        """The ledger's `set("history", "enabled")` misuse leaves a STRING in
        the tree. `data()` must show it as it is — not crash, and not pretend
        the defaults are still there."""
        self.cm.set("history", "enabled")
        data = self.cm.data()
        self.assertEqual(data["history"], "enabled")
        json.loads(self.cm.to_dict())

    def test_every_default_key_is_json_serialisable(self):
        self.assertEqual(json.loads(self.cm.to_dict())["chrome"]["port"], 9222)
        self.assertEqual(MAX_STACK_HISTORY, 100)
        self.assertIs(DEFAULTS["history"]["enabled"], True)


# ══════════════════════════════════════════════════════════════════
# CF#9 — one routing table
# ══════════════════════════════════════════════════════════════════
class TestOwnerRouting(SectionsCase):

    def test_each_routed_section_maps_to_a_stable_owner(self):
        for section in ("url_presets", "custom_blocks", "labels",
                        "stack_presets", "template_presets", "chrome"):
            with self.subTest(section=section):
                self.assertIs(self.cm._owner_for(section),
                              self.cm._owner_for(section),
                              "owners are per-store singletons, so callers can "
                              "compare them (`named_*` routes on identity)")

    def test_unknown_sections_are_owned_by_settings(self):
        self.assertIs(self.cm._owner_for("no_such_section"),
                      self.cm._owner_for("chrome"))
        self.cm.set("no_such_section", "deep", 3)
        self.cm.save()
        self.assertEqual(self.read_file("settings.json")["no_such_section"],
                         {"deep": 3})

    def test_the_route_table_covers_every_owner_it_names(self):
        from backend.config_manager import _OWNERS, _SECTION_ROUTES
        for name in {n for n in _SECTION_ROUTES.values()}:
            with self.subTest(owner=name):
                self.assertIn(name, _OWNERS,
                              f"route {name!r} has no owner class")
                self.assertIs(self.cm._owners[name], self.cm._owners[name])
        # ...and every owner class is reachable from the table
        self.assertEqual(set(_OWNERS),
                         {*_SECTION_ROUTES.values(), "settings"})

    def test_store_for_still_answers_for_every_section(self):
        """`_store_for` is part of the tested surface — it may return an owner
        now, but it must never raise for any section."""
        for section in ("chrome", "labels", "url_presets", "custom_blocks",
                        "stack_presets", "template_presets", "state", "x"):
            with self.subTest(section=section):
                self.assertIsNotNone(self.cm._store_for(section))


# ══════════════════════════════════════════════════════════════════
# CF#10 — a scalar where a dict belongs
# ══════════════════════════════════════════════════════════════════
class TestHostilePaths(SectionsCase):

    def test_read_through_a_scalar_falls_back_to_the_default(self):
        self.write_settings({"history": "oops"})
        self.assertEqual(self.cm.get("history", "media", "max_file_mb",
                                     default=1), 1)
        self.assertEqual(self.cm.get("history", "enabled", default="gone"), "gone")

    def test_write_through_a_scalar_repairs_the_path(self):
        self.write_settings({"chrome": 5})
        self.cm.set("chrome", "port", 9333)        # must not raise
        self.assertEqual(self.cm.get("chrome", "port"), 9333)

    def test_a_scalar_value_for_a_whole_section_is_still_allowed(self):
        self.cm.set("chrome", "flat")
        self.assertEqual(self.cm.get("chrome"), "flat")
        self.cm.save()
        self.assertEqual(self.read_file("settings.json")["chrome"], "flat")

    def test_a_broken_preset_payload_does_not_take_the_app_down(self):
        with open(os.path.join(self.conf_dir, "presets.json"), "w",
                  encoding="utf-8") as fh:
            fh.write("[not, an, object")
        self.cm.presets.load()
        self.assertEqual(self.cm.named_all("stack_presets"), {})
        self.cm.named_set("stack_presets", "run", [{"t": "Pause"}])
        self.assertEqual(self.cm.named_get("stack_presets", "run"),
                         [{"t": "Pause"}])


# ══════════════════════════════════════════════════════════════════
# CF#11 / CF#12 — reads and writes through the routed owners
# ══════════════════════════════════════════════════════════════════
class TestRoundedOwners(SectionsCase):

    def test_nested_read_of_the_labels_section(self):
        self.cm.set("labels", {"defs": [{"name": "vip"}], "next_id": 3})
        self.assertEqual(self.cm.get("labels", "next_id"), 3)
        self.assertEqual(self.cm.get("labels", "defs"), [{"name": "vip"}])
        self.assertEqual(self.cm.get("labels", "nope", default="D"), "D")
        self.assertEqual(self.cm.get("labels")["defs"], [{"name": "vip"}])

    def test_nested_write_of_the_labels_section_keeps_the_siblings(self):
        self.cm.set("labels", {"defs": [{"name": "vip"}], "next_id": 3})
        self.cm.set("labels", "filter", {"include": ["a"]})
        data = self.cm.get("labels")
        self.assertEqual(data["next_id"], 3,
                         "writing one key of a section may not drop the rest")
        self.assertEqual(data["filter"], {"include": ["a"]})

    def test_a_list_section_cannot_be_walked_and_says_so(self):
        self.cm.set("url_presets", ["https://a", "https://b"])
        self.assertEqual(self.cm.get("url_presets"), ["https://a", "https://b"])
        self.assertEqual(self.cm.get("url_presets", 0, default="D"), "D",
                         "bookmarks are a list: index-walking is not a thing")
        self.assertEqual(self.cm.get("custom_blocks", "0", default="D"), "D")

    def test_named_access_to_a_list_section_is_an_empty_map(self):
        self.assertEqual(self.cm.named_all("url_presets"), {},
                         "a list section has no names, so `named_all` must "
                         "not fabricate a dict out of it")

    def test_named_access_on_a_settings_section_writes_the_settings_tree(self):
        self.cm.named_set("chrome", "proxy", {"host": "x"})
        self.assertEqual(self.cm.named_get("chrome", "proxy"), {"host": "x"})
        names = set(self.cm.named_all("chrome"))
        self.assertLessEqual({"host", "port", "proxy"}, names,
                             "a named write lands in the settings tree next "
                             "to the keys that were already there")
        self.assertIn("reconnect_interval_s", names,
                      "…and the section's other defaults stay visible")
        self.assertTrue(self.cm.named_delete("chrome", "proxy"))
        self.assertFalse(self.cm.named_delete("chrome", "proxy"))
        self.assertEqual(self.cm.get("chrome", "port"), 9222,
                         "deleting a name may not disturb its neighbours")

    def test_custom_blocks_round_trip_through_their_own_file(self):
        self.cm.set("custom_blocks", [{"block_id": "X", "y": 1}])
        self.cm.save()
        self.assertEqual(self.read_file("blocks.json")["custom_blocks"],
                         [{"block_id": "X", "y": 1}])
        self.assertEqual(self.cm.get("custom_blocks"),
                         [{"block_id": "X", "y": 1}])


# ══════════════════════════════════════════════════════════════════
# CF#13 / CF#14 — state routing
# ══════════════════════════════════════════════════════════════════
class TestStateRouting(SectionsCase):

    def test_set_state_flushes_the_settings_store_too(self):
        """Load bearing for services/undo_service, which calls
        `set_state(grid_layout=…)` and expects a whole-file save."""
        self.cm.set("chrome", "port", 9333)          # unsaved
        self.cm.set_state(grid_layout={"a": 1})
        self.assertEqual(self.read_file("settings.json")["chrome"]["port"],
                         9333, "the settings file was not flushed")

    def test_undo_keys_go_to_the_undo_store_only(self):
        self.cm.set_state(undo_history=[{"kind": "x", "value": 1}],
                          undo_history_index=0)
        self.assertEqual(self.cm.get_state("undo_history"),
                         [{"kind": "x", "value": 1}])
        self.assertEqual(self.cm.get_state("undo_history_index"), 0)
        self.cm.save()
        self.assertEqual(self.read_file("undo.json")["history"],
                         [{"kind": "x", "value": 1}],
                         "the undo timeline has its own file")

    def test_get_state_falls_back_to_the_documented_default(self):
        self.assertEqual(self.cm.get_state("db_recent"), [])
        self.assertIs(self.cm.get_state("block_config_pinned"), False)
        self.assertIsNone(self.cm.get_state("grid_layout"))
        self.assertEqual(self.cm.get_state("unknown_key", "D"), "D")

    def test_session_keys_and_undo_keys_do_not_bleed_into_each_other(self):
        self.cm.set_state(db_recent=["world.db"])
        self.assertEqual(self.cm.get_state("db_recent"), ["world.db"])
        self.assertEqual(self.cm.get_state("undo_history"), [])
        self.cm.save()
        self.assertNotIn("undo_history", self.read_file("session.json"))


# ══════════════════════════════════════════════════════════════════
# CF#15 – CF#17 — what the façade hands to the rest of the app
# ══════════════════════════════════════════════════════════════════
class TestMergedView(SectionsCase):

    def test_state_section_carries_the_undo_timeline(self):
        self.cm.set_state(undo_history=[{"a": 1}], undo_history_index=0)
        state = self.cm.data()["state"]
        self.assertEqual(state["undo_history"], [{"a": 1}])
        self.assertEqual(state["undo_history_index"], 0)
        self.assertIn("db_recent", state)

    def test_validate_reports_only_the_settings_rules(self):
        self.cm.set("chrome", "port", 99999)
        self.cm.set("delays", "global_pre_action_ms", -1)
        self.assertEqual(self.cm.validate(),
                         ["chrome.port invalid: 99999",
                          "global_pre_action_ms must be >= 0"])
        self.cm.set("chrome", "port", "not a number")
        self.assertEqual(self.cm.validate(),
                         ["chrome.port invalid: not a number",
                          "global_pre_action_ms must be >= 0"])

    def test_to_dict_is_the_merged_view_as_json(self):
        self.cm.named_set("stack_presets", "монтаж", [{"t": "Pause"}])
        merged = json.loads(self.cm.to_dict())
        self.assertEqual(merged["stack_presets"],
                         self.cm.named_all("stack_presets"))
        self.assertIn("монтаж", self.cm.to_dict(),
                      "`to_dict` must not escape non-ASCII for the log pane")
        for section in SETTINGS_DEFAULTS:
            self.assertIn(section, merged)


if __name__ == "__main__":
    unittest.main(verbosity=2)
