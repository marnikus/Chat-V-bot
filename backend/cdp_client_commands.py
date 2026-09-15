"""CDP command helpers — the high-level actions over the transport.

Part of the `cdp_client` family (facade: `backend/cdp_client.py`,
Round H step H-B6). This file owns the command surface that used to live
directly on CDPClient: bindings, script injection, evaluate, cookies, input,
and file inputs. All bodies delegate to `cdp_client_transport`.

Design: docs/archive/2026-09-14-round-h/AREA_H_FINAL_VALIDATION_2026-09-14.md §6.2
"""

from __future__ import annotations

from typing import Any, Optional

from dataclasses import dataclass

from backend import cdp_client_transport as transport


@dataclass
class TabInfo:
    id: str
    title: str
    url: str
    ws_url: str


class CdpClientCommands:
    """Mixin — high-level CDP commands over the transport.

    The facade `CDPClient` inherits from this so the public API stays flat
    (API snapshot pins methods to `cdp_client.CDPClient`) while direct
    method count stays ≤15 (RULE 16 class LOC 150 / methods 15).
    """

    async def fetch_tabs(self) -> list[TabInfo]:  # type: ignore[no-redef]
        return [TabInfo(item.get("id", ""), item.get("title", ""),
                        item.get("url", ""),
                        item.get("webSocketDebuggerUrl", ""))
                for item in await transport.fetch_tabs(self)]

    async def add_binding(self, name: str) -> bool:
        return await transport.add_binding(self, name)

    async def add_script_on_new_document(self, source: str) -> str:
        return await transport.add_script_on_new_document(self, source)

    async def remove_script_on_new_document(self, identifier: str) -> bool:
        if not identifier:
            return False
        return await transport.remove_script_on_new_document(self, identifier)

    async def evaluate(self, expression: str) -> Any:
        return await transport.evaluate(self, expression)

    async def get_cookies(self, url: str = "") -> str:
        return await transport.cookie_header(self, url)

    async def click_at(self, x: float, y: float) -> None:
        await transport.click_at(self, x, y)

    async def mouse_wheel(self, dx: float, dy: float, x: float, y: float) -> None:
        await transport.mouse_wheel(self, dx, dy, x, y)

    async def get_element_rect(self, selector: str) -> Optional[dict]:
        return await transport.get_element_rect(self, selector)

    async def set_file_input_files(self, selector: str, files: list[str]) -> None:
        await transport.set_file_input_files(self, selector, files)
