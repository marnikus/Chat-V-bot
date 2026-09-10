"""AREA C2 — cycle modes through the real engine (effect traces).

Pins the decision-precedence table + bookkeeping invariants. All pass on
baseline except test_stop_after_first_user (C1 pre-mark gate, red until C1);
all must pass before and after the C2 extraction (parity); the new
pure-table tests in test_cycle_plan_unit.py are the red-then-green part.
"""

from __future__ import annotations

import asyncio
import unittest

from actions.base_action import ActionResult, BaseAction
from actions.take_person import TakePerson
from services.run.hooks import STANDALONE_NICK
from stores.user_memory import UserRecord

from tests.integration.run_safety._helpers import (
    EngineHarness,
    FakeMemory,
    FailBlock,
    SkipBlock,
    make_ok_block,
)


class CycleModesCase(unittest.IsolatedAsyncioTestCase):
    async def test_multi_user_queued_marks_each_success(self):
        with EngineHarness(
            users=[UserRecord(nick="a"), UserRecord(nick="b")]
        ) as h:
            block = make_ok_block()
            h.engine._stack = [block]
            await h.engine.execute(None)
            self.assertEqual(block.calls, ["a", "b"])
            self.assertEqual(h.memory.marked, ["a", "b"])
            self.assertEqual(h.user_done, [("a", True), ("b", True)])
            self.assertEqual(h.engine.progress.done, 2)

    async def test_zero_users_with_user_blocks_is_empty(self):
        with EngineHarness(users=[]) as h:

            class NeedsUser(BaseAction):
                block_id = "TEST_C2_NEEDS"
                name = "needs"
                icon = "x"

                async def execute(self, nick, cdp, engine=None):
                    return ActionResult.OK

            # CLICK_USER id makes it user-scoped for the mode branch.
            NeedsUser.block_id = "CLICK_USER"
            blk = NeedsUser(pre_delay_ms=0)
            # Ensure the mem-click flag is absent/False.
            blk.use_person_from_memory = False
            h.engine._stack = [blk]
            await h.engine.execute(None)
            records = h.trace_records()
            self.assertTrue(
                any(
                    r.get("type") == "run_skip"
                    and r.get("reason") == "empty_queue"
                    for r in records
                )
            )
            self.assertEqual(h.memory.marked, [])

    async def test_all_disabled_marks_nobody(self):
        with EngineHarness(users=[UserRecord(nick="a")]) as h:
            block = make_ok_block()
            block.enabled = False
            h.engine._stack = [block]
            await h.engine.execute(None)
            self.assertEqual(h.user_done, [("a", False)])
            self.assertEqual(h.memory.marked, [])

    async def test_no_stack_is_empty_stack(self):
        # Queue must be empty for empty-stack (nonempty queue wins by design).
        with EngineHarness(users=[]) as h:
            h.engine._stack = []
            await h.engine.execute(None)
            text = " ".join(h.logs).lower()
            self.assertIn("empty", text)

    async def test_standalone_runs_once_without_mark(self):
        with EngineHarness(users=[]) as h:
            block = make_ok_block()
            h.engine._stack = [block]
            await h.engine.execute(None)
            self.assertEqual(block.calls, [STANDALONE_NICK])
            self.assertEqual(h.memory.marked, [])
            self.assertEqual(h.user_done, [])

    async def test_standalone_failure_reports_error(self):
        with EngineHarness(users=[]) as h:
            block = FailBlock()
            h.engine._stack = [block]
            await h.engine.execute(None)
            self.assertEqual(block.calls, [STANDALONE_NICK])
            self.assertTrue(any(lvl == "error" for _, lvl in h.debug))

    async def test_take_miss_without_user_blocks_is_empty(self):
        with EngineHarness(users=[UserRecord(nick="a")]) as h:
            take = TakePerson(pick_mode="random_new")
            # Force no match by marking everyone done first.
            for u in h.memory._users:
                u.messaged = True
            h.engine._stack = [take, make_ok_block()]
            # make_ok_block is TEST_* (not user-scoped) → take-miss branch.
            await h.engine.execute(None)
            records = h.trace_records()
            self.assertTrue(
                any(
                    r.get("type") == "run_skip"
                    and r.get("reason") == "no_take_match"
                    for r in records
                )
            )

    async def test_memory_selection_present_runs_single_target_once(self):
        with EngineHarness(
            users=[UserRecord(nick="Anna"), UserRecord(nick="Bella")]
        ) as h:

            class PickBella(BaseAction):
                block_id = "TAKE_PERSON"
                name = "Pick"
                icon = "x"

                def choose(self, rows, engine=None):
                    return "Bella"

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
                    return ActionResult.OK

            click = MemClick()
            h.engine._stack = [PickBella(pre_delay_ms=0), click]
            await h.engine.execute(None)
            self.assertEqual(click.calls, ["Bella"])
            self.assertEqual(h.memory.marked, ["Bella"])
            self.assertEqual(h.user_done, [("Bella", True)])

    async def test_memory_selection_missing_is_safe_empty(self):
        with EngineHarness(users=[UserRecord(nick="Anna")]) as h:

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
                    return ActionResult.OK

            click = MemClick()
            h.engine._stack = [click]
            await h.engine.execute(None)
            self.assertEqual(click.calls, [])
            self.assertEqual(h.memory.marked, [])
            records = h.trace_records()
            self.assertTrue(
                any(
                    r.get("type") == "run_skip"
                    and r.get("reason") == "no_memory_nick"
                    for r in records
                )
            )

    async def test_one_failure_then_next_user(self):
        with EngineHarness(
            users=[UserRecord(nick="a"), UserRecord(nick="b")]
        ) as h:
            fail = FailBlock()
            # Fail only for user a: flip to OK after first call.
            orig = fail.execute

            async def flaky(nick, cdp, engine=None):
                fail.calls.append(nick)
                if nick == "a":
                    return ActionResult.FAIL
                return ActionResult.OK

            fail.execute = flaky  # type: ignore
            h.engine._stack = [fail]
            await h.engine.execute(None)
            self.assertEqual(h.user_done, [("a", False), ("b", True)])
            self.assertEqual(h.memory.marked, ["b"])

    async def test_skip_stops_user_without_mark(self):
        with EngineHarness(users=[UserRecord(nick="a")]) as h:
            h.engine._stack = [SkipBlock()]
            await h.engine.execute(None)
            self.assertEqual(h.user_done, [("a", False)])
            self.assertEqual(h.memory.marked, [])

    async def test_conditional_skip_for_messaged_user(self):
        with EngineHarness(
            users=[
                UserRecord(nick="old", messaged=True),
                UserRecord(nick="new", messaged=False),
            ]
        ) as h:

            class CondSkip(BaseAction):
                block_id = "CONDITIONAL_SKIP"
                name = "Cond"
                icon = "x"

                async def execute(self, nick, cdp, engine=None):
                    return ActionResult.OK

            block = make_ok_block()
            h.engine._stack = [CondSkip(pre_delay_ms=0), block]
            await h.engine.execute(None)
            # Queue hides messaged users, so only "new" runs.
            self.assertEqual(block.calls, ["new"])
            self.assertEqual(h.memory.marked, ["new"])

    async def test_repeat_termination_on_empty(self):
        from actions.repeat_loop import RepeatLoop

        with EngineHarness(users=[]) as h:

            class NeedsUser(BaseAction):
                block_id = "CLICK_USER"
                name = "Click"
                icon = "x"

                def __init__(self, **kw):
                    super().__init__(pre_delay_ms=0)
                    self.use_person_from_memory = False
                    self.calls = []

                async def execute(self, nick, cdp, engine=None):
                    self.calls.append(nick)
                    return ActionResult.OK

            click = NeedsUser()
            h.engine._stack = [RepeatLoop(repeat_count=5), click]
            await h.engine.execute(None)
            self.assertEqual(click.calls, [])
            self.assertTrue(any("Repeat Loop" in m for m in h.logs))

    async def test_label_filter_order(self):
        with EngineHarness(
            users=[UserRecord(nick="keep"), UserRecord(nick="drop")]
        ) as h:
            h.engine.label_filter = lambda n: n != "drop"
            block = make_ok_block()
            h.engine._stack = [block]
            await h.engine.execute(None)
            self.assertEqual(block.calls, ["keep"])
            self.assertEqual(h.memory.marked, ["keep"])

    async def test_stop_after_first_user(self):
        with EngineHarness(
            users=[UserRecord(nick="a"), UserRecord(nick="b")]
        ) as h:
            block = make_ok_block()

            async def stop_after_a(engine, nick):
                if nick == "a":
                    engine.stop()

            block.on_run = stop_after_a
            h.engine._stack = [block]
            await h.engine.execute(None)
            # Stop requested during final block of user a: with the C1
            # pre-mark gate, user a is NOT auto-marked.
            self.assertEqual(block.calls, ["a"])
            self.assertEqual(h.memory.marked, [])
            self.assertEqual(h.user_done, [("a", False)])


if __name__ == "__main__":
    unittest.main(verbosity=2)
