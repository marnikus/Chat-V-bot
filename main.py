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
from PySide6.QtCore import QUrl
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
    """Main window that fully tears down the process when closed."""

    def __init__(self, app: QApplication | None = None,
                 loop: QEventLoop | None = None):
        super().__init__()
        self._app = app
        self._loop = loop
        self.setWindowTitle("🤖 ChatBot Automator")
        self.resize(1400, 900)
        self._view = QWebEngineView(self)
        self.setCentralWidget(self._view)

    def closeEvent(self, event):
        """Closing the window must stop the Qt app and the asyncio loop."""
        log.info("Window closed — shutting down application")
        try:
            self._view.stop()
        except Exception:
            pass
        if self._app is not None:
            # Force the whole Qt application (and child renderer process) to exit.
            self._app.quit()
        if self._loop is not None:
            # Stop the qasync event loop so `run_forever()` returns.
            self._loop.stop()
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(True)
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

    # Window
    window = MainWindow(app=app, loop=loop)

    # QWebChannel bridge
    bridge = Bridge(cdp=cdp, memory=memory, criteria=criteria,
                    engine=engine, config=config)
    channel = QWebChannel()
    channel.registerObject("bridge", bridge)
    window._view.page().setWebChannel(channel)

    # Load UI
    ui_path = os.path.join(os.path.dirname(__file__), "ui", "index.html")
    window._view.load(QUrl.fromLocalFile(os.path.abspath(ui_path)))
    window.show()

    # Init async services
    async def startup():
        await memory.init()
        log.info("Backend ready")
        # Auto-fetch Chrome tabs after UI loads (connect is still manual).
        await asyncio.sleep(0.5)
        bridge.get_tabs()

    loop.create_task(startup())

    async def shutdown() -> None:
        """Cancel background work and release backend resources."""
        # Request the engine to stop if a stack is running.
        try:
            engine.stop()
        except Exception:
            pass
        # Disconnect the CDP WebSocket first (cancels its receive task).
        try:
            await cdp.disconnect()
        except Exception:
            pass
        # Close the SQLite connection.
        try:
            await memory.close()
        except Exception:
            pass
        # Cancel any remaining asyncio tasks (tab fetch, stack run, etc.).
        current = asyncio.current_task()
        tasks = [t for t in asyncio.all_tasks()
                 if t is not current and not t.done()]
        for t in tasks:
            t.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        log.info("ChatBot Automator exited")

    with loop:
        loop.run_forever()
        loop.run_until_complete(shutdown())


if __name__ == "__main__":
    main()
