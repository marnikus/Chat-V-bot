"""bookmark_store — the URL bookmark chips (config/bookmarks.json)."""

from __future__ import annotations

import logging
import os

from stores.jsonio import load_json, save_json

log = logging.getLogger("chatbot")

DEFAULT_BOOKMARKS: list[str] = [
    "https://ru.virt-chat.com/chat",
    "https://ru.virt-chat.com/",
]


class BookmarkStore:
    """Ordered, de-duplicated URL list. One file, atomic saves."""

    def __init__(self, path: str, data: list | None = None):
        self._path = path
        self._data: list[str] = []
        self._dirty = False
        if data is not None:
            self._data = list(data)
        else:
            self.load()

    def load(self) -> None:
        raw = load_json(self._path, default=None)
        if isinstance(raw, list):
            self._data = [str(u) for u in raw if isinstance(u, str)]
        else:
            self._data = list(DEFAULT_BOOKMARKS)

    def save(self, force: bool = False) -> bool:
        if not (self._dirty or force):
            return True
        ok = save_json(self._path, self._data)
        if ok:
            self._dirty = False
        return ok

    @property
    def dirty(self) -> bool:
        return self._dirty

    # ── API ──────────────────────────────────────────────────────
    def all(self) -> list[str]:
        return list(self._data)

    def set_all(self, urls: list) -> None:
        clean: list[str] = []
        for url in urls or []:
            text = str(url).strip()
            if text and text not in clean:
                clean.append(text)
        self._data = clean
        self._dirty = True

    def add(self, url: str) -> bool:
        """False when the URL was empty or already bookmarked."""
        text = str(url or "").strip()
        if not text or text in self._data:
            return False
        self._data.append(text)
        self._dirty = True
        return True

    def remove(self, url: str) -> bool:
        if url not in self._data:
            return False
        self._data.remove(url)
        self._dirty = True
        return True
