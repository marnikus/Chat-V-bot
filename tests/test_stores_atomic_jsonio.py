"""stores/jsonio + stores/atomic — atomic file I/O contract.

Design refs: docs/archive/2026-09-09-test-suite/STORES_TEST_DESIGN_2026-09-09.md §1 (JIO-01–12),
§2 (ATM-01–09).

Every store in the package stands on these two modules: jsonio is the only
place config files are written, AtomicJsonStore is the base of the small
stores. A silent corruption here would poison all of them, so these tests
pin the failure paths, not just the happy ones:

  * missing / corrupt / unreadable files degrade to the default, never raise;
  * a failed save returns False/Err and leaves the previous good file whole;
  * readers see old-or-new only (tmp + os.replace), never a half-write;
  * get() with missing keys returns the default, get_copy() is deep;
  * set() arity abuse is loud, never silent corruption.

Run with:  python3 tests/test_stores_atomic_jsonio.py
"""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from stores.atomic import AtomicJsonStore  # noqa: E402
from stores.jsonio import config_dir_for, load_json, save_json  # noqa: E402


class TmpCase(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "store.json")

    def tmp(self, name="x.json"):
        return os.path.join(self.dir, name)


# ── jsonio ───────────────────────────────────────────────────────
class TestLoadJson(TmpCase):
    def test_missing_file_returns_a_copy_of_the_default(self):  # JIO-01
        default = {"a": 1}
        first = load_json(self.tmp("nope.json"), default=default)
        self.assertEqual(first, {"a": 1})
        first["a"] = 999  # mutating one result must not poison the next
        self.assertEqual(load_json(self.tmp("nope.json"), default=default),
                         {"a": 1})

    def test_corrupt_file_returns_a_copy_of_the_default(self):  # JIO-02
        bad = self.tmp("bad.json")
        with open(bad, "w", encoding="utf-8") as fh:
            fh.write("{not json!!!")
        default = [1, 2]
        first = load_json(bad, default=default)
        self.assertEqual(first, [1, 2])
        first.append(3)
        self.assertEqual(load_json(bad, default=default), [1, 2])

    def test_a_directory_is_not_valid_json(self):  # JIO-03
        self.assertEqual(load_json(self.dir, default="x"), "x")

    def test_valid_file_without_default_returns_content(self):  # JIO-04
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump({"k": [1, 2]}, fh)
        self.assertEqual(load_json(self.path), {"k": [1, 2]})

    def test_empty_and_whitespace_files_return_default(self):  # JIO-05
        for body in ("", "   \n  "):
            p = self.tmp("blank.json")
            with open(p, "w", encoding="utf-8") as fh:
                fh.write(body)
            self.assertEqual(load_json(p, default={"d": 1}), {"d": 1})

    def test_invalid_bytes_degrade_to_default(self):  # JIO-02b
        p = self.tmp("bytes.json")
        with open(p, "wb") as fh:
            fh.write(b"\xff\xfe\x00bad")
        self.assertEqual(load_json(p, default=7), 7)


class TestSaveJson(TmpCase):
    def test_round_trip_leaves_no_tmp_file(self):  # JIO-06
        data = {"a": [1, {"b": "текст"}], "c": None}
        self.assertTrue(save_json(self.path, data))
        self.assertEqual(load_json(self.path), data)
        self.assertFalse(os.path.exists(self.path + ".tmp"))

    def test_overwrite_is_old_or_new_only(self):  # JIO-07
        save_json(self.path, {"v": 1})
        save_json(self.path, {"v": 2})
        self.assertEqual(load_json(self.path), {"v": 2})

    def test_unwritable_path_returns_false(self):  # JIO-08
        blocker = self.tmp("blocker")
        with open(blocker, "w", encoding="utf-8") as fh:
            fh.write("i am a file, not a dir")
        self.assertFalse(save_json(os.path.join(blocker, "x.json"), {"a": 1}))

    def test_missing_parents_are_created(self):  # JIO-08b (SPEC pin)
        deep = os.path.join(self.dir, "a", "b", "c.json")
        self.assertTrue(save_json(deep, {"a": 1}))
        self.assertEqual(load_json(deep), {"a": 1})

    def test_unserialisable_data_fails_without_touching_target(self):  # JIO-09
        save_json(self.path, {"good": True})
        self.assertFalse(save_json(self.path, {1, 2, 3}))
        self.assertEqual(load_json(self.path), {"good": True})
        self.assertFalse(os.path.exists(self.path + ".tmp"))

    def test_circular_data_fails_cleanly(self):  # JIO-09b
        save_json(self.path, {"good": True})
        evil = {}
        evil["self"] = evil
        self.assertFalse(save_json(self.path, evil))
        self.assertEqual(load_json(self.path), {"good": True})

    def test_none_round_trips_as_null(self):  # JIO-10
        self.assertTrue(save_json(self.path, None))
        self.assertIsNone(load_json(self.path, default="dflt"))


class TestConfigDirFor(TmpCase):
    def test_legacy_path_maps_to_sibling_config_dir(self):  # JIO-11
        out = config_dir_for("/a/b/config.json")
        self.assertEqual(out, os.path.join("/a", "b", "config"))

    def test_bare_name_maps_to_cwd_config(self):  # JIO-12
        out = config_dir_for("config.json")
        self.assertTrue(out.endswith("config"))
        self.assertEqual(os.path.dirname(out), os.getcwd())


# ── atomic ───────────────────────────────────────────────────────
class TestAtomicStore(TmpCase):
    def test_fresh_path_loads_empty(self):  # ATM-01
        store = AtomicJsonStore(self.tmp("fresh.json"))
        self.assertEqual(store.data(), {})

    def test_corrupt_file_loads_empty_without_raising(self):  # ATM-02
        bad = self.tmp("bad.json")
        with open(bad, "w", encoding="utf-8") as fh:
            fh.write("{{{")
        store = AtomicJsonStore(bad)
        self.assertEqual(store.data(), {})

    def test_set_deep_merges_siblings(self):  # ATM-03
        store = AtomicJsonStore(self.path)
        store.set("a", "b", 1)
        store.set("a", "c", 2)
        self.assertEqual(store.data(), {"a": {"b": 1, "c": 2}})

    def test_get_with_missing_keys_returns_default(self):  # ATM-04
        store = AtomicJsonStore(self.path)
        store.set("a", "b", 1)
        self.assertEqual(store.get("a", "b"), 1)
        self.assertEqual(store.get("a", "missing", default=5), 5)
        self.assertEqual(store.get("nope", "deeper", default=5), 5)

    def test_get_copy_is_deep(self):  # ATM-05
        store = AtomicJsonStore(self.path)
        store.set("a", {"n": [1]})
        copied = store.get_copy("a")
        copied["n"].append(2)
        self.assertEqual(store.get("a"), {"n": [1]})

    def test_set_without_a_value_is_loud(self):  # ATM-06
        store = AtomicJsonStore(self.path)
        with self.assertRaises((TypeError, ValueError)):
            store.set()
        with self.assertRaises((TypeError, ValueError)):
            store.set("only-a-key")
        # the rejected set() corrupted nothing: the store still saves
        store.set("ok", 1)
        self.assertTrue(store.save().is_ok)
        self.assertEqual(load_json(self.path), {"ok": 1})

    def test_save_and_reopen_round_trip(self):  # ATM-07
        store = AtomicJsonStore(self.path)
        store.set("a", "b", [1, 2])
        self.assertTrue(store.save().is_ok)
        again = AtomicJsonStore(self.path)
        self.assertEqual(again.data(), {"a": {"b": [1, 2]}})

    def test_failed_save_keeps_memory_intact(self):  # ATM-08
        blocker = self.tmp("blocker")
        with open(blocker, "w", encoding="utf-8") as fh:
            fh.write("x")
        store = AtomicJsonStore(os.path.join(blocker, "s.json"))
        store.set("a", 1)
        res = store.save()
        self.assertTrue(res.is_err)
        self.assertEqual(store.data(), {"a": 1})

    def test_unserialisable_key_keeps_file_valid(self):  # ATM-09
        store = AtomicJsonStore(self.path)
        store.set("good", 1)
        self.assertTrue(store.save().is_ok)
        store.set(("tuple", "key"), "v")  # not JSON-representable
        res = store.save()
        self.assertTrue(res.is_err)
        self.assertEqual(load_json(self.path), {"good": 1})

    def test_data_is_a_copy(self):  # ATM-05b
        store = AtomicJsonStore(self.path)
        store.set("a", [1])
        store.data()["a"].append(2)
        self.assertEqual(store.get("a"), [1])


if __name__ == "__main__":
    unittest.main()
