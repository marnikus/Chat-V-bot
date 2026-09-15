"""The `config_*` family's edges: the parts the section suite never reached.

Round J step J-3 split `backend/config_manager.py` (511 lines) into a facade
plus `config_defaults` / `config_owners` / `config_view`, and the design's
criterion for that step is **coverage ≥ 90%**. The gates' own numbers said
where the missing lines were — 86% on the facade, 81% on the owners, 70% on
the defaults — and every one of them was a *branch nobody had ever driven*,
not a line that merely did not execute:

* `deep_merge` with a non-dict overlay (the "a malformed set() flattened this
  section into a scalar" case it exists for);
* `set_nested` refusing to walk through a scalar instead of raising;
* the base `_Owner`'s three abstract verbs;
* `_NamedOwner`'s store-level verbs, which the facade reaches only through
  `presets` — including the `rest`-carrying form;
* the facade's own `load()` and its `validate()` delegation;
* `json_dumps`, whose single spelling now lives in `config_defaults`;
* a `state.*` key with no documented default.

Run with:  python3 tests/unit/backend/test_config_family_edges.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))))

import backend.config_defaults as defaults                      # noqa: E402
import backend.config_owners as owners                          # noqa: E402
import backend.config_view as view                              # noqa: E402
from backend.config_manager import (                            # noqa: E402
    DEFAULTS, MAX_STACK_HISTORY, ConfigManager, json_dumps,
)


class TestThePureHelpers(unittest.TestCase):
    """`config_defaults`' two tree operations, driven by shape."""

    def test_a_dict_overlay_merges_key_by_key(self):
        self.assertEqual(defaults.deep_merge({"a": {"b": 1, "c": 2}},
                                             {"a": {"b": 9}}),
                         {"a": {"b": 9, "c": 2}},
                         "the sibling under a merged dict survives")

    def test_a_non_dict_overlay_wins_wholesale(self):
        """The reason `deep_merge` is not `{**base, **overlay}`: a section a
        malformed write flattened into a scalar must stay visible."""
        self.assertEqual(defaults.deep_merge({"a": {"b": 1}}, "flattened"),
                         "flattened")
        self.assertEqual(defaults.deep_merge({"a": 1}, None), None)

    def test_set_nested_replaces_a_scalar_on_the_way_and_refuses_a_bad_root(self):
        """Two behaviours, both load-bearing:

        * a scalar standing where a dict belongs is *replaced* — this is the
          path a `set()` through a flattened section has to survive;
        * a root that is not a dict is a refusal, so a caller cannot corrupt a
          file through it.
        """
        tree = {"section": 7}
        self.assertTrue(defaults.set_nested(tree, ("section", "key"), 1))
        self.assertEqual(tree, {"section": {"key": 1}},
                         "the scalar is replaced, not written through")
        self.assertFalse(defaults.set_nested("not a tree", ("a",), 1))

    def test_set_nested_creates_the_dicts_on_the_way(self):
        tree = {"section": 7}
        self.assertTrue(defaults.set_nested(tree, ("a", "b", "c"), 3))
        self.assertEqual(tree, {"section": 7, "a": {"b": {"c": 3}}})

    def test_json_dumps_is_one_spelling_of_json(self):
        text = defaults.json_dumps({"nick": "Аня"})
        self.assertIn("Аня", text, "non-ASCII stays readable")
        self.assertEqual(json.loads(text), {"nick": "Аня"})


class TestTheBaseOwnerVerbs(unittest.TestCase):
    """`_Owner` is abstract on purpose; a subclass that forgets a verb must
    fail loudly at the call, not answer something plausible."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cm = ConfigManager(os.path.join(self.tmp.name, "config.json"))

    def test_the_abstract_verbs_raise(self):
        base = owners._Owner(self.cm)
        for call in (lambda: base.read("settings", ()),
                     lambda: base.write("settings", (), 1),
                     lambda: base.snapshot("settings")):
            with self.subTest(call=call):
                with self.assertRaises(NotImplementedError):
                    call()

    def test_a_list_section_reads_whole_and_ignores_key_paths(self):
        """`_ListOwner.read` is total: with no key path it answers the list the
        store holds, and with one it answers the caller's default — a list has
        no keys to walk, which is the difference from the dict sections."""
        own = self.cm._owner_for("url_presets")
        self.assertEqual(own.read("url_presets", (), "unused"),
                         self.cm.bookmarks.all())
        self.assertEqual(own.read("url_presets", ("nope",), "d"), "d")


class TestNamedOwnerAtTheStoreLevel(unittest.TestCase):
    """The `_NamedOwner` verbs the facade routes `presets` through."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cm = ConfigManager(os.path.join(self.tmp.name, "config.json"))
        self.owner = self.cm._owner_for("stack_presets")

    def test_named_get_and_all_read_through_the_store(self):
        self.owner.named_set("stack_presets", "one", {"blocks": []})
        self.assertEqual(self.owner.named_all("stack_presets"),
                         {"one": {"blocks": []}})
        self.assertEqual(self.owner.named_get("stack_presets", "one"),
                         {"blocks": []})
        self.assertEqual(self.owner.named_get("stack_presets", "gone", "d"), "d")

    def test_replace_all_deletes_what_is_gone_and_writes_the_rest(self):
        self.owner.named_set("stack_presets", "one", {"blocks": [1]})
        self.owner.write("stack_presets", (), {"two": {"blocks": [2]}})
        self.assertEqual(self.owner.named_all("stack_presets"),
                         {"two": {"blocks": [2]}},
                         "a whole-map write is a replace, not a merge")

    def test_a_named_write_with_a_rest_path_names_one_item(self):
        self.owner.write("stack_presets", ("one",), {"blocks": [1]})
        self.assertEqual(self.owner.named_get("stack_presets", "one"),
                         {"blocks": [1]})

    def test_a_whole_map_write_ignores_a_non_dict(self):
        """`write(section, (), value)` is the replace-all path, and a value
        that is not a map is a caller mistake: dropping it keeps the file
        valid instead of writing a scalar where presets are expected."""
        self.owner.named_set("stack_presets", "one", {"blocks": [1]})
        self.owner.write("stack_presets", (), "flattened")
        self.assertEqual(self.owner.named_all("stack_presets"),
                         {"one": {"blocks": [1]}},
                         "the map survives; nothing was written")


class TestTheFacadeEdges(unittest.TestCase):
    """The facade's own lines: the re-exported constants, `load()`, the
    `named_*` save switch and the `json_dumps` wrapper."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = os.path.join(self.tmp.name, "config.json")
        self.cm = ConfigManager(self.dir)

    def test_the_historical_import_path_still_answers(self):
        self.assertEqual(MAX_STACK_HISTORY, 100)
        self.assertIsInstance(DEFAULTS, dict)
        self.assertIn("state", DEFAULTS)
        self.assertEqual(json.loads(json_dumps({"a": 1})), {"a": 1})
        self.assertEqual(json_dumps({"nick": "Аня"}),
                         defaults.json_dumps({"nick": "Аня"}),
                         "the wrapper and the implementation agree")

    def test_load_rereads_every_store(self):
        self.cm.named_set("stack_presets", "one", {"blocks": [1]})
        self.cm.set("chrome", "port", 9333)
        self.cm.save()
        # a second manager over the same directory sees the writes...
        other = ConfigManager(self.dir)
        self.assertEqual(other.get("chrome", "port"), 9333)
        # ...and `load()` re-reads on top of a fresh, empty store set
        self.cm.settings.data().clear()
        self.cm.load()
        self.assertEqual(self.cm.get("chrome", "port"), 9333)

    def test_a_named_write_can_skip_the_save(self):
        self.cm.named_set("stack_presets", "one", {"blocks": [1]}, save=False)
        self.assertEqual(self.cm.named_get("stack_presets", "one"),
                         {"blocks": [1]})
        self.assertTrue(self.cm.named_delete("stack_presets", "one",
                                             save=False))

    def test_a_missing_name_deletes_nothing_and_says_so(self):
        self.assertFalse(self.cm.named_delete("stack_presets", "never-set"))

    def test_get_and_set_without_a_section_are_no_ops(self):
        self.assertEqual(self.cm.get(default="d"), "d")
        before = self.cm.data()
        self.cm.set(5)          # a value with no key path: nothing to route
        self.assertEqual(self.cm.data(), before)

    def test_store_for_answers_the_raw_store(self):
        self.assertIs(self.cm._store_for("chrome"), self.cm.settings)
        self.assertIs(self.cm._store_for("url_presets"), self.cm.bookmarks)

    def test_validate_reports_the_store_findings(self):
        self.assertEqual(self.cm.validate(), [],
                         "a healthy config has nothing to repair")
        self.cm.settings.set("chrome", "port", 99999)
        self.assertEqual(self.cm.validate(), ["chrome.port invalid: 99999"],
                         "the facade delegates to the settings store, which "
                         "owns what a valid config looks like")

    def test_a_migration_failure_is_a_warning_not_a_crash(self):
        """The one-time legacy split must never stop the app from booting."""
        target = os.path.join(self.tmp.name, "second.json")
        with unittest.mock.patch.object(
                __import__("backend.config_manager", fromlist=["x"]),
                "migrate_legacy_config", side_effect=RuntimeError("boom")):
            cm = ConfigManager(target)
        self.assertTrue(os.path.isdir(cm._dir))

    def test_a_state_key_without_a_documented_default_returns_the_default(self):
        self.assertEqual(self.cm.get_state("no_such_key", "fallback"),
                         "fallback")
        self.assertEqual(self.cm.get_state("no_such_key"), None)
        self.assertIsInstance(view.state_default("no_such_key", "x"), str)


import unittest.mock  # noqa: E402  (imported here so the mock target is explicit)


if __name__ == "__main__":
    unittest.main(verbosity=2)
