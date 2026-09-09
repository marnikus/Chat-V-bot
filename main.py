"""ChatBot Automator — Qt6 desktop entry point."""

from __future__ import annotations

import asyncio
import logging
import os
import sys

from PySide6.QtWidgets import QApplication
from qasync import QEventLoop

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.bootstrap import create_container, queue_path as _queue_path
from app.lifecycle import ApplicationLifecycle
from app.window import MainWindow, create_window

build_container = create_container
from backend.logger import setup_logger

log = logging.getLogger("chatbot")


def main() -> int:
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)
    setup_logger()
    container = create_container()
    log.info("Starting ChatBot Automator")
    config = container.get("config")
    cdp = container.get("cdp")
    memory = container.get("memory")
    engine = container.get("engine")
    history = container.get("history")
    bridge = container.get("bridge")
    bridge.attach_history(history)
    window = create_window(config, bridge)
    lifecycle = ApplicationLifecycle(app, cdp, memory, engine, history, bridge)
    lifecycle.bind(window)
    lifecycle.start(loop)
    with loop:
        loop.run_forever()
    log.info("Application exited cleanly")
    return 0


if __name__ == "__main__":
    sys.exit(main())
