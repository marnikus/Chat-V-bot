"""Split stores — per-file shapes, lifecycle, and legacy migration.

Design ref: docs/BLOCKERS_FIX_DESIGN_2026-09-09.md §3–§4
(LMC-01–08, BKS-01–06, BLS-01–07, SES-08–10, SET-09–12, UND-08–13).

The facade-level behavior is pinned by tests/test_stores_split.py and
tests/unit/backend/test_config_manager_contract.py; this file pins the
stores directly: what lands on disk, bool-vs-loud refusal rules, and
the corrupt-tolerance each file owes its neighbours.

Run with:  python3 tests/test_stores_split_stores.py
"""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from stores.block_store import BlockStore  # noqa: E402
from stores.bookmark_store import BookmarkStore, DEFAULT_BOOKMARKS  # noqa: E402
from stores.jsonio import load_json  # noqa: E402
from stores.migration import migrate_legacy_config  # noqa: E402
from stores.session_store import SessionStore  # noqa: E402
from stores.settings_store import SettingsStore  # noqa: E402
from stores.undo_store import UndoStore  # noqa: E402


def legacy_payload() -> dict:
    return {
        "chrome": {"port": 9333, "host": "1.2.3.4"},
        "collector": {"my_nick": "Tester", "heartbeat_ms": 1500},
        "url_presets": ["https://x.example", "https://y.example"],
        "custom_blocks": [{"name": "Tab Main", "block": {"block_id":
                                                         "CUSTOM_FIND"}}],
        "stack_presets": {"run1": {"blocks": [{"block_id": "PAUSE"}],
                                   "updated_at": "2026-01-01T00:00:00"}},
        "template_presets": {"hi": {"body": "hello",
                                    "updated_at": "2026-01-01T00:00:00"}},
        "labels": {"defs": [{"id": "lbl_1", "name": "Rude",
                             "color": "#ff3b30", "created_at": ""}],
                   "assign": {"Ann": ["lbl_1"]},
                   "filter": {"include": [], "exclude": ["lbl_1"]},
                   "next_id": 2},
        "state": {"last_url_preset": "https://x.example",
                  "last_stack": [{"block_id": "PAUSE"}],
                  "undo_history": [{"kind": "stack", "value": [], "seq": 1}],
                  "undo_history_index": 0,
                  "grid_layout": "{\"v\":3}",
                  "window_geometry": {"x": 1, "y": 2, "width": 3, "height": 4}},
    }


class MigrationCase(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.legacy = os.path.join(self.dir, "config.json")
        self.cdir = os.path.join(self.dir, "config")

    def _write_legacy(self, payload):
        with open(self.legacy, "w", encoding="utf-8") as fh:
            json.dump(payload, fh)

    def test_full_split_and_archive(self):  # LMC-01
        self._write_legacy(legacy_payload())
        res = migrate_legacy_config(self.legacy, self.cdir)
        self.assertTrue(res["migrated"])
        self.assertFalse(os.path.exists(self.legacy))
        archived = [f for f in os.listdir(self.dir)
                    if f.startswith("config.json.migrated-")]
        self.assertEqual(len(archived), 1)
        self.assertEqual(res["archived"], os.path.join(self.dir, archived[0]))
        self.assertEqual(load_json(os.path.join(self.cdir, "settings.json"))
                         ["chrome"]["port"], 9333)
        self.assertEqual(load_json(os.path.join(self.cdir, "bookmarks.json")),
                         ["https://x.example", "https://y.example"])
        blocks = load_json(os.path.join(self.cdir, "blocks.json"))
        self.assertEqual(blocks[0]["name"], "Tab Main")
        presets = load_json(os.path.join(self.cdir, "presets.json"))
        self.assertIn("run1", presets["stack_presets"])
        self.assertIn("hi", presets["template_presets"])
        labels = load_json(os.path.join(self.cdir, "labels.json"))
        self.assertEqual(labels["assign"], {"Ann": ["lbl_1"]})
        self.assertEqual(labels["next_id"], 2)
        session = load_json(os.path.join(self.cdir, "session.json"))
        self.assertEqual(session["last_url_preset"], "https://x.example")
        self.assertNotIn("undo_history", session)
        self.assertNotIn("undo_history_index", session)
        undo = load_json(os.path.join(self.cdir, "undo.json"))
        self.assertEqual(len(undo["history"]), 1)
        self.assertEqual(undo["index"], 0)

    def test_existing_settings_skips_and_keeps_legacy(self):  # LMC-02
        os.makedirs(self.cdir)
        with open(os.path.join(self.cdir, "settings.json"), "w",
                  encoding="utf-8") as fh:
            json.dump({"chrome": {"port": 1111}}, fh)
        self._write_legacy({"chrome": {"port": 2222}})
        with open(self.legacy, "rb") as fh:
            before = fh.read()
        res = migrate_legacy_config(self.legacy, self.cdir)
        self.assertFalse(res["migrated"])
        self.assertIsNone(res["archived"])
        with open(self.legacy, "rb") as fh:
            self.assertEqual(fh.read(), before)
        self.assertEqual(load_json(os.path.join(self.cdir, "settings.json"))
                         ["chrome"]["port"], 1111)

    def test_corrupt_legacy_is_kept(self):  # LMC-03
        with open(self.legacy, "w", encoding="utf-8") as fh:
            fh.write("{not json")
        res = migrate_legacy_config(self.legacy, self.cdir)
        self.assertFalse(res["migrated"])
        self.assertTrue(os.path.exists(self.legacy))
        self.assertFalse(os.path.exists(self.cdir))

    def test_missing_legacy_writes_nothing(self):  # LMC-04
        res = migrate_legacy_config(self.legacy, self.cdir)
        self.assertFalse(res["migrated"])
        self.assertFalse(os.path.exists(self.cdir))

    def test_hostile_shapes_fall_back_to_defaults(self):  # LMC-05
        self._write_legacy({
            "url_presets": {"not": "a list"},
            "custom_blocks": "nope",
            "stack_presets": ["nope"],
            "template_presets": 5,
            "labels": ["nope"],
            "state": ["nope"],
        })
        res = migrate_legacy_config(self.legacy, self.cdir)
        self.assertTrue(res["migrated"])
        self.assertEqual(load_json(os.path.join(self.cdir, "bookmarks.json")),
                         list(DEFAULT_BOOKMARKS))
        self.assertEqual(load_json(os.path.join(self.cdir, "blocks.json")), [])
        presets = load_json(os.path.join(self.cdir, "presets.json"))
        self.assertEqual(presets, {"stack_presets": {}, "template_presets": {}})
        labels = load_json(os.path.join(self.cdir, "labels.json"))
        self.assertEqual((labels["defs"], labels["assign"], labels["next_id"]),
                         ([], {}, 0))
        self.assertEqual(load_json(os.path.join(self.cdir, "session.json")), {})
        undo = load_json(os.path.join(self.cdir, "undo.json"))
        self.assertEqual((undo["history"], undo["index"]), ([], -1))

    def test_missing_undo_keys_default_to_fresh(self):  # LMC-06
        self._write_legacy({"state": {"grid_layout": "x"}})
        migrate_legacy_config(self.legacy, self.cdir)
        undo = load_json(os.path.join(self.cdir, "undo.json"))
        self.assertEqual((undo["history"], undo["index"]), ([], -1))
        session = load_json(os.path.join(self.cdir, "session.json"))
        self.assertEqual(session, {"grid_layout": "x"})

    def test_non_dict_json_migrates_defaults(self):  # LMC-07
        with open(self.legacy, "w", encoding="utf-8") as fh:
            fh.write("[1, 2]")
        res = migrate_legacy_config(self.legacy, self.cdir)
        self.assertTrue(res["migrated"])
        self.assertEqual(load_json(os.path.join(self.cdir, "settings.json")), {})
        self.assertFalse(os.path.exists(self.legacy))

    def test_return_shape(self):  # LMC-08
        res = migrate_legacy_config(self.legacy, self.cdir)
        self.assertEqual(set(res), {"migrated", "archived"})


class StoreCase(unittest.TestCase):
    fname = "store.json"

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, self.fname)


# ── bookmarks ────────────────────────────────────────────────────
class TestBookmarkSplit(StoreCase):
    fname = "bookmarks.json"

    def test_fresh_reads_default_without_creating_a_file(self):  # BKS-01
        store = BookmarkStore(self.path)
        self.assertEqual(store.all(), list(DEFAULT_BOOKMARKS))
        self.assertFalse(os.path.exists(self.path))

    def test_add_refusal_rules(self):  # BKS-02
        store = BookmarkStore(self.path)
        self.assertTrue(store.add("https://a.example/"))
        self.assertFalse(store.add("https://a.example/"))
        self.assertFalse(store.add(""))
        self.assertFalse(store.add("   "))
        with self.assertRaises(TypeError):
            store.add(None)

    def test_remove_refusal_rules(self):  # BKS-03
        store = BookmarkStore(self.path)
        store.add("https://a.example/")
        self.assertTrue(store.remove("https://a.example/"))
        self.assertFalse(store.remove("https://a.example/"))
        with self.assertRaises(TypeError):
            store.remove(None)

    def test_set_all_round_trip_and_loud_refusal(self):  # BKS-04
        store = BookmarkStore(self.path)
        self.assertTrue(store.set_all(["https://1.example/"]))
        self.assertEqual(store.all(), ["https://1.example/"])
        with self.assertRaises(TypeError):
            store.set_all("https://2.example/")
        self.assertEqual(store.all(), ["https://1.example/"])

    def test_load_save_and_corrupt_tolerance(self):  # BKS-05
        store = BookmarkStore(self.path)
        store.set_all(["https://1.example/"])
        self.assertTrue(store.save().is_ok)
        store.load()
        self.assertEqual(store.all(), ["https://1.example/"])
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write("nope{{{")
        store.load()
        self.assertEqual(store.all(), list(DEFAULT_BOOKMARKS))

    def test_file_is_a_bare_list(self):  # BKS-06
        BookmarkStore(self.path).set_all(["https://1.example/"])
        with open(self.path, encoding="utf-8") as fh:
            self.assertEqual(json.load(fh), ["https://1.example/"])


# ── blocks ───────────────────────────────────────────────────────
class TestBlockSplit(StoreCase):
    fname = "blocks.json"

    def test_save_overwrite_and_refusals(self):  # BLS-01
        store = BlockStore(self.path)
        self.assertTrue(store.save_block("b1", {"k": 1}))
        self.assertTrue(store.save_block("b1", {"k": 2}))
        self.assertEqual(len(store.all()), 1)
        self.assertEqual(store.all()[0]["block"], {"k": 2})
        with self.assertRaises(TypeError):
            store.save_block("b", ["not", "a", "dict"])
        with self.assertRaises(TypeError):
            store.save_block(None, {"k": 1})
        self.assertFalse(store.save_block("  ", {"k": 1}))

    def test_delete_is_strip_symmetric(self):  # BLS-02
        store = BlockStore(self.path)
        store.save_block("padded", {"k": 1})
        self.assertTrue(store.delete("  padded\t"))
        self.assertFalse(store.delete("padded"))

    def test_set_all_and_loud_refusal(self):  # BLS-03
        store = BlockStore(self.path)
        rows = [{"name": "a", "block": {"x": 1}, "updated_at": "t"}]
        self.assertTrue(store.set_all(rows))
        self.assertEqual(store.all(), rows)
        with self.assertRaises(TypeError):
            store.set_all({"name": "a"})
        self.assertEqual(store.all(), rows)

    def test_all_is_a_deep_copy(self):  # BLS-04
        store = BlockStore(self.path)
        store.save_block("b1", {"deep": [1]})
        store.all()[0]["block"]["deep"].append(2)
        self.assertEqual(store.all()[0]["block"], {"deep": [1]})

    def test_file_is_a_bare_list(self):  # BLS-05
        BlockStore(self.path).save_block("b1", {"k": 1})
        with open(self.path, encoding="utf-8") as fh:
            rows = json.load(fh)
        self.assertIsInstance(rows, list)
        self.assertEqual(rows[0]["name"], "b1")

    def test_corrupt_file_reads_empty(self):  # BLS-06
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write("[broken")
        self.assertEqual(BlockStore(self.path).all(), [])

    def test_named_api_is_gone(self):  # BLS-07
        store = BlockStore(self.path)
        self.assertFalse(hasattr(store, "named_set"))
        self.assertFalse(hasattr(store, "named_get"))
        self.assertFalse(hasattr(store, "named_delete"))
        self.assertFalse(hasattr(store, "named_all"))


# ── session ──────────────────────────────────────────────────────
class TestSessionSplit(StoreCase):
    fname = "session.json"

    def test_save_now_false_then_explicit_save(self):  # SES-08
        store = SessionStore(self.path)
        store.set(save_now=False, temp=1)
        self.assertIsNone(SessionStore(self.path).get("temp"))
        self.assertTrue(store.save().is_ok)
        self.assertEqual(SessionStore(self.path).get("temp"), 1)

    def test_load_tolerates_hostile_files(self):  # SES-09
        store = SessionStore(self.path)
        store.set(a=1)
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write("{\"a\": [TRUNCATED")
        store.load()
        self.assertIsNone(store.get("a"))
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write("[1, 2]")
        store.load()
        self.assertEqual(store.data(), {})
        os.remove(self.path)
        os.mkdir(self.path)
        try:
            store.load()
            self.assertEqual(store.data(), {})
        finally:
            os.rmdir(self.path)

    def test_file_is_flat(self):  # SES-10
        SessionStore(self.path).set(grid_layout="x")
        with open(self.path, encoding="utf-8") as fh:
            self.assertEqual(json.load(fh), {"grid_layout": "x"})


# ── settings ─────────────────────────────────────────────────────
class TestSettingsSplit(StoreCase):
    fname = "settings.json"

    def test_set_returns_none_and_round_trips(self):  # SET-09
        store = SettingsStore(self.path)
        self.assertIsNone(store.set("ui", "theme", "light"))
        self.assertTrue(store.save().is_ok)
        store.load()
        self.assertEqual(store.get("ui", "theme"), "light")
        self.assertEqual(SettingsStore(self.path).get("ui", "theme"), "light")

    def test_hostile_file_serves_defaults(self):  # SET-10
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write("[1, 2]")
        store = SettingsStore(self.path)
        self.assertEqual(store.data(), {})
        self.assertEqual(store.get("chrome", "port"), 9222)

    def test_empty_set_is_loud(self):  # SET-11
        store = SettingsStore(self.path)
        with self.assertRaises(ValueError):
            store.set()
        with self.assertRaises(ValueError):
            store.set("lonely-key")

    def test_deep_set_repairs_a_clobbered_section(self):  # SET-12
        store = SettingsStore(self.path)
        store.set("history", "enabled")  # malformed: section becomes a scalar
        store.set("history", "media", "cache_dir", "fixed")  # must not raise
        self.assertEqual(store.get("history", "media", "cache_dir"), "fixed")


# ── undo ─────────────────────────────────────────────────────────
class TestUndoSplit(StoreCase):
    fname = "undo.json"

    def test_history_and_index_views(self):  # UND-08
        store = UndoStore(self.path)
        self.assertEqual((store.history(), store.index()), ([], -1))
        store.set([{"k": 1}], 0)
        self.assertEqual((store.history(), store.index()), ([{"k": 1}], 0))
        store.history().append({"k": 2})
        self.assertEqual(len(store.history()), 1)

    def test_save_state_save_now_false(self):  # UND-09
        store = UndoStore(self.path)
        store.save_state([{"k": 1}], 0, save_now=False)
        self.assertEqual(store.get(), ([{"k": 1}], 0))
        self.assertFalse(os.path.exists(self.path))
        self.assertTrue(store.flush().is_ok)
        self.assertEqual(UndoStore(self.path).get(), ([{"k": 1}], 0))

    def test_load_state_is_get(self):  # UND-10
        store = UndoStore(self.path)
        store.set([{"k": 1}], 0)
        self.assertEqual(store.load_state(), store.get())

    def test_reload_and_flush(self):  # UND-11
        store = UndoStore(self.path)
        store.set([{"k": 1}], 0)
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write("nope{{{")
        store.reload()
        self.assertEqual(store.get(), ([], -1))
        self.assertTrue(store.flush().is_ok)

    def test_file_shape(self):  # UND-12
        UndoStore(self.path).set([{"k": 1}], 0)
        with open(self.path, encoding="utf-8") as fh:
            self.assertEqual(json.load(fh), {"history": [{"k": 1}], "index": 0})

    def test_load_normalizes_a_wild_file(self):  # UND-13
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump({"history": [{"k": 1}, {"k": 2}], "index": 99}, fh)
        self.assertEqual(UndoStore(self.path).get(), ([{"k": 1}, {"k": 2}], 1))
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump({"history": "nope", "index": "x"}, fh)
        self.assertEqual(UndoStore(self.path).get(), ([], -1))


if __name__ == "__main__":
    unittest.main()
