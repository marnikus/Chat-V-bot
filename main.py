"""ChatBot Automator — Qt6 entry, DI only ( <150 )."""

import sys
import os
import asyncio
import logging
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtWidgets import QApplication
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtCore import QUrl
from qasync import QEventLoop

from backend.logger import setup_logger
from app.window import MainWindow
from app.container import build_container
from core.result import Result

log = logging.getLogger("chatbot")


def main() -> int:
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)
    setup_logger()
    from backend.config_manager import ConfigManager
    config = ConfigManager()
    log.info("Starting ChatBot Automator")
    container = build_container(config)
    log.info("DI container ready: %s", list(container._factories.keys()) + list(container._singletons.keys()))
    cdp = container.resolve("cdp")
    memory = container.resolve("memory")
    engine = container.resolve("engine")
    history = container.resolve("history_service")
    bridge = container.resolve("bridge")
    window = MainWindow(config=config)
    window.set_bridge(bridge)
    channel = QWebChannel()
    channel.registerObject("bridge", bridge)
    window._view.page().setWebChannel(channel)
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
            tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
            for t in tasks:
                t.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            await cdp.disconnect()
            await history.close()
            await memory.close()
        except Exception as exc:  # noqa: BLE001
            log.warning("Shutdown cleanup warning: %s", exc)
        finally:
            log.info("Shutdown complete")
            app.quit()

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
        except Exception as exc:  # noqa: BLE001
            log.warning("Message archive unavailable: %s", exc)
        try:
            await bridge.sync_world_state()
        except Exception as exc:  # noqa: BLE001
            log.warning("world state sync failed: %s", exc)
        log.info("Backend ready")
        await asyncio.sleep(0.5)
        bridge.get_tabs()

    loop.create_task(startup())
    with loop:
        loop.run_forever()
    log.info("Application exited cleanly")
    return 0


if __name__ == "__main__":
    sys.exit(main())
