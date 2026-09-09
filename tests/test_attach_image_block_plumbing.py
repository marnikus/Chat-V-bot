"""`actions.attach_image` — the block's own plumbing (P1).

SPEC-FIRST (docs/ACTIONS_TEST_DESIGN_2026-09-09.md §11).

`tests/test_attach_image.py` already covers the media pipeline itself
(formats, active-chat scoping, dialog simulation, read-back, send
verification, missing folder / no matching files). What it cannot catch is
the block -> handler boundary: `attach_image()` takes EIGHT positional
arguments after `cdp`, so a reorder silently swaps a timeout for a boolean
and every setting still "looks right" in the UI.

Run with:  python3 tests/test_attach_image_block_plumbing.py
"""

import asyncio
import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import actions.attach_image as ai  # noqa: E402
from actions.attach_image import AttachImage  # noqa: E402
from actions.base_action import ActionResult  # noqa: E402
from backend.media_handler import DEFAULT_FILE_PATTERN  # noqa: E402


def run(coro):
    return asyncio.run(coro)


class FakeEngine:
    def report(self, message, level="info"):
        pass


class RecordingHandler:
    """Stands in for backend.media_handler.attach_image, by position."""

    SLOTS = ("folder_path", "file_pattern", "rotation_mode",
             "simulate_dialog", "verify_timeout_ms", "highlight_enabled",
             "confirm_pause_ms", "report")

    def __init__(self, ok=True):
        self.ok = ok
        self.calls = []

    async def __call__(self, cdp, *args):
        self.calls.append(dict(zip(self.SLOTS, args)))
        return self.ok

    @property
    def last(self):
        return self.calls[-1]


class BlockCase(unittest.TestCase):
    def setUp(self):
        self.handler = RecordingHandler()
        patcher = mock.patch.object(ai, "attach_image", self.handler)
        patcher.start()
        self.addCleanup(patcher.stop)

    def execute(self, block, engine=None):
        return run(block.execute("Ann", object(), engine))


class TestArgumentOrder(BlockCase):
    """AI-01 — the one thing only a positional test can prove."""

    def test_every_setting_lands_in_its_own_slot(self):
        block = AttachImage(folder_path="/imgs", file_pattern="*.webp",
                            rotation_mode="random", simulate_dialog=False,
                            verify_timeout_ms=1234, highlight_enabled=False,
                            confirm_pause_ms=77, pre_delay_ms=0)
        engine = FakeEngine()
        self.execute(block, engine=engine)
        self.assertEqual(self.handler.last, {
            "folder_path": "/imgs",
            "file_pattern": "*.webp",
            "rotation_mode": "random",
            "simulate_dialog": False,
            "verify_timeout_ms": 1234,
            "highlight_enabled": False,
            "confirm_pause_ms": 77,
            "report": engine.report,
        })

    def test_the_eight_slots_are_all_present(self):
        """A dropped argument must fail loudly, not shift the rest."""
        self.execute(AttachImage(pre_delay_ms=0))
        self.assertEqual(sorted(self.handler.last),
                         sorted(RecordingHandler.SLOTS))

    def test_report_is_none_without_an_engine(self):
        """AI-06."""
        self.execute(AttachImage(pre_delay_ms=0))
        self.assertIsNone(self.handler.last["report"])


class TestDefaultsAndClamping(BlockCase):
    """AI-02, AI-03, AI-04."""

    def test_documented_defaults(self):
        """AI-02."""
        block = AttachImage()
        self.assertEqual(block.folder_path, "")
        self.assertEqual(block.file_pattern, DEFAULT_FILE_PATTERN)
        self.assertEqual(block.rotation_mode, "sequential")
        self.assertTrue(block.simulate_dialog)
        self.assertEqual(block.verify_timeout_ms, 8000)
        self.assertTrue(block.highlight_enabled)
        self.assertEqual(block.confirm_pause_ms, 700)

    def test_an_empty_pattern_falls_back_to_the_default_formats(self):
        """AI-03."""
        self.execute(AttachImage(file_pattern="", pre_delay_ms=0))
        self.assertEqual(self.handler.last["file_pattern"],
                         DEFAULT_FILE_PATTERN)

    def test_negative_timings_are_clamped_to_zero(self):
        """AI-04."""
        self.execute(AttachImage(verify_timeout_ms=-5, confirm_pause_ms=-5,
                                 pre_delay_ms=0))
        self.assertEqual(self.handler.last["verify_timeout_ms"], 0)
        self.assertEqual(self.handler.last["confirm_pause_ms"], 0)

    def test_none_timings_are_clamped_to_zero(self):
        self.execute(AttachImage(verify_timeout_ms=None,
                                 confirm_pause_ms=None, pre_delay_ms=0))
        self.assertEqual(self.handler.last["verify_timeout_ms"], 0)
        self.assertEqual(self.handler.last["confirm_pause_ms"], 0)

    def test_numeric_strings_from_a_preset_are_coerced(self):
        self.execute(AttachImage(verify_timeout_ms="4000",
                                 confirm_pause_ms="250", pre_delay_ms=0))
        self.assertEqual(self.handler.last["verify_timeout_ms"], 4000)
        self.assertEqual(self.handler.last["confirm_pause_ms"], 250)

    def test_flags_are_coerced_to_bool(self):
        block = AttachImage(simulate_dialog=0, highlight_enabled="yes")
        self.assertIs(block.simulate_dialog, False)
        self.assertIs(block.highlight_enabled, True)


class TestOutcomeMapping(BlockCase):
    """AI-05."""

    def test_handler_success_is_ok(self):
        self.assertEqual(self.execute(AttachImage(pre_delay_ms=0)),
                         ActionResult.OK)

    def test_handler_failure_is_fail(self):
        self.handler.ok = False
        self.assertEqual(self.execute(AttachImage(pre_delay_ms=0)),
                         ActionResult.FAIL)


class TestSettings(unittest.TestCase):
    """AI-07."""

    def test_schema_exposes_every_setting(self):
        schema = AttachImage().config_schema()
        for key in ("folder_path", "file_pattern", "rotation_mode",
                    "simulate_dialog", "highlight_enabled",
                    "confirm_pause_ms", "verify_timeout_ms", "pre_delay_ms"):
            self.assertIn(key, schema, f"{key} missing from the schema")

    def test_rotation_options_are_the_two_documented_modes(self):
        options = AttachImage().config_schema()["rotation_mode"]["options"]
        self.assertEqual(sorted(options), ["random", "sequential"])

    def test_settings_round_trip_and_stay_json_safe(self):
        block = AttachImage(folder_path="/a", file_pattern="*.png",
                            rotation_mode="random", simulate_dialog=False,
                            verify_timeout_ms=0, highlight_enabled=False,
                            confirm_pause_ms=0, pre_delay_ms=0)
        data = block.to_dict()
        json.dumps(data, ensure_ascii=False)
        clone = AttachImage(**{k: v for k, v in data.items()
                               if k != "block_id"})
        self.assertEqual(clone.to_dict(), data)


if __name__ == "__main__":
    unittest.main(verbosity=2)
