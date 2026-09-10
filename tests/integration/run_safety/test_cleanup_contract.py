"""Area C1 — cleanup, cancellation and hook-failure precedence.

Parent design: docs/SAFETY_REFACTOR_AREA_C_IMPL_DESIGN_2026-09-10.md §3.2–§3.4 (B3/B4/B5).
Task list: docs/SAFETY_REFACTOR_AREA_C_2026-09-10.md C1a/C1c.

Test-first: fails against the baseline (post_run masks cleanup, CancelledError
skips restoration, hook failures are unhandled), passes after C1.
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
from services.run.hooks import RunHooks  # noqa: E402
from stores.user_memory import UserRecord  # noqa: E402

try:
    from actions.cancellation import RunStopped  # noqa: E402
    HAS_CANCELLATION = True
except ImportError:
    HAS_CANCELLATION = False

    class RunStopped(Exception):
        pass


class RecordingBlock(BaseAction):
    block_id = "CUSTOM_FIND"
    name = "Find & Click"
    icon = "🔎"

    def __init__(self, **kw):
        super().__init__(pre_delay_ms=0)
        self.calls = []
        self.message = kw.get("message", "hi {{nick}}")

    async def execute(self, user_nick, cdp, engine=None):
        self.calls.append(user_nick)
        return ActionResult.OK


class GateBlock(BaseAction):
    block_id = "CUSTOM_FIND"
    name = "Find & Click"
    icon = "🔎"

    def __init__(self, **kw):
        super().__init__(pre_delay_ms=0)
        self.calls = []
        self.gate = asyncio.Event()

    async def execute(self, user_nick, cdp, engine=None):
        self.calls.append(user_nick)
        await self.gate.wait()
        return ActionResult.OK


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
        self.stack_complete = []
        self.engine.log_msg.connect(lambda m: self.logs.append(m))
        self.engine.debug_msg.connect(lambda m, l: self.debug.append((m, l)))
        self.engine.user_complete.connect(
            lambda n, ok: self.user_done.append((n, ok)))
        self.engine.stack_complete.connect(
            lambda: self.stack_complete.append(True))
        return self.engine


# ── post_run precedence (B3) ──────────────────────────────────────
class TestPostRunFailures(EngineCase):
    async def test_post_run_raise_still_cleans_up_and_reports_once(self):
        engine = self.make([UserRecord(nick="a")])
        block = RecordingBlock()
        engine._stack = [block]

        class BadPost(RunHooks):
            def post_run(self, coordinator, outcome):
                raise RuntimeError("post exploded")

        engine._hooks = BadPost()
        await engine.execute()  # must not raise for ordinary hook errors
        self.assertFalse(engine.is_running)
        self.assertIsNone(engine._tracer,
                          "tracer must be closed even when post_run raises")
        self.assertEqual(engine._ctx, {})
        self.assertEqual(self.stack_complete, [True],
                         "completion must fire exactly once")
        self.assertEqual(block.calls, ["a"])
        text = " ".join(m for m, _ in self.debug) + " " + " ".join(self.logs)
        self.assertIn("post", text.lower())

    async def test_post_run_cancel_still_cleans_up_then_propagates(self):
        engine = self.make([UserRecord(nick="a")])
        engine._stack = [RecordingBlock()]

        class CancelPost(RunHooks):
            async def post_run(self, coordinator, outcome):
                raise asyncio.CancelledError()

        engine._hooks = CancelPost()
        with self.assertRaises(asyncio.CancelledError):
            await engine.execute()
        self.assertFalse(engine.is_running)
        self.assertIsNone(engine._tracer)
        self.assertEqual(self.stack_complete, [True])

    async def test_pre_run_raise_resets_and_completes_once(self):
        engine = self.make([UserRecord(nick="a")])
        engine._stack = [RecordingBlock()]

        class BadPre(RunHooks):
            def pre_run(self, coordinator):
                raise RuntimeError("pre exploded")

        outcomes = []

        class BadPreAndPost(BadPre):
            def post_run(self, coordinator, outcome):
                outcomes.append(outcome)

        engine._hooks = BadPreAndPost()
        await engine.execute()
        self.assertFalse(engine.is_running)
        self.assertEqual(self.stack_complete, [True])
        self.assertEqual(outcomes, ["worked"],
                         "post_run still observes the run outcome on pre failure")

    async def test_action_hook_raise_is_contained_and_run_continues(self):
        engine = self.make([UserRecord(nick="a"), UserRecord(nick="b")])
        block = RecordingBlock()
        engine._stack = [block]

        class BadAction(RunHooks):
            def on_action_complete(self, coordinator, block, nick, status):
                raise RuntimeError("hook exploded")

        engine._hooks = BadAction()
        await engine.execute()
        self.assertEqual(block.calls, ["a", "b"],
                         "a raising on_action_complete must not kill the run")
        self.assertEqual(self.user_done, [("a", True), ("b", True)])
        self.assertEqual(self.stack_complete, [True])


# ── external cancellation (B4) ────────────────────────────────────
class TestExternalCancellation(EngineCase):
    async def test_cancel_mid_block_propagates_after_cleanup_without_mark(self):
        engine = self.make([UserRecord(nick="a")])
        gated = GateBlock()
        engine._stack = [gated]
        task = asyncio.ensure_future(engine.execute())
        while not gated.calls:
            await asyncio.sleep(0.01)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertFalse(engine.is_running)
        self.assertIsNone(engine._tracer)
        self.assertEqual(self.stack_complete, [True])
        self.assertEqual(self.memory.marked, [],
                         "cancelled work must never be auto-marked")
        self.assertNotIn(("a", True), self.user_done)
        from services.run.state_machine import RunState
        self.assertEqual(engine._state.state, RunState.IDLE,
                         "external cancel resets to restartable IDLE")
        # Restart works.
        engine._stack = [RecordingBlock()]
        await engine.execute()
        self.assertEqual(self.memory.marked, ["a"])

    async def test_cancel_while_paused_propagates_and_cleans_up(self):
        engine = self.make([UserRecord(nick="a"), UserRecord(nick="b")])
        gated = GateBlock()
        engine._stack = [gated]
        task = asyncio.ensure_future(engine.execute())
        while not gated.calls:
            await asyncio.sleep(0.01)
        engine.pause()
        gated.gate.set()
        await asyncio.sleep(0.3)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertFalse(engine.is_running)
        self.assertEqual(self.stack_complete, [True])


# ── expansion restoration (B5) ────────────────────────────────────
class TestExpansionRestoration(EngineCase):
    async def test_nick_expansion_restored_on_block_error(self):
        engine = self.make([UserRecord(nick="Zoe")])

        class Boom(BaseAction):
            block_id = "CUSTOM_FIND"
            name = "Find & Click"
            icon = "🔎"

            def __init__(self):
                super().__init__(pre_delay_ms=0)
                self.selector = 'li:has-text("{{nick}}")'

            async def execute(self, user_nick, cdp, engine=None):
                raise RuntimeError("boom")

        block = Boom()
        engine._stack = [block]
        engine._tracer = None
        # Drive the user path directly with a stub tracer.
        from services.run.hooks import RunTracer
        engine._tracer = RunTracer("test-restore", log_dir="logs")
        try:
            out = await engine._execute_for_user(UserRecord(nick="Zoe"), False)
            self.assertEqual(out, "fail")
            self.assertEqual(block.selector, 'li:has-text("{{nick}}")',
                             "expansion must be restored even on error")
            self.assertEqual(engine._ctx, {})
        finally:
            engine._tracer.close()
            engine._tracer = None

    async def test_nick_expansion_restored_on_cancel(self):
        engine = self.make([UserRecord(nick="Zoe")])

        class Hanging(BaseAction):
            block_id = "CUSTOM_FIND"
            name = "Find & Click"
            icon = "🔎"

            def __init__(self):
                super().__init__(pre_delay_ms=0)
                self.selector = 'x-{{nick}}-y'
                self.entered = asyncio.Event()

            async def execute(self, user_nick, cdp, engine=None):
                self.entered.set()
                await asyncio.sleep(30)
                return ActionResult.OK

        block = Hanging()
        engine._stack = [block]
        from services.run.hooks import RunTracer
        engine._tracer = RunTracer("test-restore-cancel", log_dir="logs")
        try:
            task = asyncio.ensure_future(
                engine._execute_for_user(UserRecord(nick="Zoe"), False))
            await block.entered.wait()
            # Expansion happened before the hang.
            self.assertEqual(block.selector, "x-Zoe-y")
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            self.assertEqual(block.selector, "x-{{nick}}-y",
                             "expansion must be restored even on cancel")
            self.assertEqual(engine._ctx, {})
        finally:
            engine._tracer.close()
            engine._tracer = None

    async def test_nick_expansion_restored_on_cooperative_stop(self):
        if not HAS_CANCELLATION:
            self.fail("actions/cancellation.py must exist (Area C1)")
        engine = self.make([UserRecord(nick="Zoe")])

        class Stopper(BaseAction):
            block_id = "CUSTOM_FIND"
            name = "Find & Click"
            icon = "🔎"

            def __init__(self):
                super().__init__(pre_delay_ms=0)
                self.selector = 'x-{{nick}}-y'

            async def execute(self, user_nick, cdp, engine=None):
                raise RunStopped()

        block = Stopper()
        engine._stack = [block]
        from services.run.hooks import RunTracer
        engine._tracer = RunTracer("test-restore-stop", log_dir="logs")
        try:
            out = await engine._execute_for_user(UserRecord(nick="Zoe"), False)
            self.assertEqual(out, "stop")
            self.assertEqual(block.selector, "x-{{nick}}-y")
            self.assertEqual(engine._ctx, {})
        finally:
            engine._tracer.close()
            engine._tracer = None


ActionRegistry._classes.clear()
ActionRegistry._classes.update(_REGISTRY_SNAPSHOT)

if __name__ == "__main__":
    unittest.main(verbosity=2)
