"""HistoryService (trimmed) — 15 explicit methods, returns Result[T].

Wraps backend.history_service.HistoryService but exposes only the 15 methods
that bridges need. No __getattr__ — every allowed method is explicit and
typed via HistoryServiceProto. MediaStore is called only via this service
(or MediaService which delegates here), never directly by CollectorService
or bridges. Reusable without Qt.
"""

from __future__ import annotations

import logging
from typing import Any

from core.result import Result
from backend.history_service import HistoryService as BackendHistory

log = logging.getLogger("chatbot")


class HistoryService:
    """Facade with Result[T] and trimmed surface — 15 methods, reusable."""

    def __init__(self, *args, **kwargs) -> None:
        self._inner = BackendHistory(*args, **kwargs)

    # --- lifecycle ---
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

    # --- settings ---
    def settings(self) -> Result[dict[str, Any]]:
        try:
            return Result.ok(self._inner.settings())
        except Exception as exc:  # noqa: BLE001
            return Result.err(str(exc))

    def apply_settings(self, patch: dict[str, Any]) -> Result[dict[str, Any]]:
        try:
            res = self._inner.apply_settings(patch)
            return Result.ok(res)
        except Exception as exc:  # noqa: BLE001
            return Result.err(str(exc))

    def preview_settings(self) -> Result[dict[str, Any]]:
        try:
            return Result.ok(self._inner.preview_settings())
        except Exception as exc:  # noqa: BLE001
            return Result.err(str(exc))

    def set_my_nick(self, nick: str) -> Result[str]:
        try:
            clean = self._inner.set_my_nick(nick)
            return Result.ok(clean)
        except Exception as exc:  # noqa: BLE001
            return Result.err(str(exc))

    # --- queries ---
    async def page(self, nick: str, **kwargs) -> Result[dict[str, Any]]:
        try:
            payload = await self._inner.page(nick, **kwargs)
            return Result.ok(payload)
        except Exception as exc:  # noqa: BLE001
            return Result.err(str(exc))

    @property
    def query(self) -> Any:
        # read-model, still returns raw query object (bridge adapts to Result)
        return self._inner.query  # type: ignore[no-any-return]

    # --- world / undo ---
    async def load_world_undo(self) -> Result[list[dict[str, Any]]]:
        try:
            entries = await self._inner.load_world_undo()
            return Result.ok(entries)
        except Exception as exc:  # noqa: BLE001
            return Result.err(str(exc))

    async def save_world_undo(self, entries: list[dict[str, Any]]) -> Result[None]:
        try:
            await self._inner.save_world_undo(entries)
            return Result.ok(None)
        except Exception as exc:  # noqa: BLE001
            return Result.err(str(exc))

    async def switch_db(self, path: str) -> Result[dict[str, Any]]:
        try:
            res = await self._inner.switch_db(path)
            return Result.ok(res)
        except Exception as exc:  # noqa: BLE001
            return Result.err(str(exc))

    async def migrate_install(self) -> Result[dict[str, Any]]:
        try:
            res = await self._inner.migrate_install()
            return Result.ok(res)
        except Exception as exc:  # noqa: BLE001
            return Result.err(str(exc))

    # --- media dirs ---
    def world_media_dir(self, path: str = "") -> Result[str]:
        try:
            return Result.ok(self._inner.world_media_dir(path))
        except Exception as exc:  # noqa: BLE001
            return Result.err(str(exc))

    def media_base_dir(self) -> Result[str]:
        try:
            return Result.ok(self._inner.media_base_dir())
        except Exception as exc:  # noqa: BLE001
            return Result.err(str(exc))

    # --- expose inner for advanced use (read-only) ---
    @property
    def inner(self) -> BackendHistory:
        return self._inner
