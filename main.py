"""ChatBot Automator — Qt6 Desktop Application Entry Point."""

import sys
from datetime import datetime
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
from backend.criteria_engine import CriteriaEngine
from backend.bridge import Bridge
from services.run_service import ActionEngine
from services.history_service import HistoryService
from stores.user_memory import UserMemory
from core.di import Container
from core.events import EventBus

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
        geometry = self.geometry()
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
                    if (window.StackDnD &&
                        typeof window.StackDnD.flushPersistence === 'function') {
                        window.StackDnD.flushPersistence();
                    }
                } catch (e) {}
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


def build_container() -> Container:
    """The ONLY place objects are constructed and wired (the composition
    root). Every factory resolves its dependencies from the container;
    nothing else in the app reaches for a global singleton."""
    container = Container()
    container.register("config", lambda _c: ConfigManager())
    container.register("bus", lambda _c: EventBus())
    container.register(
        "cdp",
        lambda c: CDPClient(
            host=c.get("config").get("chrome", "host", default="127.0.0.1"),
            port=c.get("config").get("chrome", "port", default=9222)))
    container.register(
        "memory",
        lambda c: UserMemory(_queue_path(c.get("config"))))
    container.register("criteria", lambda _c: CriteriaEngine())
    container.register(
        "engine",
        lambda c: ActionEngine(cdp=c.get("cdp"), memory=c.get("memory"),
                               criteria=c.get("criteria")))
    # Message archive: one database, one media cache, one passive collector
    # shared by the COLLECT_HISTORY block, the history windows and the
    # Chat Message Collector panel.
    container.register(
        "history",
        lambda c: HistoryService(
            cdp=c.get("cdp"), config=c.get("config"),
            session_id=datetime.now().strftime("%Y%m%d-%H%M%S"),
            memory=c.get("memory")))
    container.register(
        "bridge",
        lambda c: Bridge(cdp=c.get("cdp"), memory=c.get("memory"),
                         criteria=c.get("criteria"), engine=c.get("engine"),
                         config=c.get("config")))
    return container


def _queue_path(config: ConfigManager) -> str:
    """People queue: since the unified single-DB redesign the queue's
    `users` table lives INSIDE the world file. A pre-redesign install
    still has a separate chatbot.db — start from it, the startup
    migration (HistoryService.migrate_install) merges it into the active
    world and renames it out of the way, after which the queue follows
    the world on every switch."""
    legacy_queue = "chatbot.db"
    world_path = str(config.get("history", "db_path", default="history.db"))
    return legacy_queue if os.path.exists(legacy_queue) else world_path


def main() -> int:
    app = QApplication(sys.argv)
    # We drive shutdown ourselves from MainWindow.closeEvent so that async
    # cleanup can finish before the process exits.
    app.setQuitOnLastWindowClosed(False)

    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)

    setup_logger()
    container = build_container()
    config = container.get("config")
    log.info("Starting ChatBot Automator")

    cdp = container.get("cdp")
    memory = container.get("memory")
    engine = container.get("engine")
    history = container.get("history")

    # Window + bridge
    window = MainWindow(config=config)
    bridge = container.get("bridge")
    bridge.attach_history(history)
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
            await history.close()
            await memory.close()
        except Exception as exc:  # never let cleanup block the exit
            log.warning("Shutdown cleanup warning: %s", exc)
        finally:
            log.info("Shutdown complete")
            app.quit()  # ends QApplication.exec() -> run_forever() returns

    window.closing.connect(lambda: asyncio.ensure_future(shutdown()))

    async def startup() -> None:
        await memory.init()
        try:
            await history.init()
            history.start()
        except Exception as exc:                      # noqa: BLE001
            log.warning("Message archive unavailable: %s", exc)
        # rebuild the unified undo timeline from both stores (config's
        # app-level half + this world's undo_history table) and let the UI
        # see the world that is actually live
        try:
            await bridge.sync_world_state()
        except Exception as exc:                      # noqa: BLE001
            log.warning("world state sync failed: %s", exc)
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
