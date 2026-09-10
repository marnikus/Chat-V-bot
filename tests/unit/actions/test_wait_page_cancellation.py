"""Area C1 — WaitPageLoad cooperative cancellation + cancellation helper contract.

Parent design: docs/SAFETY_REFACTOR_AREA_C_IMPL_DESIGN_2026-09-10.md §3.1 + §2.1.
Task list: docs/SAFETY_REFACTOR_AREA_C_2026-09-10.md C1a/C1b.

Written BEFORE the refactor (test-first). Against the baseline:
  * behaviour tests fail (pre-stopped still probes, stop is not honoured, hanging
    probes are unbounded);
  * contract tests fail with ImportError (actions/cancellation.py does not exist).

After C1 they all pass. No long sleeps in the passing state; event-driven timing.
"""

import asyncio
import os
import sys
import time
import unittest
import unittest.mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))))

from actions.base_action import ActionResult  # noqa: E402
from actions.wait_page import WaitPageLoad  # noqa: E402

try:
    from actions.cancellation import (  # noqa: E402
        RunStopped,
        await_or_stop,
        is_stop_requested,
        raise_if_stopped,
        sleep_or_stop,
    )
    HAS_CANCELLATION = True
except ImportError:
    HAS_CANCELLATION = False

    class RunStopped(Exception):  # placeholder so assertRaises collects pre-fix
        pass

    def is_stop_requested(engine):  # pragma: no cover - pre-fix stub
        return False

    def raise_if_stopped(engine):  # pragma: no cover - pre-fix stub
        return None

    async def sleep_or_stop(delay_s, engine=None, **kw):  # pragma: no cover
        await asyncio.sleep(delay_s)

    async def await_or_stop(awaitable, engine=None, **kw):  # pragma: no cover
        return await awaitable


class Recorder:
    """Duck-typed run context with a stop flag."""

    def __init__(self, stopped=False, **attrs):
        self.lines = []
        self._stop_requested = bool(stopped)
        self.__dict__.update(attrs)

    def report(self, message, level="info"):
        self.lines.append((str(message), str(level)))

    def is_stopping(self):
        return bool(self._stop_requested)

    def stop(self):
        self._stop_requested = True

    def has(self, needle, level=None):
        return any(needle in m and (level is None or lv == level)
                   for m, lv in self.lines)


class ScriptCDP:
    """Answers dom_probe with scripted payloads / errors / hangs."""

    def __init__(self, answers):
        self.answers = list(answers)
        self.calls = []

    async def evaluate(self, expression):
        self.calls.append(expression)
        if not self.answers:
            return '{"found": false, "total": 0}'
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        if callable(answer):
            return await answer()
        return answer


def run(coro):
    return asyncio.run(coro)


FOUND = ('{"found": true, "total": 1, "index": 0, "text": "hi", '
         '"visible": true, "disabled": false}')
NOT_FOUND = '{"found": false, "total": 0}'


# ── cancellation helper contract (§2.1) ──────────────────────────────
class TestCancellationContract(unittest.TestCase):
    def test_module_exists(self):
        self.assertTrue(HAS_CANCELLATION,
                        "actions/cancellation.py must exist (Area C1)")

    def test_run_stopped_is_plain_exception_not_cancelled(self):
        self.assertTrue(issubclass(RunStopped, Exception))
        self.assertNotEqual(RunStopped, asyncio.CancelledError)
        self.assertFalse(issubclass(RunStopped, asyncio.CancelledError))
        self.assertFalse(issubclass(asyncio.CancelledError, RunStopped))

    def test_is_stop_requested_matrix(self):
        self.assertTrue(HAS_CANCELLATION)
        self.assertFalse(is_stop_requested(None))
        self.assertFalse(is_stop_requested(object()))
        self.assertFalse(is_stop_requested(Recorder(stopped=False)))
        self.assertTrue(is_stop_requested(Recorder(stopped=True)))

        class Legacy:
            _stop_requested = True
        self.assertTrue(is_stop_requested(Legacy()))

        class LegacyOff:
            _stop_requested = False
        self.assertFalse(is_stop_requested(LegacyOff()))

        class Raising:
            def is_stopping(self):
                raise RuntimeError("boom")
        self.assertFalse(is_stop_requested(Raising()),
                         "a raising predicate must fail open, never crash a block")

        class NonCallable:
            is_stopping = True
            _stop_requested = False
        self.assertFalse(is_stop_requested(NonCallable()))

    def test_raise_if_stopped(self):
        self.assertTrue(HAS_CANCELLATION)
        raise_if_stopped(None)  # must not raise
        raise_if_stopped(Recorder(stopped=False))
        with self.assertRaises(RunStopped):
            raise_if_stopped(Recorder(stopped=True))

    def test_sleep_or_stop_no_engine_behaves_like_sleep(self):
        self.assertTrue(HAS_CANCELLATION)
        t0 = time.monotonic()
        run(sleep_or_stop(0.05, None))
        self.assertLess(time.monotonic() - t0, 1.0)

    def test_sleep_or_stop_pre_stopped_raises_without_sleeping(self):
        self.assertTrue(HAS_CANCELLATION)
        eng = Recorder(stopped=True)
        t0 = time.monotonic()
        with self.assertRaises(RunStopped):
            run(sleep_or_stop(5.0, eng))
        self.assertLess(time.monotonic() - t0, 0.5,
                        "pre-stopped sleep must raise immediately")

    def test_sleep_or_stop_stop_mid_sleep_raises_promptly(self):
        self.assertTrue(HAS_CANCELLATION)
        eng = Recorder(stopped=False)

        async def scenario():
            task = asyncio.ensure_future(sleep_or_stop(5.0, eng, slice_s=0.02))
            await asyncio.sleep(0.05)
            eng.stop()
            t0 = time.monotonic()
            with self.assertRaises(RunStopped):
                await task
            return time.monotonic() - t0

        elapsed = run(scenario())
        self.assertLess(elapsed, 0.5, "stop mid-sleep must surface promptly")

    def test_await_or_stop_returns_value_and_propagates_errors(self):
        self.assertTrue(HAS_CANCELLATION)

        async def value():
            return "probe-ok"

        async def boom():
            raise RuntimeError("probe exploded")

        self.assertEqual(run(await_or_stop(value(), None)), "probe-ok")
        with self.assertRaises(RuntimeError):
            run(await_or_stop(boom(), None))

    def test_await_or_stop_pre_stopped_fails_fast_without_starting_probe(self):
        self.assertTrue(HAS_CANCELLATION)
        eng = Recorder(stopped=True)
        started = asyncio.Event()

        async def hanging():
            started.set()
            await asyncio.sleep(30)
            return "never"

        async def scenario():
            with self.assertRaises(RunStopped):
                await await_or_stop(hanging(), eng, slice_s=0.02)
            self.assertFalse(started.is_set(),
                             "pre-stopped must fail fast without starting the probe")

        run(scenario())

    def test_await_or_stop_stop_during_probe_cancels_and_raises(self):
        self.assertTrue(HAS_CANCELLATION)
        eng = Recorder(stopped=False)
        started = asyncio.Event()
        cancelled = asyncio.Event()

        async def hanging():
            started.set()
            try:
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                cancelled.set()
                raise
            return "never"

        async def scenario():
            task = asyncio.ensure_future(
                await_or_stop(hanging(), eng, slice_s=0.02))
            await started.wait()
            await asyncio.sleep(0.05)
            eng.stop()
            t0 = time.monotonic()
            with self.assertRaises(RunStopped):
                await task
            self.assertLess(time.monotonic() - t0, 0.5)
            self.assertTrue(cancelled.is_set())

        run(scenario())


# ── WaitPageLoad cancellation behaviour (§3.1) ───────────────────────
class TestWaitCancellation(unittest.TestCase):
    def test_pre_stopped_does_no_delay_no_probe(self):
        """Already-stopped wait: no pre-delay, no probe, cooperative stop."""
        cdp = ScriptCDP([FOUND])
        eng = Recorder(stopped=True)
        block = WaitPageLoad(target_selector="textarea", timeout_ms=5000,
                             pre_delay_ms=1000)
        t0 = time.monotonic()
        if HAS_CANCELLATION:
            with self.assertRaises(RunStopped):
                run(block.execute("N", cdp, eng))
        else:
            # Baseline reproducer: probes + delay happen anyway (fails below).
            run(block.execute("N", cdp, eng))
        elapsed = time.monotonic() - t0
        self.assertEqual(cdp.calls, [],
                         "a pre-stopped wait must not probe at all")
        self.assertLess(elapsed, 0.5,
                        "a pre-stopped wait must not honour the 1000 ms pre-delay")

    def test_stop_during_pre_delay_is_honoured_before_probe(self):
        cdp = ScriptCDP([FOUND])
        eng = Recorder(stopped=False)
        block = WaitPageLoad(target_selector="textarea", timeout_ms=5000,
                             pre_delay_ms=3000)

        async def scenario():
            task = asyncio.ensure_future(block.execute("N", cdp, eng))
            await asyncio.sleep(0.05)
            eng.stop()
            t0 = time.monotonic()
            if HAS_CANCELLATION:
                with self.assertRaises(RunStopped):
                    await task
            else:
                await task  # baseline: sleeps the full pre-delay (slow, fails below)
            return time.monotonic() - t0

        elapsed = run(scenario())
        self.assertEqual(cdp.calls, [],
                         "stop during pre-delay must pre-empt the first probe")
        self.assertLess(elapsed, 1.0,
                        "stop during a 3000 ms pre-delay must surface promptly")

    def test_stop_during_polling_delay_exits_promptly(self):
        cdp = ScriptCDP([NOT_FOUND] * 100)
        eng = Recorder(stopped=False)
        block = WaitPageLoad(target_selector="textarea", timeout_ms=5000,
                             pre_delay_ms=0)

        async def scenario():
            task = asyncio.ensure_future(block.execute("N", cdp, eng))
            while not cdp.calls:
                await asyncio.sleep(0.01)
            first_probe_count = len(cdp.calls)
            eng.stop()
            t0 = time.monotonic()
            if HAS_CANCELLATION:
                with self.assertRaises(RunStopped):
                    await task
            else:
                await task  # baseline: polls until timeout (slow, fails below)
            return time.monotonic() - t0, first_probe_count

        elapsed, first_probe_count = run(scenario())
        self.assertGreaterEqual(first_probe_count, 1)
        self.assertLessEqual(len(cdp.calls), first_probe_count + 1,
                             "no further probes after stop was requested")
        self.assertLess(elapsed, 1.0,
                        "stop during polling must exit well before the 5000 ms timeout")

    def test_stop_during_hanging_probe_cancels_without_orphan(self):
        started = asyncio.Event()

        async def hanging():
            started.set()
            await asyncio.sleep(30)
            return NOT_FOUND

        cdp = ScriptCDP([hanging])
        eng = Recorder(stopped=False)
        block = WaitPageLoad(target_selector="textarea", timeout_ms=5000,
                             pre_delay_ms=0)

        async def scenario():
            task = asyncio.ensure_future(block.execute("N", cdp, eng))
            await started.wait()
            await asyncio.sleep(0.05)
            eng.stop()
            t0 = time.monotonic()
            if HAS_CANCELLATION:
                with self.assertRaises(RunStopped):
                    await asyncio.wait_for(task, timeout=2)
            else:
                # Baseline hangs: wait_for times out, proving the defect.
                await asyncio.wait_for(task, timeout=1)
            return time.monotonic() - t0

        # Baseline: TimeoutError from wait_for proves the hang (test fails below
        # on purpose — it documents the reproduced defect).
        if HAS_CANCELLATION:
            elapsed = run(scenario())
            self.assertLess(elapsed, 1.0)
        else:
            with self.assertRaises(asyncio.TimeoutError):
                run(scenario())
            self.fail("baseline hangs on a pending probe (reproduced B8)")

    def test_hanging_probe_is_bounded_by_deadline(self):
        async def hanging():
            await asyncio.sleep(30)
            return NOT_FOUND

        cdp = ScriptCDP([hanging] * 10)
        eng = Recorder(stopped=False)
        block = WaitPageLoad(target_selector="textarea", timeout_ms=150,
                             pre_delay_ms=0)
        t0 = time.monotonic()
        if HAS_CANCELLATION:
            out = run(block.execute("N", cdp, eng))
            elapsed = time.monotonic() - t0
            self.assertEqual(out, ActionResult.FAIL)
            self.assertLess(elapsed, 2.0,
                            "a hanging probe must be bounded by the deadline")
            self.assertTrue(eng.has("Failed to find element", "error"))
        else:
            # Baseline hangs beyond the deadline; bound the demonstration.
            async def bounded():
                await asyncio.wait_for(block.execute("N", cdp, eng), timeout=1)
            with self.assertRaises(asyncio.TimeoutError):
                run(bounded())
            self.fail("baseline ignores its deadline while a probe hangs (B8)")

    def test_no_engine_preserves_success_and_timeout(self):
        cdp_ok = ScriptCDP([FOUND])
        out = run(WaitPageLoad(target_selector="textarea", timeout_ms=50,
                               pre_delay_ms=0).execute("N", cdp_ok, None))
        self.assertEqual(out, ActionResult.OK)

        cdp_miss = ScriptCDP([NOT_FOUND])
        out = run(WaitPageLoad(target_selector="textarea", timeout_ms=0,
                               pre_delay_ms=0).execute("N", cdp_miss, None))
        self.assertEqual(out, ActionResult.FAIL)

    def test_found_notfound_error_malformed_diagnostics_preserved(self):
        # Found → OK with the probe message.
        cdp = ScriptCDP([FOUND])
        eng = Recorder()
        out = run(WaitPageLoad(target_selector="textarea", timeout_ms=50,
                               pre_delay_ms=0).execute("N", cdp, eng))
        self.assertEqual(out, ActionResult.OK)
        self.assertTrue(eng.has("found — visible & enabled"), eng.lines)

        # Timeout → FAIL with matched-node count.
        cdp = ScriptCDP(['{"found": false, "total": 3}'])
        eng = Recorder()
        out = run(WaitPageLoad(target_selector="textarea", timeout_ms=0,
                               pre_delay_ms=0).execute("N", cdp, eng))
        self.assertEqual(out, ActionResult.FAIL)
        self.assertTrue(eng.has("Failed to find element"), eng.lines)
        self.assertTrue(eng.has("matched 3 node(s)", "error"), eng.lines)

        # Probe errors throttled: first of five only.
        cdp = ScriptCDP([RuntimeError("detached")] * 4 + [FOUND])
        eng = Recorder()
        block = WaitPageLoad(target_selector="textarea", timeout_ms=5000,
                             pre_delay_ms=0)
        out = run(block.execute("N", cdp, eng))
        self.assertEqual(out, ActionResult.OK)
        errors = [m for m, lv in eng.lines
                  if lv == "error" and "Probe error" in m]
        self.assertEqual(len(errors), 1, eng.lines)

        # Malformed payload → treated as not-found, timeout FAIL (never a crash).
        cdp = ScriptCDP(["not-json{{{", ""])
        eng = Recorder()
        out = run(WaitPageLoad(target_selector="textarea", timeout_ms=0,
                               pre_delay_ms=0).execute("N", cdp, eng))
        self.assertEqual(out, ActionResult.FAIL)

    def test_cancellation_state_never_leaks_into_presets(self):
        block = WaitPageLoad(target_selector="a", timeout_ms=1234,
                             pre_delay_ms=10)
        data = block.to_dict()
        self.assertEqual(data["timeout_ms"], 1234)
        self.assertEqual(data["target_selector"], "a")
        for key in data:
            self.assertFalse(key.startswith("_"), key)
            self.assertNotIn("cancel", key.lower(), data)
            self.assertNotIn("stop", key.lower(), data)
        # Round-trip through the constructor keeps working.
        again = WaitPageLoad(**{k: v for k, v in data.items()
                                if k != "block_id"})
        self.assertEqual(again.to_dict(), data)


# ── cancellation helper edge branches (defensive coercion/close paths) ──
class TestCancellationEdges(unittest.TestCase):
    def test_is_stop_requested_evil_engine_fails_open(self):
        self.assertTrue(HAS_CANCELLATION)

        class Evil:
            # Neither callable is_stopping nor readable _stop_requested.
            @property
            def _stop_requested(self):
                raise RuntimeError("getattr down")

        self.assertFalse(is_stop_requested(Evil()))

    def test_sleep_or_stop_bad_delay_returns_immediately(self):
        self.assertTrue(HAS_CANCELLATION)
        t0 = time.monotonic()
        run(sleep_or_stop("not-a-number", None))
        run(sleep_or_stop(None, None))
        self.assertLess(time.monotonic() - t0, 0.5)

    def test_sleep_or_stop_bad_slice_falls_back_to_default(self):
        self.assertTrue(HAS_CANCELLATION)
        t0 = time.monotonic()
        run(sleep_or_stop(0.06, None, slice_s="bad"))
        run(sleep_or_stop(0.06, None, slice_s=0))
        run(sleep_or_stop(0.06, None, slice_s=-2))
        self.assertLess(time.monotonic() - t0, 1.0)

    def test_await_or_stop_pre_stopped_non_coroutine_skips_close(self):
        self.assertTrue(HAS_CANCELLATION)
        eng = Recorder(stopped=True)

        async def scenario():
            fut = asyncio.get_event_loop().create_future()
            fut.set_result("unused")
            with self.assertRaises(RunStopped):
                await await_or_stop(fut, eng)

        run(scenario())

    def test_await_or_stop_pre_stopped_close_failure_is_contained(self):
        self.assertTrue(HAS_CANCELLATION)
        eng = Recorder(stopped=True)

        class Unclosable:
            def close(self):
                raise RuntimeError("close down")

        async def scenario():
            with unittest.mock.patch("asyncio.iscoroutine",
                                     return_value=True):
                with self.assertRaises(RunStopped):
                    await await_or_stop(Unclosable(), eng)

        run(scenario())

    def test_await_or_stop_bad_slice_falls_back_to_default(self):
        self.assertTrue(HAS_CANCELLATION)

        async def value():
            return "ok"

        self.assertEqual(run(await_or_stop(value(), None, slice_s="bad")),
                         "ok")
        self.assertEqual(run(await_or_stop(value(), None, slice_s=0)), "ok")

    def test_await_or_stop_stop_as_task_completes_skips_cancel(self):
        self.assertTrue(HAS_CANCELLATION)

        class Flipper:
            def __init__(self):
                self.calls = 0

            def is_stopping(self):
                self.calls += 1
                return self.calls > 1

        async def quick():
            await asyncio.sleep(0.01)
            return "done"

        async def scenario():
            # Pre-check passes (call 1); the probe finishes during the first
            # poll and stop lands right after (call 2) — no cancel needed.
            with self.assertRaises(RunStopped):
                await await_or_stop(quick(), Flipper())

        run(scenario())

    def test_await_or_stop_probe_error_on_cancel_is_contained(self):
        self.assertTrue(HAS_CANCELLATION)
        eng = Recorder(stopped=False)
        started = asyncio.Event()

        async def nasty():
            started.set()
            try:
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                raise RuntimeError("probe broke while cancelling")

        async def scenario():
            task = asyncio.ensure_future(
                await_or_stop(nasty(), eng, slice_s=0.02))
            await started.wait()
            await asyncio.sleep(0.05)
            eng.stop()
            with self.assertRaises(RunStopped):
                await task

        run(scenario())

    def test_await_or_stop_external_cancel_with_done_task_propagates(self):
        self.assertTrue(HAS_CANCELLATION)

        async def scenario():
            fut = asyncio.get_event_loop().create_future()

            def cancelling(*args, **kwargs):
                # The probe finishes just as external cancellation lands.
                if not fut.done():
                    fut.set_result("done")
                raise asyncio.CancelledError()

            with unittest.mock.patch("asyncio.wait_for",
                                     side_effect=cancelling):
                with self.assertRaises(asyncio.CancelledError):
                    await await_or_stop(fut, None)

        run(scenario())

    def test_await_or_stop_external_cancel_probe_error_is_contained(self):
        self.assertTrue(HAS_CANCELLATION)
        started = asyncio.Event()

        async def nasty():
            started.set()
            try:
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                raise RuntimeError("probe broke while cancelling")

        async def scenario():
            task = asyncio.ensure_future(await_or_stop(nasty(), None,
                                                       slice_s=0.02))
            await started.wait()
            await asyncio.sleep(0.05)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task

        run(scenario())


# ── WaitPageLoad edge branches ──────────────────────────────────────
class TestWaitEdges(unittest.TestCase):
    def test_bad_timeout_ms_falls_back_to_default(self):
        block = WaitPageLoad(target_selector="a", timeout_ms="bad",
                             pre_delay_ms=0)
        cdp = ScriptCDP([FOUND])
        out = run(block.execute("n", cdp, Recorder()))
        self.assertEqual(out, ActionResult.OK)

    def test_external_cancel_during_probe_propagates(self):
        block = WaitPageLoad(target_selector="a", timeout_ms=5000,
                             pre_delay_ms=0)
        started = asyncio.Event()

        async def hanging():
            started.set()
            await asyncio.sleep(30)
            return NOT_FOUND

        async def scenario():
            task = asyncio.ensure_future(
                block.execute("n", ScriptCDP([hanging]), Recorder()))
            await started.wait()
            await asyncio.sleep(0.05)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task

        run(scenario())

    def test_no_engine_slow_probe_timeout_reports_nothing(self):
        block = WaitPageLoad(target_selector="a", timeout_ms=50,
                             pre_delay_ms=0)
        out = run(block.execute("n", ScriptCDP([]), None))
        self.assertEqual(out, ActionResult.FAIL)


if __name__ == "__main__":
    unittest.main(verbosity=2)
