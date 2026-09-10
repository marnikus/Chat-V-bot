"""stores/preset_store — named sections, hostile names, cache edges.

Design refs: docs/archive/2026-09-09-test-suite/STORES_TEST_DESIGN_2026-09-09.md §9 (PRS-01–10).

test_preset_store_unit.py pins stack/template CRUD, overwrite, reopen,
dirty/force and the one-time legacy import. This file pins what it does
not: the named_* compatibility surface the ConfigManager facade talks
through (including its survival across a restart), hostile preset names,
hostile payloads, and the per-path instance cache.

Run with:  python3 tests/test_preset_store_defaults.py
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from stores.preset_store import PresetStore  # noqa: E402


class PresetCase(unittest.TestCase):
    def setUp(self):
        PresetStore._by_path.clear()
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "config", "presets.json")
        self.store = PresetStore(path=self.path)

    def tearDown(self):
        PresetStore._by_path.clear()

    def reopen(self):
        PresetStore._by_path.pop(os.path.abspath(self.path), None)
        return PresetStore(path=self.path)


class TestNamedSections(PresetCase):
    def test_named_round_trip(self):  # PRS-01
        self.store.named_set("stack_presets", "a", {"blocks": []})
        self.assertEqual(self.store.named_get("stack_presets", "a"),
                         {"blocks": []})
        self.assertIn("a", self.store.named_all("stack_presets"))
        self.assertTrue(self.store.named_delete("stack_presets", "a"))
        self.assertIsNone(self.store.named_get("stack_presets", "a"))
        self.assertFalse(self.store.named_delete("stack_presets", "ghost"))

    def test_unknown_section_and_name_are_empty_safe(self):  # PRS-02
        self.assertEqual(self.store.named_all("nope"), {})
        self.assertEqual(self.store.named_get("nope", "x", default="d"), "d")
        self.assertFalse(self.store.named_delete("nope", "x"))

    def test_named_sections_survive_a_reopen(self):  # PRS-03
        self.store.named_set("stack_presets", "a", {"blocks": [{"b": 1}]})
        self.store.named_set("custom_section", "k", [1, 2])
        self.assertTrue(self.store.save())
        again = self.reopen()
        self.assertEqual(again.named_get("stack_presets", "a"),
                         {"blocks": [{"b": 1}]})
        self.assertEqual(again.named_get("custom_section", "k"), [1, 2])

    def test_named_mutations_mark_dirty(self):  # PRS-10
        mtime_miss = not os.path.exists(self.path)
        self.store.named_set("s", "k", 1)
        self.assertTrue(self.store.dirty)
        self.assertTrue(self.store.save())
        self.assertFalse(self.store.dirty)
        # a clean save(force=False) touches nothing on disk
        before = os.stat(self.path).st_mtime_ns if not mtime_miss else None
        self.store.save()
        if before is not None:
            self.assertEqual(os.stat(self.path).st_mtime_ns, before)


class TestHostileNames(PresetCase):
    def test_stack_names_are_plain_dict_keys(self):  # PRS-04
        names = ["a/b", "..", "x" * 500, "Сборка 🎉", " spaced "]
        for name in names:
            self.store.save_stack(name, [{"b": 1}])
        listed = {entry["name"] for entry in self.store.list_stacks()}
        self.assertIn("a/b", listed)
        self.assertIn("..", listed)
        self.assertIn("x" * 500, listed)
        self.assertIn("Сборка 🎉", listed)
        self.assertIn("spaced", listed)  # stripped, like templates
        self.assertTrue(self.store.save())
        again = self.reopen()
        self.assertEqual(again.load_stack("a/b"), [{"b": 1}])
        # nothing escaped the single presets file
        self.assertEqual(os.listdir(os.path.join(self.dir, "config")),
                         ["presets.json"])

    def test_empty_stack_and_template_names_are_loud(self):  # PRS-04b (pin)
        with self.assertRaises(ValueError):
            self.store.save_stack("", [])
        with self.assertRaises(ValueError):
            self.store.save_stack("   ", [])
        with self.assertRaises(ValueError):
            self.store.save_template("", "body")
        self.assertFalse(self.store.dirty)


class TestHostilePayloads(PresetCase):
    def test_non_list_blocks_are_refused(self):  # PRS-05
        for bad in ({"not": "a list"}, 5, "str"):
            with self.assertRaises(ValueError, msg=repr(bad)):
                self.store.save_stack("s", bad)
        self.assertFalse(self.store.dirty)
        self.assertIsNone(self.store.load_stack("s"))

    def test_none_blocks_become_empty(self):  # PRS-05b (pin)
        self.store.save_stack("s", None)
        self.assertEqual(self.store.load_stack("s"), [])

    def test_non_dict_items_pass_through_verbatim(self):  # PRS-05c (pin)
        self.store.save_stack("s", [None, "x", 5])
        self.assertTrue(self.store.save())
        self.assertEqual(self.reopen().load_stack("s"), [None, "x", 5])

    def test_non_string_template_body_is_refused(self):  # PRS-06
        with self.assertRaises(ValueError):
            self.store.save_template("t", 123)
        self.assertFalse(self.store.dirty)
        self.assertIsNone(self.store.load_template("t"))

    def test_none_template_body_becomes_empty(self):  # PRS-06b (pin)
        self.store.save_template("t", None)
        self.assertEqual(self.store.load_template("t"), "")

    def test_delete_unknown_is_quiet(self):  # PRS-07
        self.assertFalse(self.store.delete_stack("ghost"))
        self.assertFalse(self.store.delete_template("ghost"))


class TestCacheAndDefaults(PresetCase):
    def test_same_path_shares_state(self):  # PRS-08
        twin = PresetStore(path=self.path)
        self.assertIs(twin, self.store)
        self.store.save_stack("s", [])
        self.assertEqual(twin.load_stack("s"), [])

    def test_different_paths_are_isolated(self):  # PRS-08b
        other = PresetStore(path=os.path.join(self.dir, "other.json"))
        self.assertIsNot(other, self.store)
        self.store.save_stack("s", [{"b": 1}])
        self.assertIsNone(other.load_stack("s"))

    def test_no_default_preset_unknown_is_none(self):  # PRS-09 (pin)
        self.assertIsNone(self.store.load_stack("default"))
        self.assertIsNone(self.store.load_template("default"))
        self.assertEqual(self.store.list_stacks(), [])
        self.assertEqual(self.store.list_templates(), [])


if __name__ == "__main__":
    unittest.main()
