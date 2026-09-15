"""How a wire slot hands work to an async part: guards, scheduling, refusals.

Part of the `history_bridge` family (facade: `bridge/history_bridge.py`,
Round J step J-1). The facade declares the QWebChannel surface — seven
signals and twenty-one `@Slot`s, every name and signature frozen — and this
module owns the policy all twenty-one of those slots share, so the facade
reads as a wire table instead of a dispatch mechanism:

* a slot is a **synchronous** call from JavaScript and cannot await, so the
  coroutine has to be scheduled (`run_async`) — on the world's loop, and
  only while the world is open (`services/world_events.run_when_world_open`);
* most slots need the archive to exist. `ask` announces its absence on
  `history_error` (with the slot's scope, so the UI can say *what* failed);
  `run_if_archive` refuses silently, which is the delete/undo surface's
  contract — a person who is not there is not an error;
* neither guard may raise: they run inside a Qt slot, where an exception
  escapes into the event loop and nowhere useful.

The parts (`history_bridge_read` / `_delete` / `_media` / `_settings`) hold
the coroutines themselves; this module is the contract between them and the
wire. Imports go one way: parts never import the facade back.
"""

from __future__ import annotations

import asyncio
import logging

from services.world_events import run_when_world_open

log = logging.getLogger("chatbot")


def schedule(coro) -> bool:
    """Hand `coro` to the running loop. False when there is no loop at all.

    A dropped coroutine is closed rather than left to be garbage-collected
    mid-flight, which is what turns "no loop" from a warning into a clean
    refusal (`RuntimeWarning: coroutine was never awaited` is a bug report
    nobody reads).
    """
    try:
        asyncio.ensure_future(coro)
        return True
    except RuntimeError:
        coro.close()
        return False


def run_async(bridge, scope: str, coro) -> None:
    """Wait for the world to be open, then run `coro`, or drop it with a
    debug line (the boot's `announce_world_ready` path is what unblocks the
    queued ones)."""
    if not schedule(run_when_world_open(
            scope, coro, getattr(bridge.ctx.archive, "db", None),
            bridge.history_error.emit)):
        log.debug("no running event loop — %s dropped", scope)


def ask(bridge, scope: str, fn, *args) -> bool:
    """Guard + schedule `fn(bridge, *args)`.

    False — and an announcement on `history_error` naming `scope` — when the
    archive is missing; True once the work is scheduled. The slot answers
    synchronously either way (its payload leaves on a signal, not by return).
    """
    if bridge.ctx.archive is None:
        bridge.history_error.emit(scope, "the message archive is not "
                                        "running")
        return False
    run_async(bridge, scope, fn(bridge, *args))
    return True


def run_if_archive(bridge, scope: str, fn, *args) -> bool:
    """Like `ask` minus the error announcement — a silent refusal."""
    if bridge.ctx.archive is None:
        return False
    run_async(bridge, scope, fn(bridge, *args))
    return True
