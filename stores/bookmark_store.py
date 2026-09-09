"""Bookmark store — one file (bookmarks.json) holding a bare URL list."""

from __future__ import annotations

from core.result import Result
from stores.jsonio import load_json, save_json


DEFAULT_BOOKMARKS: list[str] = [
    "https://ru.virt-chat.com/chat",
    "https://ru.virt-chat.com/",
]


class BookmarkStore:
    """URL presets. Mutations return True on change, False when the
    store is untouched (duplicate, missing, blank); wrong-type
    arguments raise TypeError."""

    def __init__(self, path: str = "bookmarks.json") -> None:
        self._path = path
        self._data: list[str] = []
        self.load()

    def load(self) -> None:
        data = load_json(self._path, None)
        self._data = list(data) if isinstance(data, list) else list(DEFAULT_BOOKMARKS)

    def save(self) -> Result[None]:
        if save_json(self._path, self._data):
            return Result.ok(None)
        return Result.err(f"bookmarks save failed: {self._path}")

    def all(self) -> list[str]:
        return list(self._data)

    def add(self, url: str) -> bool:
        if not isinstance(url, str):
            raise TypeError(f"url must be a str, got {type(url).__name__}")
        url = url.strip()
        if not url or url in self._data:
            return False
        self._data.append(url)
        self.save()
        return True

    def remove(self, url: str) -> bool:
        if not isinstance(url, str):
            raise TypeError(f"url must be a str, got {type(url).__name__}")
        url = url.strip()
        if url not in self._data:
            return False
        self._data.remove(url)
        self.save()
        return True

    def set_all(self, urls: list[str]) -> bool:
        if not isinstance(urls, list):
            raise TypeError(f"urls must be a list, got {type(urls).__name__}")
        self._data = list(urls)
        self.save()
        return True
