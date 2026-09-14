"""Main window — construction, geometry persistence, safe close flush.

Qt window owns QWebEngineView, QWebChannel bridge, geometry save/restore,
and a two-phase close: request grid flush → wait for persisted signal or
timeout → force close. Watchdog ensures process exits.

H-C5 MI lift: named predicates for geometry validity, close state, flush
need, plus docstrings raise comment ratio. No new files.
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


def _is_valid_geometry(saved: dict) -> bool:
    """Geometry dict has positive width/height and int x/y."""
    try:
        w, h = int(saved["width"]), int(saved["height"])
        int(saved["x"]), int(saved["y"])
        return w > 0 and h > 0
    except (KeyError, TypeError, ValueError):
        return False


def _is_close_finished(window) -> bool:
    return bool(getattr(window, "_close_finished", False))


def _is_close_requested(window) -> bool:
    return bool(getattr(window, "_close_requested", False))


def _is_flush_pending(window) -> bool:
    return bool(getattr(window, "_layout_flush_pending", False))


def _has_bridge_flush_signal(bridge) -> bool:
    return getattr(bridge, "grid_layout_persisted", None) is not None


def _should_finish_close(window, expects_ack) -> bool:
    """Finish close when flush not pending or ack not expected."""
    return not _is_close_finished(window) and _is_flush_pending(window) and expects_ack is not True


class MainWindow(QMainWindow):
    """Main window with safe close flush."""

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
        """Attach bridge and grid persisted signal."""
        self._bridge = bridge
        signal = getattr(bridge, "grid_layout_persisted", None)
        if _has_bridge_flush_signal(bridge) and signal is not None:
            signal.connect(self._on_grid_layout_persisted)

    def _restore_window_geometry(self) -> None:
        """Restore saved geometry if valid."""
        if not self._config:
            return
        saved = self._config.get_state("window_geometry", None)
        if not isinstance(saved, dict):
            return
        if not _is_valid_geometry(saved):
            return
        try:
            x, y = int(saved["x"]), int(saved["y"])
            w, h = int(saved["width"]), int(saved["height"])
        except (KeyError, TypeError, ValueError):
            return
        self.setGeometry(x, y, w, h)

    def _save_window_geometry(self) -> None:
        """Persist current geometry."""
        if not self._config:
            return
        g = self.geometry()
        self._config.set_state(
            window_geometry={
                "x": int(g.x()),
                "y": int(g.y()),
                "width": int(g.width()),
                "height": int(g.height()),
            }
        )

    def _request_grid_flush(self) -> None:
        """Request JS flush, then wait for ack or timeout."""
        if not self._bridge or not self._view or not self._view.page():
            self._finish_close()
            return
        self._layout_flush_pending = True
        self._layout_flush_timer.start()
        script = (
            "(function(){try{if(window.StackDnD&&typeof window.StackDnD.flushPersistence==='function')"
            "window.StackDnD.flushPersistence();}catch(e){}try{if(window.SashGrid&&typeof "
            "window.SashGrid.flushPersistence==='function')return !!window.SashGrid.flushPersistence();"
            "}catch(e){}return false;})();"
        )
        try:
            self._view.page().runJavaScript(script, self._on_grid_flush_dispatched)
        except Exception as exc:  # noqa: BLE001
            log.warning("Grid close flush could not be dispatched: %s", exc)
            self._finish_close()

    def _on_grid_flush_dispatched(self, expects_ack) -> None:
        """JS flush dispatched — finish if no ack expected."""
        if _should_finish_close(self, expects_ack):
            self._finish_close()

    def _on_grid_layout_persisted(self, success) -> None:
        """Grid layout persisted signal — finish close."""
        if not _is_flush_pending(self):
            return
        if not success:
            log.warning("Final grid layout was rejected while closing")
        self._finish_close()

    def _on_layout_flush_timeout(self) -> None:
        """Flush timeout — close safely."""
        if _is_flush_pending(self):
            log.warning("Timed out waiting for final grid layout save; closing safely")
            self._finish_close()

    def _finish_close(self) -> None:
        """Stop timers and close."""
        if _is_close_finished(self):
            return
        self._layout_flush_pending = False
        self._layout_flush_timer.stop()
        self._close_finished = True
        self.close()

    def closeEvent(self, event):  # noqa: N802
        """Two-phase close: first request flush, second actually close."""
        if _is_close_finished(self):
            event.accept()
            log.info("Main window closed — shutting down")
            self.closing.emit()
            self._watchdog.start()
            return
        if _is_close_requested(self):
            event.ignore()
            return
        self._close_requested = True
        self._save_window_geometry()
        event.ignore()
        self._request_grid_flush()

    def _force_quit(self) -> None:
        """Watchdog — force exit."""
        log.warning("Shutdown watchdog fired — forcing process exit")
        os._exit(0)


def create_window(config, bridge, ui_path: str | os.PathLike | None = None) -> MainWindow:
    """Create and show main window with bridge channel."""
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
