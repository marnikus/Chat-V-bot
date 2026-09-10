"""AREA C1 — WaitPageLoad cooperative cancellation.

Covers the C1a wait rows: already-stopped entry, stop in pre-delay /
poll-gap / probe-await, hanging-probe bounds, engine-None compat, and
preserved found/not-found/error/malformed diagnostics.

Red on baseline (WaitPageLoad ignores stop, probes twice, returns FAIL);
green after actions/cancellation.py + wait_page.py rework.
"""

from __future__ import annotations

import asyncio
import json
import time
import unittest

from tests.integration.run_safety._helpers import FakeCDP  # noqa: E402

from actions.wait_page import WaitPageLoad  # noqa: E402

try:
    from actions.cancellation import (  # noqa: E402
        RunStopped,
        await_with_stop,
        is_stop_requested,
        sleep_with_stop,
    )

    HAS_CANCELLATION = True
except ImportError:
    HAS_CANCELLATION = False

    class RunStopped(Exception):  # placeholder for red-phase assertions
        pass

    def is_stop_requested(engine):  # minimal fallback
        if engine is None:
            return False
        fn = getattr(engine, "is_stopping", None)
        if callable(fn):
            try:
                return bool(fn())
            except Exception:
                return False
        return bool(getattr(engine, "_stop_requested", False))

    async def sleep_with_stop(delay_s, engine, slice_s=0.02):  # noqa: ANN001
        await asyncio.sleep(delay_s)

    async def await_with_stop(factory, engine, slice_s=0.05, deadline_monotonic=None):  # noqa: ANN001
        return await factory()


class FakeEngine:
    def __init__(self, stopping=False):
        self._stop = stopping
        self.reports = []

    def report(self, msg, level="info"):
        self.reports.append((msg, level))

    def is_stopping(self):
        return self._stop

    def stop(self):
        self._stop = True

    def text(self):
        return " | ".join(m for m, _ in self.reports)


class LegacyEngine:
    """Old duck-typed caller: only _stop_requested, no is_stopping."""

    def __init__(self, stopping=False):
        self._stop_requested = stopping
        self.reports = []

    def report(self, msg, level="info"):
        self.reports.append((msg, level))


class CancellationHelperCase(unittest.TestCase):
    def test_is_stop_requested_none_is_false(self):
        self.assertFalse(is_stop_requested(None))

    def test_is_stop_requested_uses_is_stopping(self):
        self.assertFalse(is_stop_requested(FakeEngine(False)))
        self.assertTrue(is_stop_requested(FakeEngine(True)))

    def test_is_stop_requested_fallback_to_flag(self):
        self.assertFalse(is_stop_requested(LegacyEngine(False)))
        self.assertTrue(is_stop_requested(LegacyEngine(True)))

    def test_is_stop_requested_broken_predicate_fails_open(self):
        class Broken:
            def is_stopping(self):
                raise RuntimeError("boom")

        self.assertFalse(is_stop_requested(Broken()))


class WaitCancellationCase(unittest.IsolatedAsyncioTestCase):
    async def test_already_stopped_does_no_delay_or_probe(self):
        if not HAS_CANCELLATION:
            self.fail("actions/cancellation.py not implemented (red)")
        cdp = FakeCDP()
        eng = FakeEngine(stopping=True)
        blk = WaitPageLoad(
            target_selector="div", timeout_ms=5000, pre_delay_ms=1000
        )
        t0 = time.monotonic()
        with self.assertRaises(RunStopped):
            await blk.execute("u", cdp, eng)
        dt = time.monotonic() - t0
        self.assertEqual(cdp.calls, 0, "already-stopped must not probe")
        self.assertLess(
            dt, 0.5, f"already-stopped must skip the 1s pre-delay (took {dt:.2f}s)"
        )
        self.assertTrue(
            any("stopped" in m.lower() for m, _ in eng.reports),
            "must report stopped, not timeout/failure",
        )

    async def test_stop_during_pre_delay_is_prompt(self):
        if not HAS_CANCELLATION:
            self.fail("actions/cancellation.py not implemented (red)")
        cdp = FakeCDP()
        eng = FakeEngine(stopping=False)
        blk = WaitPageLoad(
            target_selector="div", timeout_ms=5000, pre_delay_ms=5000
        )

        async def stopper():
            await asyncio.sleep(0.05)
            eng.stop()

        t0 = time.monotonic()
        with self.assertRaises(RunStopped):
            await asyncio.wait_for(
                asyncio.gather(blk.execute("u", cdp, eng), stopper()),
                timeout=2.0,
            )
        dt = time.monotonic() - t0
        self.assertEqual(cdp.calls, 0, "stop in pre-delay must not probe")
        self.assertLess(dt, 1.0, f"stop in 5s pre-delay must be prompt ({dt:.2f}s)")

    async def test_stop_during_poll_gap_exits_without_next_probe(self):
        if not HAS_CANCELLATION:
            self.fail("actions/cancellation.py not implemented (red)")
        cdp = FakeCDP(script=[{"found": False, "total": 0}])
        eng = FakeEngine(stopping=False)
        blk = WaitPageLoad(
            target_selector="div", timeout_ms=10000, pre_delay_ms=0
        )

        async def stopper():
            while cdp.calls < 1:
                await asyncio.sleep(0.01)
            eng.stop()  # lands in the 0.3s poll gap after probe 1

        with self.assertRaises(RunStopped):
            await asyncio.wait_for(
                asyncio.gather(blk.execute("u", cdp, eng), stopper()),
                timeout=2.0,
            )
        self.assertEqual(
            cdp.calls, 1, "stop in the poll gap must prevent probe 2"
        )

    async def test_hanging_probe_stop_cancels_without_orphan(self):
        if not HAS_CANCELLATION:
            self.fail("actions/cancellation.py not implemented (red)")
        gate = asyncio.Event()
        cdp = FakeCDP()
        cdp.hang_event = gate  # first probe hangs until released
        eng = FakeEngine(stopping=False)
        blk = WaitPageLoad(
            target_selector="div", timeout_ms=10000, pre_delay_ms=0
        )
        before = len(asyncio.all_tasks())

        async def stopper():
            while cdp.calls < 1:
                await asyncio.sleep(0.01)
            eng.stop()
            await asyncio.sleep(0.05)
            gate.set()  # release the hung probe; wait must already have let go

        t0 = time.monotonic()
        blk_task = asyncio.ensure_future(blk.execute("u", cdp, eng))
        stop_task = asyncio.ensure_future(stopper())
        with self.assertRaises(RunStopped):
            await asyncio.wait_for(blk_task, timeout=3.0)
        await asyncio.wait_for(stop_task, timeout=3.0)
        dt = time.monotonic() - t0
        self.assertLess(dt, 2.0, f"hung probe + stop must exit promptly ({dt:.2f}s)")
        await asyncio.sleep(0)  # let cancellations settle
        lingering = [
            t
            for t in asyncio.all_tasks()
            if not t.done() and t is not asyncio.current_task()
        ]
        # The probe task must not linger (stopper already awaited above).
        self.assertLessEqual(
            len(asyncio.all_tasks()), before + 2, "no orphaned probe task may survive"
        )
        self.assertEqual(len(lingering), 0, f"orphaned tasks: {lingering}")

    async def test_hanging_probe_deadline_bounds_without_stop(self):
        cdp_gate = asyncio.Event()  # never set → probe hangs forever
        cdp = FakeCDP()
        cdp.hang_event = cdp_gate
        eng = FakeEngine(stopping=False)
        blk = WaitPageLoad(target_selector="div", timeout_ms=120, pre_delay_ms=0)
        t0 = time.monotonic()
        try:
            res = await asyncio.wait_for(blk.execute("u", cdp, eng), timeout=2.0)
        finally:
            cdp.hang_event = None
        dt = time.monotonic() - t0
        # Baseline FAILS here (hung evaluate never returns → wait_for times out).
        # Fixed code cancels the probe at the deadline and returns FAIL.
        self.assertEqual(res, "fail")
        self.assertLess(dt, 2.0, f"deadline must bound a hung probe ({dt:.2f}s)")

    async def test_engine_none_success_and_timeout_preserved(self):
        cdp_ok = FakeCDP(
            script=[{"found": True, "total": 1, "text": "hi", "visible": True}]
        )
        blk = WaitPageLoad(target_selector="div", timeout_ms=500, pre_delay_ms=0)
        self.assertEqual(await blk.execute("u", cdp_ok, None), "ok")
        cdp_miss = FakeCDP(script=[{"found": False, "total": 0}])
        blk2 = WaitPageLoad(target_selector="div", timeout_ms=60, pre_delay_ms=0)
        self.assertEqual(await blk2.execute("u", cdp_miss, None), "fail")

    async def test_found_reports_success_diagnostics(self):
        cdp = FakeCDP(
            script=[
                {
                    "found": True,
                    "total": 3,
                    "text": "hello",
                    "visible": True,
                    "disabled": False,
                }
            ]
        )
        eng = FakeEngine()
        blk = WaitPageLoad(target_selector="div", timeout_ms=500, pre_delay_ms=0)
        self.assertEqual(await blk.execute("u", cdp, eng), "ok")
        self.assertTrue(any("found" in m.lower() for m, _ in eng.reports))

    async def test_not_found_times_out_with_counts(self):
        cdp = FakeCDP(script=[{"found": False, "total": 2}])
        eng = FakeEngine()
        blk = WaitPageLoad(target_selector="div", timeout_ms=60, pre_delay_ms=0)
        self.assertEqual(await blk.execute("u", cdp, eng), "fail")
        text = eng.text().lower()
        self.assertIn("timeout", text)
        self.assertIn("2", text)  # last known matched-node count

    async def test_probe_error_and_malformed_are_tolerated(self):
        cdp = FakeCDP(
            script=[
                RuntimeError("cdp down"),
                "not-json{{{",
                {"found": True, "total": 1, "text": "x", "visible": True},
            ]
        )
        eng = FakeEngine()
        blk = WaitPageLoad(target_selector="div", timeout_ms=2000, pre_delay_ms=0)
        self.assertEqual(await blk.execute("u", cdp, eng), "ok")
        self.assertGreaterEqual(cdp.calls, 3)

    async def test_to_dict_and_schema_do_not_leak_helpers(self):
        blk = WaitPageLoad(
            target_selector="span.x", timeout_ms=1234, pre_delay_ms=50
        )
        data = blk.to_dict()
        self.assertEqual(data["block_id"], "WAIT_PAGE_LOAD")
        self.assertEqual(data["target_selector"], "span.x")
        self.assertEqual(data["timeout_ms"], 1234)
        self.assertEqual(data["pre_delay_ms"], 50)
        for key in data:
            self.assertFalse(
                key.startswith("_"),
                f"private helper {key!r} must not serialize",
            )
            self.assertNotIn("stop", key.lower())
            self.assertNotIn("cancel", key.lower())
        clone = WaitPageLoad(**{k: v for k, v in data.items() if k != "block_id"})
        self.assertEqual(clone.to_dict(), data)
        schema = blk.config_schema()
        self.assertIn("target_selector", schema)
        self.assertIn("timeout_ms", schema)

    async def test_await_with_stop_no_orphan_on_external_cancel(self):
        if not HAS_CANCELLATION:
            self.skipTest("cancellation helper not implemented (red)")
        gate = asyncio.Event()

        async def probe():
            await gate.wait()
            return "late"

        eng = FakeEngine()
        task = asyncio.ensure_future(
            await_with_stop(lambda: probe(), eng, slice_s=0.02)
        )
        await asyncio.sleep(0.05)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        gate.set()
        await asyncio.sleep(0)
        self.assertTrue(task.done())

    async def test_sleep_with_stop_is_prompt_and_bounded(self):
        if not HAS_CANCELLATION:
            self.skipTest("cancellation helper not implemented (red)")
        eng = FakeEngine()

        async def stopper():
            await asyncio.sleep(0.05)
            eng.stop()

        t0 = time.monotonic()
        with self.assertRaises(RunStopped):
            await asyncio.gather(sleep_with_stop(5.0, eng), stopper())
        self.assertLess(time.monotonic() - t0, 1.0)
        # No stop → full sleep (short).
        eng2 = FakeEngine()
        await sleep_with_stop(0.02, eng2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
