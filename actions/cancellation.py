"""Private cooperative-stop helpers for Area C1.

This module is deliberately dependency-free (stdlib only: no services, no Qt,
no actions.base*). Both action blocks (e.g. WaitPageLoad) and the run engine
(services/run/*) import it.

Contract (see docs/SAFETY_REFACTOR_AREA_C_IMPL_DESIGN_2026-09-10.md §2.1):

* `RunStopped` is an ordinary `Exception` signalling cooperative stop. It is
  distinct from `asyncio.CancelledError` (external task cancellation) and must
  never be retried, mapped to ActionResult, or mistaken for SKIP/FAIL.
* `is_stop_requested(engine)` prefers callable `engine.is_stopping()`, falls
  back to truthy `engine._stop_requested` for duck-typed callers, and fails
  open to False (engine=None, missing attrs, raising predicates).
* `sleep_or_stop` / `await_or_stop` slice long waits into short polls so stop
  surfaces promptly. `await_or_stop` is for READ-ONLY probes only: cancelling
  the local await never undoes a remote side effect.
"""

from __future__ import annotations

import asyncio
from typing import Any


class RunStopped(Exception):
    """Cooperative stop requested.

    Raised by stop-aware waits when the engine asks to stop. Translated to
    "stop"/"stopped" only at run-execution boundaries. Never retried.
    """


def is_stop_requested(engine: Any) -> bool:
    """True when engine asks to stop. Fails open to False."""
    if engine is None:
        return False
    try:
        predicate = getattr(engine, "is_stopping", None)
        if callable(predicate):
            return bool(predicate())
    except Exception:
        return False
    try:
        return bool(getattr(engine, "_stop_requested", False))
    except Exception:
        return False


def raise_if_stopped(engine: Any) -> None:
    """Raise RunStopped when is_stop_requested(engine)."""
    if is_stop_requested(engine):
        raise RunStopped()


async def sleep_or_stop(delay_s: float, engine: Any = None,
                        *, slice_s: float = 0.05) -> None:
    """Sleep `delay_s` seconds in short slices; raise RunStopped if stopped.

    delay<=0 still performs one stop check and returns immediately.
    slice_s is clamped to (0, delay] when delay>0.
    """
    raise_if_stopped(engine)
    try:
        delay = max(0.0, float(delay_s))
    except (TypeError, ValueError):
        delay = 0.0
    if delay <= 0:
        return
    try:
        sl = float(slice_s)
    except (TypeError, ValueError):
        sl = 0.05
    if not (sl > 0):
        sl = 0.05
    sl = min(sl, delay)
    loop = asyncio.get_event_loop()
    deadline = loop.time() + delay
    while True:
        remaining = deadline - loop.time()
        if remaining <= 0:
            raise_if_stopped(engine)
            return
        await asyncio.sleep(min(sl, remaining))
        raise_if_stopped(engine)


async def _cancel_and_reap(task: "asyncio.Task") -> None:
    """Cancel a probe we own and await it, suppressing whatever it raises.

    Awaiting after cancel is mandatory (no orphaned tasks); the probe's own
    CancelledError — or any error it raises while tearing down — must not
    mask the stop/cancellation that triggered the reap.
    """
    if task.done():
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    except Exception:
        pass


async def await_or_stop(awaitable: Any, engine: Any = None,
                        *, slice_s: float = 0.05) -> Any:
    """Await a read-only awaitable; raise RunStopped promptly if stopped.

    Wraps the awaitable in a Task, polls for completion/stop, and on stop
    cancels + awaits the task (suppressing its CancelledError) before raising
    RunStopped. Probe exceptions propagate unchanged. No orphaned tasks.
    Pre-stopped engines fail fast without starting the probe.
    """
    if is_stop_requested(engine):
        if asyncio.iscoroutine(awaitable):
            try:
                awaitable.close()
            except Exception:
                pass
        raise RunStopped()
    try:
        sl = float(slice_s)
    except (TypeError, ValueError):
        sl = 0.05
    if not (sl > 0):
        sl = 0.05
    # Ensure we own a Task we can cancel (awaitable may be a coroutine).
    task = asyncio.ensure_future(awaitable)
    try:
        while not task.done():
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=sl)
            except asyncio.TimeoutError:
                pass
            raise_if_stopped(engine)
        return task.result()
    except RunStopped:
        await _cancel_and_reap(task)
        raise
    except asyncio.CancelledError:
        # External cancellation while polling: cancel the probe too, then
        # propagate (we do not own the probe's side effects, but we must not
        # orphan the task).
        await _cancel_and_reap(task)
        raise


__all__ = ["RunStopped", "is_stop_requested", "raise_if_stopped",
           "sleep_or_stop", "await_or_stop"]
