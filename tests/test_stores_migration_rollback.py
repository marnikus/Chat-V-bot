"""stores/migration — migrate, dry-run, idempotency, rollback.

Design refs: docs/STORES_TEST_DESIGN_2026-09-09.md §16 (MIG-01–12).

The happy path (backup created, legacy archived, idempotent) is pinned by
test_stores_migration.py / test_stores_split.py. This file pins the edges a
buggy updater would turn into lost user data: dry-run purity, partial
layouts that must not be overwritten, corrupt/missing legacy files, and —
the one the design target names explicitly — that the backup is a REAL
rollback, byte for byte.

Run with:  python3 tests/test_stores_migration_rollback.py
"""

import glob
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from stores.migration import migrate, needs_migration  # noqa: E402


class MigCase(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "config.json")

    def backups(self):
        return sorted(glob.glob(self.path + ".bak.*"))

    def write_legacy(self, data):
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump(data, fh)


class TestNeedsMigration(MigCase):
    def test_missing_file_needs_creation(self):  # MIG-01 (SPEC pin)
        # A fresh dir "needs migration": migrate() creates the defaults
        # file (documented in migrate(): "new installs start clean").
        self.assertTrue(needs_migration(self.path))

    def test_legacy_only_needs_migration(self):  # MIG-02
        self.write_legacy({"chrome": {"host": "x"}})
        self.assertTrue(needs_migration(self.path))

    def test_completed_migration_needs_nothing(self):  # MIG-03
        self.write_legacy({"chrome": {"host": "x"}})
        migrate(self.path)
        self.assertFalse(needs_migration(self.path))


class TestMigrate(MigCase):
    def test_dry_run_changes_nothing_on_disk(self):  # MIG-04
        self.write_legacy({"chrome": {"host": "x"}})
        with open(self.path, "rb") as fh:
            before = fh.read()
        res = migrate(self.path, dry_run=True)
        self.assertTrue(res["migrated"])
        self.assertIsNone(res["backup"])
        self.assertTrue(res["added"])
        with open(self.path, "rb") as fh:
            self.assertEqual(fh.read(), before)
        self.assertEqual(self.backups(), [])

    def test_return_shape(self):  # MIG-05
        self.write_legacy({"chrome": {"host": "x"}})
        res = migrate(self.path)
        self.assertEqual(set(res), {"migrated", "backup", "added"})
        self.assertIs(res["migrated"], True)
        self.assertIsInstance(res["backup"], str)
        self.assertIsInstance(res["added"], list)

    def test_second_migrate_is_a_noop(self):  # MIG-06
        self.write_legacy({"chrome": {"host": "x"}})
        migrate(self.path)
        with open(self.path, "rb") as fh:
            migrated_bytes = fh.read()
        res = migrate(self.path)
        self.assertEqual(res,
                         {"migrated": False, "backup": None, "added": []})
        self.assertEqual(len(self.backups()), 1)
        with open(self.path, "rb") as fh:
            self.assertEqual(fh.read(), migrated_bytes)

    def test_partial_layout_keeps_user_data(self):  # MIG-07
        self.write_legacy({"chrome": {"host": "mine", "port": 1234},
                           "state": {"undo_history": [{"k": 1}],
                                     "undo_history_index": 0,
                                     "grid_layout": "mine"}})
        res = migrate(self.path)
        self.assertTrue(res["migrated"])
        with open(self.path, encoding="utf-8") as fh:
            data = json.load(fh)
        # user values untouched …
        self.assertEqual(data["chrome"], {"host": "mine", "port": 1234})
        self.assertEqual(data["state"]["undo_history"], [{"k": 1}])
        self.assertEqual(data["state"]["grid_layout"], "mine")
        # … missing keys added, and `added` lists exactly those …
        self.assertIn("scroll", data)
        self.assertNotIn("chrome", res["added"])
        self.assertNotIn("state", res["added"])

    def test_corrupt_legacy_is_a_clean_failure(self):  # MIG-08
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write("{oops")
        res = migrate(self.path)
        self.assertFalse(res["migrated"])
        self.assertIsNone(res["backup"])
        self.assertEqual(res["added"], [])
        self.assertEqual(res.get("error"), "invalid json")
        self.assertEqual(self.backups(), [])

    def test_missing_legacy_creates_defaults(self):  # MIG-09 (SPEC pin)
        res = migrate(self.path)
        self.assertTrue(res["migrated"])
        self.assertIsNone(res["backup"])
        self.assertEqual(res["added"], ["fresh_defaults"])
        with open(self.path, encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertIn("chrome", data)

    def test_backup_is_a_real_rollback(self):  # MIG-10
        legacy = {"chrome": {"host": "mine"}}
        self.write_legacy(legacy)
        res = migrate(self.path)
        with open(res["backup"], encoding="utf-8") as fh:
            self.assertEqual(json.load(fh), legacy)
        # restore the backup → the world is pre-migration again
        with open(res["backup"], "rb") as src:
            restored = src.read()
        with open(self.path, "wb") as dst:
            dst.write(restored)
        self.assertTrue(needs_migration(self.path))

    def test_backup_naming(self):  # MIG-11
        self.write_legacy({"chrome": {}})
        res = migrate(self.path)
        base = os.path.basename(res["backup"])
        self.assertTrue(base.startswith("config.json.bak."))
        stamp = base.rsplit(".", 1)[1]
        self.assertEqual(len(stamp), 14)
        self.assertTrue(stamp.isdigit())

    def test_legacy_sections_survive_key_for_key(self):  # MIG-12
        legacy = {"chrome": {"host": "h", "port": 1},
                  "url_presets": ["https://kept.example/"],
                  "custom_blocks": [{"name": "b"}]}
        self.write_legacy(legacy)
        migrate(self.path)
        with open(self.path, encoding="utf-8") as fh:
            data = json.load(fh)
        for key, value in legacy.items():
            self.assertEqual(data[key], value)

    def test_directory_path_is_loud(self):  # MIG-13 (pin)
        with self.assertRaises(OSError):
            migrate(self.dir)


if __name__ == "__main__":
    unittest.main()
