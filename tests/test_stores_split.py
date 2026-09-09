"""Tests for the config split (stores/ package + ConfigManager facade).

The seven files are independent: a failed save in one must never corrupt
another; every save is atomic; a legacy single-file config.json is
migrated exactly once and archived, never deleted.

Run:  python -m pytest tests/test_stores_split.py
"""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.config_manager import ConfigManager, DEFAULTS, MAX_STACK_HISTORY
from stores.jsonio import load_json, save_json, config_dir_for
from stores.migration import migrate_legacy_config
from stores.settings_store import SettingsStore
from stores.bookmark_store import BookmarkStore
from stores.block_store import BlockStore
from stores.session_store import SessionStore
from stores.undo_store import UndoStore
from stores.labels_file_store import LabelsFileStore
from stores.preset_store import PresetStore
from stores.label_store import LabelStore


def legacy_payload() -> dict:
    """A representative pre-split config.json."""
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
        with open(self.legacy, "w", encoding="utf-8") as fh:
            json.dump(legacy_payload(), fh)
        self.cfg = ConfigManager(self.legacy)

    def test_legacy_file_is_archived_not_deleted(self):
        archived = [f for f in os.listdir(self.dir)
                    if f.startswith("config.json.migrated-")]
        self.assertTrue(archived, "the original must be renamed, not gone")
        self.assertFalse(os.path.exists(self.legacy))

    def test_every_section_lands_in_its_own_file(self):
        cdir = os.path.join(self.dir, "config")
        settings = load_json(os.path.join(cdir, "settings.json"))
        self.assertEqual(settings["chrome"]["port"], 9333)
        self.assertEqual(load_json(os.path.join(cdir, "bookmarks.json")),
                         ["https://x.example", "https://y.example"])
        blocks = load_json(os.path.join(cdir, "blocks.json"))
        self.assertEqual(blocks[0]["name"], "Tab Main")
        presets = load_json(os.path.join(cdir, "presets.json"))
        self.assertIn("run1", presets["stack_presets"])
        self.assertIn("hi", presets["template_presets"])
        labels = load_json(os.path.join(cdir, "labels.json"))
        self.assertEqual(labels["assign"], {"Ann": ["lbl_1"]})
        session = load_json(os.path.join(cdir, "session.json"))
        self.assertEqual(session["last_url_preset"], "https://x.example")
        self.assertNotIn("undo_history", session)
        undo = load_json(os.path.join(cdir, "undo.json"))
        self.assertEqual(len(undo["history"]), 1)
        self.assertEqual(undo["index"], 0)

    def test_facade_reads_after_migration(self):
        self.assertEqual(self.cfg.get("chrome", "port"), 9333)
        self.assertEqual(self.cfg.get_state("grid_layout"), "{\"v\":3}")
        self.assertEqual(self.cfg.get_state("undo_history_index"), 0)
        self.assertEqual(self.cfg.named_all("stack_presets").keys(),
                         {"run1"})

    def test_migration_is_idempotent(self):
        # second construction: files exist → nothing re-imported
        with open(self.legacy, "w", encoding="utf-8") as fh:
            json.dump({"chrome": {"port": 1}}, fh)      # a DIFFERENT legacy
        again = ConfigManager(self.legacy)
        self.assertEqual(again.get("chrome", "port"), 9333)  # stores win
        # the stray legacy file is untouched (no data loss)

    def test_unreadable_legacy_starts_fresh(self):
        dir2 = tempfile.mkdtemp()
        bad = os.path.join(dir2, "config.json")
        with open(bad, "w", encoding="utf-8") as fh:
            fh.write("{not json")
        cfg = ConfigManager(bad)
        self.assertEqual(cfg.get("chrome", "port"), 9222)  # defaults
        self.assertTrue(os.path.exists(bad))               # kept for repair


class FacadeCase(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.cfg = ConfigManager(os.path.join(self.dir, "config.json"))

    def test_round_trip_through_reopen(self):
        self.cfg.set("chrome", {"port": 7777})
        self.cfg.set_state(last_stack=[{"block_id": "PAUSE"}])
        self.cfg.save()
        reopened = ConfigManager(self.cfg._path)
        self.assertEqual(reopened.get("chrome", "port"), 7777)
        self.assertEqual(reopened.get_state("last_stack"),
                         [{"block_id": "PAUSE"}])

    def test_undo_and_session_are_separate_files(self):
        self.cfg.set_state(undo_history=[{"kind": "grid", "value": "x",
                                          "seq": 1}],
                           undo_history_index=0,
                           grid_layout="x", block_config_pinned=True)
        cdir = os.path.join(self.dir, "config")
        undo = load_json(os.path.join(cdir, "undo.json"))
        session = load_json(os.path.join(cdir, "session.json"))
        self.assertEqual(undo["history"][0]["kind"], "grid")
        self.assertNotIn("grid_layout", undo)
        self.assertEqual(session["grid_layout"], "x")
        self.assertTrue(session["block_config_pinned"])

    def test_a_failed_undo_save_leaves_presets_intact(self):
        self.cfg.presets.save_stack("mine", [])
        self.cfg.save()
        # sabotage the undo store's file target
        self.cfg.undo._path = os.path.join(self.dir, "no", "such",
                                           "dir", "undo.json")
        self.cfg.undo.save_state([{"kind": "stack", "value": [],
                                   "seq": 1}], 0, save_now=True)
        reopened = ConfigManager(self.cfg._path)
        self.assertTrue(reopened.named_all("stack_presets"))  # untouched

    def test_named_preset_crud(self):
        self.cfg.named_set("stack_presets", "p1", {"blocks": [1]})
        self.assertEqual(self.cfg.named_get("stack_presets", "p1"),
                         {"blocks": [1]})
        self.assertTrue(self.cfg.named_delete("stack_presets", "p1"))
        self.assertFalse(self.cfg.named_delete("stack_presets", "p1"))

    def test_state_defaults_fall_back(self):
        self.assertEqual(self.cfg.get_state("undo_history"), [])
        self.assertEqual(self.cfg.get_state("grid_layout_history"), [])
        self.assertIsNone(self.cfg.get_state("no_such_key", None))

    def test_preset_store_is_cached_per_path(self):
        from stores.preset_store import PresetStore as PS
        a = PS(config=self.cfg)
        b = PS(config=self.cfg)
        self.assertIs(a, b, "two writers must share one instance")

    def test_get_copy_is_deep(self):
        self.cfg.set("chrome", {"port": 1})
        got = self.cfg.get_copy("chrome")
        got["port"] = 2
        self.assertEqual(self.cfg.get("chrome", "port"), 1)

    def test_bookmarks_dedup(self):
        # a fresh install seeds the default bookmarks (as the old
        # config.json DEFAULTS did) — adding a new one appends, duplicates
        # are refused
        seeded = len(self.cfg.bookmarks.all())
        self.assertTrue(self.cfg.bookmarks.add("https://a"))
        self.assertFalse(self.cfg.bookmarks.add("https://a"))
        self.assertEqual(len(self.cfg.bookmarks.all()), seeded + 1)
        self.assertIn("https://a", self.cfg.bookmarks.all())
        self.assertTrue(self.cfg.bookmarks.remove("https://a"))
        self.assertEqual(len(self.cfg.bookmarks.all()), seeded)

    def test_defaults_when_no_files_exist(self):
        fresh = ConfigManager(os.path.join(tempfile.mkdtemp(),
                                           "config.json"))
        self.assertEqual(fresh.get("chrome", "port"), 9222)
        self.assertEqual(fresh.get("url_presets", default=[]),
                         DEFAULTS["url_presets"])
        self.assertEqual(fresh.get("labels", default={})["next_id"], 0)

    def test_label_store_legacy_mode_writes_labels_file(self):
        store = LabelStore(self.cfg)          # no db → legacy config mode
        made = store.create("Nice", "#00ff7f")
        self.assertTrue(made)
        reopened = ConfigManager(self.cfg._path)
        defs = reopened.get("labels", default={}).get("defs")
        self.assertEqual(defs[0]["name"], "Nice")

    def test_max_stack_history_constant(self):
        self.assertEqual(MAX_STACK_HISTORY, 100)


class AtomicityCase(unittest.TestCase):
    def test_save_json_is_replace_not_truncate(self):
        dirp = tempfile.mkdtemp()
        path = os.path.join(dirp, "x.json")
        save_json(path, {"a": 1})
        save_json(path, {"a": 2})
        self.assertEqual(load_json(path), {"a": 2})
        self.assertFalse(os.path.exists(path + ".tmp"))

    def test_config_dir_for(self):
        self.assertEqual(
            config_dir_for(os.path.join("t", "config.json")),
            os.path.join(os.path.abspath("t"), "config"))


if __name__ == "__main__":
    unittest.main()
