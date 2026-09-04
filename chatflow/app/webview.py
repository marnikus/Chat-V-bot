"""QWebEngineView hosting the HTML/CSS/JS UI + Python->JS event sink."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView

from ..core.logconf import get

_log = get("ui")


def ui_dir() -> Path:
    """The ui/ folder: bundled next to the executable, else repo-relative."""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "ui"
    return Path(__file__).resolve().parents[2] / "ui"


class _Page(QWebEnginePage):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.settings().setAttribute(QWebEngineSettings.JavascriptEnabled, True)
        self.settings().setAttribute(QWebEngineSettings.LocalContentCanAccessFileUrls, True)

    def javaScriptConsoleMessage(self, level, message, line, source) -> None:  # noqa: N802
        _log.debug("js %s:%s %s", source, line, message)


class ChatWebView(QWebEngineView):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._page = _Page(self)
        self.setPage(self._page)
        index = ui_dir() / "index.html"
        _log.info("loading UI from %s", index)
        self.load(QUrl.fromLocalFile(str(index)))

    def call_js(self, fn: str, payload: str | None = None) -> None:
        """Invoke `window.__call(fn, payload)` where payload is a JSON string."""
        args = ", ".join(json.dumps(a) for a in (fn, payload))
        self.page().runJavaScript(f"window.__call && window.__call({args})")
