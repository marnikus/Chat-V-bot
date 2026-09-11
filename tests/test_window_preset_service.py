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

    def test_required_metadata_errors_are_specific(self):
        cases = (
            (lambda doc: doc.pop("format"), "missing format"),
            (lambda doc: doc.update(format="other"), "unsupported format"),
            (lambda doc: doc.pop("schema_version"), "missing schema_version"),
            (lambda doc: doc.update(schema_version=0), "unsupported schema"),
            (lambda doc: doc.update(app_version=""), "missing app_version"),
            (lambda doc: doc.pop("name"), "missing name"),
            (lambda doc: doc.update(name="x" * 81), "longer than 80"),
            (lambda doc: doc.pop("grid"), "grid.type"),
            (lambda doc: doc["grid"].update(version=True), "grid.version"),
            (lambda doc: doc["grid"].update(tree=object()), "JSON data"),
            (lambda doc: doc["grid"].update(window_count=1), "window_count"),
            (lambda doc: doc["grid"].update(sizes_unit="pixels"), "sizes_unit"),
        )
        for mutate, fragment in cases:
            doc = _document()
            mutate(doc)
            parsed, error = WindowPresetService.validate(doc)
            self.assertIsNone(parsed, fragment)
            self.assertIn(fragment, error, fragment)

    def test_window_state_and_screen_errors_are_refused(self):
        cases = (
            (lambda doc: doc.update(window_states=[]), "window_states must"),
            (lambda doc: doc["window_states"].update(closed="bad"),
             "closed must"),
            (lambda doc: doc["window_states"].update(closed=["ghost"]),
             "closed contains"),
            (lambda doc: doc["window_states"].update(closed=["stats", "stats"]),
             "closed contains a duplicate"),
            (lambda doc: doc["window_states"].update(minimized="bad"),
             "minimized must"),
            (lambda doc: doc["window_states"].update(minimized=["ghost"]),
             "minimized contains"),
            (lambda doc: doc.update(windows={}), "windows must be a list"),
            (lambda doc: doc["windows"].__setitem__(0, None),
             "each window entry"),
            (lambda doc: doc["windows"].__setitem__(0, {"id": "ghost"}),
             "unknown or duplicate id"),
            (lambda doc: doc["windows"][0].update(state="closed"),
             "inconsistent state"),
            (lambda doc: doc["windows"][0].update(bounds=None),
             "bounds must be an object"),
            (lambda doc: doc["windows"][0]["bounds"].update(width="wide"),
             "finite numbers"),
            (lambda doc: doc["windows"][0]["bounds"].update(width=-1),
             "between 0 and 1"),
            (lambda doc: doc["windows"][0]["bounds"].update(
                x=0.8, width=0.5), "outside the screen"),
            (lambda doc: doc["windows"].pop(), "current window set"),
            (lambda doc: doc.update(screen=[]), "screen must"),
            (lambda doc: doc["screen"].update(width=0), "positive numbers"),
            (lambda doc: doc["screen"].update(device_pixel_ratio=0),
             "device_pixel_ratio"),
        )
        for mutate, fragment in cases:
            doc = _document()
            mutate(doc)
            parsed, error = WindowPresetService.validate(doc)
            self.assertIsNone(parsed, fragment)
            self.assertIn(fragment, error, fragment)

    def test_closed_minimized_windows_and_optional_values_are_canonical(self):
        doc = _document()
        doc.pop("created_at")
        doc.pop("updated_at")
        doc["window_states"] = {"closed": ["stats"],
                                 "minimized": ["composer"]}
        source = {item["id"]: item for item in doc["windows"]}
        source["stats"]["state"] = "closed"
        source["composer"]["state"] = "minimized"
        source["composer"]["title"] = 42
        parsed, error = WindowPresetService.validate(doc)
        self.assertIsNone(error)
        result = {item["id"]: item for item in parsed["windows"]}
        self.assertEqual(result["stats"]["state"], "closed")
        self.assertEqual(result["composer"]["state"], "minimized")
        self.assertEqual(result["composer"]["title"], "composer")
        self.assertTrue(parsed["created_at"])
        self.assertTrue(parsed["updated_at"])
        self.assertEqual(WindowPresetService.compatibility_note(parsed), "")
        self.assertEqual(WindowPresetService.resolution_note(
            parsed, parsed["screen"]["width"], parsed["screen"]["height"]), "")

    def test_non_object_input_and_invalid_grid_tree_are_refused(self):
        parsed, error = WindowPresetService.validate([])
        self.assertIsNone(parsed)
        self.assertIn("JSON object", error)

        doc = _document()
        doc["grid"]["tree"] = {"t": "not-a-real-node"}
        parsed, error = WindowPresetService.validate(doc)
        self.assertIsNone(parsed)
        self.assertIn("invalid grid tree", error)


if __name__ == "__main__":
    unittest.main(verbosity=2)
