"""stores.migration.migrate_legacy_config — split, idempotency, rollback.

The old test file imported ``migrate`` / ``needs_migration``, which do not
exist.  The public API is ``migrate_legacy_config(legacy_path, config_dir)``.

This pins the data-safety contract around the one-time config.json → config/*
split: legacy data is never overwritten or deleted, the split is idempotent,
and the archived legacy file is a real byte-for-byte rollback.
"""

from __future__ import annotations

import glob
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from stores.migration import migrate_legacy_config  # noqa: E402
from stores.jsonio import load_json  # noqa: E402


def legacy_payload():
    return {
        "chrome": {"host": "1.2.3.4", "port": 9333},
        "collector": {"my_nick": "Tester"},
        "url_presets": ["https://x.example"],
        "custom_blocks": [{"name": "b", "block": {"block_id": "CUSTOM_FIND"}}],
        "stack_presets": {"run1": {"blocks": [{"block_id": "PAUSE"}]}},
        "template_presets": {"hi": {"body": "hello"}},
        "labels": {"defs": [{"id": "lbl_1", "name": "Rude",
                             "color": "#ff3b30"}],
                   "assign": {"Ann": ["lbl_1"]}},
        "state": {"last_url_preset": "https://x.example",
                  "undo_history": [{"kind": "stack", "value": [], "seq": 1}],
                  "undo_history_index": 0,
                  "grid_layout": '{"v":3}'},
    }


class MigCase(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.legacy = os.path.join(self.dir, "config.json")
        self.config_dir = os.path.join(self.dir, "config")

    def write_legacy(self, data):
        with open(self.legacy, "w", encoding="utf-8") as fh:
            json.dump(data, fh)

    def backups(self):
        return sorted(glob.glob(self.legacy + ".migrated-*"))

    def store_files(self):
        return sorted(
            os.path.join(self.config_dir, name)
            for name in ("settings.json", "presets.json", "bookmarks.json",
                         "blocks.json", "labels.json", "session.json",
                         "undo.json"))


class TestMigrateLegacyConfig(MigCase):
    def test_missing_legacy_returns_false_and_writes_nothing(self):
        self.assertFalse(migrate_legacy_config(self.legacy, self.config_dir))
        self.assertEqual(glob.glob(self.legacy), [])
        self.assertEqual(glob.glob(os.path.join(self.config_dir, "*")), [])

    def test_legacy_only_is_split_and_archived(self):
        self.write_legacy(legacy_payload())
        self.assertTrue(migrate_legacy_config(self.legacy, self.config_dir))
        self.assertFalse(os.path.exists(self.legacy))
        archives = self.backups()
        self.assertEqual(len(archives), 1)
        for path in self.store_files():
            self.assertTrue(os.path.exists(path), f"missing {path}")

    def test_second_migrate_is_a_noop(self):
        self.write_legacy(legacy_payload())
        migrate_legacy_config(self.legacy, self.config_dir)
        # The legacy is gone; re-writing it must NOT overwrite the split files.
        self.write_legacy({"chrome": {"port": 1}})
        self.assertFalse(migrate_legacy_config(self.legacy, self.config_dir))
        self.assertEqual(load_json(os.path.join(self.config_dir,
                                                "settings.json"))["chrome"],
                         {"host": "1.2.3.4", "port": 9333})

    def test_existing_store_files_are_not_overwritten(self):
        settings = os.path.join(self.config_dir, "settings.json")
        os.makedirs(self.config_dir, exist_ok=True)
        with open(settings, "w", encoding="utf-8") as fh:
            json.dump({"chrome": {"host": "mine", "port": 1111}}, fh)
        self.write_legacy(legacy_payload())
        self.assertFalse(migrate_legacy_config(self.legacy, self.config_dir))
        self.assertEqual(load_json(settings),
                         {"chrome": {"host": "mine", "port": 1111}})
        # Original legacy kept for manual recovery.
        self.assertTrue(os.path.exists(self.legacy))

    def test_corrupt_legacy_is_a_clean_failure(self):
        with open(self.legacy, "w", encoding="utf-8") as fh:
            fh.write("{oops")
        self.assertFalse(migrate_legacy_config(self.legacy, self.config_dir))
        self.assertTrue(os.path.exists(self.legacy))
        self.assertEqual(self.backups(), [])
        self.assertEqual(glob.glob(os.path.join(self.config_dir, "*")), [])

    def test_non_dict_legacy_is_a_clean_failure(self):
        with open(self.legacy, "w", encoding="utf-8") as fh:
            json.dump(["not", "an", "object"], fh)
        self.assertFalse(migrate_legacy_config(self.legacy, self.config_dir))
        self.assertTrue(os.path.exists(self.legacy))
        self.assertEqual(glob.glob(os.path.join(self.config_dir, "*")), [])

    def test_archived_legacy_is_a_real_rollback(self):
        legacy_bytes = json.dumps(legacy_payload(), indent=2,
                                  ensure_ascii=False).encode("utf-8")
        with open(self.legacy, "wb") as fh:
            fh.write(legacy_bytes)
        migrate_legacy_config(self.legacy, self.config_dir)
        archived = self.backups()[0]
        with open(archived, "rb") as fh:
            self.assertEqual(fh.read(), legacy_bytes)


class TestMigrateContentFidelity(MigCase):
    def test_every_section_lands_in_its_own_file(self):
        self.write_legacy(legacy_payload())
        migrate_legacy_config(self.legacy, self.config_dir)

        settings = load_json(os.path.join(self.config_dir, "settings.json"))
        self.assertEqual(settings["chrome"], {"host": "1.2.3.4", "port": 9333})
        self.assertEqual(settings["collector"], {"my_nick": "Tester"})

        self.assertEqual(load_json(os.path.join(self.config_dir,
                                                "bookmarks.json")),
                         ["https://x.example"])
        self.assertEqual(load_json(os.path.join(self.config_dir,
                                                "blocks.json"))[0]["name"], "b")
        presets = load_json(os.path.join(self.config_dir, "presets.json"))
        self.assertIn("run1", presets["stack_presets"])
        self.assertIn("hi", presets["template_presets"])
        self.assertEqual(load_json(os.path.join(self.config_dir,
                                                "labels.json"))["assign"],
                         {"Ann": ["lbl_1"]})
        session = load_json(os.path.join(self.config_dir, "session.json"))
        self.assertEqual(session["last_url_preset"], "https://x.example")
        self.assertEqual(session["grid_layout"], '{"v":3}')
        self.assertNotIn("undo_history", session)
        undo = load_json(os.path.join(self.config_dir, "undo.json"))
        self.assertEqual(len(undo["history"]), 1)
        self.assertEqual(undo["index"], 0)


if __name__ == "__main__":
    unittest.main()
