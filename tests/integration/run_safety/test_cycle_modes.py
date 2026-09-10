"""Area C2 — cycle mode matrix through the real engine (effect traces).

Parent design: docs/SAFETY_REFACTOR_AREA_C_IMPL_DESIGN_2026-09-10.md §4 + §5.
Task list: docs/SAFETY_REFACTOR_AREA_C_2026-09-10.md C2.

Parity suite: non-stop rows pass before and after C1/C2 (they pin the extraction).
Stop-pre-empts rows fail before C1 (B2/B6/B11) and pass after.
All rows must pass identically after the C2 extraction (no silent semantic change).
"""

import asyncio
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))))

from actions.base_action import (ActionResult, ActionRegistry,  # noqa: E402
                                 BaseAction)
_REGISTRY_SNAPSHOT = dict(ActionRegistry._classes)

from services.run import RunCoordinator  # noqa: E402
from services.run.hooks import STANDALONE_NICK, RunHooks  # noqa: E402
from stores.user_memory import UserRecord  # noqa: E402


class RecordingBlock(BaseAction):
    block_id = "CUSTOM_FIND"
    name = "Find & Click"
    icon = "🔎"

    def __init__(self, result=ActionResult.OK, **kw):
        super().__init__(pre_delay_ms=0)
        self.calls = []
        self._result = result

    async def execute(self, user_nick, cdp, engine=None):
        self.calls.append(user_nick)
        return self._result


class UserBlock(BaseAction):
    block_id = "CLICK_USER"
    name = "Click User"
    icon = "👤"

    def __init__(self, **kw):
        super().__init__(pre_delay_ms=0)
        self.calls = []
        self.use_person_from_memory = False

    async def execute(self, user_nick, cdp, engine=None):
        self.calls.append(user_nick)
        return ActionResult.OK


class MemoryClickBlock(UserBlock):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.use_person_from_memory = True


class TakeStub:
    block_id = "TAKE_PERSON"
    enabled = True
    mode_phrase = "matching person"

    def __init__(self, nick=None):
        self._nick = nick

    def choose(self, rows, eng=None):
        return self._nick


class FakeMemory:
    def __init__(self, users=None):
        self._users = list(users or [])
        self.marked = []

    async def get_queue(self):
        return [u for u in self._users if not u.messaged]

    async def get_all(self):
        return list(self._users)

    async def upsert_user(self, user):
        self._users.append(user)

    async def mark_messaged(self, nick):
        self.marked.append(nick)
        for u in self._users:
            if u.nick == nick:
                u.messaged = True


class OutcomeHooks(RunHooks):
    def __init__(self):
        self.outcomes = []

    def post_run(self, coordinator, outcome):
        self.outcomes.append(outcome)


class EngineCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.old = os.getcwd()
        self.tmp = tempfile.TemporaryDirectory()
        os.chdir(self.tmp.name)
        self.addCleanup(self._restore_registry)

    def tearDown(self):
        os.chdir(self.old)
        self.tmp.cleanup()

    def _restore_registry(self):
        ActionRegistry._classes.clear()
        ActionRegistry._classes.update(_REGISTRY_SNAPSHOT)

    def make(self, users=None):
        self.memory = FakeMemory(users)
        self.engine = RunCoordinator(cdp=None, memory=self.memory,
                                     criteria=None)
        self.logs = []
        self.debug = []
        self.user_done = []
        self.engine.log_msg.connect(lambda m: self.logs.append(m))
        self.engine.debug_msg.connect(lambda m, l: self.debug.append((m, l)))
        self.engine.user_complete.connect(
            lambda n, ok: self.user_done.append((n, ok)))
        self.hooks = OutcomeHooks()
        self.engine._hooks = self.hooks
        return self.engine


class TestCycleModes(EngineCase):
    async def test_memory_click_precedence_single_target_once_per_cycle(self):
        engine = self.make([UserRecord(nick="Anna"), UserRecord(nick="Bella")])
        take = TakeStub(nick="Bella")
        click = MemoryClickBlock()
        consumer = RecordingBlock()
        engine._stack = [take, click, consumer]
        await engine.execute()
        self.assertEqual(click.calls, ["Bella"],
                         "single-target runs the saved nick once, not per queue entry")
        self.assertEqual(consumer.calls, ["Bella"])
        self.assertEqual(self.memory.marked, ["Bella"])
        self.assertNotIn("Anna", click.calls)
        self.assertEqual(self.hooks.outcomes, ["worked"])

    async def test_take_miss_without_user_blocks_is_empty(self):
        # Empty queue is required for the no_take_match short-circuit; with a
        # non-empty queue the engine correctly runs queued mode instead.
        engine = self.make([])
        take = TakeStub(nick=None)
        plain = RecordingBlock()
        engine._stack = [take, plain]
        await engine.execute()
        self.assertEqual(plain.calls, [],
                         "take-miss with no user blocks must not go standalone")
        self.assertEqual(self.hooks.outcomes, ["empty"])
        self.assertEqual(self.memory.marked, [])
        text = " ".join(self.logs)
        self.assertIn("Pick Person", text)

    async def test_queued_mode_runs_each_user(self):
        engine = self.make([UserRecord(nick="a"), UserRecord(nick="b")])
        block = RecordingBlock()
        engine._stack = [block]
        await engine.execute()
        self.assertEqual(block.calls, ["a", "b"])
        self.assertEqual(self.memory.marked, ["a", "b"])
        self.assertEqual(self.user_done, [("a", True), ("b", True)])
        self.assertEqual(self.hooks.outcomes, ["worked"])

    async def test_empty_stack_reports_empty_stack(self):
        # Empty queue + empty stack -> empty_stack. (A non-empty queue takes
        # precedence and runs queued mode even with an empty stack — pinned
        # separately in the planner truth table.)
        engine = self.make([])
        engine._stack = []
        await engine.execute()
        text = " ".join(self.logs).lower()
        self.assertIn("empty", text)

    async def test_empty_queue_with_user_blocks_is_empty(self):
        engine = self.make([])
        block = UserBlock()
        engine._stack = [block]
        await engine.execute()
        self.assertEqual(block.calls, [])
        text = " ".join(m for m, _ in self.debug)
        self.assertIn("CLICK_USER", text)

    async def test_standalone_runs_once_and_never_marks_sentinel(self):
        engine = self.make([])
        block = RecordingBlock()
        engine._stack = [block]
        await engine.execute()
        self.assertEqual(block.calls, [STANDALONE_NICK])
        self.assertEqual(self.memory.marked, [],
                         "successful standalone must not mark the sentinel nick")
        self.assertEqual(self.user_done, [],
                         "standalone emits no per-user completion")

    async def test_all_disabled_marks_nobody(self):
        engine = self.make([UserRecord(nick="a")])
        block = RecordingBlock()
        block.enabled = False
        engine._stack = [block]
        await engine.execute()
        self.assertEqual(self.user_done, [("a", False)])
        self.assertEqual(self.memory.marked, [])

    async def test_fail_and_skip_never_auto_mark(self):
        engine = self.make([UserRecord(nick="a"), UserRecord(nick="b")])

        class FailThenOk(BaseAction):
            block_id = "CUSTOM_FIND"
            name = "Find & Click"
            icon = "🔎"

            def __init__(self):
                super().__init__(pre_delay_ms=0)
                self.calls = []

            async def execute(self, user_nick, cdp, engine=None):
                self.calls.append(user_nick)
                if user_nick == "a":
                    return ActionResult.FAIL
                return ActionResult.OK

        block = FailThenOk()
        engine._stack = [block]
        await engine.execute()
        self.assertEqual(self.user_done, [("a", False), ("b", True)])
        self.assertEqual(self.memory.marked, ["b"])

    async def test_stop_preempts_normal_completion(self):
        engine = self.make([UserRecord(nick="a"), UserRecord(nick="b")])

        class StopOnFirst(BaseAction):
            block_id = "CUSTOM_FIND"
            name = "Find & Click"
            icon = "🔎"

            def __init__(self):
                super().__init__(pre_delay_ms=0)
                self.calls = []

            async def execute(self, user_nick, cdp, engine=None):
                self.calls.append(user_nick)
                if user_nick == "a":
                    engine.stop()
                return ActionResult.OK

        first = StopOnFirst()
        second = RecordingBlock()
        engine._stack = [first, second]
        await engine.execute()
        self.assertEqual(self.hooks.outcomes, ["stopped"],
                         "stop must take precedence over normal completion")
        self.assertNotIn("b", first.calls)
        self.assertEqual(self.memory.marked, [],
                         "stopped work must not be auto-marked")


ActionRegistry._classes.clear()
ActionRegistry._classes.update(_REGISTRY_SNAPSHOT)

if __name__ == "__main__":
    unittest.main(verbosity=2)
