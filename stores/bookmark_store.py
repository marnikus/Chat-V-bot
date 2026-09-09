"""Bookmark store — url_presets list."""

from __future__ import annotations

from core.result import Result
from stores.atomic import AtomicJsonStore


DEFAULT_URLS = ["https://ru.virt-chat.com/chat", "https://ru.virt-chat.com/"]


class BookmarkStore:
    def __init__(self, atomic: AtomicJsonStore | None = None, path: str = "config.json") -> None:
        self._atomic = atomic or AtomicJsonStore(path)

    def all(self) -> list[str]:
        raw = self._atomic.get("url_presets", default=None)
        if isinstance(raw, list):
            return list(raw)
        return list(DEFAULT_URLS)

    def add(self, url: str) -> Result[None]:
        url = (url or "").strip()
        if not url:
            return Result.err("empty url")
        presets = self.all()
        if url not in presets:
            presets.append(url)
            self._atomic.set("url_presets", presets)
            return self._atomic.save()
        return Result.ok(None)

    def remove(self, url: str) -> Result[None]:
        url = (url or "").strip()  # add() strips on write
        presets = self.all()
        if url in presets:
            presets.remove(url)
            self._atomic.set("url_presets", presets)
            return self._atomic.save()
        return Result.ok(None)

    def set_all(self, urls: list[str]) -> Result[None]:
        self._atomic.set("url_presets", list(urls))
        return self._atomic.save()
