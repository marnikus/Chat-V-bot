from __future__ import annotations

import asyncio
import logging

log = logging.getLogger("chatbot")


class ApplicationLifecycle:
    def __init__(self, app, cdp, memory, engine, history, bridge):
        self.app = app
        self.cdp = cdp
        self.memory = memory
        self.engine = engine
        self.history = history
        self.bridge = bridge
        self._shutdown_started = False

    def bind(self, window) -> None:
        window.closing.connect(lambda: asyncio.ensure_future(self.shutdown()))

    async def startup(self) -> None:
        await self.memory.init()
        try:
            await self.history.init()
            self.history.start()
        except Exception as exc:
            log.warning("Message archive unavailable: %s", exc)
        try:
            await self.bridge.sync_world_state()
        except Exception as exc:
            log.warning("world state sync failed: %s", exc)
        await self._announce_world_ready()
        log.info("Backend ready")
        await asyncio.sleep(0.5)
        self.bridge.get_tabs()

    async def _announce_world_ready(self) -> None:
        """The world is open: tell the windows, so they load by themselves.

        The page boots while this method is still opening the world, so its
        first requests for the people list / the database window came back
        empty and stayed empty until the user pressed refresh (2026-09-11).
        """
        try:
            await self.bridge.announce_world_ready()
        except Exception as exc:                        # noqa: BLE001
            log.warning("world ready broadcast failed: %s", exc)

    async def shutdown(self) -> None:
        if self._shutdown_started:
            return
        self._shutdown_started = True
        log.info("Graceful shutdown…")
        try:
            self.engine.stop()
            pending = list(getattr(self.bridge, "_undo_pendings", None) or [])
            if pending:
                await asyncio.wait_for(asyncio.gather(*pending, return_exceptions=True), timeout=2.0)
            tasks = [task for task in asyncio.all_tasks() if task is not asyncio.current_task()]
            for task in tasks:
                task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            await self.cdp.disconnect()
            await self.history.close()
            await self.memory.close()
        except Exception as exc:
            log.warning("Shutdown cleanup warning: %s", exc)
        finally:
            log.info("Shutdown complete")
            self.app.quit()

    def start(self, loop) -> None:
        loop.create_task(self.startup())
