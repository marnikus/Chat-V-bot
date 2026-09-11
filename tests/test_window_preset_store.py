"""Atomic persistence for named window presets."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from stores.atomic import AtomicJsonStore  # noqa: E402
from stores.window_preset_store import WindowPresetStore  # noqa: E402


class TestWindowPresetStore(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.directory.name, "window_presets.json")
        WindowPresetStore._by_path.pop(os.path.abspath(self.path), None)
        self.store = WindowPresetStore(path=self.path)

    def tearDown(self):
        WindowPresetStore._by_path.pop(os.path.abspath(self.path), None)
        self.directory.cleanup()

    def test_named_document_survives_reopen_and_lists_metadata(self):
        document = {"name": "Desk", "updated_at": "2026-09-10T12:00:00",
                    "grid": {"window_count": 12}}
        self.store.save_preset("Desk", document)
        self.assertTrue(self.store.save(force=True))

        WindowPresetStore._by_path.pop(os.path.abspath(self.path), None)
        reopened = WindowPresetStore(path=self.path)
        self.assertEqual(reopened.load_preset("Desk"), document)
        self.assertEqual(reopened.list_presets()[0]["name"], "Desk")
        self.assertEqual(reopened.list_presets()[0]["window_count"], 12)

    def test_delete_and_missing_are_explicit(self):
        self.assertIsNone(self.store.load_preset("ghost"))
        self.assertFalse(self.store.delete_preset("ghost"))
        self.store.save_preset("Desk", {"name": "Desk"})
        self.assertTrue(self.store.delete_preset("Desk"))
        self.assertTrue(self.store.dirty)
        self.assertEqual(self.store.list_presets(), [])

    def test_store_keeps_invalid_raw_shape_out_of_the_projection(self):
        self.store._data = {"window_presets": {"bad": "not a document"}}
        self.assertEqual(self.store.list_presets(), [])
        self.assertIsNone(self.store.load_preset("bad"))

    def test_store_like_atomic_input_writes_through_atomically(self):
        WindowPresetStore._by_path.pop(os.path.abspath(self.path), None)
        atomic = AtomicJsonStore(self.path)
        store = WindowPresetStore(atomic)
        store.save_preset("Desk", {"name": "Desk"})
        self.assertTrue(store.save(force=True))
        self.assertEqual(atomic.load()["window_presets"]["Desk"]["name"], "Desk")

    def test_config_path_forms_and_cached_instances_are_supported(self):
        config_path = os.path.join(self.directory.name, "legacy.json")
        config = SimpleNamespace(_path=config_path)
        derived = os.path.join(self.directory.name, "config",
                               "window_presets.json")
        WindowPresetStore._by_path.pop(os.path.abspath(derived), None)
        from_config = WindowPresetStore(config=config)
        self.assertEqual(from_config.path, os.path.abspath(derived))
        self.assertIs(from_config, WindowPresetStore(config=config))

        path_config = SimpleNamespace(path=self.path)
        WindowPresetStore._by_path.pop(os.path.abspath(self.path), None)
        from_path = WindowPresetStore(config=path_config)
        self.assertEqual(from_path.path, os.path.abspath(self.path))
        self.assertEqual(from_path._coerce("bad"), {"window_presets": {}})

        string_path = os.path.join(self.directory.name, "string.json")
        WindowPresetStore._by_path.pop(os.path.abspath(string_path), None)
        from_string = WindowPresetStore(config=string_path)
        self.assertEqual(from_string.path, os.path.abspath(string_path))


if __name__ == "__main__":
    unittest.main(verbosity=2)
