"""The nine CDP command verbs, as the mixin `CDPClient` inherits.

Part of the `cdp_client` family (façade: `backend/cdp_client.py`, Round J step
J-8). The implementations are the functions in
`backend/cdp_client_transport.py` — they take the client as their first
argument and own the framing — so every method here is a one-line delegation
to `wire.<name>(self, …)`.

Why this is its own module, and why it has **no** `from __future__ import
annotations`:

The API snapshot pins these nine signatures as
`(self, expression: str) -> Any` — the spelling the façade declared them
with. With PEP 563 in effect the annotations are strings, and `inspect.signature
renders them quoted (`(self, expression: 'str') -> 'Any'`), which the snapshot
reads as a changed public signature. The alternative — a signature that is
identical in meaning but different in text — is exactly what the snapshot
exists to catch, so the future import stays out and the spellings are
transcribed. `Optional` is spelled out for the same reason: the recorded
signature says `Optional[dict]`, not `dict | None`.

Inheritance is what makes this a *move* rather than a loss: `_class_drift`
sanctions a member that "moved UP into a shared base" when the same callable
with the same signature is still reachable through the class. It is, and the
two historical test seams survive it — an instance attribute (a test shadowing
`cdp.send`) beats an inherited method, and `cdp._ws` / `cdp._connected` are
still plain instance attributes, because the transport functions write to the
object they are handed.
"""

from typing import Any, Optional

from backend import cdp_client_transport as wire


class WireCommands:
    """The CDP command verbs `CDPClient` publishes — nine, see the module doc."""

    async def add_binding(self, name: str) -> bool:
        """Expose `window[name](payload)` as a `Runtime.bindingCalled` event."""
        return await wire.add_binding(self, name)

    async def add_script_on_new_document(self, source: str) -> str:
        """Re-inject `source` after every navigation. Returns its identifier."""
        return await wire.add_script_on_new_document(self, source)

    async def remove_script_on_new_document(self, identifier: str) -> bool:
        if not identifier:
            return False
        return await wire.remove_script_on_new_document(self, identifier)

    async def evaluate(self, expression: str) -> Any:
        return await wire.evaluate(self, expression)

    async def get_cookies(self, url: str = "") -> str:
        """A `Cookie` header string for the given origin.

        Used by the media cache's Python download path: the browser tab can
        load `images.virt-chat.com` through an `<img>` tag with the session
        cookies (no CORS), but the in-page `fetch()` needed for the old cache
        can be blocked by CORS. Downloading from Python with the same cookies
        bypasses that while still authenticating like the page.
        """
        return await wire.cookie_header(self, url)

    async def click_at(self, x: float, y: float) -> None:
        await wire.click_at(self, x, y)

    async def mouse_wheel(self, dx: float, dy: float, x: float,
                          y: float) -> None:
        await wire.mouse_wheel(self, dx, dy, x, y)

    async def get_element_rect(self, selector: str) -> Optional[dict]:
        return await wire.get_element_rect(self, selector)

    async def set_file_input_files(self, selector: str,
                                   files: list[str]) -> None:
        await wire.set_file_input_files(self, selector, files)
