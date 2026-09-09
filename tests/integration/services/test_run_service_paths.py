"""
services/run_service — Key Path Tests (Normalize, Norm, Trace)
Real assertions on logic, not pass-through.
"""
import unittest
import os
import tempfile
import sys
import types
sys.path.insert(0, "/home/user/Chat-V-bot")
# Stub missing PySide6 so run_service import succeeds for path testing
if "PySide6" not in sys.modules:
    import types
    pyside = types.ModuleType("PySide6")
    pyside.QtCore = types.ModuleType("PySide6.QtCore")
    class _QObject: pass
    class _Signal:
        def __init__(self, *a, **kw): pass
        def connect(self, *a, **kw): pass
        def emit(self, *a, **kw): pass
    pyside.QtCore.QObject = _QObject
    pyside.QtCore.Signal = _Signal
    pyside.QtCore.Slot = lambda *a, **kw: (lambda f: f)
    pyside.QtCore.QMetaMethod = object
    sys.modules["PySide6"] = pyside
    sys.modules["PySide6.QtCore"] = pyside.QtCore
from services.run_service import normalize_blocks, norm_level, RunTracer, USER_SCOPED_BLOCKS, STANDALONE_NICK, RETIRED_BLOCK_KEYS


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


if __name__ == "__main__":
    unittest.main(verbosity=2)
