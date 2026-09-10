"""AREA C1 — cleanup contract: external cancel, hook failures, restoration.

Red on baseline (RUNNING strands, post_run can skip cleanup, nick/_ctx not
restored on cancel, RunStopped retried); green after C1.
"""

from __future__ import annotations

import asyncio
import unittest

from actions.base_action import ActionResult, BaseAction
from services.run.error_recovery import RetryPolicy
from services.run.hooks import RunHooks
from services.run.state_machine import RunState
from stores.user_memory import UserRecord

from tests.integration.run_safety._helpers import (
    EngineHarness,
    FakeMemory,
    RunStopped,
    SlowBlock,
    make_ok_block,
)


class CleanupCase(unittest.IsolatedAsyncioTestCase):
    async def test_external_cancel_propagates_after_cleanup(self):
        with EngineHarness(users=[UserRecord(nick="a")]) as h:
            h.engine._stack = [SlowBlock(delay=5.0)]
            task = asyncio.ensure_future(h.engine.execute(None))
            await asyncio.sleep(0.15)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            self.assertFalse(h.engine.is_running)
            self.assertEqual(h.engine._ctx, {})
            self.assertIsNone(h.engine._tracer, "tracer must be closed")
            self.assertEqual(h.stack_complete, [True], "signal exactly once")
            self.assertEqual(h.engine._state.state, RunState.ERROR)
            self.assertEqual(h.memory.marked, [], "cancel must not mark")
            # Restartable after cancel.
            h.engine._memory = FakeMemory([UserRecord(nick="b")])
            h.engine._stack = [make_ok_block()]
            await h.engine.execute(None)
            self.assertEqual(h.engine._state.state, RunState.DONE)

    async def test_cancel_restores_nick_expansion_and_ctx(self):
        with EngineHarness(users=[UserRecord(nick="Zoe")]) as h:
            block = make_ok_block()
            block.selector = 'li:has-text("{{nick}}")'

            orig_execute = block.execute

            async def hanging_execute(nick, cdp, engine=None):
                await asyncio.sleep(5.0)
                return ActionResult.OK

            block.execute = hanging_execute  # type: ignore
            h.engine._stack = [block]
            task = asyncio.ensure_future(h.engine.execute(None))
            await asyncio.sleep(0.15)
            # Expansion happened (block attr rewritten while running).
            self.assertIn("Zoe", getattr(block, "selector", ""))
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            self.assertEqual(
                block.selector,
                'li:has-text("{{nick}}")',
                "cancel must restore {{nick}} expansion",
            )
            self.assertEqual(h.engine._ctx, {})

    async def test_pre_run_failure_still_runs_post_run_and_signals_once(self):
        calls = []

        class Hooks(RunHooks):
            def pre_run(self, coordinator):
                calls.append("pre")
                raise RuntimeError("pre exploded")

            def post_run(self, coordinator, outcome):
                calls.append(f"post:{outcome}")

        with EngineHarness(
            users=[UserRecord(nick="a")], hooks=Hooks()
        ) as h:
            h.engine._stack = [make_ok_block()]
            await h.engine.execute(None)  # must not raise
            self.assertIn("pre", calls)
            self.assertTrue(any(c.startswith("post:") for c in calls))
            self.assertEqual(h.stack_complete, [True])
            self.assertFalse(h.engine.is_running)
            self.assertEqual(h.engine._state.state, RunState.ERROR)

    async def test_action_hook_failure_restores_and_errors(self):
        class Hooks(RunHooks):
            async def on_action_complete(
                self, coordinator, block, nick, status
            ):
                raise RuntimeError("hook exploded")

        with EngineHarness(
            users=[UserRecord(nick="Zoe")], hooks=Hooks()
        ) as h:
            block = make_ok_block()
            block.selector = 'x{{nick}}'
            h.engine._stack = [block]
            await h.engine.execute(None)  # must not raise (ERROR path)
            self.assertEqual(
                block.selector, "x{{nick}}", "hook raise must still restore"
            )
            self.assertEqual(h.engine._ctx, {})
            self.assertEqual(h.stack_complete, [True])
            self.assertEqual(h.engine._state.state, RunState.ERROR)
            self.assertFalse(h.engine.is_running)
            self.assertIsNone(h.engine._tracer)

    async def test_post_run_failure_still_cleans_up_and_propagates_on_success(self):
        class Hooks(RunHooks):
            def post_run(self, coordinator, outcome):
                raise RuntimeError("post exploded")

        with EngineHarness(
            users=[UserRecord(nick="a")], hooks=Hooks()
        ) as h:
            h.engine._stack = [make_ok_block()]
            with self.assertRaises(RuntimeError):
                await h.engine.execute(None)
            self.assertFalse(h.engine.is_running)
            self.assertIsNone(h.engine._tracer)
            self.assertEqual(h.stack_complete, [True])
            self.assertEqual(h.engine._ctx, {})
            self.assertTrue(
                any("post_run" in m.lower() for m, _ in h.debug)
                or any("post" in m.lower() for m in h.logs),
                "post_run failure must be reported, not silent",
            )

    async def test_post_run_failure_does_not_mask_original_run_error(self):
        class Hooks(RunHooks):
            def post_run(self, coordinator, outcome):
                raise RuntimeError("post exploded")

        with EngineHarness(
            users=[UserRecord(nick="a")], hooks=Hooks()
        ) as h:

            class Boom(BaseAction):
                block_id = "TEST_C1_BOOM"
                name = "boom"
                icon = "x"

                async def execute(self, nick, cdp, engine=None):
                    raise RuntimeError("body exploded")

            h.engine._stack = [Boom(pre_delay_ms=0)]
            # Body failure is contained per-user (fail, not raise); post_run
            # failure on this path must be reported, not mask the body error.
            with self.assertRaises(RuntimeError) as ctx:
                await h.engine.execute(None)
            self.assertIn("post exploded", str(ctx.exception))
            self.assertEqual(h.stack_complete, [True])
            self.assertFalse(h.engine.is_running)
            # The body error must still be visible in debug/trace.
            self.assertTrue(
                any("exploded" in m for m, _ in h.debug),
                "original body error must remain reported",
            )

    async def test_cancel_during_post_run_still_cleans_up(self):
        class Hooks(RunHooks):
            async def post_run(self, coordinator, outcome):
                await asyncio.sleep(5.0)

        with EngineHarness(
            users=[UserRecord(nick="a")], hooks=Hooks()
        ) as h:
            h.engine._stack = [make_ok_block()]
            task = asyncio.ensure_future(h.engine.execute(None))
            await asyncio.sleep(0.3)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            self.assertFalse(h.engine.is_running)
            self.assertIsNone(h.engine._tracer)
            self.assertEqual(h.stack_complete, [True])

    async def test_permissive_retry_still_cannot_retry_stop(self):
        class Permissive(RetryPolicy):
            def should_retry(self, exc, attempt):
                return True  # tries to retry everything

        policy = Permissive(max_retries=3, base_delay=0.0)
        calls = []

        async def op():
            calls.append(1)
            raise RunStopped()

        async def fallback(exc):
            calls.append("fallback")
            return "fallback-result"

        # Baseline: RunStopped unknown to retry → should_retry(True) →
        # retried or fallback. Fixed: immediate propagate, no fallback.
        kwargs = {}
        try:
            import inspect

            if "stop" in inspect.signature(policy.retry_with_backoff).parameters:
                kwargs["stop"] = None
        except Exception:
            pass
        with self.assertRaises(RunStopped):
            await policy.retry_with_backoff(op, fallback=fallback, **kwargs)
        self.assertEqual(calls, [1], "stop must never be retried")
        self.assertNotIn("fallback", calls)

    async def test_cancel_never_produces_success_trace_or_mark(self):
        with EngineHarness(users=[UserRecord(nick="a")]) as h:
            h.engine._stack = [SlowBlock(delay=5.0)]
            task = asyncio.ensure_future(h.engine.execute(None))
            await asyncio.sleep(0.15)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            records = h.trace_records()
            self.assertFalse(
                any(
                    r.get("type") == "run_end" and r.get("reason") == "completed"
                    for r in records
                ),
                "cancel must not look like success",
            )
            self.assertTrue(
                any(
                    r.get("type") == "run_end"
                    and r.get("reason") in ("cancelled", "stopped", "exception")
                    for r in records
                ),
                f"cancel must close the trace, got {[r for r in records if r.get('type')=='run_end']}",
            )
            self.assertEqual(h.memory.marked, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
