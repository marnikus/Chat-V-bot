"""Application entry point: python -m chatflow.app.main"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtCore import QLockFile
from PySide6.QtWidgets import QApplication

from . import channel
from .webview import ChatWebView
from .window import MainWindow


def data_root() -> Path:
    if sys.platform.startswith("win"):
        base = os.environ.get("LOCALAPPDATA", str(Path.home()))
    else:
        base = str(Path.home() / ".local" / "share")
    root = Path(base) / "ChatFlowOrchestrator"
    root.mkdir(parents=True, exist_ok=True)
    return root


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("ChatFlowOrchestrator")
    lock = QLockFile(str(data_root() / "chatflow.lock"))
    if not lock.tryLock(100):
        print("ChatFlow Orchestrator is already running.")
        return 2

    root = data_root()
    sv = channel.build_services(_initial_settings(), root)
    webview = ChatWebView()
    window = MainWindow(webview, sv)
    channel.make_channel(sv, webview)
    sv.worker.start()  # the QThread that executes everything (RUN, tests, …)
    window.show()
    rc = app.exec()
    try:
        sv.worker.shutdown()
        sv.worker.wait(3000)
        sv.db.close()
    except Exception:  # noqa: BLE001
        pass
    return rc


def _initial_settings():
    from ..core.config import Settings
    return Settings()


if __name__ == "__main__":
    raise SystemExit(main())
