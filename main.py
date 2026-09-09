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
from backend.user_memory import UserMemory
from backend.criteria_engine import CriteriaEngine
from backend.action_engine import ActionEngine
try:
    # W1 canonical: Router is the bridge (bridge/ is the source of truth)
    from bridge import Router as Bridge  # type: ignore
    from bridge.router import Router  # type: ignore
except Exception:  # noqa: BLE001
    from backend.bridge import Bridge  # type: ignore
    Router = Bridge  # type: ignore
from backend.history_service import HistoryService as BackendHistoryService
from services.history_service import HistoryService
from services.media_service import MediaService
from services.db_service import DbService
from services.collector_service import CollectorService
from core.di import Container
from core.result import Result
from core.events import EventBus
from stores.atomic import AtomicJsonStore
from stores.settings_store import SettingsStore

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


def build_container(config: ConfigManager | None = None) -> Container:
    """DI container — ~50 lines, no third-party framework.

    Arrows down only: main -> bridge/router -> services(Result) -> stores(atomic).
    Registers 12 keys: config, event_bus, atomic_store, settings_store, cdp,
    memory, criteria, engine, history_service, media_service, db_service,
    collector_service, bridge (13 with bus). Each service <150 LOC, reusable.
    """
    c = Container()
    cfg = config or ConfigManager()
    c.register_instance("config", cfg)
    c.register_instance("event_bus", EventBus())
    c.register("atomic_store", lambda cont: AtomicJsonStore(cfg._path if hasattr(cfg, "_path") else "config.json"))
    c.register("settings_store", lambda cont: SettingsStore(cont.resolve("atomic_store")))
    c.register("cdp", lambda cont: CDPClient(host=cont.resolve("config").get("chrome", "host", default="127.0.0.1"), port=cont.resolve("config").get("chrome", "port", default=9222)))

    def _memory_factory(cont: Container) -> UserMemory:
        legacy_queue = "chatbot.db"
        world_path = str(cont.resolve("config").get("history", "db_path", default="history.db"))
        queue_path = legacy_queue if os.path.exists(legacy_queue) else world_path
        return UserMemory(queue_path)

    c.register("memory", _memory_factory)
    c.register("criteria", lambda cont: CriteriaEngine())
    c.register("engine", lambda cont: ActionEngine(cdp=cont.resolve("cdp"), memory=cont.resolve("memory"), criteria=cont.resolve("criteria")))

    def _history_factory(cont: Container) -> HistoryService:
        return HistoryService(cdp=cont.resolve("cdp"), config=cont.resolve("config"),
                             session_id=datetime.now().strftime("%Y%m%d-%H%M%S"), memory=cont.resolve("memory"))

    c.register("history_service", _history_factory)
    c.register("media_service", lambda cont: MediaService(cont.resolve("history_service")))
    c.register("db_service", lambda cont: DbService(cont.resolve("history_service")))
    c.register("collector_service", lambda cont: CollectorService(cont.resolve("history_service")))

    def _bridge_factory(cont: Container):  # type: ignore
        br = Bridge(cdp=cont.resolve("cdp"), memory=cont.resolve("memory"), criteria=cont.resolve("criteria"),
                    engine=cont.resolve("engine"), config=cont.resolve("config"))
        hist = cont.resolve("history_service")
        try:
            br.attach_history(hist)
        except Exception:  # noqa: BLE001
            pass
        try:
            cont.resolve("engine").history = hist
        except Exception:  # noqa: BLE001
            pass
        return br

    c.register("bridge", _bridge_factory)
    return c


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
    # DI container (main.py is DI only — no business logic here)
    container = build_container(config)
    log.info("DI container ready: %s", list(container._factories.keys()) + list(container._singletons.keys()))

    # Backend services — all via DI (main.py is DI only, no business logic)
    cdp = container.resolve("cdp")
    memory = container.resolve("memory")
    criteria = container.resolve("criteria")
    engine = container.resolve("engine")
    history = container.resolve("history_service")
    bridge = container.resolve("bridge")

    # Window (geometry still via config)
    window = MainWindow(config=config)
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
            res = await history.init()
            if isinstance(res, Result) and res.is_err:
                log.warning("Message archive unavailable: %s", res.error)
            else:
                start_res = history.start()
                if isinstance(start_res, Result) and start_res.is_err:
                    log.warning("Message archive start failed: %s", start_res.error)
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
