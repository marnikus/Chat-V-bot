"""Area C1 — stop contract at run/cycle/user boundaries.

Parent design: docs/SAFETY_REFACTOR_AREA_C_IMPL_DESIGN_2026-09-10.md §3.2–§3.4.
Task list: docs/SAFETY_REFACTOR_AREA_C_2026-09-10.md C1a.

Test-first: every stop test fails against the baseline and passes after C1.
Parity assertions (progress mapping, repeat termination) pass before and after
and guard the C2 extraction.
"""

import asyncio
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))))

from actions.base_action import (ActionResult, ActionRegistry,  # noqa: E402
                                 BaseAction)
_REGISTRY_SNAPSHOT = dict(ActionRegistry._classes)

from services.run import RunCoordinator  # noqa: E402
from services.run.error_recovery import RetryPolicy  # noqa: E402
from services.run.hooks import RunHooks, RunTracer  # noqa: E402
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

    def __init__(self, result=ActionResult.OK, **kw):
        super().__init__(pre_delay_ms=0)
        self.calls = []
        self._result = result

    async def execute(self, user_nick, cdp, engine=None):
        self.calls.append(user_nick)
        return self._result


class StopAfterFirstBlock(BaseAction):
    """Returns OK for the first block position, then requests stop."""

    block_id = "CUSTOM_FIND"
    name = "Find & Click"
    icon = "🔎"

    def __init__(self, **kw):
        super().__init__(pre_delay_ms=0)
        self.calls = []

    async def execute(self, user_nick, cdp, engine=None):
        self.calls.append(user_nick)
        if engine is not None:
            engine.stop()
        return ActionResult.OK


class GateBlock(BaseAction):
    block_id = "CUSTOM_FIND"
    name = "Find & Click"
    icon = "🔎"
    gate = None

    def __init__(self, **kw):
        super().__init__(pre_delay_ms=0)
        self.calls = []

    async def execute(self, user_nick, cdp, engine=None):
        self.calls.append(user_nick)
        if self.gate is not None:
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

    async def delete_user(self, nick):
        return False


class SlowMemory(FakeMemory):
    """get_queue gated on an event so stop can land mid-preparation."""

    def __init__(self, users=None):
        super().__init__(users)
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def get_queue(self):
        self.entered.set()
        await self.release.wait()
        return await super().get_queue()


class CollectResult:
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


class ScrollBlock(BaseAction):
    block_id = "SCROLL_PARSE"
    name = "Scroll & Parse"
    icon = "📜"

    def __init__(self, result=None, gate=None, **kw):
        super().__init__(pre_delay_ms=0)
        self._result = result or CollectResult()
        self.gate = gate
        self.calls = 0

    async def execute(self, user_nick, cdp, engine=None):
        return ActionResult.OK

    async def run_pipeline(self, cdp, engine, panel_criteria=None,
                           known_messaged=None):
        self.calls += 1
        if self.gate is not None:
            await self.gate.wait()
        return self._result


class TakeBlock:
    block_id = "TAKE_PERSON"
    enabled = True
    mode_phrase = "matching person"

    def __init__(self, nick=None, gate=None):
        self._nick = nick
        self.gate = gate
        self.calls = 0

    def choose(self, rows, eng=None):
        self.calls += 1
        return self._nick


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

    def make(self, users=None, **kw):
        self.memory = kw.pop("memory", None) or FakeMemory(users)
        self.engine = RunCoordinator(cdp=None, memory=self.memory,
                                     criteria=None, **kw)
        self.logs = []
        self.debug = []
        self.user_done = []
        self.marked_live = []
        self.stack_complete = []
        self.engine.log_msg.connect(lambda m: self.logs.append(m))
        self.engine.debug_msg.connect(lambda m, l: self.debug.append((m, l)))
        self.engine.user_complete.connect(
            lambda n, ok: self.user_done.append((n, ok)))
        self.engine.person_marked.connect(lambda n: self.marked_live.append(n))
        self.engine.stack_complete.connect(
            lambda: self.stack_complete.append(True))
        return self.engine


def _debug_text(case):
    return " ".join(m for m, _ in case.debug)


# ── pause/stop interaction (B2) ───────────────────────────────────
class TestStopAfterPause(EngineCase):
    async def test_resume_after_stop_starts_no_further_block(self):
        engine = self.make([UserRecord(nick="a")])

        class PausingFirst(BaseAction):
            block_id = "CUSTOM_FIND"
            name = "Find & Click"
            icon = "🔎"

            def __init__(self):
                super().__init__(pre_delay_ms=0)
                self.calls = []

            async def execute(self, user_nick, cdp, engine=None):
                self.calls.append(user_nick)
                engine.pause()
                return ActionResult.OK

        first = PausingFirst()
        second = RecordingBlock()
        engine._stack = [first, second]

        async def controller():
            while not first.calls:
                await asyncio.sleep(0.01)
            # First paused itself; the engine is now parked before the second
            # block. Stop while paused, then resume (resume must not start it).
            await asyncio.sleep(0.3)
            engine.stop()
            await asyncio.sleep(0.1)
            try:
                engine.resume()
            except ValueError:
                pass

        await asyncio.gather(engine.execute(), controller())
        self.assertEqual(first.calls, ["a"])
        self.assertEqual(second.calls, [],
                         "stop while paused must pre-empt the next block")
        self.assertEqual(self.user_done, [("a", False)])
        self.assertEqual(self.memory.marked, [])
        self.assertIn("stopped", _debug_text(self).lower())

    async def test_stop_while_paused_between_users_runs_nobody_else(self):
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
            await asyncio.sleep(0.3)
            engine.stop()

        await asyncio.wait_for(
            asyncio.gather(engine.execute(), controller()), timeout=5)
        self.assertEqual(block.calls, ["a"])
        self.assertEqual(self.stack_complete, [True])
        self.assertIn("stopped", _debug_text(self).lower())


# ── collect / take / queue preparation (B10) ──────────────────────
class TestStopDuringPreparation(EngineCase):
    async def test_stop_during_collect_runs_no_downstream_action(self):
        engine = self.make([])
        gate = asyncio.Event()
        scroll = ScrollBlock(result=CollectResult(
            collected=[UserRecord(nick="c")],
            all_people=[UserRecord(nick="c")]), gate=gate)
        downstream = RecordingBlock()
        engine._stack = [scroll, downstream]

        async def controller():
            while scroll.calls == 0:
                await asyncio.sleep(0.01)
            engine.stop()
            gate.set()

        hooks = OutcomeHooks()
        engine._hooks = hooks
        await asyncio.wait_for(
            asyncio.gather(engine.execute(), controller()), timeout=5)
        self.assertEqual(downstream.calls, [],
                         "stop during collect must not fall through to standalone")
        self.assertEqual(hooks.outcomes, ["stopped"])
        self.assertEqual(self.memory.marked, [])

    async def test_stop_during_queue_preparation_is_stopped_not_empty(self):
        mem = SlowMemory([UserRecord(nick="a")])
        engine = self.make(memory=mem)
        block = RecordingBlock()
        engine._stack = [block]
        hooks = OutcomeHooks()
        engine._hooks = hooks

        async def controller():
            await mem.entered.wait()
            engine.stop()
            mem.release.set()

        await asyncio.wait_for(
            asyncio.gather(engine.execute(), controller()), timeout=5)
        self.assertEqual(block.calls, [])
        self.assertEqual(hooks.outcomes, ["stopped"])
        self.assertIn("stopped", _debug_text(self).lower())


# ── retry backoff (B9) ────────────────────────────────────────────
class TestStopDuringRetry(EngineCase):
    async def test_stop_during_backoff_makes_no_next_attempt(self):
        attempts = []
        fallback_calls = []

        class Flaky(BaseAction):
            block_id = "CUSTOM_FIND"
            name = "Find & Click"
            icon = "🔎"

            def __init__(self):
                super().__init__(pre_delay_ms=0)

            async def execute(self, user_nick, cdp, engine=None):
                attempts.append(user_nick)
                raise TimeoutError("transient")

        engine = self.make([UserRecord(nick="a")],
                           retry_policy=RetryPolicy(max_retries=3,
                                                    base_delay=2.0))
        engine._stack = [Flaky()]
        orig_fallback = engine._step_failed

        async def counting_fallback(block, nick, exc):
            fallback_calls.append(exc)
            return await orig_fallback(block, nick, exc)

        engine._step_failed = counting_fallback
        hooks = OutcomeHooks()
        engine._hooks = hooks

        async def controller():
            while not attempts:
                await asyncio.sleep(0.01)
            engine.stop()

        t0 = time.monotonic()
        await asyncio.wait_for(
            asyncio.gather(engine.execute(), controller()), timeout=5)
        elapsed = time.monotonic() - t0
        self.assertEqual(len(attempts), 1,
                         "stop during backoff must not attempt again")
        self.assertEqual(fallback_calls, [],
                         "cooperative stop must not invoke the error fallback")
        self.assertEqual(hooks.outcomes, ["stopped"])
        self.assertLess(elapsed, 1.5,
                        "stop must interrupt the 2 s backoff promptly")

    async def test_run_stopped_is_never_retried_even_by_permissive_policy(self):
        class Permissive(RetryPolicy):
            def should_retry(self, exc, attempt):
                return True

        policy = Permissive(max_retries=5, base_delay=0)
        calls = []

        async def op():
            calls.append(1)
            raise RunStopped()

        async def fallback(exc):
            calls.append("fallback")
            return "fallback"

        if not HAS_CANCELLATION:
            self.fail("actions/cancellation.py must exist (Area C1)")
        with self.assertRaises(RunStopped):
            await policy.retry_with_backoff(op, fallback=fallback)
        self.assertEqual(calls, [1],
                         "RunStopped must propagate without retry or fallback")
        # The base policy never retries stop; a permissive override may still
        # claim True, but retry_with_backoff passes RunStopped through before
        # consulting should_retry, so no retry happens either way.
        self.assertFalse(RetryPolicy().should_retry(RunStopped(), 0))


# ── automatic-mark boundary (B11) ─────────────────────────────────
class TestMarkBoundary(EngineCase):
    async def test_stop_after_final_ok_prevents_automatic_mark(self):
        engine = self.make([UserRecord(nick="a")])
        engine._stack = [StopAfterFirstBlock()]
        hooks = OutcomeHooks()
        engine._hooks = hooks
        await engine.execute()
        self.assertEqual(self.memory.marked, [],
                         "stop between final OK and the mark boundary must win")
        self.assertEqual(self.marked_live, [])
        self.assertEqual(self.user_done, [("a", False)])
        self.assertEqual(hooks.outcomes, ["stopped"])

    async def test_explicit_mark_before_stop_is_kept_but_no_auto_mark(self):
        engine = self.make([UserRecord(nick="a")])

        class ExplicitThenStop(BaseAction):
            block_id = "CUSTOM_FIND"
            name = "Find & Click"
            icon = "🔎"

            def __init__(self):
                super().__init__(pre_delay_ms=0)

            async def execute(self, user_nick, cdp, engine=None):
                await engine.mark_person_messaged(user_nick)
                engine.stop()
                return ActionResult.OK

        engine._stack = [ExplicitThenStop()]
        hooks = OutcomeHooks()
        engine._hooks = hooks
        await engine.execute()
        # The explicit write completed before stop: it stays. The coordinator's
        # automatic mark must not fire on top of it.
        self.assertEqual(self.memory.marked, ["a"])
        self.assertEqual(hooks.outcomes, ["stopped"])
        self.assertEqual(self.user_done, [("a", False)])


# ── single-target stop masking (B6) ───────────────────────────────
class TestSingleTargetStop(EngineCase):
    def _single_target_stack(self, engine):
        first = StopAfterFirstBlock()
        first.block_id = "CLICK_USER"
        first.use_person_from_memory = True
        second = RecordingBlock()
        engine._stack = [first, second]
        engine.selected_nick = "tgt"
        return first, second

    async def test_single_target_stop_returns_stopped(self):
        engine = self.make([UserRecord(nick="a")])
        engine._tracer = RunTracer("test-single-stop", log_dir="logs")
        try:
            first, second = self._single_target_stack(engine)
            out = await engine._run_single_target_cycle(False, False)
            self.assertEqual(out, "stopped")
            self.assertEqual(second.calls, [])
        finally:
            engine._tracer.close()
            engine._tracer = None

    async def test_single_target_stop_progress_matches_queued_mapping(self):
        """Legacy counter parity: stop increments `failed` in both paths."""
        engine = self.make([UserRecord(nick="a")])
        engine._tracer = RunTracer("test-single-progress", log_dir="logs")
        try:
            self._single_target_stack(engine)
            out = await engine._run_single_target_cycle(False, False)
            self.assertEqual(out, "stopped")
            self.assertEqual(engine.progress.failed, 1,
                             "single-target stop must map stop→fail like queued")
            self.assertEqual(engine.progress.done, 0)
        finally:
            engine._tracer.close()
            engine._tracer = None

    async def test_single_target_stop_ends_repeat_without_next_cycle(self):
        from actions.repeat_loop import RepeatLoop
        from actions.take_person import TakePerson
        engine = self.make([UserRecord(nick="a")])
        first, second = self._single_target_stack(engine)
        # TakePerson picks "a" so selected_nick is set by the take phase
        # (execute() clears any manually preset selected_nick at start).
        take = TakePerson(pick_mode="order_first")
        engine._stack = [RepeatLoop(repeat_count=3), take, first, second]
        hooks = OutcomeHooks()
        engine._hooks = hooks
        await engine.execute()
        self.assertEqual(hooks.outcomes, ["stopped"])
        self.assertEqual(len(first.calls), 1,
                         "no next repeat cycle after a stopped single-target cycle")
        self.assertEqual(second.calls, [])


# ── restartability (B1/B7) ────────────────────────────────────────
class TestRestartability(EngineCase):
    async def test_stopped_run_reports_stopped_and_restarts(self):
        engine = self.make([UserRecord(nick="a"), UserRecord(nick="b")])
        block = RecordingBlock()
        engine._stack = [block]
        hooks = OutcomeHooks()
        engine._hooks = hooks

        gate = asyncio.Event()
        gated = GateBlock()
        gated.gate = gate
        engine._stack = [gated]

        async def controller():
            while not gated.calls:
                await asyncio.sleep(0.01)
            engine.stop()
            gate.set()

        await asyncio.wait_for(
            asyncio.gather(engine.execute(), controller()), timeout=5)
        self.assertEqual(hooks.outcomes, ["stopped"])
        from services.run.state_machine import RunState
        self.assertEqual(engine._state.state, RunState.DONE,
                         "a stopped run must terminate, not strand in STOPPING")

        # Second run starts cleanly.
        block2 = RecordingBlock()
        engine._stack = [block2]
        hooks.outcomes.clear()
        await engine.execute()
        self.assertEqual(block2.calls, ["a", "b"])
        self.assertEqual(hooks.outcomes, ["worked"])

    async def test_stop_before_first_cycle_is_stopped_and_restartable(self):
        engine = self.make([UserRecord(nick="a")])
        block = RecordingBlock()
        engine._stack = [block]

        class StopInPre(RunHooks):
            def __init__(self, outer):
                self.outer = outer

            def pre_run(self, coordinator):
                coordinator.stop()

            def post_run(self, coordinator, outcome):
                self.outer.outcomes.append(outcome)

        self.outcomes = []
        engine._hooks = StopInPre(self)
        await engine.execute()
        self.assertEqual(block.calls, [])
        self.assertEqual(self.outcomes, ["stopped"])

        from services.run.state_machine import RunState
        self.assertEqual(engine._state.state, RunState.DONE)
        # Restart works (baseline raised ValueError: stopping -> running).
        engine._hooks = RunHooks()
        await engine.execute()
        self.assertEqual(block.calls, ["a"])

    async def test_repeated_stops_are_safe_and_restartable(self):
        engine = self.make([UserRecord(nick="a")])
        engine._stack = [RecordingBlock()]
        engine.stop()
        engine.stop()
        engine.stop()
        hooks = OutcomeHooks()
        engine._hooks = hooks
        # A stale stop while idle is cleared by the next Run (existing contract).
        await engine.execute()
        self.assertEqual(hooks.outcomes, ["worked"])


# ── accounting + latency gates ────────────────────────────────────
class TestProgressAndLatency(EngineCase):
    async def test_queued_stop_maps_to_failed_counter(self):
        engine = self.make([UserRecord(nick="a"), UserRecord(nick="b")])
        engine._stack = [StopAfterFirstBlock(), RecordingBlock()]
        # First user: first block stops, second sees stop → user "stop".
        # The coordinator maps stop→fail for the legacy progress counter.
        await engine.execute()
        self.assertEqual(engine.progress.failed, 1)
        self.assertEqual(engine.progress.done, 0)

    async def test_stop_latency_under_500ms_with_cooperative_cdp(self):
        engine = self.make([UserRecord(nick="a")])
        gate = asyncio.Event()
        block = GateBlock()
        block.gate = gate
        engine._stack = [block]

        async def controller():
            while not block.calls:
                await asyncio.sleep(0.01)
            t0 = time.monotonic()
            engine.stop()
            gate.set()
            return t0

        task = asyncio.ensure_future(engine.execute())
        t0 = await controller()
        await asyncio.wait_for(task, timeout=5)
        elapsed = time.monotonic() - t0
        self.assertLess(elapsed, 0.5,
                        "cooperative stop must land well under 500 ms")


_RESTORE = dict(ActionRegistry._classes)
ActionRegistry._classes.clear()
ActionRegistry._classes.update(_REGISTRY_SNAPSHOT)

if __name__ == "__main__":
    unittest.main(verbosity=2)
