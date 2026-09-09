"""app.window.MainWindow — geometry restore, close/flush lifecycle.

Moved here from the stale ``main.MainWindow`` section of
``tests/test_main_entry.py``.  ``MainWindow`` lives in ``app.window`` now.
The module is loaded under scoped Qt fakes so no real QWebEngineView is
constructed.
"""

from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from qt_stubs import Signal, load_app_window  # noqa: E402


class TestMainWindowGeometryAndClose(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.MainWindow = load_app_window().MainWindow

    def setUp(self):
        self.saved = {}
        window = self.MainWindow

        class Cfg:
            def __init__(self, box):
                self.box = box

            def get_state(self, key, default=None):
                return self.box.get(key, default)

            def set_state(self, **kwargs):
                self.box.update(kwargs)

        self.cfg = Cfg(self.saved)
        self.window = window

    def _make(self):
        return self.window(config=self.cfg)

    def test_invalid_geometry_is_ignored(self):
        self.saved["window_geometry"] = {"x": "nope"}
        w = self._make()
        self.assertEqual(w.geometry().width(), 1400)
        self.assertEqual(w.geometry().height(), 900)

    def test_zero_size_is_ignored(self):
        self.saved["window_geometry"] = {"x": 1, "y": 2, "width": 0, "height": 10}
        w = self._make()
        self.assertEqual(w.geometry().width(), 1400)

    def test_valid_geometry_restored(self):
        self.saved["window_geometry"] = {"x": 10, "y": 20, "width": 800,
                                         "height": 600}
        w = self._make()
        g = w.geometry()
        self.assertEqual((g.x(), g.y(), g.width(), g.height()),
                         (10, 20, 800, 600))

    def test_non_dict_geometry_ignored(self):
        self.saved["window_geometry"] = [1, 2, 3]
        w = self._make()
        self.assertEqual(w.geometry().width(), 1400)

    def test_first_close_saves_geometry_and_ignores_event(self):
        w = self._make()
        w._bridge = object()  # keep flush in-flight
        w.setGeometry(3, 4, 500, 400)

        class Ev:
            def __init__(self):
                self.accepted = None

            def accept(self):
                self.accepted = True

            def ignore(self):
                self.accepted = False

        ev = Ev()
        w.closeEvent(ev)
        self.assertIs(ev.accepted, False)
        self.assertIn("window_geometry", self.saved)
        geo = self.saved["window_geometry"]
        self.assertEqual(geo["width"], 500)
        self.assertEqual(geo["height"], 400)
        self.assertTrue(w._close_requested)
        self.assertFalse(w._close_finished)

    def test_second_close_while_flush_pending_still_ignored(self):
        w = self._make()
        w._bridge = object()

        class Ev:
            def __init__(self):
                self.ok = None

            def accept(self):
                self.ok = True

            def ignore(self):
                self.ok = False

        w.closeEvent(Ev())
        ev2 = Ev()
        w.closeEvent(ev2)
        self.assertIs(ev2.ok, False)

    def test_finish_close_accepts_and_emits_closing_once(self):
        w = self._make()
        hits = []
        w.closing.connect(lambda: hits.append(1))
        w._close_requested = True
        w._finish_close()
        self.assertEqual(hits, [1])
        w._finish_close()
        self.assertEqual(hits, [1])
        self.assertTrue(w._watchdog._active)
        self.assertEqual(w._watchdog._interval, 3000)

    def test_flush_without_bridge_finishes(self):
        w = self._make()
        w._bridge = None
        hits = []
        w.closing.connect(lambda: hits.append("c"))
        w._request_grid_flush()
        self.assertEqual(hits, ["c"])

    def test_js_false_finishes_without_waiting_ack(self):
        w = self._make()
        w._bridge = object()
        hits = []
        w.closing.connect(lambda: hits.append(1))
        w._layout_flush_pending = True
        w._on_grid_flush_dispatched(False)
        self.assertEqual(hits, [1])

    def test_js_true_waits_for_persisted_signal(self):
        w = self._make()
        hits = []
        w.closing.connect(lambda: hits.append(1))
        w._layout_flush_pending = True
        w._on_grid_flush_dispatched(True)
        self.assertEqual(hits, [])
        w._on_grid_layout_persisted(True)
        self.assertEqual(hits, [1])

    def test_persisted_signal_ignored_when_not_pending(self):
        w = self._make()
        hits = []
        w.closing.connect(lambda: hits.append(1))
        w._on_grid_layout_persisted(True)
        self.assertEqual(hits, [])

    def test_flush_timeout_closes_safely(self):
        w = self._make()
        hits = []
        w.closing.connect(lambda: hits.append(1))
        w._layout_flush_pending = True
        w._on_layout_flush_timeout()
        self.assertEqual(hits, [1])

    def test_runjavascript_error_still_closes(self):
        w = self._make()
        w._bridge = object()
        w._view.page().fail_js = True
        hits = []
        w.closing.connect(lambda: hits.append(1))
        w._request_grid_flush()
        self.assertEqual(hits, [1])

    def test_set_bridge_connects_persisted_signal(self):
        w = self._make()

        class Br:
            def __init__(self):
                self.grid_layout_persisted = Signal()

        bridge = Br()
        w.set_bridge(bridge)
        hits = []
        w.closing.connect(lambda: hits.append(1))
        w._layout_flush_pending = True
        bridge.grid_layout_persisted.emit(True)
        self.assertEqual(hits, [1])

    def test_flush_script_mentions_both_sash_and_stack(self):
        w = self._make()
        w._bridge = object()
        w._request_grid_flush()
        script = w._view.page().last_script or ""
        self.assertIn("SashGrid", script)
        self.assertIn("flushPersistence", script)
        self.assertIn("StackDnD", script)


if __name__ == "__main__":
    unittest.main(verbosity=2)
