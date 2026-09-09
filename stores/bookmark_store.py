"""Bookmark store — url_presets list."""

from __future__ import annotations

from core.result import Result, ok, err
from stores.atomic import AtomicJsonStore


DEFAULT_URLS = ["https://ru.virt-chat.com/chat", "https://ru.virt-chat.com/"]
DEFAULT_BOOKMARKS = DEFAULT_URLS


class BookmarkStore:
    def __init__(self, atomic: AtomicJsonStore | None = None,
                 path: str = "config.json") -> None:
        # ConfigManager passes a *path* positionally; the store tests pass
        # an *AtomicJsonStore*. Accept either.
        if isinstance(atomic, AtomicJsonStore):
            self._atomic = atomic
        elif isinstance(atomic, str) and atomic:
            self._atomic = AtomicJsonStore(atomic)
        else:
            self._atomic = AtomicJsonStore(path)

    # ── lifecycle (ConfigManager load()/save()) ─────────────────
    def load(self) -> None:
        self._atomic.load()

    def reload(self) -> None:
        self._atomic.load()

    def save(self):
        return self._atomic.save()

    def flush(self):
        return self._atomic.save()

    def all(self) -> list[str]:
        raw = self._atomic.get("url_presets", default=None)
        if isinstance(raw, list):
            return list(raw)
        return list(DEFAULT_URLS)

    def add(self, url: str) -> Result[None]:
        url = (url or "").strip()
        if not url:
            return err("empty url")
        presets = self.all()
        if url not in presets:
            presets.append(url)
            self._atomic.set("url_presets", presets)
            return self._atomic.save()
        return ok(None)

    def remove(self, url: str) -> Result[None]:
        url = (url or "").strip()  # add() strips on write
        presets = self.all()
        if url in presets:
            presets.remove(url)
            self._atomic.set("url_presets", presets)
            return self._atomic.save()
        return ok(None)

    def set_all(self, urls: list[str]) -> Result[None]:
        self._atomic.set("url_presets", list(urls))
        return self._atomic.save()
