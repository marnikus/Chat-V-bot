"""Scoped PySide6 stubs for tests that exercise app/ Qt wiring.

The app modules (``app.window``, ``main``) need QWidget/QWebEngine types that
cannot be created headless without a real GL/display.  These tests swap only
the Qt symbols they touch with lightweight Python fakes, and always restore
``sys.modules`` afterwards, so no other test module can be poisoned by a fake
``PySide6.QtCore`` the same way the historical module-level ``_install_qt_stubs``
did.

The fake classes below are the same ones that previously lived inside
``tests/test_main_entry.py``.  They spell the exact minimal surface those tests
rely on and are intentionally tiny.
"""

from __future__ import annotations

import asyncio
import importlib
import sys
import types
from contextlib import contextmanager
from unittest import mock


# ── fake Qt classes ──────────────────────────────────────────────────────

class Signal:
    """Minimal fake of PySide6's Signal descriptor used by the app tests."""

    def __init__(self, *args, **kwargs):
        self._subs = []

    def connect(self, fn):
        self._subs.append(fn)
        return fn

    def emit(self, *args, **kwargs):
        for fn in list(self._subs):
            fn(*args, **kwargs)


class Timer:
    def __init__(self, parent=None):
        self._interval = 0
        self._single = False
        self.timeout = Signal()
        self._active = False

    def setSingleShot(self, value):
        self._single = value

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


class Geometry:
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


class Page:
    def __init__(self):
        self.channel = None
        self.last_script = None
        self._cb = None
        self.fail_js = False

    def setWebChannel(self, channel):
        self.channel = channel

    def runJavaScript(self, script, cb=None):
        if self.fail_js:
            raise RuntimeError("no page")
        self.last_script = script
        self._cb = cb


class View:
    def __init__(self, parent=None):
        self._page = Page()
        self.loaded = None

    def page(self):
        return self._page

    def load(self, url):
        self.loaded = url


class QMainWindow:
    def __init__(self, *args, **kwargs):
        self._title = ""
        self._geo = Geometry()
        self._central = None
        self.close_accepted = None
        self.show_called = False

    def setWindowTitle(self, title):
        self._title = title

    def resize(self, w, h):
        self._geo = Geometry(self._geo.x(), self._geo.y(), w, h)

    def setCentralWidget(self, widget):
        self._central = widget

    def setGeometry(self, x, y, w, h):
        self._geo = Geometry(x, y, w, h)

    def geometry(self):
        return self._geo

    def show(self):
        self.show_called = True

    def close(self):
        class Event:
            def __init__(self):
                self._acc = None

            def accept(self):
                self._acc = True

            def ignore(self):
                self._acc = False

        event = Event()
        self.closeEvent(event)
        self.close_accepted = event._acc


class QApplication:
    instances = []
    quit_on_last = True
    quit_called = False
    argv = None

    def __init__(self, argv):
        QApplication.argv = list(argv)
        QApplication.instances.append(self)
        QApplication.quit_called = False

    def setQuitOnLastWindowClosed(self, value):
        QApplication.quit_on_last = value

    def quit(self):
        QApplication.quit_called = True

    def exec(self):
        return 0


class QUrl:
    def __init__(self, value=""):
        self._value = value

    @classmethod
    def fromLocalFile(cls, path):
        url = cls(path)
        url.is_local = True
        return url

    def toString(self):
        return self._value


class QWebChannel:
    def __init__(self, parent=None):
        self.objects = {}

    def registerObject(self, name, obj):
        self.objects[name] = obj


class QEventLoop:
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

    def __exit__(self, *args):
        self._running = False
        for coro in self._tasks:
            if asyncio.iscoroutine(coro):
                coro.close()
        return False


def _slot(*args, **kwargs):
    def decorator(fn):
        return fn
    return decorator


def _stub_modules():
    """Build the fake PySide6/qasync mapping installed by ``stub_qt``."""
    qtwidgets = types.ModuleType("PySide6.QtWidgets")
    qtwidgets.QApplication = QApplication
    qtwidgets.QMainWindow = QMainWindow

    webeng = types.ModuleType("PySide6.QtWebEngineWidgets")
    webeng.QWebEngineView = View

    webch = types.ModuleType("PySide6.QtWebChannel")
    webch.QWebChannel = QWebChannel

    qtcore = types.ModuleType("PySide6.QtCore")
    qtcore.QUrl = QUrl
    qtcore.QTimer = Timer
    qtcore.Signal = lambda *a, **k: Signal()
    qtcore.QObject = type("_QObject", (), {"__init__": lambda self, parent=None: None})
    qtcore.Slot = _slot
    qtcore.Property = lambda *a, **k: (lambda f: f)
    qtcore.Qt = types.SimpleNamespace()
    qtcore.QMetaMethod = object
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
    qasync.QEventLoop = QEventLoop

    return {
        "PySide6": pyside,
        "PySide6.QtWidgets": qtwidgets,
        "PySide6.QtWebEngineWidgets": webeng,
        "PySide6.QtWebChannel": webch,
        "PySide6.QtCore": qtcore,
        "PySide6.QtGui": qtgui,
        "qasync": qasync,
    }


@contextmanager
def stub_qt():
    """Install the fake Qt modules for the duration of one test and restore.

    This deliberately does *not* pop already-imported ``app``/``main``
    modules; callers that need a fresh loading use :func:`load_main` or
    explicitly reload the module they want.
    """
    with mock.patch.dict(sys.modules, _stub_modules()):
        yield


@contextmanager
def _fresh_app_imports():
    """Reset the entry-point modules so they reload under the currently
    installed (stub or real) PySide6 modules."""
    for name in ("main", "app.bootstrap", "app.window", "app.lifecycle"):
        sys.modules.pop(name, None)
    yield


def load_main():
    """Import ``main`` under scoped Qt fakes.

    The fakes are present only while importing; afterwards ``sys.modules``
    returns to the real PySide6 modules, but the already-cached ``main`` and
    ``app.window`` globals keep the fake classes this test used.
    """
    with stub_qt():
        with _fresh_app_imports():
            return importlib.import_module("main")


def load_app_window():
    """Import ``app.window`` under scoped Qt fakes."""
    with stub_qt():
        sys.modules.pop("app.window", None)
        return importlib.import_module("app.window")
