"""Window preset export helpers — extracted from window_preset_bridge (H-C5 split)

≤100 LOC.
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path

log = logging.getLogger("chatbot")


def _safe_filename(name: str) -> str:
    stem = re.sub(r"[^\w-]+", "-", str(name), flags=re.UNICODE).strip("-_")
    return f"window-preset-{stem or 'untitled'}.json"


def _choose_export_folder() -> str:
    from PySide6.QtWidgets import QFileDialog

    return str(QFileDialog.getExistingDirectory(None, "Export window preset — choose a folder", str(Path.home())))


def _write_export(folder: str, document: dict) -> Path:
    target = Path(folder) / _safe_filename(document["name"])
    temporary = target.with_name(f".{target.name}.tmp")
    payload = json.dumps(document, ensure_ascii=False, indent=2) + "\n"
    try:
        temporary.write_text(payload, encoding="utf-8")
        os.replace(temporary, target)
    except OSError:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    return target


def _open_in_folder(path: str) -> bool:
    target = Path(path)
    folder = target if target.is_dir() else target.parent
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QDesktopServices

    return bool(QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder))))
