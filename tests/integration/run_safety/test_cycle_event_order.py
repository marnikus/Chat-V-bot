"""AREA C2 — cycle event/signal ordering + snapshot parity.

Asserts effect-trace order (collect/filter/order/take → steps → marks →
signals → progress → outcome) with volatile fields normalized. Must pass
before and after C2 extraction.
"""

from __future__ import annotations

import asyncio
import unittest

from actions.base_action import ActionResult, BaseAction
from services.run.hooks import RunHooks, STANDALONE_NICK
from stores.user_memory import UserRecord

from tests.integration.run_safety._helpers import (
    EngineHarness,
    FakeMemory,
    make_ok_block,
)


class EventOrderCase(unittest.IsolatedAsyncioTestCase):
    async def test_queued_event_order(self):
        with EngineHarness(
            users=[UserRecord(nick="a"), UserRecord(nick="b")]
        ) as h:
            events = []
            h.engine.step_started.connect(
                lambda i, b, u: events.append(f"started:{b}:{u}")
            )
            h.engine.step_complete.connect(
                lambda n, u: events.append(f"complete:{n}:{u}")
            )
            h.engine.user_complete.connect(
                lambda n, ok: events.append(f"user:{n}:{ok}")
            )
            h.engine.person_marked.connect(
                lambda n: events.append(f"marked:{n}")
            )
            block = make_ok_block()
            block.custom_name = "Step"
            h.engine._stack = [block]
            await h.engine.execute(None)
            # Per user: started → complete → marked → user-complete.
            self.assertEqual(
                events,
                [
                    "started:TEST_OK_GENERIC:a",
                    "complete:Step:a",
                    "marked:a",
                    "user:a:True",
                    "started:TEST_OK_GENERIC:b",
                    "complete:Step:b",
                    "marked:b",
                    "user:b:True",
                ],
            )

    async def test_standalone_event_order(self):
        with EngineHarness(users=[]) as h:
            events = []
            h.engine.step_started.connect(
                lambda i, b, u: events.append(f"started:{u}")
            )
            h.engine.user_complete.connect(
                lambda n, ok: events.append(f"user:{n}")
            )
            h.engine.person_marked.connect(lambda n: events.append("marked"))
            block = make_ok_block()
            h.engine._stack = [block]
            await h.engine.execute(None)
            self.assertIn(f"started:{STANDALONE_NICK}", events)
            self.assertNotIn("marked", events)
            self.assertEqual([e for e in events if e.startswith("user:")], [])

    async def test_progress_increments_per_user(self):
        with EngineHarness(
            users=[UserRecord(nick="a"), UserRecord(nick="b")]
        ) as h:
            seen = []
            orig_emit = h.engine.progress.emit

            def spy_emit():
                seen.append(
                    (
                        h.engine.progress.done,
                        h.engine.progress.total,
                        h.engine.progress.skipped,
                        h.engine.progress.failed,
                    )
                )
                return orig_emit()

            h.engine.progress.emit = spy_emit  # type: ignore
            h.engine._stack = [make_ok_block()]
            await h.engine.execute(None)
            # Total extended to 2, then done increments per user.
            self.assertIn((0, 2, 0, 0), seen)
            self.assertIn((1, 2, 0, 0), seen)
            self.assertIn((2, 2, 0, 0), seen)

    async def test_stack_mutating_hook_parity(self):
        # A hook that legally mutates the stack mid-preparation must see the
        # same mode selection before/after C2 (no hoisted snapshot).
        with EngineHarness(users=[UserRecord(nick="a")]) as h1:
            injected = make_ok_block()

            class InjectingHooks(RunHooks):
                def pre_run(self, coordinator):
                    # Inject a standalone-capable block before the run.
                    coordinator._stack.append(injected)

            h1.engine._hooks = InjectingHooks()
            h1.engine._stack = [make_ok_block()]
            await h1.engine.execute(None)
            calls1 = list(injected.calls)

        with EngineHarness(users=[UserRecord(nick="a")]) as h2:
            injected2 = make_ok_block()

            class InjectingHooks2(RunHooks):
                def pre_run(self, coordinator):
                    coordinator._stack.append(injected2)

            h2.engine._hooks = InjectingHooks2()
            h2.engine._stack = [make_ok_block()]
            await h2.engine.execute(None)
            calls2 = list(injected2.calls)

        self.assertEqual(calls1, calls2)
        self.assertEqual(calls1, ["a"])

    async def test_stop_tail_marks_stopped_once(self):
        with EngineHarness(
            users=[UserRecord(nick="a"), UserRecord(nick="b")]
        ) as h:
            block = make_ok_block()

            async def stop_on_a(engine, nick):
                if nick == "a":
                    engine.stop()

            block.on_run = stop_on_a
            h.engine._stack = [block]
            await h.engine.execute(None)
            records = h.trace_records()
            ends = [r for r in records if r.get("type") == "run_end"]
            self.assertTrue(ends)
            self.assertEqual(ends[-1].get("reason"), "stopped")
            self.assertEqual(h.stack_complete, [True])

    async def test_take_phase_order_before_user_execution(self):
        from actions.take_person import TakePerson

        with EngineHarness(
            users=[UserRecord(nick="Anna"), UserRecord(nick="Bella")]
        ) as h:
            order = []
            take = TakePerson(pick_mode="order_first")
            orig_choose = take.choose

            def spy_choose(rows, engine=None):
                order.append("take")
                return orig_choose(rows, engine)

            take.choose = spy_choose  # type: ignore
            block = make_ok_block()

            async def spy_run(engine, nick):
                order.append(f"run:{nick}")

            block.on_run = spy_run
            h.engine._stack = [take, block]
            await h.engine.execute(None)
            self.assertTrue(order[0] == "take")
            self.assertIn("run:Anna", order)

    async def test_external_cancel_event_tail(self):
        from tests.integration.run_safety._helpers import SlowBlock

        with EngineHarness(users=[UserRecord(nick="a")]) as h:
            h.engine._stack = [SlowBlock(delay=5.0)]
            task = asyncio.ensure_future(h.engine.execute(None))
            await asyncio.sleep(0.15)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            records = h.trace_records()
            ends = [r for r in records if r.get("type") == "run_end"]
            self.assertTrue(ends)
            self.assertNotEqual(ends[-1].get("reason"), "completed")
            self.assertEqual(h.stack_complete, [True])


if __name__ == "__main__":
    unittest.main(verbosity=2)
