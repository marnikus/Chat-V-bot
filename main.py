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
from PySide6.QtCore import QUrl, Qt
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
    def __init__(self):
        super().__init__()
        self.setWindowTitle("🤖 ChatBot Automator")
        self.resize(1400, 900)
        self._view = QWebEngineView(self)
        self.setCentralWidget(self._view)


def main():
    app = QApplication(sys.argv)
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
    window = MainWindow()

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
        # Auto-fetch Chrome tabs after UI loads
        await asyncio.sleep(0.5)
        bridge.get_tabs()
    loop.create_task(startup())

    with loop:
        loop.run_forever()


if __name__ == "__main__":
    main()
