"""stores/preset_store — CRUD, dirty/force semantics, legacy import.

Design refs: docs/archive/2026-09-09-test-suite/BACKEND_TESTS_DESIGN_2026-09-09.md §PS#1–3.

test_stores_split covers the migration machinery. This file pins the
store contract itself: stacks and templates round-trip, overwrite in
place, persist across instances (the per-path cache must not become a
stale-memory trap), and the legacy SQLite import runs at most once.

Run with:  python3 tests/test_preset_store_unit.py
"""

import os
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from stores.preset_store import PresetStore  # noqa: E402


class PresetCase(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        # unique path per test: the store is cached per path globally
        self.path = os.path.join(self.dir, "presets.json")
        self.store = PresetStore(path=self.path)

    def tearDown(self):
        PresetStore._by_path.pop(os.path.abspath(self.path), None)

    def reopen(self) -> PresetStore:
        """A NEW instance over the same file (what a restart sees).

        The per-path instance cache must be dropped first — otherwise
        the "new" store is the same live object and the test proves
        nothing about the file."""
        PresetStore._by_path.pop(os.path.abspath(self.path), None)
        return PresetStore(path=self.path)


class TestStackCrud(PresetCase):

    def test_save_load_delete_round_trip(self):
        blocks = [{"block_id": "TYPE_MESSAGE", "text": "привет"},
                  {"block_id": "PAUSE"}]
        self.store.save_stack("run1", blocks)
        self.assertEqual(self.store.load_stack("run1"), blocks)
        self.assertEqual([s["name"] for s in self.store.list_stacks()],
                         ["run1"])
        self.assertTrue(self.store.delete_stack("run1"))
        self.assertIsNone(self.store.load_stack("run1"))
        self.assertFalse(self.store.delete_stack("run1"),
                         "deleting twice must report False")
        self.assertEqual(self.store.list_stacks(), [])

    def test_overwrite_is_in_place(self):
        self.store.save_stack("p", [{"block_id": "A"}])
        self.store.save_stack("p", [{"block_id": "B"}])
        self.assertEqual(len(self.store.list_stacks()), 1)
        self.assertEqual(self.store.load_stack("p"),
                         [{"block_id": "B"}])

    def test_blocks_survive_a_reopen(self):
        self.store.save_stack("run", [{"block_id": "TYPE_MESSAGE",
                                       "text": "привет 👋"}])
        self.store.save()
        fresh = self.reopen()
        self.assertEqual(fresh.load_stack("run"),
                         [{"block_id": "TYPE_MESSAGE", "text": "привет 👋"}])

    def test_load_of_an_unknown_name_is_none(self):
        self.assertIsNone(self.store.load_stack("ghost"))
        self.assertIsNone(self.store.load_template("ghost"))


class TestTemplates(PresetCase):

    def test_template_round_trip_and_overwrite(self):
        self.store.save_template("hi", "Hello!")
        self.assertEqual(self.store.load_template("hi"), "Hello!")
        self.store.save_template("hi", "Changed")
        self.assertEqual(self.store.load_template("hi"), "Changed")
        self.assertTrue(self.store.delete_template("hi"))
        self.assertIsNone(self.store.load_template("hi"))


class TestDirtyAndForce(PresetCase):

    def test_mutations_mark_dirty_and_save_clears_it(self):
        self.assertFalse(self.store.dirty)
        self.store.save_stack("p", [])
        self.assertTrue(self.store.dirty)
        self.assertTrue(self.store.save())
        self.assertFalse(self.store.dirty)
        # an untouched store saves without touching the file
        mtime = os.path.getmtime(self.path)
        self.reopen().save()
        self.assertEqual(os.path.getmtime(self.path), mtime,
                         "a clean save() must not rewrite the file")

    def test_save_without_save_stays_in_memory_only(self):
        self.store.save_stack("volatile", [])
        fresh = self.reopen()
        self.assertIsNone(fresh.load_stack("volatile"),
                          "an unsaved preset must not be on disk")
        self.store.save()
        self.assertIsNotNone(self.reopen().load_stack("volatile"))

    def test_force_save_writes_even_when_clean(self):
        self.store.save_stack("p", [])
        self.store.save()
        self.store.load()                     # clean again
        self.store._data["stack_presets"]["forced"] = {"blocks": []}
        self.assertTrue(self.store.save(force=True))


class TestLegacyImport(PresetCase):

    def test_import_runs_once_and_preserves_both_sources(self):
        legacy = os.path.join(self.dir, "chatbot.db")
        conn = sqlite3.connect(legacy)
        # the legacy schema: `stacks(name, blocks)` + `templates(name, body)`
        conn.execute("CREATE TABLE stacks (name TEXT PRIMARY KEY, blocks TEXT)")
        conn.execute("INSERT INTO stacks VALUES (?, ?)",
                     ("old", '[{"block_id": "PAUSE"}]'))
        conn.execute("INSERT INTO stacks VALUES (?, ?)", ("bad", "not-json"))
        conn.execute("CREATE TABLE templates (name TEXT PRIMARY KEY, body TEXT)")
        conn.execute("INSERT INTO templates VALUES (?, ?)", ("greet", "hi"))
        conn.commit()
        conn.close()

        # a store with current data refuses to import at all
        self.store.save_stack("fresh", [])
        self.assertFalse(self.store.import_legacy(legacy),
                         "an import into a non-empty store would clobber")
        # an EMPTY store imports the legacy rows once
        fresh_empty = self.reopen()
        self.assertTrue(fresh_empty.import_legacy(legacy))
        self.assertEqual(fresh_empty.load_stack("old"),
                         [{"block_id": "PAUSE"}])
        self.assertIsNone(fresh_empty.load_stack("bad"),
                          "an unparseable legacy row must be skipped")
        self.assertEqual(fresh_empty.load_template("greet"), "hi")
        # second run: no-op (the store is no longer empty)
        self.assertFalse(fresh_empty.import_legacy(legacy))
        self.assertEqual(fresh_empty.load_stack("old"),
                         [{"block_id": "PAUSE"}])

    def test_import_without_a_legacy_file_is_a_clean_false(self):
        self.assertFalse(self.store.import_legacy(
            os.path.join(self.dir, "ghost.db")))


if __name__ == "__main__":
    unittest.main(verbosity=2)
