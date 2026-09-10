"""
services/run — Key Path Tests (Normalize, Norm, Trace) +
AREA A P0-1/P0-2 regression pins for RunCoordinator.load_stack and
RunProgress.UserRecord.

Real assertions on logic, not pass-through.  This module deliberately does
NOT stub PySide6: the run engine is a real QObject subclass and importing it
with real Qt headless is part of the harness contract.

INTEGRATION-01/I2: the `services.run_service` alias package is retired;
everything comes from `services.run` now.
"""
import unittest
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))

from services.run import (  # noqa: E402
    STANDALONE_NICK, USER_SCOPED_BLOCKS, RETIRED_BLOCK_KEYS,
    RunCoordinator, RunProgress, RunTracer, norm_level, normalize_blocks,
)


class TestRunServicePaths(unittest.TestCase):
    def test_normalize_blocks_drops_non_dict_and_removes_retired(self):
        raw = [
            {"id": "A", "enabled": True, "use_panel_filters": True},
            "bad string",
            None,
            {"id": "B", "enabled": False},
            {"id": "C", "_hidden": 1},
        ]
        clean = normalize_blocks(raw)
        ids = [b.get("id") for b in clean]
        self.assertIn("A", ids)
        self.assertIn("B", ids)
        self.assertIn("C", ids)
        # Retired key removed
        for b in clean:
            if b.get("id") == "A":
                self.assertNotIn("use_panel_filters", b)
        # Enabled defaulted to True
        for b in clean:
            if b.get("id") == "C":
                self.assertTrue(b.get("enabled") is True)

    def test_normalize_blocks_empty_input(self):
        self.assertEqual(normalize_blocks([]), [])
        self.assertEqual(normalize_blocks(None), [])

    def test_norm_level_map(self):
        self.assertEqual(norm_level("ok"), "success")
        self.assertEqual(norm_level("success"), "success")
        self.assertEqual(norm_level("done"), "success")
        self.assertEqual(norm_level("info"), "info")
        self.assertEqual(norm_level("debug"), "info")
        self.assertEqual(norm_level("warn"), "warn")
        self.assertEqual(norm_level("warning"), "warn")
        self.assertEqual(norm_level("error"), "error")
        self.assertEqual(norm_level("fail"), "error")
        self.assertEqual(norm_level("unknown"), "info")
        self.assertEqual(norm_level(None), "info")

    def test_constants_defined(self):
        self.assertIn("CLICK_USER", USER_SCOPED_BLOCKS)
        self.assertEqual(STANDALONE_NICK, "—")
        self.assertIn("use_panel_filters", RETIRED_BLOCK_KEYS)

    def test_run_tracer_writes_jsonl(self):
        with tempfile.TemporaryDirectory() as td:
            tracer = RunTracer("test-123", log_dir=td)
            tracer.note({"step": 1, "status": "ok"})
            tracer.close()
            path = os.path.join(td, "run_trace_test-123.jsonl")
            self.assertTrue(os.path.exists(path))
            with open(path, "r", encoding="utf-8") as f:
                line = f.readline()
                self.assertIn("test-123", line)
                self.assertIn("step", line)


class TestRunCoordinatorLoadStack(unittest.TestCase):
    """P0-1 pin: load_stack must resolve registered action classes."""

    def _engine(self):
        return RunCoordinator(cdp=None, memory=None, criteria=None)

    def test_load_stack_instantiates_registered_block(self):
        engine = self._engine()
        engine.load_stack([{"block_id": "PAUSE", "id": "A", "pause_ms": 1}])
        stack = engine.get_stack()
        self.assertEqual(len(stack), 1)
        self.assertEqual(stack[0]["block_id"], "PAUSE")
        self.assertEqual(stack[0]["pause_ms"], 1)
        self.assertIsInstance(engine._stack[0], object)

    def test_load_stack_drops_unknown_and_garbage(self):
        engine = self._engine()
        engine.load_stack([
            {"block_id": "NOT_A_REAL_BLOCK"},
            {"block_id": "PAUSE", "pause_ms": 1},
            "garbage",
            None,
            {"block_id": "PAUSE", "enabled": False, "pause_ms": 2},
        ])
        stack = engine.get_stack()
        self.assertEqual(len(stack), 2, "unknown ids and non-dicts are dropped")
        self.assertEqual([s["enabled"] for s in stack], [True, False])

    def test_load_stack_clears_previous_stack(self):
        engine = self._engine()
        engine.load_stack([{"block_id": "PAUSE"}])
        engine.load_stack([])
        self.assertEqual(engine.get_stack(), [])


class TestRunProgressUserRecord(unittest.TestCase):
    """P0-2 pin: UserRecord must be importable/constructible at runtime."""

    def test_user_record_is_importable_from_progress(self):
        from services.run.progress import UserRecord

        rec = UserRecord(nick="wheel")
        self.assertEqual(rec.nick, "wheel")
        self.assertFalse(rec.messaged)

    def test_run_progress_is_usable_without_a_bus_until_emitted(self):
        progress = RunProgress()
        self.assertEqual(progress.total, 0)
        progress.extend_total(2)
        self.assertEqual(progress.total, 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
