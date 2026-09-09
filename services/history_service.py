"""HistoryService (trimmed) — ~15 public methods, returns Result[T].

Wraps backend.history_service.HistoryService but exposes only the 15 methods
that bridges need. MediaStore is called only via this service, never directly
by CollectorService or bridges.
"""

from __future__ import annotations

import logging
from typing import Any

from core.result import Result
from backend.history_service import HistoryService as BackendHistory

log = logging.getLogger("chatbot")

# Trimmed public API target: 15 methods
ALLOWED = {
    "init", "close", "start", "settings", "apply_settings",
    "page", "preview_settings", "set_my_nick", "load_world_undo", "save_world_undo",
    "switch_db", "migrate_install", "world_media_dir", "media_base_dir", "query",
}


class HistoryService:
    """Facade with Result[T] and trimmed surface."""

    def __init__(self, *args, **kwargs) -> None:
        self._inner = BackendHistory(*args, **kwargs)

    # delegate trimming: only these are exposed
    async def init(self) -> Result[Any]:
        try:
            await self._inner.init()
            return Result.ok(self._inner)
        except Exception as exc:  # noqa: BLE001
            return Result.err(str(exc))

    async def close(self) -> Result[None]:
        try:
            await self._inner.close()
            return Result.ok(None)
        except Exception as exc:  # noqa: BLE001
            return Result.err(str(exc))

    def start(self) -> Result[None]:
        try:
            self._inner.start()
            return Result.ok(None)
        except Exception as exc:  # noqa: BLE001
            return Result.err(str(exc))

    def settings(self) -> Result[dict[str, Any]]:
        try:
            return Result.ok(self._inner.settings())
        except Exception as exc:  # noqa: BLE001
            return Result.err(str(exc))

    async def page(self, nick: str, **kwargs) -> Result[dict[str, Any]]:
        try:
            payload = await self._inner.page(nick, **kwargs)
            return Result.ok(payload)
        except Exception as exc:  # noqa: BLE001
            return Result.err(str(exc))

    async def switch_db(self, path: str) -> Result[dict[str, Any]]:
        try:
            res = await self._inner.switch_db(path)
            return Result.ok(res)
        except Exception as exc:  # noqa: BLE001
            return Result.err(str(exc))

    # proxy any other needed attribute for backward compat
    def __getattr__(self, name: str):
        if name in ALLOWED or name.startswith("_"):
            return getattr(self._inner, name)
        raise AttributeError(name)
