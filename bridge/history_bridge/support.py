"""The archive bridge's three module-level helpers.

Pure, Qt-lazy and stateless: the clipboard object, the FILE-URL mime
bundle, and the UI's JSON blob turned into the frozen
`PersonPageRequest`. Imports point down only (`backend.history_query`);
Qt is imported inside the functions so the module loads headless.
"""

from __future__ import annotations

from backend.history_query import (
    DEFAULT_LIMIT, DEFAULT_SORT, PersonPageRequest,
)


def _qt_clipboard():
    """The Qt clipboard object, or None when there is no app (headless)."""
    from PySide6.QtGui import QGuiApplication
    app = QGuiApplication.instance()
    return None if app is None else app.clipboard()

def _file_mime(path: str, mode: str):
    """Clipboard content for a FILE: URL + path text (+ pixels for images)."""
    from PySide6.QtCore import QMimeData, QUrl
    from PySide6.QtGui import QImage
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(path)])
    mime.setText(path)
    if mode == "image":
        image = QImage(path)
        if not image.isNull():
            mime.setImageData(image)
    return mime

def _person_request(opts: dict) -> PersonPageRequest:
    """The UI's JSON blob as a `PersonPageRequest`.

    Kept out of the `work()` closure so that closure stays a short, readable
    "fetch, decorate, emit" sequence.

    `dir` defaults to `""` — the sort key's *natural* direction — so a payload
    written before the sortable headers existed means exactly what it meant.
    """
    return PersonPageRequest(
        q=str(opts.get("q") or ""),
        limit=int(opts.get("limit") or DEFAULT_LIMIT),
        offset=int(opts.get("offset") or 0),
        sort=str(opts.get("sort") or DEFAULT_SORT),
        dir=str(opts.get("dir") or ""),
        include_deleted=bool(opts.get("include_deleted")))
