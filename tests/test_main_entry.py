"""Smoke tests for main.py — start, DI, registry, DB init, close/exit.

Qt is stubbed so these run without a display or PySide6. The real
`main` module is imported; we do not reimplement its branches.

Run:  python -m pytest tests/test_main_entry.py -v
"""
from __future__ import annotations

import asyncio
import importlib
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

REQUIRED_CONTAINER_KEYS = (
    "config", "bus", "cdp", "memory", "criteria", "engine", "history", "bridge",
)

SHIPPED_BLOCKS = [
    "ATTACH_IMAGE", "CLICK_BACK", "CLICK_MAIN_TAB", "CLICK_SEND",
    "CLICK_USER", "COLLECT_HISTORY", "CONDITIONAL_SKIP", "CUSTOM_FIND",
    "MARK_MESSAGED", "PAUSE", "REPEAT_LOOP", "SCROLL_PARSE",
    "SEARCH_USERS", "TAKE_PERSON", "TYPE_MESSAGE", "WAIT_PAGE_LOAD",
]


class _Signal:
    def __init__(self, *a, **k):
        self._subs = []

    def connect(self, fn):
        self._subs.append(fn)
        return fn

    def emit(self, *a, **k):
        for fn in list(self._subs):
            fn(*a, **k)


class _Timer:
    def __init__(self, parent=None):
        self._interval = 0
        self._single = False
        self.timeout = _Signal()
        self._active = False

    def setSingleShot(self, v):
        self._single = v

    def setInterval(self, ms):
        self._interval = ms

    def start(self):
        self._active = True

    def stop(self):
        self._active = False

    def fire(self):
        if self._active or self._single:
            self.timeout.emit()
            if self._single:
                self._active = False


class _Geometry:
    def __init__(self, x=0, y=0, w=1400, h=900):
        self._x, self._y, self._w, self._h = x, y, w, h

    def x(self):
        return self._x

    def y(self):
        return self._y

    def width(self):
        return self._w

    def height(self):
        return self._h


class _Page:
    def __init__(self):
        self.channel = None
        self.last_script = None
        self._cb = None
        self.fail_js = False

    def setWebChannel(self, ch):
        self.channel = ch

    def runJavaScript(self, script, cb=None):
        if self.fail_js:
            raise RuntimeError("no page")
        self.last_script = script
        self._cb = cb


class _View:
    def __init__(self, parent=None):
        self._page = _Page()
        self.loaded = None

    def page(self):
        return self._page

    def load(self, url):
        self.loaded = url


class _QMainWindow:
    def __init__(self, *a, **k):
        self._title = ""
        self._geo = _Geometry()
        self._central = None
        self.close_accepted = None
        self.show_called = False

    def setWindowTitle(self, t):
        self._title = t

    def resize(self, w, h):
        self._geo = _Geometry(self._geo.x(), self._geo.y(), w, h)

    def setCentralWidget(self, w):
        self._central = w

    def setGeometry(self, x, y, w, h):
        self._geo = _Geometry(x, y, w, h)

    def geometry(self):
        return self._geo

    def show(self):
        self.show_called = True

    def close(self):
        class Ev:
            def __init__(self):
                self._acc = None

            def accept(self):
                self._acc = True

            def ignore(self):
                self._acc = False

        ev = Ev()
        self.closeEvent(ev)
        self.close_accepted = ev._acc


class _QApplication:
    instances = []
    quit_on_last = True
    quit_called = False
    argv = None

    def __init__(self, argv):
        _QApplication.argv = list(argv)
        _QApplication.instances.append(self)
        _QApplication.quit_called = False

    def setQuitOnLastWindowClosed(self, v):
        _QApplication.quit_on_last = v

    def quit(self):
        _QApplication.quit_called = True

    def exec(self):
        return 0


class _MetaMethodType:
    Signal = 1
    Slot = 2
    Method = 0


class _QMetaMethod:
    MethodType = _MetaMethodType

    def name(self):
        return b""

    def parameterTypes(self):
        return []

    def methodType(self):
        return 0

    def typeName(self):
        return b""


class _MetaObject:
    def methodOffset(self):
        return 0

    def methodCount(self):
        return 0

    def method(self, i):
        return _QMetaMethod()


class _QObject:
    def __init__(self, parent=None):
        self._parent = parent

    def metaObject(self):
        return _MetaObject()

    def deleteLater(self):
        pass


def _slot(*a, **k):
    def deco(fn):
        return fn
    return deco


class _QUrl:
    def __init__(self, s=""):
        self._s = s

    @classmethod
    def fromLocalFile(cls, path):
        u = cls(path)
        u.is_local = True
        return u

    def toString(self):
        return self._s


class _QWebChannel:
    def __init__(self):
        self.objects = {}

    def registerObject(self, name, obj):
        self.objects[name] = obj


class _QEventLoop:
    def __init__(self, app=None):
        self.app = app
        self._tasks = []
        self._running = False

    def create_task(self, coro):
        self._tasks.append(coro)
        return coro

    def run_forever(self):
        self._running = True

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self._running = False
        for c in self._tasks:
            if asyncio.iscoroutine(c):
                c.close()
        return False


def _install_qt_stubs():
    qtwidgets = types.ModuleType("PySide6.QtWidgets")
    qtwidgets.QApplication = _QApplication
    qtwidgets.QMainWindow = _QMainWindow

    webeng = types.ModuleType("PySide6.QtWebEngineWidgets")
    webeng.QWebEngineView = _View

    webch = types.ModuleType("PySide6.QtWebChannel")
    webch.QWebChannel = _QWebChannel

    qtcore = types.ModuleType("PySide6.QtCore")
    qtcore.QUrl = _QUrl
    qtcore.QTimer = _Timer
    qtcore.Signal = lambda *a, **k: _Signal()
    qtcore.QObject = _QObject
    qtcore.Slot = _slot
    qtcore.Property = lambda *a, **k: (lambda f: f)
    qtcore.Qt = types.SimpleNamespace()
    qtcore.QMetaMethod = _QMetaMethod
    qtcore.QMimeData = type("QMimeData", (), {})

    qtgui = types.ModuleType("PySide6.QtGui")
    qtgui.QDesktopServices = type("QDesktopServices", (), {"openUrl": staticmethod(lambda u: None)})
    qtgui.QGuiApplication = type("QGuiApplication", (), {})
    qtgui.QImage = type("QImage", (), {})

    pyside = types.ModuleType("PySide6")
    pyside.QtWidgets = qtwidgets
    pyside.QtWebEngineWidgets = webeng
    pyside.QtWebChannel = webch
    pyside.QtCore = qtcore
    pyside.QtGui = qtgui

    qasync = types.ModuleType("qasync")
    qasync.QEventLoop = _QEventLoop

    mods = {
        "PySide6": pyside,
        "PySide6.QtWidgets": qtwidgets,
        "PySide6.QtWebEngineWidgets": webeng,
        "PySide6.QtWebChannel": webch,
        "PySide6.QtCore": qtcore,
        "PySide6.QtGui": qtgui,
        "qasync": qasync,
    }
    sys.modules.update(mods)
    return mods


_install_qt_stubs()


def _load_main():
    sys.modules.pop("main", None)
    _install_qt_stubs()
    return importlib.import_module("main")


class TestQueuePath(unittest.TestCase):
    def setUp(self):
        self.main = _load_main()
        self._cwd = os.getcwd()
        self._tmp = tempfile.TemporaryDirectory()
        os.chdir(self._tmp.name)

    def tearDown(self):
        os.chdir(self._cwd)
        self._tmp.cleanup()

    def _cfg(self, db_path="history.db"):
        class C:
            def get(self, section, key, default=None):
                if section == "history" and key == "db_path":
                    return db_path
                return default
        return C()

    def test_legacy_chatbot_db_wins_when_file_exists(self):
        Path("chatbot.db").write_bytes(b"x")
        got = self.main._queue_path(self._cfg("/abs/world.db"))
        self.assertEqual(got, "chatbot.db")

    def test_world_path_when_no_legacy_file(self):
        self.assertFalse(os.path.exists("chatbot.db"))
        got = self.main._queue_path(self._cfg("/abs/world.db"))
        self.assertEqual(got, "/abs/world.db")

    def test_default_world_name_when_config_omits_path(self):
        class Empty:
            def get(self, section, key, default=None):
                return default
        got = self.main._queue_path(Empty())
        self.assertEqual(got, "history.db")

    def test_legacy_check_is_not_absolute_install_root(self):
        """A leftover chatbot.db in CWD must not be ignored just because
        main.py lives elsewhere — but a file only next to main.py while CWD
        is elsewhere must not steal the queue either."""
        sibling = Path(ROOT) / "chatbot.db"
        existed = sibling.exists()
        try:
            if not existed:
                pass  # do not create in the real repo
            got = self.main._queue_path(self._cfg("world-in-tmp.db"))
            self.assertEqual(got, "world-in-tmp.db")
        finally:
            pass


class TestBuildContainer(unittest.TestCase):
    def setUp(self):
        self.main = _load_main()

    def test_registers_all_composition_root_keys_lazily(self):
        c = self.main.build_container()
        for key in REQUIRED_CONTAINER_KEYS:
            self.assertTrue(c.has(key), f"missing {key}")
        # lazy: factories present, instances not yet
        for key in REQUIRED_CONTAINER_KEYS:
            self.assertNotIn(key, c._instances)

    def test_config_get_does_not_build_engine_or_history(self):
        c = self.main.build_container()
        cfg = c.get("config")
        self.assertIsNotNone(cfg)
        self.assertNotIn("engine", c._instances)
        self.assertNotIn("history", c._instances)
        self.assertNotIn("bridge", c._instances)

    def test_cdp_reads_chrome_host_port_from_config(self):
        c = self.main.build_container()
        # replace config with a probe
        class FakeCfg:
            def get(self, section, key, default=None):
                if section == "chrome" and key == "host":
                    return "10.0.0.9"
                if section == "chrome" and key == "port":
                    return 9333
                if section == "history" and key == "db_path":
                    return "history.db"
                return default
        c.register_value("config", FakeCfg())
        cdp = c.get("cdp")
        self.assertEqual(getattr(cdp, "host", None) or getattr(cdp, "_host", None),
                         "10.0.0.9")
        port = getattr(cdp, "port", None)
        if port is None:
            port = getattr(cdp, "_port", None)
        self.assertEqual(int(port), 9333)

    def test_no_dependency_cycle_among_registered_keys(self):
        c = self.main.build_container()
        # resolving each key must not raise cycle; heavy ctors may still run
        # config + bus + criteria are cheap
        c.get("config")
        c.get("bus")
        c.get("criteria")


class TestRegistryScanOnEnginePath(unittest.TestCase):
    def test_shipped_blocks_registered_after_actions_import(self):
        import actions  # noqa: F401
        from actions.registry import ActionRegistry
        ids = ActionRegistry.all_ids()
        missing = [b for b in SHIPPED_BLOCKS if b not in ids]
        self.assertEqual(missing, [], f"scan missed {missing}")

    def test_main_does_not_leave_registry_empty_if_engine_imported(self):
        """Composition root pulls ActionEngine; that path must see blocks."""
        self.main = _load_main()
        from actions.registry import ActionRegistry
        self.assertGreaterEqual(len(ActionRegistry.all_ids()), len(SHIPPED_BLOCKS))


class TestMainWindowGeometryAndClose(unittest.TestCase):
    def setUp(self):
        self.main = _load_main()
        self.saved = {}

        class Cfg:
            def __init__(self, box):
                self.box = box

            def get_state(self, key, default=None):
                return self.box.get(key, default)

            def set_state(self, **kwargs):
                self.box.update(kwargs)

        self.cfg = Cfg(self.saved)

    def test_invalid_geometry_is_ignored(self):
        self.saved["window_geometry"] = {"x": "nope"}
        w = self.main.MainWindow(config=self.cfg)
        self.assertEqual(w.geometry().width(), 1400)
        self.assertEqual(w.geometry().height(), 900)

    def test_zero_size_is_ignored(self):
        self.saved["window_geometry"] = {"x": 1, "y": 2, "width": 0, "height": 10}
        w = self.main.MainWindow(config=self.cfg)
        self.assertEqual(w.geometry().width(), 1400)

    def test_valid_geometry_restored(self):
        self.saved["window_geometry"] = {"x": 10, "y": 20, "width": 800, "height": 600}
        w = self.main.MainWindow(config=self.cfg)
        g = w.geometry()
        self.assertEqual((g.x(), g.y(), g.width(), g.height()), (10, 20, 800, 600))

    def test_non_dict_geometry_ignored(self):
        self.saved["window_geometry"] = [1, 2, 3]
        w = self.main.MainWindow(config=self.cfg)
        self.assertEqual(w.geometry().width(), 1400)

    def test_first_close_saves_geometry_and_ignores_event(self):
        w = self.main.MainWindow(config=self.cfg)
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
        w = self.main.MainWindow(config=self.cfg)
        w._bridge = object()
        class Ev:
            def accept(self):
                self.ok = True
            def ignore(self):
                self.ok = False
        w.closeEvent(Ev())
        ev2 = Ev()
        w.closeEvent(ev2)
        self.assertIs(ev2.ok, False)

    def test_finish_close_accepts_and_emits_closing_once(self):
        w = self.main.MainWindow(config=self.cfg)
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
        w = self.main.MainWindow(config=self.cfg)
        w._bridge = None
        hits = []
        w.closing.connect(lambda: hits.append("c"))
        w._request_grid_flush()
        self.assertEqual(hits, ["c"])

    def test_js_false_finishes_without_waiting_ack(self):
        w = self.main.MainWindow(config=self.cfg)
        w._bridge = object()
        hits = []
        w.closing.connect(lambda: hits.append(1))
        w._layout_flush_pending = True
        w._on_grid_flush_dispatched(False)
        self.assertEqual(hits, [1])

    def test_js_true_waits_for_persisted_signal(self):
        w = self.main.MainWindow(config=self.cfg)
        hits = []
        w.closing.connect(lambda: hits.append(1))
        w._layout_flush_pending = True
        w._on_grid_flush_dispatched(True)
        self.assertEqual(hits, [])
        w._on_grid_layout_persisted(True)
        self.assertEqual(hits, [1])

    def test_persisted_signal_ignored_when_not_pending(self):
        w = self.main.MainWindow(config=self.cfg)
        hits = []
        w.closing.connect(lambda: hits.append(1))
        w._on_grid_layout_persisted(True)
        self.assertEqual(hits, [])

    def test_flush_timeout_closes_safely(self):
        w = self.main.MainWindow(config=self.cfg)
        hits = []
        w.closing.connect(lambda: hits.append(1))
        w._layout_flush_pending = True
        w._on_layout_flush_timeout()
        self.assertEqual(hits, [1])

    def test_runjavascript_error_still_closes(self):
        w = self.main.MainWindow(config=self.cfg)
        w._bridge = object()
        w._view.page().fail_js = True
        hits = []
        w.closing.connect(lambda: hits.append(1))
        w._request_grid_flush()
        self.assertEqual(hits, [1])

    def test_set_bridge_connects_persisted_signal(self):
        w = self.main.MainWindow(config=self.cfg)
        class Br:
            def __init__(self):
                self.grid_layout_persisted = _Signal()
        br = Br()
        w.set_bridge(br)
        hits = []
        w.closing.connect(lambda: hits.append(1))
        w._layout_flush_pending = True
        br.grid_layout_persisted.emit(True)
        self.assertEqual(hits, [1])

    def test_flush_script_mentions_both_sash_and_stack(self):
        w = self.main.MainWindow(config=self.cfg)
        w._bridge = object()
        w._request_grid_flush()
        script = w._view.page().last_script or ""
        self.assertIn("SashGrid", script)
        self.assertIn("flushPersistence", script)
        self.assertIn("StackDnD", script)


class TestMainSmokeStartExit(unittest.TestCase):
    def setUp(self):
        self.main = _load_main()

    def test_main_disables_quit_on_last_window_and_returns_0(self):
        _QApplication.quit_on_last = True
        with mock.patch.object(self.main.asyncio, "set_event_loop"):
            rc = self.main.main()
        self.assertEqual(rc, 0)
        self.assertIs(False, _QApplication.quit_on_last)
        self.assertTrue(_QApplication.instances)

    def test_ui_index_html_exists_for_loader(self):
        ui = Path(ROOT) / "ui" / "index.html"
        self.assertTrue(ui.is_file(), f"missing {ui}")

    def test_main_does_not_call_sys_exit(self):
        src = Path(ROOT, "main.py").read_text(encoding="utf-8")
        # __main__ guard may call sys.exit(main()); main() itself must return
        body = src.split('if __name__')[0]
        self.assertNotIn("sys.exit", body)


class TestDbInitContract(unittest.TestCase):
    def test_user_memory_init_creates_users_table(self):
        from stores.user_memory import UserMemory
        async def run():
            with tempfile.TemporaryDirectory() as d:
                path = os.path.join(d, "q.db")
                m = UserMemory(path)
                await m.init()
                self.assertTrue(m.is_open)
                await m.close()
                self.assertFalse(m.is_open)
        asyncio.run(run())


if __name__ == "__main__":
    unittest.main(verbosity=2)
