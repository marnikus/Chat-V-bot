"""Guarded Playwright operations — the ONLY module that calls Playwright.

Every op: re-queries fresh (Angular re-renders), retries with backoff,
converts exceptions to OpError, logs at debug (F-NF: never crash on a
missing element).
"""
from __future__ import annotations

import asyncio

from ..core.logconf import get
from ..engine.errors import OpError

_log = get("ops")


class GuardedOps:
    def __init__(self, page, settings):
        self.page = page
        self.s = settings
        self.timeout_ms = int(getattr(settings, "op_timeout_ms", 8000))

    @property
    def timeout(self) -> float:
        return self.timeout_ms / 1000.0

    async def find(self, selector: str, timeout: float | None = None, retries: int = 2):
        last: Exception | None = None
        for attempt in range(retries + 1):
            try:
                loc = self.page.locator(selector).first
                await loc.wait_for(state="attached", timeout=int(self.timeout * 1000))
                return loc
            except Exception as e:  # noqa: BLE001
                last = e
                _log.debug("find failed [%s] attempt %d: %s", selector, attempt + 1, e)
                if attempt < retries:
                    await asyncio.sleep(0.4 * (attempt + 1))
        raise OpError(f"element not found: {selector}") from last

    async def exists(self, selector: str) -> bool:
        try:
            return (await self.page.locator(selector).count()) > 0
        except Exception:  # noqa: BLE001
            return False

    async def count(self, selector: str) -> int:
        try:
            return await self.page.locator(selector).count()
        except Exception:  # noqa: BLE001
            return 0

    async def text(self, selector: str) -> str:
        try:
            loc = self.page.locator(selector).first
            return ((await loc.inner_text(timeout=self.timeout_ms)) or "").strip()
        except Exception:  # noqa: BLE001
            return ""

    async def click(self, selector: str, timeout: float | None = None, retries: int = 1):
        try:
            loc = await self.find(selector, retries=retries)
            await loc.scroll_into_view_if_needed(timeout=self.timeout_ms)
            await loc.click(timeout=self.timeout_ms)
        except OpError:
            raise
        except Exception as e:  # noqa: BLE001
            raise OpError(f"click failed: {selector}: {e}") from e

    async def fill(self, selector: str, text: str) -> None:
        try:
            loc = await self.find(selector)
            await loc.fill(text, timeout=self.timeout_ms)
        except OpError:
            raise
        except Exception as e:  # noqa: BLE001
            raise OpError(f"fill failed: {selector}: {e}") from e

    async def set_files(self, selector: str, path: str) -> None:
        try:
            await self.page.locator(selector).first.set_input_files(path)
        except Exception as e:  # noqa: BLE001
            raise OpError(f"set_files failed: {selector}: {e}") from e

    async def scroll(self, selector: str, dy: int) -> None:
        try:
            loc = self.page.locator(selector).first
            await loc.scroll_into_view_if_needed(timeout=self.timeout_ms)
            await loc.hover(timeout=self.timeout_ms)
            await self.page.mouse.wheel(0, int(dy))
        except Exception as e:  # noqa: BLE001
            raise OpError(f"scroll failed: {selector}: {e}") from e

    async def keyboard_type(self, ch: str) -> None:
        try:
            await self.page.keyboard.type(ch)
        except Exception as e:  # noqa: BLE001
            raise OpError(f"typing failed: {e}") from e

    async def eval_js(self, js: str, *args) -> object:
        try:
            return await self.page.evaluate(js, *args)
        except Exception as e:  # noqa: BLE001
            raise OpError(f"eval_js failed: {e}") from e

    async def wait(self, seconds: float) -> None:
        await asyncio.sleep(seconds)
