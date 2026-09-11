"""Private cooperative-stop helpers (AREA C1).

Leaf module: stdlib only, no services/Qt imports. Actions and the run engine
share the stop predicate through here so ``engine.is_stopping()`` stays the
single duck-compatible query.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Awaitable, Callable


class RunStopped(Exception):
    """Private cooperative-stop signal.

    Raised when ``is_stop_requested(engine)`` is true at a defined boundary.
    Caught only at run-execution boundaries and translated to the existing
    ``stop``/``stopped`` statuses. Never serialized, never added to
    ``ActionResult``, never confused with ``asyncio.CancelledError`` (external
    cancellation), which must propagate after cleanup.
    """


def _as_predicate(stop) -> Callable[[], bool] | None:
    """Normalise ``stop`` to a ``() -> bool`` predicate or None.

    Accepts None, an engine with ``is_stopping``/``_stop_requested``, or a
    bare callable. A broken predicate fails open to False (never crashes a
    wait); the engine-level tests pin fail-open.
    """
    if stop is None:
        return None
    if callable(stop) and not hasattr(stop, "is_stopping") and not hasattr(
        stop, "_stop_requested"
    ):
        # Bare callable predicate.
        def _call() -> bool:
            try:
                return bool(stop())
            except Exception:
                return False

        return _call
    # Engine-like object.
    fn = getattr(stop, "is_stopping", None)
    if callable(fn):

        def _engine() -> bool:
            try:
                return bool(fn())
            except Exception:
                return False

        return _engine
    # Compatibility fallback for old duck-typed callers.
    def _flag() -> bool:
        try:
            return bool(getattr(stop, "_stop_requested", False))
        except Exception:
            return False

    return _flag


def is_stop_requested(engine) -> bool:
    """True when the engine asks for cooperative stop (fail-open)."""
    if engine is None:
        return False
    pred = _as_predicate(engine)
    if pred is None:
        return False
    return pred()


def check_stopped(engine) -> None:
    """Raise :class:`RunStopped` when stop was requested."""
    if is_stop_requested(engine):
        raise RunStopped


async def sleep_with_stop(
    delay_s: float, engine, *, slice_s: float = 0.02
) -> None:
    """Cooperative sleep: raises :class:`RunStopped` promptly on stop.

    Checks before/after and sleeps in slices so a stop during a long
    pre-delay/poll-gap/backoff is honored without waiting out the delay.
    ``delay_s <= 0`` still performs a stop check.
    """
    if is_stop_requested(engine):
        raise RunStopped
    try:
        remaining = max(0.0, float(delay_s))
    except (TypeError, ValueError):
        remaining = 0.0
    if remaining <= 0:
        return
    try:
        step = float(slice_s)
    except (TypeError, ValueError):
        step = 0.02
    if step <= 0:
        step = 0.02
    deadline = time.monotonic() + remaining
    while True:
        if is_stop_requested(engine):
            raise RunStopped
        now = time.monotonic()
        left = deadline - now
        if left <= 0:
            break
        await asyncio.sleep(min(step, left))
    if is_stop_requested(engine):
        raise RunStopped


def _step_seconds(slice_s, default: float = 0.05) -> float:
    """The poll slice as a positive float; garbage, 0 and negatives fall back.

    A supervisor that slept for a computed `0` would busy-loop and starve the
    loop it is supposed to stay responsive to, so the slice is never smaller
    than the default.
    """
    try:
        step = float(slice_s)
    except (TypeError, ValueError):
        step = default
    return step if step > 0 else default


def _as_supervised_task(awaitable_factory: Callable[[], Awaitable[Any]]):
    """Create the ONE task that gets supervised.

    The factory may return a coroutine or an already-created future/task; the
    latter is adopted rather than wrapped, so the caller keeps its handle.
    """
    coro = awaitable_factory()
    if asyncio.isfuture(coro) or isinstance(coro, asyncio.Task):
        return coro
    return asyncio.ensure_future(coro)


def _discard_result(task) -> None:
    """Consume a settled task's outcome so asyncio logs no unretrieved error."""
    try:
        task.result()
    except (asyncio.CancelledError, Exception):
        pass


async def _cancel_and_drain(task) -> None:
    """Cancel the supervised task and await it — never leave an orphan behind.

    The task's own ``CancelledError`` is swallowed here on purpose: the
    exception the caller sees must stay the one this helper chose to raise
    (``RunStopped`` / ``TimeoutError``), and an external cancellation is
    re-raised by the caller after this returns.
    """
    task.cancel()
    try:
        await task
    except (asyncio.CancelledError, Exception):
        pass


def _accept_or_stop(task, engine):
    """Return a finished task's result — unless stop arrived at the same time.

    Stop wins over a result that landed concurrently with the request, because
    a user who pressed Stop must never see the step reported as completed.
    """
    if not is_stop_requested(engine):
        return task.result()
    _discard_result(task)
    raise RunStopped


async def _poll_supervised(task, engine, deadline_monotonic, step) -> Any:
    """The supervision loop: stop → deadline → done → sleep one slice.

    Raises ``RunStopped`` on stop, ``TimeoutError`` on deadline expiry and
    returns the task's result once it lands. ``asyncio.CancelledError`` from
    outside propagates through the caller, which drains the task first.
    """
    while True:
        if is_stop_requested(engine):
            await _cancel_and_drain(task)
            raise RunStopped
        if deadline_monotonic is not None and time.monotonic() >= deadline_monotonic:
            await _cancel_and_drain(task)
            raise TimeoutError
        if task.done():
            return _accept_or_stop(task, engine)
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=step)
        except asyncio.TimeoutError:
            continue


async def await_with_stop(
    awaitable_factory: Callable[[], Awaitable[Any]],
    engine,
    *,
    slice_s: float = 0.05,
    deadline_monotonic: float | None = None,
) -> Any:
    """Await a read-only operation with stop/deadline supervision.

    Creates ONE task from ``awaitable_factory()``, polls in slices, and on
    stop/deadline cancels + awaits it (no orphaned task). Raises
    :class:`RunStopped` on stop, :class:`TimeoutError` on deadline expiry,
    and propagates external ``CancelledError`` after cancelling + awaiting
    the inner task.

    Only read-only awaits (WaitPageLoad probes) may use this: cancelling the
    local await of a write does not undo the remote side effect.
    """
    if is_stop_requested(engine):
        raise RunStopped
    step = _step_seconds(slice_s)
    task = _as_supervised_task(awaitable_factory)
    try:
        return await _poll_supervised(task, engine, deadline_monotonic, step)
    except asyncio.CancelledError:
        # External cancellation: cancel + await the inner task, then propagate.
        if not task.done():
            await _cancel_and_drain(task)
        raise
