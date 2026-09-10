"""services/run — state machine, retry policy, execution-mixin branch contract.

Extends tests/integration/services/test_services_run.py (the loop/state
contract) with the exhaustive branch coverage the AREA C refactor needs:

  * every RunStateMachine transition edge (valid and invalid);
  * the idle -> paused fix (P2-8) and the pause/resume round trip;
  * RetryPolicy should_retry / retry_with_backoff branches;
  * _handle_step_result / _step_failed / mark_person_messaged branches;
  * the "stopped" announcement while paused between users;
  * the all-disabled stack contract (user must NOT be reported completed);
  * RunHooks / normalize_blocks / norm_level / RunTracer / maybe_await
    branches.

Design ref: docs/REFACTOR_2026-09-09_AREA_C_DESIGN.md §7.

Run with:  python3 -m pytest tests/integration/services/test_run_state_machine_contract.py
"""

import asyncio
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))

from actions.base_action import (ActionResult, ActionRegistry,  # noqa: E402
                                 BaseAction)

# Snapshot the global ActionRegistry BEFORE this module's fake blocks
# (CUSTOM_FIND / CONDITIONAL_SKIP / SCROLL_PARSE) shadow the shipped
# classes at import time; restored at module end and after every EngineCase
# test so later test modules see the real actions.
_REGISTRY_SNAPSHOT = dict(ActionRegistry._classes)


def _restore_action_registry():
    ActionRegistry._classes.clear()
    ActionRegistry._classes.update(_REGISTRY_SNAPSHOT)


from services.run.error_recovery import RetryPolicy  # noqa: E402
from services.run.hooks import (STANDALONE_NICK, USER_SCOPED_BLOCKS,  # noqa: E402
                                RunHooks, RunTracer, maybe_await,
                                normalize_blocks, norm_level)
from services.run.state_machine import RunState, RunStateMachine  # noqa: E402
from services.run import ActionEngine  # noqa: E402
from stores.user_memory import UserRecord  # noqa: E402


class RecordingBlock(BaseAction):
    """A block that records every user it ran for."""

    block_id = "CUSTOM_FIND"
    name = "Find & Click"
    icon = "\U0001f50e"

    def __init__(self, result=ActionResult.OK, pre_delay_ms=0, **kw):
        super().__init__(pre_delay_ms=0)
        self.calls = []
        self._result = result

    async def execute(self, user_nick, cdp, engine=None):
        self.calls.append(user_nick)
        return self._result


class GateBlock(RecordingBlock):
    """A block that parks on an event so pause/stop can land mid-user."""

    gate = None

    async def execute(self, user_nick, cdp, engine=None):
        self.calls.append(user_nick)
        if self.gate is not None:
            await self.gate.wait()
        return self._result


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

    async def delete_user(self, nick):
        return False


class EngineCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.old = os.getcwd()
        self.tmp = tempfile.TemporaryDirectory()
        os.chdir(self.tmp.name)
        # Runtime-registered fakes (e.g. the local Boom block) must not
        # shadow shipped actions for the rest of the session.
        self.addCleanup(_restore_action_registry)

    def tearDown(self):
        os.chdir(self.old)
        self.tmp.cleanup()

    def make(self, users=None):
        self.memory = FakeMemory(users)
        self.engine = ActionEngine(cdp=None, memory=self.memory,
                                   criteria=None)
        self.logs = []
        self.debug = []
        self.user_done = []
        self.marked = []
        self.stack_complete = []
        self.engine.log_msg.connect(lambda m: self.logs.append(m))
        self.engine.debug_msg.connect(lambda m, l: self.debug.append((m, l)))
        self.engine.user_complete.connect(
            lambda n, ok: self.user_done.append((n, ok)))
        self.engine.person_marked.connect(lambda n: self.marked.append(n))
        self.engine.stack_complete.connect(
            lambda: self.stack_complete.append(True))
        return self.engine


# ══════════════════════════════════════════════════════════════════
# RunStateMachine — every transition edge
# ══════════════════════════════════════════════════════════════════
class TestTransitions(unittest.TestCase):
    VALID = {
        (RunState.IDLE, RunState.RUNNING),
        (RunState.IDLE, RunState.PAUSED),      # P2-8: pause while idle is legal
        (RunState.RUNNING, RunState.PAUSED),
        (RunState.RUNNING, RunState.STOPPING),
        (RunState.RUNNING, RunState.ERROR),
        (RunState.RUNNING, RunState.DONE),
        (RunState.PAUSED, RunState.RUNNING),
        (RunState.PAUSED, RunState.STOPPING),
        (RunState.PAUSED, RunState.ERROR),
        (RunState.STOPPING, RunState.DONE),
        (RunState.STOPPING, RunState.ERROR),
        (RunState.STOPPING, RunState.IDLE),
        (RunState.ERROR, RunState.IDLE),
        (RunState.ERROR, RunState.RUNNING),
        (RunState.DONE, RunState.IDLE),
        (RunState.DONE, RunState.RUNNING),
    }

    def test_every_valid_edge_transitions(self):
        for src, dst in self.VALID:
            sm = RunStateMachine()
            sm.state = src
            self.assertEqual(sm.transition(dst), dst,
                             f"{src.value} -> {dst.value} must be allowed")

    def test_every_other_edge_raises(self):
        all_states = set(RunState)
        for src in all_states:
            for dst in all_states:
                if (src, dst) in self.VALID or src == dst:
                    continue
                sm = RunStateMachine()
                sm.state = src
                with self.assertRaises(ValueError) as ctx:
                    sm.transition(dst)
                self.assertIn(f"{src.value} -> {dst.value}",
                              str(ctx.exception))

    def test_same_state_is_a_noop(self):
        sm = RunStateMachine()
        sm.state = RunState.RUNNING
        self.assertEqual(sm.transition(RunState.RUNNING), RunState.RUNNING)

    def test_reset(self):
        sm = RunStateMachine()
        sm.state = RunState.ERROR
        self.assertEqual(sm.reset(), RunState.IDLE)

    def test_mark_running_from_error_and_done_resets_first(self):
        for src in (RunState.ERROR, RunState.DONE):
            sm = RunStateMachine()
            sm.state = src
            self.assertEqual(sm.mark_running(), RunState.RUNNING)

    def test_mark_paused_from_idle_is_allowed(self):
        """P2-8: pausing while idle must not raise (the Run press resets it)."""
        sm = RunStateMachine()
        self.assertEqual(sm.mark_paused(), RunState.PAUSED)
        self.assertEqual(sm.mark_resumed(), RunState.RUNNING)

    def test_mark_paused_from_running(self):
        sm = RunStateMachine()
        sm.state = RunState.RUNNING
        self.assertEqual(sm.mark_paused(), RunState.PAUSED)

    def test_mark_stopping_only_from_running_and_paused(self):
        for src in (RunState.RUNNING, RunState.PAUSED):
            sm = RunStateMachine()
            sm.state = src
            self.assertEqual(sm.mark_stopping(), RunState.STOPPING)
        for src in (RunState.IDLE, RunState.ERROR, RunState.DONE,
                    RunState.STOPPING):
            sm = RunStateMachine()
            sm.state = src
            self.assertEqual(sm.mark_stopping(), src)

    def test_mark_error_from_idle_is_direct(self):
        sm = RunStateMachine()
        self.assertEqual(sm.mark_error(), RunState.ERROR)

    def test_mark_done_only_from_running_and_stopping(self):
        for src in (RunState.RUNNING, RunState.STOPPING):
            sm = RunStateMachine()
            sm.state = src
            self.assertEqual(sm.mark_done(), RunState.DONE)
        for src in (RunState.IDLE, RunState.ERROR, RunState.DONE):
            sm = RunStateMachine()
            sm.state = src
            self.assertEqual(sm.mark_done(), src)


# ══════════════════════════════════════════════════════════════════
# RetryPolicy
# ══════════════════════════════════════════════════════════════════
class TestRetryPolicy(unittest.IsolatedAsyncioTestCase):
    def test_should_retry_transient_errors_within_budget(self):
        policy = RetryPolicy(max_retries=2)
        self.assertTrue(policy.should_retry(TimeoutError(), 0))
        self.assertTrue(policy.should_retry(ConnectionError(), 1))
        self.assertFalse(policy.should_retry(TimeoutError(), 2))
        self.assertFalse(policy.should_retry(RuntimeError(), 0))

    def test_should_retry_asyncio_timeout(self):
        policy = RetryPolicy(max_retries=1)
        self.assertTrue(policy.should_retry(asyncio.TimeoutError(), 0))

    def test_should_retry_respects_zero_retries(self):
        policy = RetryPolicy(max_retries=0)
        self.assertFalse(policy.should_retry(TimeoutError(), 0))

    async def test_retry_with_backoff_returns_on_success(self):
        policy = RetryPolicy(max_retries=3)
        self.assertEqual(await policy.retry_with_backoff(
            lambda: asyncio.sleep(0, result="ok")), "ok")

    async def test_retry_with_backoff_retries_then_succeeds(self):
        calls = []

        async def op():
            calls.append(1)
            if len(calls) < 3:
                raise TimeoutError("nope")
            return "ok"

        policy = RetryPolicy(max_retries=3)
        self.assertEqual(await policy.retry_with_backoff(op), "ok")
        self.assertEqual(len(calls), 3)

    async def test_retry_with_backoff_permanent_error_raises(self):
        policy = RetryPolicy(max_retries=3)
        with self.assertRaises(RuntimeError):
            await policy.retry_with_backoff(lambda: (_ for _ in ()).throw(
                RuntimeError("boom")))

    async def test_retry_with_backoff_exhausted_falls_back(self):
        calls = []

        async def op():
            calls.append(1)
            raise TimeoutError("always")

        async def fallback(exc):
            return f"fell back: {exc}"

        policy = RetryPolicy(max_retries=2)
        self.assertIn("fell back",
                      await policy.retry_with_backoff(op, fallback=fallback))
        self.assertEqual(len(calls), 3)  # 2 retries + the final attempt

    async def test_retry_with_backoff_exhausted_raises_without_fallback(self):
        policy = RetryPolicy(max_retries=1, base_delay=0)
        with self.assertRaises(TimeoutError):
            await policy.retry_with_backoff(
                lambda: (_ for _ in ()).throw(TimeoutError()))

    async def test_fallback_reraises(self):
        policy = RetryPolicy(max_retries=0)
        with self.assertRaises(RuntimeError):
            await policy.fallback(RuntimeError("boom"))


# ══════════════════════════════════════════════════════════════════
# RunExecutionMixin branches (through ActionEngine)
# ══════════════════════════════════════════════════════════════════
class TestExecutionBranches(EngineCase):
    async def test_handle_step_result_variants(self):
        engine = self.make([UserRecord(nick="a")])
        block = RecordingBlock(result=ActionResult.SKIP)
        engine._stack = [block]
        await engine.execute()
        # SKIP for the user → reported not completed, nobody marked
        self.assertEqual(self.user_done, [("a", False)])
        self.assertEqual(self.memory.marked, [])

    async def test_step_failure_message_lands_in_debug(self):
        engine = self.make([UserRecord(nick="a")])

        class Boom(BaseAction):
            block_id = "CUSTOM_FIND"
            name = "Find & Click"
            icon = "\U0001f50e"

            async def execute(self, user_nick, cdp, engine=None):
                raise RuntimeError("exploded")

        engine._stack = [Boom(pre_delay_ms=0)]
        await engine.execute()
        self.assertEqual(self.user_done, [("a", False)])
        self.assertTrue(any("exploded" in m for m, _ in self.debug))

    async def test_mark_person_messaged_branches(self):
        engine = self.make([UserRecord(nick="a")])
        self.assertEqual(await engine.mark_person_messaged(""), "missing")
        self.assertEqual(await engine.mark_person_messaged("ghost"),
                         "missing")
        self.assertEqual(await engine.mark_person_messaged("a"), "ok")
        self.assertEqual(await engine.mark_person_messaged("a"), "already")
        self.assertEqual(self.marked, ["a"])

    async def test_stop_while_paused_announces_stopped(self):
        """The 'stopped' announcement must land even when stop arrives
        between users while paused (the early return used to be silent)."""
        engine = self.make([UserRecord(nick="a"), UserRecord(nick="b")])
        gate = asyncio.Event()
        block = GateBlock()
        block.gate = gate
        engine._stack = [block]

        async def controller():
            while not block.calls:
                await asyncio.sleep(0.01)
            engine.pause()
            gate.set()

        task = asyncio.ensure_future(engine.execute())
        await controller()
        await asyncio.sleep(0.3)
        engine.stop()
        await asyncio.wait_for(task, timeout=3)
        self.assertEqual(block.calls, ["a"])
        self.assertEqual(self.stack_complete, [True])
        self.assertTrue(any("stopped" in m.lower() for m, _ in self.debug))

    async def test_all_disabled_stack_reports_nobody_completed(self):
        """B5 regression: an all-disabled stack must NOT mark the queue
        person as messaged and must report them as not completed."""
        engine = self.make([UserRecord(nick="a")])
        block = RecordingBlock()
        block.enabled = False
        engine._stack = [block]
        await engine.execute()
        self.assertEqual(self.user_done, [("a", False)])
        self.assertEqual(self.memory.marked, [])
        self.assertFalse(self.memory._users[0].messaged)


class ConditionalSkipBlock(BaseAction):
    """A CONDITIONAL_SKIP block (skipped in the per-user loop itself)."""

    block_id = "CONDITIONAL_SKIP"
    name = "Conditional Skip"
    icon = "\u23ed"

    def __init__(self, **kw):
        super().__init__(pre_delay_ms=0)

    async def execute(self, user_nick, cdp, engine=None):
        return ActionResult.OK


class CollectResult:
    """Duck-typed Scroll & Parse pipeline result."""

    def __init__(self, collected=(), all_people=(), purged=(), seeking=False,
                 found=None, stopped=False):
        self.collected = list(collected)
        self.all_people = list(all_people)
        self.purged = list(purged)
        self.seeking = seeking
        self.found = found
        self.stopped = stopped
        self.scrolls = 0
        self.reached_end = False
        self.stopped_early = False


class ScrollParseBlock(BaseAction):
    block_id = "SCROLL_PARSE"
    name = "Scroll & Parse"
    icon = "\U0001f4dc"

    def __init__(self, result=None, raise_pipeline=False, **kw):
        super().__init__(pre_delay_ms=0)
        self._result = result
        self.raise_pipeline = raise_pipeline

    async def execute(self, user_nick, cdp, engine=None):
        return ActionResult.OK

    async def run_pipeline(self, cdp, engine, panel_criteria=None,
                           known_messaged=None):
        if self.raise_pipeline:
            raise RuntimeError("collect exploded")
        return self._result


class TestCollectPhaseBranches(EngineCase):
    """_run_collect_phase branch coverage (error_recovery.py)."""

    def stub_tracer(self):
        self.engine._tracer = type(
            "TracerStub", (), {"note": lambda self, *a, **k: None})()

    async def test_pipeline_success_and_purged_suffix(self):
        engine = self.make()
        self.stub_tracer()
        block = ScrollParseBlock(result=CollectResult(
            collected=[UserRecord(nick="a")],
            all_people=[UserRecord(nick="a"), UserRecord(nick="b")],
            purged=[UserRecord(nick="b")]))
        queue = await engine._run_collect_phase(block)
        self.assertEqual([u.nick for u in queue], ["a"])
        self.assertTrue(any("1 removed" in m for m in self.logs))

    async def test_seeking_hit_and_miss_messages(self):
        engine = self.make()
        self.stub_tracer()
        hit = ScrollParseBlock(result=CollectResult(
            seeking=True, found=UserRecord(nick="b")))
        await engine._run_collect_phase(hit)
        self.assertTrue(any("found \u201cb\u201d" in m for m in self.logs))
        miss = ScrollParseBlock(result=CollectResult(seeking=True))
        await engine._run_collect_phase(miss)
        self.assertTrue(
            any("no un-messaged person" in m for m in self.logs))

    async def test_stopped_collection_queues_nobody(self):
        engine = self.make()
        self.stub_tracer()
        block = ScrollParseBlock(result=CollectResult(
            collected=[UserRecord(nick="a")], stopped=True))
        self.assertEqual(await engine._run_collect_phase(block), [])
        self.assertTrue(
            any("not queueing anyone" in m for m, _ in self.debug))

    async def test_pipeline_crash_is_contained(self):
        engine = self.make()
        self.stub_tracer()
        block = ScrollParseBlock(raise_pipeline=True)
        self.assertEqual(await engine._run_collect_phase(block), [])
        self.assertTrue(any("raised" in m for m, _ in self.debug))

    async def test_memory_errors_are_contained(self):
        engine = self.make()
        self.stub_tracer()
        engine._memory.get_all = lambda: (_ for _ in ()).throw(
            RuntimeError("mem down"))
        engine._memory.upsert_user = lambda user: (_ for _ in ()).throw(
            RuntimeError("upsert down"))
        block = ScrollParseBlock(result=CollectResult(
            collected=[UserRecord(nick="a")]))
        queue = await engine._run_collect_phase(block)
        self.assertEqual([u.nick for u in queue], ["a"])


class TestExecuteForUserBranches(EngineCase):
    """_execute_for_user branches not reachable through execute()."""

    def stub_tracer(self):
        self.engine._tracer = type(
            "TracerStub", (), {"note": lambda self, *a, **k: None})()

    async def test_messaged_user_with_skip_guard_short_circuits(self):
        engine = self.make()
        self.stub_tracer()
        engine._stack = [RecordingBlock()]
        out = await engine._execute_for_user(
            UserRecord(nick="a", messaged=True), has_skip=True)
        self.assertEqual(out, "skip")
        self.assertTrue(any("Skipping (already messaged)" in m
                            for m in self.logs))

    async def test_conditional_skip_block_skips_messaged_user(self):
        engine = self.make()
        self.stub_tracer()
        engine._stack = [ConditionalSkipBlock()]
        out = await engine._execute_for_user(
            UserRecord(nick="a", messaged=True), has_skip=False)
        self.assertEqual(out, "skip")
        self.assertTrue(any("Conditional skip" in m for m, _ in self.debug))

    async def test_conditional_skip_block_continues_for_fresh_user(self):
        engine = self.make()
        self.stub_tracer()
        engine._stack = [ConditionalSkipBlock()]
        out = await engine._execute_for_user(
            UserRecord(nick="a"), has_skip=False)
        self.assertEqual(out, "ok")
        self.assertTrue(any("All steps done" in m for m, _ in self.debug))


class TestAsyncActionHook(EngineCase):
    """A coroutine on_action_complete hook must be awaited (not leaked)."""

    async def test_coroutine_hook_is_awaited(self):
        class Hooky(RunHooks):
            def __init__(self):
                self.calls = []

            async def on_action_complete(self, coordinator, block, nick,
                                         status):
                self.calls.append((nick, status))

        hooks = Hooky()
        engine = self.make([UserRecord(nick="a")])
        engine._hooks = hooks
        engine._stack = [RecordingBlock()]
        await engine.execute()
        self.assertEqual(hooks.calls, [("a", "ok")])

    async def test_hooks_without_action_callback_still_complete(self):
        class NoActionHook:
            def pre_run(self, coordinator):
                return None

            def post_run(self, coordinator, outcome):
                return None

        engine = self.make([UserRecord(nick="a")])
        engine._hooks = NoActionHook()
        engine._stack = [RecordingBlock()]
        await engine.execute()
        self.assertEqual(self.user_done, [("a", True)])


# ══════════════════════════════════════════════════════════════════
# RunHooks helpers
# ══════════════════════════════════════════════════════════════════
class TestHookHelpers(unittest.IsolatedAsyncioTestCase):
    def test_normalize_blocks_strips_retired_and_private_keys(self):
        clean = normalize_blocks([{
            "block_id": "PAUSE", "pause_ms": 9,
            "use_panel_filters": True, "skip_if_backlog": True,
            "backlog_threshold": 50, "_x": 1, "enabled": None,
        }])
        self.assertEqual(clean, [{"block_id": "PAUSE", "pause_ms": 9,
                                  "enabled": True}])

    def test_normalize_blocks_skips_non_dicts(self):
        self.assertEqual(normalize_blocks([None, 3, {"block_id": "PAUSE"}]),
                         [{"block_id": "PAUSE", "enabled": True}])

    def test_norm_level_maps_every_spelling(self):
        self.assertEqual(norm_level("ok"), "success")
        self.assertEqual(norm_level("done"), "success")
        self.assertEqual(norm_level("info"), "info")
        self.assertEqual(norm_level("debug"), "info")
        self.assertEqual(norm_level("warn"), "warn")
        self.assertEqual(norm_level("warning"), "warn")
        self.assertEqual(norm_level("error"), "error")
        self.assertEqual(norm_level("fail"), "error")
        self.assertEqual(norm_level("bogus"), "info")
        self.assertEqual(norm_level(None), "info")

    def test_user_scoped_and_standalone_constants(self):
        self.assertIn("CLICK_USER", USER_SCOPED_BLOCKS)
        self.assertIn("TYPE_MESSAGE", USER_SCOPED_BLOCKS)
        self.assertNotIn("PAUSE", USER_SCOPED_BLOCKS)
        self.assertEqual(STANDALONE_NICK, "\u2014")

    def test_run_tracer_writes_jsonl_and_closes(self):
        with tempfile.TemporaryDirectory() as tmp:
            tracer = RunTracer("abc", log_dir=tmp)
            tracer.note({"type": "x", "k": "v"})
            tracer.close()
            with open(tracer.path, encoding="utf-8") as fh:
                lines = fh.readlines()
        self.assertEqual(len(lines), 1)
        record = json.loads(lines[0])
        self.assertEqual(record["run_id"], "abc")
        self.assertEqual(record["type"], "x")
        self.assertEqual(record["k"], "v")
        self.assertIn("ts", record)

    async def test_maybe_await_awaits_and_ignores_plain(self):
        results = []

        async def coro():
            return 42

        results.append(await maybe_await(None))
        results.append(await maybe_await(3))
        results.append(await maybe_await(coro()))
        self.assertEqual(results, [None, None, None])


class TestHooks(unittest.TestCase):
    def test_default_hooks_are_noops(self):
        hooks = RunHooks()
        self.assertIsNone(hooks.pre_run(None))
        self.assertIsNone(hooks.post_run(None, "worked"))
        self.assertIsNone(hooks.on_action_complete(None, None, "a", "ok"))


# Undo the import-time registry shadowing done by this module's fakes.
_restore_action_registry()


if __name__ == "__main__":
    unittest.main(verbosity=2)
