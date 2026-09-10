"""Block store — `custom_blocks`, plus the named preset sections of a
legacy single-file install (stack_presets / template_presets).

One JSON file, and — unlike the overlay stores — every accepted write is on
disk when the call returns: `ConfigManager` treats these two stores as the
"the UI just clicked save" stores, so `SAVE_ALWAYS` is set here and
`save()`/`flush()` answer "did the file take the payload?" with a bool while
the per-operation `named_*` calls keep reporting a `Result`.
"""

from __future__ import annotations

import copy
from datetime import datetime
from typing import Any

from core.result import Result, err, ok

from stores.json_store import JsonFileStore


class BlockStore(JsonFileStore):
    """Named sections + the `custom_blocks` list, over one file."""

    DEFAULT_FILE = "config.json"
    SAVE_ALWAYS = True            # every write persists, as before the split

    # ── named sections (stack_presets, template_presets) ────────
    def named_all(self, section: str) -> dict[str, Any]:
        raw = self._data.get(section)
        return copy.deepcopy(raw) if isinstance(raw, dict) else {}

    def named_get(self, section: str, name: str, default: Any = None) -> Any:
        return self.named_all(section).get(str(name), default)

    def named_set(self, section: str, name: str, value: Any) -> Result[None]:
        all_items = self.named_all(section)
        all_items[str(name)] = value
        return self._write_section(section, all_items)

    def named_delete(self, section: str, name: str) -> Result[bool]:
        all_items = self.named_all(section)
        if str(name) not in all_items:
            return ok(False)
        del all_items[str(name)]
        return self._write_section(section, all_items, changed=True)

    # ── the list section the facade reads as one block ───────────
    def all(self) -> list[dict[str, Any]]:
        """The whole custom_blocks list (ConfigManager facade view)."""
        return self.custom_blocks()

    def set_all(self, blocks: Any) -> Result[None]:
        items = copy.deepcopy(blocks) if isinstance(blocks, list) else []
        self._data["custom_blocks"] = items
        return self._saved()

    def custom_blocks(self) -> list[dict[str, Any]]:
        raw = self._data.get("custom_blocks")
        return copy.deepcopy(raw) if isinstance(raw, list) else []

    def save_custom_block(self, name: str,
                          block: Any) -> Result[None]:
        name = (name or "").strip()
        if not name or not isinstance(block, dict):
            return err("name and block required")
        items = [b for b in self.custom_blocks()
                 if isinstance(b, dict) and b.get("name") != name]
        items.append({"name": name, "block": block,
                      "updated_at": datetime.now().isoformat(
                          timespec="seconds")})
        self._data["custom_blocks"] = items
        return self._saved()

    def delete_custom_block(self, name: str) -> Result[bool]:
        name = (name or "").strip()      # save_custom_block strips on write
        items = self.custom_blocks()
        filtered = [b for b in items
                    if isinstance(b, dict) and b.get("name") != name]
        if len(filtered) == len(items):
            return ok(False)
        self._data["custom_blocks"] = filtered
        return ok(True) if self._saved().is_ok else \
            err("save failed", "custom_blocks")

    # ── the one write path ───────────────────────────────────────
    def _write_section(self, section: str, items: dict[str, Any],
                       changed: bool = False) -> Result[Any]:
        self._data[section] = items
        saved = self._saved()
        if not saved.is_ok:
            return saved
        return ok(True) if changed else ok(None)

    def _saved(self) -> Result[None]:
        """Persist now (this store writes inline) and report it honestly."""
        self._touch()
        return ok(None) if not self._dirty else err("save failed", self.path)
