"""Block store — stack_presets, template_presets, custom_blocks."""

from __future__ import annotations

import copy
from typing import Any
from datetime import datetime

from core.result import Result, ok, err
from stores.atomic import AtomicJsonStore


class BlockStore:
    def __init__(self, atomic: AtomicJsonStore | None = None, path: str = "config.json") -> None:
        self._atomic = atomic or AtomicJsonStore(path)

    # generic named section helpers
    def named_all(self, section: str) -> dict[str, Any]:
        raw = self._atomic.get(section, default={})
        return copy.deepcopy(raw) if isinstance(raw, dict) else {}

    def named_get(self, section: str, name: str, default: Any = None) -> Any:
        return self.named_all(section).get(name, default)

    def named_set(self, section: str, name: str, value: Any) -> Result[None]:
        all_items = self.named_all(section)
        all_items[str(name)] = value
        self._atomic.set(section, all_items)
        return self._atomic.save()

    def named_delete(self, section: str, name: str) -> Result[bool]:
        all_items = self.named_all(section)
        if str(name) not in all_items:
            return ok(False)
        del all_items[str(name)]
        self._atomic.set(section, all_items)
        res = self._atomic.save()
        return ok(True) if res.is_ok else err(res.detail or res.code or "save failed")

    # custom_blocks is a list
    def custom_blocks(self) -> list[dict[str, Any]]:
        raw = self._atomic.get("custom_blocks", default=[])
        return copy.deepcopy(raw) if isinstance(raw, list) else []

    def save_custom_block(self, name: str, block: dict[str, Any]) -> Result[None]:
        name = (name or "").strip()
        if not name or not isinstance(block, dict):
            return err("name and block required")
        items = [b for b in self.custom_blocks() if isinstance(b, dict) and b.get("name") != name]
        items.append({"name": name, "block": block, "updated_at": datetime.now().isoformat(timespec="seconds")})
        self._atomic.set("custom_blocks", items)
        return self._atomic.save()

    def delete_custom_block(self, name: str) -> Result[bool]:
        name = (name or "").strip()  # save_custom_block strips on write
        items = self.custom_blocks()
        filtered = [b for b in items if isinstance(b, dict) and b.get("name") != name]
        if len(filtered) == len(items):
            return ok(False)
        self._atomic.set("custom_blocks", filtered)
        res = self._atomic.save()
        return ok(True) if res.is_ok else err(res.detail or res.code or "save failed")
