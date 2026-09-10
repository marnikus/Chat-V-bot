"""Portable window-preset document validation and compatibility contract."""

from __future__ import annotations

import copy
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.layout_service import LayoutService  # noqa: E402
from services.window_preset_service import (  # noqa: E402
    APP_VERSION,
    FORMAT,
    SCHEMA_VERSION,
    WindowPresetService,
)


def _bounds():
    return [
        {"id": wid, "title": wid.title(), "state": "open",
         "bounds": {"x": 0.0, "y": 0.0, "width": 0.5, "height": 0.5}}
        for wid in LayoutService.WINDOW_IDS
    ]


def _document():
    return {
        "format": FORMAT,
        "schema_version": SCHEMA_VERSION,
        "app_version": APP_VERSION,
        "name": "Desk",
        "created_at": "2026-09-10T12:00:00",
        "updated_at": "2026-09-10T12:00:00",
        "grid": {
            "type": "sash-tree", "version": LayoutService.GRID_VERSION,
            "window_count": len(LayoutService.WINDOW_IDS),
            "sizes_unit": "percent",
            "tree": LayoutService.default_grid_tree(),
        },
        "windows": _bounds(),
        "window_states": {"closed": [], "minimized": []},
        "screen": {"width": 1400, "height": 900,
                   "device_pixel_ratio": 1},
    }


class TestWindowPresetService(unittest.TestCase):
    def test_valid_document_is_canonical_and_round_trips_from_json(self):
        result, error = WindowPresetService.validate(json.dumps(_document()))
        self.assertIsNone(error)
        self.assertEqual(result["format"], FORMAT)
        self.assertEqual(result["grid"]["type"], "sash-tree")
        self.assertEqual(result["grid"]["window_count"],
                         len(LayoutService.WINDOW_IDS))
        self.assertEqual(result["grid"]["tree"], LayoutService.default_grid_tree())

    def test_malformed_or_future_documents_are_refused(self):
        for raw, fragment in (("{oops", "bad JSON"),
                              (json.dumps({"format": FORMAT}), "missing"),
                              (json.dumps(dict(_document(), schema_version=2)),
                               "unsupported schema")):
            parsed, error = WindowPresetService.validate(raw)
            self.assertIsNone(parsed)
            self.assertIn(fragment, error)

    def test_wrong_window_set_and_bad_bounds_are_refused(self):
        missing = _document()
        missing["windows"] = missing["windows"][:-1]
        parsed, error = WindowPresetService.validate(missing)
        self.assertIsNone(parsed)
        self.assertIn("window", error)

        bad = _document()
        bad["windows"][0]["bounds"]["width"] = 2
        parsed, error = WindowPresetService.validate(bad)
        self.assertIsNone(parsed)
        self.assertIn("bounds", error)

    def test_state_overlap_is_refused_without_mutating_input(self):
        original = _document()
        bad = copy.deepcopy(original)
        bad["window_states"] = {"closed": ["stats"],
                                 "minimized": ["stats"]}
        parsed, error = WindowPresetService.validate(bad)
        self.assertIsNone(parsed)
        self.assertIn("overlap", error)
        self.assertEqual(original["window_states"],
                         {"closed": [], "minimized": []})

    def test_name_override_and_resolution_note(self):
        doc = _document()
        doc["app_version"] = "9.4.0"
        parsed, error = WindowPresetService.validate(doc, name="  Imported  ")
        self.assertIsNone(error)
        self.assertEqual(parsed["name"], "Imported")
        self.assertIn("9.4.0", WindowPresetService.compatibility_note(parsed))
        self.assertIn("different", WindowPresetService.resolution_note(
            parsed, 1920, 1080))


if __name__ == "__main__":
    unittest.main(verbosity=2)
