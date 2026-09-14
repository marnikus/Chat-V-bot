"""Event fan-out of the CDP client — the listener table and its isolation.

Part of the `cdp_client` family (facade: `backend/cdp_client.py`). The
client talks to one Chrome tab; many subsystems (the push channel, the
collector, the run engine) subscribe to CDP events on it. This module owns
the table and the one rule it must never break: a listener that raises — or
an async listener with no running loop — must never stop the remaining
listeners or the receive loop (Round H step H-B6).

Import direction: this module needs nothing from the client; the facade
delegates in, so nothing here can import `backend.cdp_client` back.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from typing import Callable

log = logging.getLogger("chatbot")


class CdpEvents:
    """`method → [callbacks]` and the isolated dispatch over it."""

    def __init__(self):
        self._listeners: dict[str, list[Callable]] = {}

    def on_event(self, method: str, callback: Callable) -> Callable:
        """Subscribe to a CDP event (e.g. `Runtime.bindingCalled`)."""
        self._listeners.setdefault(method, []).append(callback)
        return callback

    def off_event(self, method: str,
                  callback: Callable | None = None) -> None:
        """Unsubscribe one callback, or every callback for `method`."""
        if callback is None:
            self._listeners.pop(method, None)
            return
        handlers = self._listeners.get(method)
        if handlers and callback in handlers:
            handlers.remove(callback)

    def dispatch(self, frame: dict) -> None:
        """Deliver one received event frame to its listeners.

        A listener that raises (or an async listener with no running loop)
        must never stop the remaining listeners or the receive loop.
        """
        method = frame.get("method")
        if not method:
            return
        params = frame.get("params") or {}
        for callback in list(self._listeners.get(method, ())):
            try:
                result = callback(params)
                if inspect.isawaitable(result):
                    try:
                        asyncio.get_event_loop().create_task(result)
                    except RuntimeError:      # no loop — drop, do not crash
                        result.close()
            except Exception as e:            # noqa: BLE001 - isolation
                log.warning("CDP listener for %s failed: %s", method, e)
