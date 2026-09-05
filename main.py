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

    def closeEvent(self, event):
        self._save_window_geometry()
        log.info("Main window closed — shutting down")
        self.closing.emit()
        self._watchdog.start()
        event.accept()

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
