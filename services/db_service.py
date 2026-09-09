"""DbService — world DB switching and world-bound undo, via HistoryService.

Handles DB lifecycle: switch_db, load/save world undo, migrate_install.
All methods return Result[T]; coroutines only here, @asyncSlot only in bridges.
Reusable without Qt or CDP.
"""

from __future__ import annotations

import logging
from typing import Any

from core.result import Result

log = logging.getLogger("chatbot")


class DbService:
    """Reusable DB facade — delegates to HistoryService (which owns HistoryDB)."""

    def __init__(self, history_service) -> None:
        self._hs = history_service

    async def switch_db(self, path: str) -> Result[dict[str, Any]]:
        try:
            # HistoryService.switch_db already wraps Result
            res = await self._hs.switch_db(path)
            return res if isinstance(res, Result) else Result.ok(res)
        except Exception as exc:  # noqa: BLE001
            return Result.err(str(exc))

    async def load_world_undo(self) -> Result[list[dict[str, Any]]]:
        try:
            res = await self._hs.load_world_undo()
            return res if isinstance(res, Result) else Result.ok(res)
        except Exception as exc:  # noqa: BLE001
            return Result.err(str(exc))

    async def save_world_undo(self, entries: list[dict[str, Any]]) -> Result[None]:
        try:
            res = await self._hs.save_world_undo(entries)
            return res if isinstance(res, Result) else Result.ok(None)
        except Exception as exc:  # noqa: BLE001
            return Result.err(str(exc))

    async def migrate_install(self) -> Result[dict[str, Any]]:
        try:
            res = await self._hs.migrate_install()
            return res if isinstance(res, Result) else Result.ok(res)
        except Exception as exc:  # noqa: BLE001
            return Result.err(str(exc))

    def db_path(self) -> Result[str]:
        try:
            inner = getattr(self._hs, "inner", None) or getattr(self._hs, "_inner", None) or self._hs
            # HistoryDB path is via inner.db.path when available
            db = getattr(inner, "db", None)
            if db and hasattr(db, "path"):
                return Result.ok(str(db.path))
            # fallback to HistoryService's world_media_dir parent? use config
            if hasattr(self._hs, "world_media_dir"):
                res = self._hs.world_media_dir()
                if isinstance(res, Result) and res.is_ok:
                    return Result.ok(str(res.value))
            return Result.err("db path not available")
        except Exception as exc:  # noqa: BLE001
            return Result.err(str(exc))
