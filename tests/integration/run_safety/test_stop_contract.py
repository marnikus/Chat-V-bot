"""AREA C1 — stop contract: gates, marking boundary, single-target, restart.

Red on baseline (pause starts blocks, final-OK marks, single-target masks
stop, STOPPING strands, collect misclassifies); green after C1.
"""

from __future__ import annotations

import asyncio
import time
import unittest

from actions.base_action import ActionResult, BaseAction
from services.run.hooks import RunHooks
from services.run.state_machine import RunState
from stores.user_memory import UserRecord

from tests.integration.run_safety._helpers import (
    EngineHarness,
    FakeCDP,
    FakeMemory,
    GateBlock,
    OkBlock,
    RunStopped,
    ScriptedMemory,
    StopRequestBlock,
    make_ok_block,
)


class StopGatesCase(unittest.IsolatedAsyncioTestCase):
    async def test_stop_while_paused_between_blocks_starts_nothing(self):
        with EngineHarness(users=[UserRecord(nick="a")]) as h:
            calls = []

            class B1(BaseAction):
                block_id = "TEST_C1_B1"
                name = "b1"
                icon = "x"

                async def execute(self, nick, cdp, engine=None):
                    calls.append("b1")
                    engine.pause()

                    async def stopper():
                        await asyncio.sleep(0.05)
                        engine.stop()

                    asyncio.create_task(stopper())
                    return ActionResult.OK

            class B2(BaseAction):
                block_id = "TEST_C1_B2"
                name = "b2"
                icon = "x"

                async def execute(self, nick, cdp, engine=None):
                    calls.append("b2")
                    return ActionResult.OK

            h.engine._stack = [B1(pre_delay_ms=0), B2(pre_delay_ms=0)]
            await asyncio.wait_for(h.engine.execute(None), timeout=5)
            self.assertEqual(
                calls, ["b1"], "stop during pause must not start the next block"
            )
            self.assertEqual(h.memory.marked, [])
            self.assertEqual(h.user_done, [("a", False)])
            self.assertTrue(any("stopped" in m.lower() for m, _ in h.debug))

    async def test_stop_while_paused_between_users_runs_no_next_user(self):
        with EngineHarness(
            users=[UserRecord(nick="a"), UserRecord(nick="b")]
        ) as h:
            gate = asyncio.Event()
            block = GateBlock(gate=gate)
            h.engine._stack = [block]

            async def controller():
                while not block.calls:
                    await asyncio.sleep(0.01)
                h.engine.pause()
                gate.set()  # let user a finish, then pause before b
                while len(block.calls) < 1 or h.engine.is_running is False:
                    await asyncio.sleep(0.01)
                await asyncio.sleep(0.05)
                h.engine.stop()

            await asyncio.wait_for(
                asyncio.gather(h.engine.execute(None), controller()),
                timeout=5,
            )
            self.assertEqual(block.calls, ["a"])
            self.assertEqual(h.memory.marked, ["a"])
            self.assertEqual(h.user_done, [("a", True)])
            # user b must never start: no user_complete for b
            self.assertNotIn("b", [n for n, _ in h.user_done])

    async def test_stop_during_collect_yields_stopped_not_empty(self):
        with EngineHarness(memory=FakeMemory([])) as h:
            from types import SimpleNamespace

            class ScrollStop(BaseAction):
                block_id = "SCROLL_PARSE"
                name = "Scroll"
                icon = "x"

                async def execute(self, nick, cdp, engine=None):
                    return ActionResult.OK

                async def run_pipeline(
                    self, cdp, engine, panel_criteria=None, known_messaged=None
                ):
                    engine.stop()
                    return SimpleNamespace(
                        collected=[],
                        all_people=[],
                        purged=[],
                        seeking=False,
                        found=None,
                        stopped=True,
                        scrolls=0,
                        reached_end=False,
                        stopped_early=False,
                    )

            h.engine._stack = [ScrollStop(pre_delay_ms=0)]
            await h.engine.execute(None)
            # Must be stopped (trace/outcome), not empty/completed.
            records = h.trace_records()
            reasons = [r.get("reason") for r in records if r.get("type") == "run_end"]
            self.assertIn(
                "stopped", reasons, f"collect-stop must end stopped, got {reasons}"
            )
            self.assertNotIn("completed", reasons)
            self.assertEqual(h.engine._state.state, RunState.DONE)

    async def test_stop_during_take_phase_yields_stopped(self):
        mem = ScriptedMemory(
            users=[UserRecord(nick="a")],
            on_get_all=lambda: None,
        )
        with EngineHarness(memory=mem) as h:
            from actions.take_person import TakePerson

            take = TakePerson(pick_mode="order_first")
            h.engine._stack = [take, make_ok_block()]

            orig_get_all = mem.get_all

            async def hooked_get_all():
                rows = await FakeMemory.get_all(mem)
                h.engine.stop()  # stop lands inside the take-phase read
                return rows

            mem.get_all = hooked_get_all  # type: ignore
            await h.engine.execute(None)
            records = h.trace_records()
            reasons = [r.get("reason") for r in records if r.get("type") == "run_end"]
            self.assertIn("stopped", reasons)
            self.assertEqual(h.memory.marked, [])

    async def test_stop_during_retry_backoff_skips_next_attempt_and_fallback(self):
        from services.run.error_recovery import RetryPolicy

        policy = RetryPolicy(max_retries=5, base_delay=0.5)
        calls = []
        fallbacks = []

        async def op():
            calls.append(1)
            raise TimeoutError("transient")

        async def fallback(exc):
            fallbacks.append(exc)
            raise exc

        class Stopper:
            def __init__(self):
                self._stop_requested = False

            def is_stopping(self):
                return self._stop_requested

        stopper = Stopper()

        async def stop_soon():
            await asyncio.sleep(0.05)
            stopper._stop_requested = True

        # New signature has stop=; baseline lacks it → TypeError (red).
        try:
            task = asyncio.ensure_future(
                policy.retry_with_backoff(op, fallback=fallback, stop=stopper)
            )
        except TypeError:
            self.fail("retry_with_backoff must accept stop= (red)")
        stopper_task = asyncio.ensure_future(stop_soon())
        with self.assertRaises(RunStopped):
            await task
        await stopper_task
        self.assertEqual(len(calls), 1, "stop must prevent the next attempt")
        self.assertEqual(fallbacks, [], "stop must not invoke the fallback")

    async def test_stop_on_final_ok_prevents_automatic_mark(self):
        with EngineHarness(users=[UserRecord(nick="solo")]) as h:
            h.engine._stack = [StopRequestBlock()]
            await h.engine.execute(None)
            self.assertEqual(
                h.memory.marked, [], "stop before the mark boundary must not mark"
            )
            self.assertEqual(h.user_done, [("solo", False)])
            # Progress: stop counts as failed on the wire.
            self.assertEqual(h.engine.progress.failed, 1)
            self.assertEqual(h.engine.progress.done, 0)
            records = h.trace_records()
            reasons = [r.get("reason") for r in records if r.get("type") == "run_end"]
            self.assertIn("stopped", reasons)

    async def test_explicit_mark_before_stop_is_not_rolled_back(self):
        from actions.mark_messaged import MarkMessaged

        with EngineHarness(users=[UserRecord(nick="Zoe")]) as h:

            class PickZoe(BaseAction):
                block_id = "TAKE_PERSON"
                name = "Pick"
                icon = "x"

                def choose(self, rows, engine=None):
                    return "Zoe"

                async def execute(self, nick, cdp, engine=None):
                    return ActionResult.SKIP

            mark = MarkMessaged(pre_delay_ms=0)

            class StopAfter(BaseAction):
                block_id = "TEST_C1_STOP_AFTER"
                name = "stop"
                icon = "x"

                async def execute(self, nick, cdp, engine=None):
                    engine.stop()
                    return ActionResult.OK

            h.engine._stack = [
                PickZoe(pre_delay_ms=0),
                mark,
                StopAfter(pre_delay_ms=0),
            ]
            await h.engine.execute(None)
            # Explicit mark completed before stop → stays marked.
            self.assertIn("Zoe", h.memory.marked)
            # But the automatic post-user mark must not double-add for a
            # stopped user: exactly one mark (the explicit one).
            self.assertEqual(h.memory.marked.count("Zoe"), 1)

    async def test_single_target_stop_returns_stopped_not_worked(self):
        with EngineHarness(
            users=[UserRecord(nick="Anna"), UserRecord(nick="Bella")]
        ) as h:
            h.engine.note_selected("Anna")

            class MemClick(BaseAction):
                block_id = "CLICK_USER"
                name = "Click"
                icon = "x"

                def __init__(self, **kw):
                    super().__init__(pre_delay_ms=0)
                    self.use_person_from_memory = True

                async def execute(self, nick, cdp, engine=None):
                    engine.stop()
                    return ActionResult.OK

            class Next(BaseAction):
                block_id = "TEST_C1_NEXT"
                name = "next"
                icon = "x"

                async def execute(self, nick, cdp, engine=None):
                    return ActionResult.OK

            h.engine._stack = [MemClick(), Next(pre_delay_ms=0)]
            # Drive one cycle directly to pin the return value.
            h.engine._tracer = type(
                "T", (), {"note": lambda self, *a, **k: None}
            )()
            h.engine._running = True
            h.engine._state.mark_running()
            out = await h.engine._run_single_target_cycle(False, False)
            self.assertEqual(out, "stopped")
            self.assertEqual(h.memory.marked, [])
            self.assertEqual(h.user_done, [("Anna", False)])

    async def test_single_target_stop_ends_repeat_without_next_cycle(self):
        from actions.repeat_loop import RepeatLoop

        with EngineHarness(users=[UserRecord(nick="Anna")]) as h:

            class PickAnna(BaseAction):
                block_id = "TAKE_PERSON"
                name = "Pick"
                icon = "x"

                def choose(self, rows, engine=None):
                    return "Anna"

                async def execute(self, nick, cdp, engine=None):
                    return ActionResult.SKIP

            class MemClick(BaseAction):
                block_id = "CLICK_USER"
                name = "Click"
                icon = "x"

                def __init__(self, **kw):
                    super().__init__(pre_delay_ms=0)
                    self.use_person_from_memory = True
                    self.calls = []

                async def execute(self, nick, cdp, engine=None):
                    self.calls.append(nick)
                    engine.stop()
                    return ActionResult.OK

            click = MemClick()
            h.engine._stack = [
                RepeatLoop(repeat_count=5),
                PickAnna(pre_delay_ms=0),
                click,
            ]
            await h.engine.execute(None)
            self.assertEqual(
                len(click.calls), 1, "stopped single-target must not repeat"
            )
            records = h.trace_records()
            reasons = [r.get("reason") for r in records if r.get("type") == "run_end"]
            self.assertIn("stopped", reasons)
            self.assertNotIn("completed", reasons)

    async def test_stop_then_start_is_restartable(self):
        with EngineHarness(
            users=[UserRecord(nick="a"), UserRecord(nick="b")]
        ) as h:
            h.engine._stack = [StopRequestBlock()]
            await h.engine.execute(None)
            self.assertEqual(h.engine._state.state, RunState.DONE)
            # Second run on fresh memory must start (no ValueError).
            h.engine._memory = FakeMemory([UserRecord(nick="c")])
            h.engine._stack = [make_ok_block()]
            await h.engine.execute(None)  # must not raise
            self.assertEqual(h.engine._state.state, RunState.DONE)
            self.assertEqual(h.stack_complete, [True, True])

    async def test_repeated_stop_calls_are_safe(self):
        with EngineHarness(users=[UserRecord(nick="a")]) as h:
            h.engine._stack = [make_ok_block()]
            h.engine.stop()
            h.engine.stop()
            h.engine.stop()
            await h.engine.execute(None)
            # Fresh run clears the stale stop (existing contract).
            self.assertEqual(h.engine._state.state, RunState.DONE)

    async def test_stop_latency_under_500ms_with_cooperative_cdp(self):
        from actions.wait_page import WaitPageLoad

        with EngineHarness(users=[UserRecord(nick="a")]) as h:
            gate = asyncio.Event()
            cdp = FakeCDP()
            cdp.hang_event = gate
            h.engine._cdp = cdp
            wait = WaitPageLoad(
                target_selector="div", timeout_ms=30000, pre_delay_ms=0
            )
            h.engine._stack = [wait]

            async def stopper():
                while cdp.calls < 1:
                    await asyncio.sleep(0.01)
                t1 = time.monotonic()
                h.engine.stop()
                return t1

            t0 = time.monotonic()
            stop_task = asyncio.ensure_future(stopper())
            run_task = asyncio.ensure_future(h.engine.execute(None))
            await asyncio.wait_for(
                asyncio.gather(run_task, stop_task), timeout=5
            )
            dt = time.monotonic() - t0
            gate.set()
            self.assertLess(dt, 0.5 + 0.4, f"cooperative stop took {dt:.2f}s")
            self.assertEqual(h.memory.marked, [])
            self.assertEqual(h.user_done, [("a", False)])

    async def test_progress_stop_counts_as_failed_with_identity_in_outcome(self):
        with EngineHarness(
            users=[UserRecord(nick="a"), UserRecord(nick="b")]
        ) as h:
            h.engine._stack = [StopRequestBlock()]
            await h.engine.execute(None)
            # First user stopped before mark → failed+1; second never starts.
            self.assertEqual(h.engine.progress.failed, 1)
            self.assertEqual(h.engine.progress.done, 0)
            # Identity preserved outside the wire counter:
            self.assertEqual(h.user_done, [("a", False)])
            records = h.trace_records()
            self.assertTrue(
                any(r.get("reason") == "stopped" for r in records),
                "stop identity must be in the trace",
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
