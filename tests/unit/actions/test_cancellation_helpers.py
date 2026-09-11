"""The supervisor's own units in `actions/cancellation.py`.

`await_with_stop` is the API callers use, but the guarantees live in the
helpers, and a caller cannot observe them from outside:

  * the poll slice is never 0 — a supervisor that busy-loops starves the very
    loop it exists to keep responsive;
  * exactly one task is supervised, and a task the caller already created is
    adopted rather than wrapped, so their handle stays theirs;
  * a settled task's outcome is always consumed, or asyncio logs
    "exception was never retrieved" for an error the caller chose to ignore;
  * a Stop that arrives together with a result wins;
  * the supervised task is cancelled *and awaited* on every exit path, so no
    orphan keeps running after the step is declared over.

Each test below calls the helper directly, so deleting the helper — or the
guarantee it carries — fails here rather than in a live run.

Run with:  python3 -m pytest tests/unit/actions/test_cancellation_helpers.py
"""

from __future__ import annotations

import asyncio
import gc
import time
import unittest

from actions.cancellation import (                          # noqa: E402
    RunStopped,
    _accept_or_stop,
    _as_supervised_task,
    _cancel_and_drain,
    _discard_result,
    _poll_supervised,
    _step_seconds,
    await_with_stop,
    is_stop_requested,
)


class Engine:
    """Enough of an engine for the stop predicate: one method, no Qt."""

    def __init__(self, stopping: bool = False) -> None:
        self.stopping = stopping

    def is_stopping(self) -> bool:
        return self.stopping


class PredicateCase(unittest.TestCase):
    def test_no_engine_means_no_stop(self):
        self.assertFalse(is_stop_requested(None))
        self.assertFalse(is_stop_requested(object()))

    def test_a_flagged_attribute_counts(self):
        class Stop:
            _stop_requested = True

        self.assertTrue(is_stop_requested(Stop()))


class StepSecondsCase(unittest.TestCase):
    def test_a_positive_slice_is_used_as_it_came(self):
        self.assertEqual(_step_seconds(0.25), 0.25)
        self.assertEqual(_step_seconds("0.3"), 0.3)       # app.json stores strings

    def test_garbage_zero_and_negative_fall_back_to_the_default(self):
        for bad in (None, "", "x", 0, -1, float("nan"), [], object()):
            with self.subTest(slice_s=bad):
                self.assertEqual(_step_seconds(bad), 0.05)

    def test_the_caller_owns_the_default(self):
        self.assertEqual(_step_seconds(None, default=1.5), 1.5)
        self.assertEqual(_step_seconds(0, default=1.5), 1.5)


class SupervisedTaskCase(unittest.IsolatedAsyncioTestCase):
    async def test_a_coroutine_becomes_exactly_one_task(self):
        async def work():
            return 7

        task = _as_supervised_task(work)
        self.assertIsInstance(task, asyncio.Task)
        self.assertEqual(await task, 7)

    async def test_a_task_the_caller_made_is_adopted_not_wrapped(self):
        future = asyncio.get_running_loop().create_future()
        self.assertIs(_as_supervised_task(lambda: future), future)
        future.cancel()


class SettleCase(unittest.IsolatedAsyncioTestCase):
    async def _settled(self, coro):
        task = asyncio.ensure_future(coro())
        await asyncio.wait({task})
        return task

    async def test_a_settled_error_is_consumed_and_stays_silent(self):
        async def boom():
            raise ValueError("inner")

        seen = []
        asyncio.get_running_loop().set_exception_handler(
            lambda _loop, context: seen.append(context))
        try:
            task = await self._settled(boom)
            _discard_result(task)                          # must not raise
            gc.collect()                                   # silence is about retrieval
            await asyncio.sleep(0)
        finally:
            asyncio.get_running_loop().set_exception_handler(None)
        self.assertTrue(task.done())
        self.assertEqual([], [r for r in seen if "never retrieved" in str(r)])

    async def test_a_result_is_fine_too(self):
        async def ok():
            return 1

        task = await self._settled(ok)
        _discard_result(task)
        self.assertEqual(task.result(), 1)

    async def test_a_pending_task_is_cancelled_and_awaited(self):
        started = asyncio.Event()

        async def hang():
            started.set()
            await asyncio.Event().wait()

        task = asyncio.ensure_future(hang())
        await started.wait()
        await _cancel_and_drain(task)
        self.assertTrue(task.done())
        self.assertTrue(task.cancelled())


class AcceptOrStopCase(unittest.IsolatedAsyncioTestCase):
    async def test_the_result_is_handed_back_while_nobody_stopped(self):
        future = asyncio.get_running_loop().create_future()
        future.set_result("value")
        self.assertEqual(_accept_or_stop(future, Engine(False)), "value")

    async def test_stop_wins_over_a_result_that_landed_with_it(self):
        future = asyncio.get_running_loop().create_future()
        future.set_result("value")
        with self.assertRaises(RunStopped):
            _accept_or_stop(future, Engine(True))


class PollCase(unittest.IsolatedAsyncioTestCase):
    async def test_a_finished_task_ends_the_loop_with_its_value(self):
        async def value():
            return 3

        task = asyncio.ensure_future(value())
        self.assertEqual(await _poll_supervised(task, Engine(False), None, 0.01), 3)

    async def test_stop_ends_it_with_runstopped_and_no_live_task(self):
        async def hang():
            await asyncio.Event().wait()

        task = asyncio.ensure_future(hang())
        await asyncio.sleep(0)
        with self.assertRaises(RunStopped):
            await _poll_supervised(task, Engine(True), None, 0.01)
        self.assertTrue(task.done())

    async def test_the_deadline_ends_it_with_timeout_and_no_live_task(self):
        async def hang():
            await asyncio.Event().wait()

        task = asyncio.ensure_future(hang())
        await asyncio.sleep(0)
        with self.assertRaises(TimeoutError):
            await _poll_supervised(task, Engine(False), time.monotonic() - 1, 0.01)
        self.assertTrue(task.done())


class WrapperCase(unittest.IsolatedAsyncioTestCase):
    async def test_an_already_stopped_engine_short_circuits_the_factory(self):
        calls = []

        async def work():
            calls.append(1)
            return "never"

        with self.assertRaises(RunStopped):
            await await_with_stop(work, Engine(True))
        self.assertEqual([], calls)

    async def test_external_cancellation_cancels_the_inner_task_and_propagates(self):
        cancelled: list = []

        async def hang():
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.append("inner saw the cancel")
                raise

        waiter = asyncio.ensure_future(
            await_with_stop(hang, Engine(False), slice_s=0.01))
        await asyncio.sleep(0.05)
        waiter.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await waiter
        self.assertEqual(["inner saw the cancel"], cancelled)


if __name__ == "__main__":
    unittest.main()
