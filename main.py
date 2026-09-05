"""ChatBot Automator — Qt6 Desktop Application Entry Point."""

import sys
import os
import asyncio
import logging

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtWidgets import QApplication, QMainWindow
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtCore import QUrl, QTimer, Signal
from qasync import QEventLoop

from backend.logger import setup_logger
from backend.config_manager import ConfigManager
from backend.cdp_client import CDPClient
from backend.user_memory import UserMemory
from backend.criteria_engine import CriteriaEngine
from backend.action_engine import ActionEngine
from backend.bridge import Bridge

log = logging.getLogger("chatbot")


class MainWindow(QMainWindow):
    """Main window with geometry persisted in the shared config settings."""

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
        # Watchdog: if Qt/WebEngine ever refuses to release, force-exit so the
        # terminal prompt always returns after the user closes the window.
        self._watchdog = QTimer(self)
        self._watchdog.setSingleShot(True)
        self._watchdog.setInterval(3000)
        self._watchdog.timeout.connect(self._force_quit)
        self._layout_flush_timer = QTimer(self)
        self._layout_flush_timer.setSingleShot(True)
        self._layout_flush_timer.setInterval(1000)
        self._layout_flush_timer.timeout.connect(self._on_layout_flush_timeout)

    def set_bridge(self, bridge):
        """Attach the WebChannel bridge used by the close-time grid flush."""
        self._bridge = bridge
        persisted = getattr(bridge, "grid_layout_persisted", None)
        if persisted is not None:
            persisted.connect(self._on_grid_layout_persisted)

    def _restore_window_geometry(self):
        """Restore the last normal position/size when it is valid."""
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
        """Persist exact Qt geometry before shutdown starts."""
        if not self._config:
            return
        geometry = (self.normalGeometry()
                    if self.isMaximized() or self.isFullScreen()
                    else self.geometry())
        self._config.set_state(window_geometry={
            "x": int(geometry.x()),
            "y": int(geometry.y()),
            "width": int(geometry.width()),
            "height": int(geometry.height()),
        })

    def _request_grid_flush(self):
        """Ask the live WebEngine page to persist its final grid tree."""
        if not self._bridge or not self._view or not self._view.page():
            self._finish_close()
            return
        self._layout_flush_pending = True
        self._layout_flush_timer.start()
        script = """
            (function () {
                try {
                    if (window.SashGrid &&
                        typeof window.SashGrid.flushPersistence === 'function') {
                        return !!window.SashGrid.flushPersistence();
                    }
                } catch (e) {}
                return false;
            })();
        """
        try:
            self._view.page().runJavaScript(
                script, self._on_grid_flush_dispatched)
        except Exception as exc:
            log.warning("Grid close flush could not be dispatched: %s", exc)
            self._finish_close()

    def _on_grid_flush_dispatched(self, expects_ack):
        """Finish immediately only when JS has no backend save to await."""
        if self._close_finished or not self._layout_flush_pending:
            return
        if expects_ack is not True:
            self._finish_close()

    def _on_grid_layout_persisted(self, success):
        """Bridge acknowledgment that the final grid payload reached config."""
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
        # Re-enter closeEvent so Qt owns a live close event when it is
        # accepted. The first close request was intentionally ignored while
        # the WebEngine save was in flight.
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


def main() -> int:
    app = QApplication(sys.argv)
    # We drive shutdown ourselves from MainWindow.closeEvent so that async
    # cleanup can finish before the process exits.
    app.setQuitOnLastWindowClosed(False)

    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)

    setup_logger()
    config = ConfigManager()
    log.info("Starting ChatBot Automator")

    # Backend services
    cdp = CDPClient(
        host=config.get("chrome", "host", default="127.0.0.1"),
        port=config.get("chrome", "port", default=9222),
    )
    memory = UserMemory()
    criteria = CriteriaEngine()
    engine = ActionEngine(cdp=cdp, memory=memory, criteria=criteria)

    # Window + bridge
    window = MainWindow(config=config)
    bridge = Bridge(cdp=cdp, memory=memory, criteria=criteria,
                    engine=engine, config=config)
    window.set_bridge(bridge)
    channel = QWebChannel()
    channel.registerObject("bridge", bridge)
    window._view.page().setWebChannel(channel)

    # Load UI
    ui_path = os.path.join(os.path.dirname(__file__), "ui", "index.html")
    window._view.load(QUrl.fromLocalFile(os.path.abspath(ui_path)))
    window.show()

    shutdown_started = {"flag": False}

    async def shutdown() -> None:
        if shutdown_started["flag"]:
            return
        shutdown_started["flag"] = True
        log.info("Graceful shutdown…")
        try:
            engine.stop()
            tasks = [t for t in asyncio.all_tasks()
                     if t is not asyncio.current_task()]
            for t in tasks:
                t.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            await cdp.disconnect()
            await memory.close()
        except Exception as exc:  # never let cleanup block the exit
            log.warning("Shutdown cleanup warning: %s", exc)
        finally:
            log.info("Shutdown complete")
            app.quit()  # ends QApplication.exec() -> run_forever() returns

    window.closing.connect(lambda: asyncio.ensure_future(shutdown()))

    async def startup() -> None:
        await memory.init()
        log.info("Backend ready")
        # Auto-fetch Chrome tabs once the UI has loaded
        await asyncio.sleep(0.5)
        bridge.get_tabs()

    loop.create_task(startup())

    with loop:
        loop.run_forever()

    log.info("Application exited cleanly")
    return 0


if __name__ == "__main__":
    sys.exit(main())
