"""File bridge dialogs — extracted from file_bridge (H-C5 split)

Native dialogs + naming helpers, ≤100 LOC.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from PySide6.QtWidgets import QApplication, QFileDialog

FILE_FILTER = "Chat-V-Bot presets (*.json);;All files (*)"


def _json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False)


def _slug(name: str) -> str:
    bad = set('\\/:*?"<>|')
    cleaned = "".join("_" if c in bad else c for c in (name or "").strip())
    return cleaned or "stack"


def _default_name(name: str, timed: bool = False) -> str:
    base = _slug(name)
    if not timed:
        return base + ".json"
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    return f"{base}_{stamp}.json"


def _dialog_parent():
    app = QApplication.instance()
    return app.activeWindow() if app else None


def pick_save_path(caption: str, default_name: str) -> str:
    path, _ = QFileDialog.getSaveFileName(_dialog_parent(), caption, default_name, FILE_FILTER)
    return path or ""


def pick_open_path(caption: str) -> str:
    path, _ = QFileDialog.getOpenFileName(_dialog_parent(), caption, "", FILE_FILTER)
    return path or ""


def _library_of(config: Any) -> list[dict]:
    return config.blocks.all() if config is not None else []
