"""MainWindow — Qt window with geometry + close flush ( <150 )."""

import logging
import os

from PySide6.QtWidgets import QMainWindow
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtCore import QTimer, Signal

from backend.config_manager import ConfigManager

log = logging.getLogger("chatbot")


class MainWindow(QMainWindow):
    """Window with geometry persisted in config state."""

    closing = Signal()

    def __init__(self, config: ConfigManager | None = None):
        super().__init__()
        self._config = config
        self._bridge = None
        self._close_requested = False
        self._close_finished = False
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

    def set_bridge(self, bridge):
        self._bridge = bridge
        persisted = getattr(bridge, "grid_layout_persisted", None)
        if persisted is not None:
            persisted.connect(self._on_grid_layout_persisted)

    def _restore_window_geometry(self):
        if not self._config:
            return
        saved = self._config.get_state("window_geometry", None)
        if not isinstance(saved, dict):
            return
        try:
            x, y = int(saved["x"]), int(saved["y"])
            width, height = int(saved["width"]), int(saved["height"])
        except (KeyError, TypeError, ValueError):
            return
        if width > 0 and height > 0:
            self.setGeometry(x, y, width, height)

    def _save_window_geometry(self):
        if not self._config:
            return
        geometry = self.geometry()
        self._config.set_state(window_geometry={
            "x": int(geometry.x()), "y": int(geometry.y()),
            "width": int(geometry.width()), "height": int(geometry.height()),
        })

    def _request_grid_flush(self):
        if not self._bridge or not self._view or not self._view.page():
            self._finish_close()
            return
        self._layout_flush_pending = True
        self._layout_flush_timer.start()
        script = """
            (function () {
                try { if (window.StackDnD && typeof window.StackDnD.flushPersistence === 'function') window.StackDnD.flushPersistence(); } catch (e) {}
                try { if (window.SashGrid && typeof window.SashGrid.flushPersistence === 'function') return !!window.SashGrid.flushPersistence(); } catch (e) {}
                return false;
            })();
        """
        try:
            self._view.page().runJavaScript(script, self._on_grid_flush_dispatched)
        except Exception as exc:  # noqa: BLE001
            log.warning("Grid close flush could not be dispatched: %s", exc)
            self._finish_close()

    def _on_grid_flush_dispatched(self, expects_ack):
        if self._close_finished or not self._layout_flush_pending:
            return
        if expects_ack is not True:
            self._finish_close()

    def _on_grid_layout_persisted(self, success):
        if not self._layout_flush_pending:
            return
        if not success:
            log.warning("Final grid layout was rejected while closing")
        self._finish_close()

    def _on_layout_flush_timeout(self):
        if self._layout_flush_pending:
            log.warning("Timed out waiting for final grid layout save; closing safely")
            self._finish_close()

    def _finish_close(self):
        if self._close_finished:
            return
        self._layout_flush_pending = False
        self._layout_flush_timer.stop()
        self._close_finished = True
        self.close()

    def closeEvent(self, event):
        if self._close_finished:
            event.accept()
            log.info("Main window closed — shutting down")
            self.closing.emit()
            self._watchdog.start()
            return
        if self._close_requested:
            event.ignore()
            return
        self._close_requested = True
        self._save_window_geometry()
        event.ignore()
        self._request_grid_flush()

    def _force_quit(self):
        log.warning("Shutdown watchdog fired — forcing process exit")
        os._exit(0)
