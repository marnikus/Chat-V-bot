"""The world's own clock: waiting for it, and announcing it is live.

One `.db` file is one complete world: its people queue, its messages, its
labels and its undo timeline. The page is built BEFORE `ApplicationLifecycle
.startup` opens any of that, so every window faces the same two-sided race —
and both sides are served from here:

* `wait_for_world_open` / `run_when_world_open` — a read that arrives before
  the world is open WAITS for it and then runs, instead of failing with
  `history database is not open`: that error was a reply the window never got,
  so the table stayed empty until ↻ was pressed;
* `announce_world_live` — the ONE emitter that tells every window to reload
  from the world that is live now (PeopleChanged + UserDbChanged, plus
  LabelsChanged when a label store is given);
* `bridge.history_bridge._run_async` and
  `bridge.people_bridge._refresh_users_async` run their work through the
  runner, so the first request of a session is answered by itself;
* `services.undo_service.restart_world` calls the emitter after a switch;
* the boot reaches it through `Router.announce_world_ready()`, called once
  `ApplicationLifecycle.startup` finished opening the world.

Imports point down only: stdlib and `core.events` — no Qt, no bridges, no
other service, so either layer may call it.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time

from core.events import (EventBus, LabelsChanged, PeopleChanged,
                         UserDbChanged)

# Historical module constant remains patchable by legacy callers.
from core.scheduler import WAIT_S, POLL_STEP_S, Scheduler, poll

log = logging.getLogger("chatbot")


class AsyncioScheduler:
    """Production monotonic clock; the same polling policy as the fake."""

    def now(self) -> float:
        return time.monotonic()

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)

    async def until(self, predicate, timeout: float,
                    step: float = POLL_STEP_S) -> bool:
        return await poll(self, predicate, timeout, step)


class WorldGate:
    """Wait for a store, then run even on timeout so work reports its error."""

    def __init__(self, scheduler: Scheduler | None = None):
        self.scheduler = AsyncioScheduler() if scheduler is None else scheduler

    async def wait(self, store, timeout: float | None = None,
                   step: float = POLL_STEP_S) -> bool:
        if store is None or not hasattr(store, "is_open"):
            return False
        return await self.scheduler.until(
            lambda: store.is_open, WAIT_S if timeout is None else timeout, step)

    async def run(self, scope: str, coro, store, on_error=None) -> None:
        started = False
        try:
            await self.wait(store)
            started = True
            await coro
        except Exception as exc:                         # noqa: BLE001
            log.warning("archive %s failed: %s", scope, exc)
            if on_error is not None:
                on_error(scope, str(exc))
        finally:
            if not started and asyncio.iscoroutine(coro):
                coro.close()


async def wait_for_world_open(store, timeout: float | None = None,
                              step: float = 0.05) -> bool:
    """Compatibility facade; WAIT_S is still read at call time."""
    return await WorldGate().wait(store, timeout, step)


async def run_when_world_open(scope: str, coro, store, on_error=None) -> None:
    """Compatibility facade preserving the two-argument error callback."""
    await WorldGate().run(scope, coro, store, on_error)


def announce_world_live(bus: EventBus, labels=None,
                        reason: str = "db_switch") -> None:
    """Tell every world-bound window to reload from the world live now.

    `reason` travels in the payload as the action the JS windows report;
    each window reacts to the event itself — `userdb_changed` reloads the
    Full User Database and the DB Connection panels, `people_changed`
    re-renders User Memory, `labels_changed` the label pills.
    """
    bus.emit(PeopleChanged(reason=reason))
    bus.emit(UserDbChanged(payload=json.dumps(
        {"action": reason, "ok": True}, ensure_ascii=False)))
    _announce_labels(bus, labels)


def _announce_labels(bus: EventBus, labels) -> None:
    """A broken label store must not cost the other two announcements."""
    if labels is None:
        return
    try:
        bus.emit(LabelsChanged(
            payload=json.dumps(labels.state(), ensure_ascii=False)))
    except Exception as exc:                            # noqa: BLE001
        log.warning("label state not announced: %s", exc)
