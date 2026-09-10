"""Bookmark store — the `url_presets` list of one JSON file.

`add()` / `remove()` answer the question their two callers actually ask —
"did the list change?" — with an `Outcome`/`Refusal` (see
`stores/outcome.py`): the value is a bool, `is_ok`/`is_err` still read as a
`Result`, and `bool()` is the same answer, which is what
`bridge/cdp_bridge.py` needs before it reports a bookmark as saved.

Like `BlockStore`, an accepted write is on disk when the call returns.
"""

from __future__ import annotations

from typing import Any

from core.result import Result, err, ok
from stores.json_store import JsonFileStore
from stores.outcome import Refusal, changed, refused, unchanged

#: the two addresses a fresh install starts with — the chat, and the site
#: root, because the chat URL changes with the active tab
DEFAULT_URLS = ["https://ru.virt-chat.com/chat", "https://ru.virt-chat.com/"]
DEFAULT_BOOKMARKS = DEFAULT_URLS

SECTION = "url_presets"


class BookmarkStore(JsonFileStore):
    """One list of URLs, atomic writes, no silent duplicates."""

    DEFAULT_FILE = "config.json"
    SAVE_ALWAYS = True            # every write persists, as before the split

    # ── reads ────────────────────────────────────────────────────
    def all(self) -> list[str]:
        raw = self._data.get(SECTION)
        if isinstance(raw, list):
            return list(raw)
        return list(DEFAULT_URLS)

    # ── writes ───────────────────────────────────────────────────
    def add(self, url: str) -> Result[bool]:
        """File one address. Truthy only when the list actually grew."""
        clean = str(url or "").strip()
        if not clean:
            return refused("empty url", str(url or ""))
        presets = self.all()
        if clean in presets:
            return refused("duplicate", clean)
        presets.append(clean)
        return self._write(presets)

    def remove(self, url: str) -> Result[bool]:
        """Drop one address. A no-op removal is `Outcome(False)`, not an error:
        the caller asked for "not in the list", and it is not."""
        clean = str(url or "").strip()      # add() strips on write
        presets = self.all()
        if clean not in presets:
            return unchanged()
        presets.remove(clean)
        return self._write(presets)

    def set_all(self, urls: Any) -> Result[None]:
        """Replace the whole list. A non-list is a programmer error, not a
        request to forget every bookmark: `list(urls)` raises and the old list
        stays exactly as it was (BMK-07)."""
        items = list(urls)
        self._data[SECTION] = items
        self._touch()
        return ok(None) if not self._dirty else err("save failed", self.path)

    def _write(self, presets: list[str]) -> Result[bool]:
        self._data[SECTION] = list(presets)
        self._touch()
        if self._dirty:
            # the file rejected the write; the in-memory list keeps it, and
            # the caller must not report success it cannot show
            return Refusal("save failed", self.path)
        return changed(True)
