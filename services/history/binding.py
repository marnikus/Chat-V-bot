"""HistoryBinding: internal HistoryService responsibilities."""

from __future__ import annotations
import asyncio
import logging

log = logging.getLogger("chatbot")


class HistoryBinding:
    async def _install_push_binding(self) -> None:
        if self._binding or not hasattr(self.cdp, "add_binding"):
            return
        try:
            ok = await self.cdp.add_binding("__cvbPush")
        except Exception as exc:
            log.debug("push binding unavailable: %s", exc)
            return
        if ok:
            self._binding = True
            if hasattr(self.cdp, "on_event"):
                self.cdp.on_event("Runtime.bindingCalled", self._on_binding)

    async def _rebind(self) -> None:
        self._binding = False
        await self._install_push_binding()

    def _on_disconnected(self) -> None:
        self._binding = False

    def _on_binding(self, params: dict):
        return (
            None
            if (params or {}).get("name") != "__cvbPush"
            else self.collector.handle_push((params or {}).get("payload") or "")
        )

    def start(self) -> None:
        if not ((self._task and not self._task.done()) or not self.enabled):
            self._task = asyncio.ensure_future(self.collector.run())

    async def _stop_collector(self) -> dict:
        state = {
            "task": bool(self._task and not self._task.done()),
            "collector": bool(getattr(self.collector, "running", False)),
        }
        self.collector.stop()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
            self._task = None
        return state

    def _restart_collector(self, state) -> None:
        if state and state.get("task"):
            self.start()
        elif state and state.get("collector"):
            self.collector.start()
