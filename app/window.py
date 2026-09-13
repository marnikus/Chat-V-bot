"""app/window — the QMainWindow that hosts the whole UI in one web view.

Owns three things and nothing else: the window itself, the geometry it
remembers between runs, and the *close protocol*. Everything the user sees
inside it belongs to `ui/`, and every backend call goes through the bridge
object handed to `create_window`.

Imports point one way: this module imports Qt and the bridge's signal by name.
Nothing in `app/` imports back into it.

The close protocol is the part worth reading, because a window that closes
before the grid layout is saved silently loses the user's arrangement. Closing
is not one event, it is a handshake with four possible endings:

    1. closeEvent fires -> geometry is saved, the close is REFUSED, and the
       page is asked to flush its layout;
    2. the page answers "I will persist" -> the bridge's
       `grid_layout_persisted` signal ends the wait;
    3. the page answers anything else (no grid, JS error, dead page) -> the
       dispatch callback ends the wait immediately;
    4. the page never answers at all -> a 1 s timer ends the wait.

Whichever arrives first calls `_finish_close`, which is idempotent because
several of them can arrive. The second closeEvent then accepts, emits
`closing`, and starts a 3 s watchdog that force-exits the process if some
background task refuses to unwind. The refuse-then-accept dance is why
`closeEvent` is read twice for one user click.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from PySide6.QtCore import QTimer, QUrl, Signal
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QMainWindow

log = logging.getLogger("chatbot")
UI_PATH = Path(__file__).resolve().parent.parent / "ui" / "index.html"


class MainWindow(QMainWindow):
    closing = Signal()

    def __init__(self, config=None):
        super().__init__()
        self._config = config
        self._bridge = None
        self._close_requested = self._close_finished = False
        self._layout_flush_pending = False
        self.setWindowTitle("🤖 ChatBot Automator")
        self.resize(1400, 900)
        self._view = QWebEngineView(self)
        self.setCentralWidget(self._view)
        self._restore_window_geometry()
        self._watchdog = QTimer(self)
        self._watchdog.setSingleShot(True)
        self._watchdog.setInterval(3000)
        self._watchdog.timeout.connect(self._force_quit)
        self._layout_flush_timer = QTimer(self)
        self._layout_flush_timer.setSingleShot(True)
        self._layout_flush_timer.setInterval(1000)
        self._layout_flush_timer.timeout.connect(self._on_layout_flush_timeout)

    def set_bridge(self, bridge) -> None:
        self._bridge = bridge
        signal = getattr(bridge, "grid_layout_persisted", None)
        if signal is not None:
            signal.connect(self._on_grid_layout_persisted)

    def _restore_window_geometry(self) -> None:
        if not self._config:
            return
        saved = self._config.get_state("window_geometry", None)
        if not isinstance(saved, dict):
            return
        try:
            x, y = int(saved["x"]), int(saved["y"])
            w, h = int(saved["width"]), int(saved["height"])
        except (KeyError, TypeError, ValueError):
            return
        if w > 0 and h > 0:
            self.setGeometry(x, y, w, h)

    def _save_window_geometry(self) -> None:
        if not self._config:
            return
        g = self.geometry()
        self._config.set_state(window_geometry={"x": int(g.x()), "y": int(g.y()),
                                                "width": int(g.width()),
                                                "height": int(g.height())})

    def _request_grid_flush(self) -> None:
        if not self._bridge or not self._view or not self._view.page():
            self._finish_close(); return
        self._layout_flush_pending = True
        self._layout_flush_timer.start()
        script = """(function(){try{if(window.StackDnD&&typeof window.StackDnD.flushPersistence==='function')window.StackDnD.flushPersistence();}catch(e){}try{if(window.SashGrid&&typeof window.SashGrid.flushPersistence==='function')return !!window.SashGrid.flushPersistence();}catch(e){}return false;})();"""
        try:
            self._view.page().runJavaScript(script, self._on_grid_flush_dispatched)
        except Exception as exc:
            log.warning("Grid close flush could not be dispatched: %s", exc)
            self._finish_close()

    def _on_grid_flush_dispatched(self, expects_ack) -> None:
        if not self._close_finished and self._layout_flush_pending and expects_ack is not True:
            self._finish_close()

    def _on_grid_layout_persisted(self, success) -> None:
        if not self._layout_flush_pending:
            return
        if not success:
            log.warning("Final grid layout was rejected while closing")
        self._finish_close()

    def _on_layout_flush_timeout(self) -> None:
        if self._layout_flush_pending:
            log.warning("Timed out waiting for final grid layout save; closing safely")
            self._finish_close()

    def _finish_close(self) -> None:
        if self._close_finished:
            return
        self._layout_flush_pending = False
        self._layout_flush_timer.stop()
        self._close_finished = True
        self.close()

    def closeEvent(self, event):
        if self._close_finished:
            event.accept(); log.info("Main window closed — shutting down")
            self.closing.emit(); self._watchdog.start(); return
        if self._close_requested:
            event.ignore(); return
        self._close_requested = True
        self._save_window_geometry()
        event.ignore(); self._request_grid_flush()

    def _force_quit(self) -> None:
        log.warning("Shutdown watchdog fired — forcing process exit")
        os._exit(0)


def create_window(config, bridge, ui_path: str | os.PathLike | None = None) -> MainWindow:
    window = MainWindow(config=config)
    window.set_bridge(bridge)
    channel = QWebChannel(window)
    channel.registerObject("bridge", bridge)
    window._channel = channel
    window._view.page().setWebChannel(channel)
    path = Path(ui_path or UI_PATH).resolve()
    window._view.load(QUrl.fromLocalFile(str(path)))
    window.show()
    return window
