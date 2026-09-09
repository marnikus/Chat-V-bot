"""Reveal a local file, never execute it or invoke its file association."""

from __future__ import annotations

import ntpath
import os
import sys


def _start_detached(program: str, arguments: list[str]) -> bool:
    from PySide6.QtCore import QProcess
    result = QProcess.startDetached(program, arguments)
    # PySide returns (started, pid); bool((False, 0)) would incorrectly succeed.
    return bool(result[0] if isinstance(result, tuple) else result)


def _open_folder(folder: str) -> bool:
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QDesktopServices
    return bool(QDesktopServices.openUrl(QUrl.fromLocalFile(folder)))


def reveal_file(path: str) -> dict:
    """Called only after the DB inventory has authorized this exact local path.

    Native argument arrays handle spaces/non-ASCII names without a shell. Linux
    desktops have no universal select-file command: open the containing folder.
    The launcher's acceptance is not proof that a native window became visible.
    """
    if not path or not os.path.lexists(path):
        return {"ok": False, "error": "That file no longer exists. Refresh Databases."}
    try:
        if sys.platform == "win32":
            ok = _start_detached("explorer.exe", ["/select,", ntpath.normpath(path)])
        elif sys.platform == "darwin":
            ok = _start_detached("/usr/bin/open", ["-R", path])
        else:
            ok = _open_folder(os.path.dirname(os.path.abspath(path)))
        if not ok:
            return {"ok": False, "error": "The file manager could not be opened.", "reveal_path": path}
        return {"ok": True, "reveal_path": path}
    except Exception as exc:
        return {"ok": False, "error": f"Cannot reveal the database file: {exc}", "reveal_path": path}
