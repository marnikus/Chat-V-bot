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

log = logging.getLogger("chatbot")

#: how long a request that raced the boot waits for the world to open. The
#: same 15 s the write gate waits for an outside holder: long enough for the
#: install migration on a big world, short enough to still answer with an
#: error instead of hanging forever.
WAIT_S = 15.0


async def wait_for_world_open(store, timeout: float | None = None,
                              step: float = 0.05) -> bool:
    """Wait until `store.is_open`; False when it never opened in time.

    Nothing is waited on when `store` is not a store (no `is_open`): a test
    double must not turn a unit test into a 15-second sleep. The caller runs
    its work either way — a world that never opened still reports its own
    error, exactly as before this helper existed.

    `timeout=None` means `WAIT_S`, read at call time so a test can shorten it.
    """
    if store is None or not hasattr(store, "is_open"):
        return False
    deadline = time.monotonic() + max(0.0, WAIT_S if timeout is None
                                      else timeout)
    while not store.is_open:
        if time.monotonic() >= deadline:
            return False
        await asyncio.sleep(step)
    return True


async def run_when_world_open(scope: str, coro, store, on_error=None) -> None:
    """Await `coro` once `store` is open, and never lose its failure.

    The archive's reply used to be an exception the window never heard:
    `userdb_page` before the world opened raised “history database is not
    open”, nothing answered the `req_id`, and the table stayed empty until ↻
    was pressed (bug 2026-09-11). Waiting here answers the same request; a
    world that never opens still reports its own error through `on_error`.
    """
    try:
        await wait_for_world_open(store)
        await coro
    except Exception as exc:                            # noqa: BLE001
        log.warning("archive %s failed: %s", scope, exc)
        if on_error is not None:
            on_error(scope, str(exc))


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
