"""Area C — coverage for defensive/edge branches (no behaviour change).

Pins the small edge contracts the main safety suites do not hit directly:
progress accounting for unknown statuses, label-guard failures, repeat-count
coercion, order-column fallbacks, single-target mark/skip/fail paths, take
failures, and tracer-failure containment. All pass before and after C2.
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

from actions.cancellation import RunStopped  # noqa: E402
from services.run import RunCoordinator, RunProgress  # noqa: E402
from services.run.hooks import RunTracer  # noqa: E402
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
        return self.engine


class TestProgressEdges(unittest.TestCase):
    def test_unknown_status_is_ignored_but_emitted(self):
        prog = RunProgress()
        prog.extend_total(1)
        prog.note_status("stop")
        prog.note_status("bogus")
        self.assertEqual((prog.done, prog.skipped, prog.failed), (0, 0, 0))
        self.assertEqual(prog.total, 1)


class TestLabelGuardEdges(EngineCase):
    async def test_reason_raise_still_announces_without_reason(self):
        engine = self.make()
        engine._tracer = RunTracer("t", log_dir="logs")
        try:
            debugs = []
            engine.debug_msg.connect(lambda m, l: debugs.append(m))
            engine.label_filter = lambda n: n != "rude"
            def bad_reason(nick):
                raise RuntimeError("reason down")
            engine.label_reason = bad_reason
            kept = engine.filter_by_labels(
                [UserRecord(nick="nice"), UserRecord(nick="rude")],
                announce=True)
            self.assertEqual([u.nick for u in kept], ["nice"])
            self.assertTrue(any("rude" in m for m in debugs))
        finally:
            engine._tracer.close()


class TestRepeatCoercion(EngineCase):
    async def test_bad_repeat_count_falls_back_to_one(self):
        engine = self.make()

        class BadRepeat:
            block_id = "REPEAT_LOOP"
            enabled = True
            repeat_count = "not-a-number"

        engine._stack = [BadRepeat()]
        self.assertEqual(engine._repeat_cycles(), 1)

        class NoneRepeat:
            block_id = "REPEAT_LOOP"
            enabled = True
            repeat_count = None

        engine._stack = [NoneRepeat()]
        self.assertEqual(engine._repeat_cycles(), 1)


class TestOrderColumnEdges(EngineCase):
    async def test_empty_ranked_returns_queue(self):
        engine = self.make([])

        class RespectClick(BaseAction):
            block_id = "CLICK_USER"
            name = "Click User"
            icon = "👤"

            def __init__(self):
                super().__init__(pre_delay_ms=0)
                self.respect_order = True

            async def execute(self, nick, cdp, eng=None):
                return ActionResult.OK

        engine._stack = [RespectClick()]
        engine._tracer = RunTracer("t", log_dir="logs")
        try:
            queue = [UserRecord(nick="a")]
            out = await engine._order_queue_by_column(queue)
            # No rows in memory -> ranked empty -> original queue.
            self.assertEqual(out, queue)
        finally:
            engine._tracer.close()

    async def test_ranked_with_no_tracer_still_returns_ranked(self):
        mem = FakeMemory([UserRecord(nick="b", first_seen="2026-09-01"),
                          UserRecord(nick="a", first_seen="2026-09-02")])
        engine = self.make()
        engine._memory = mem

        class RespectClick(BaseAction):
            block_id = "CLICK_USER"
            name = "Click User"
            icon = "👤"

            def __init__(self):
                super().__init__(pre_delay_ms=0)
                self.respect_order = True

            async def execute(self, nick, cdp, eng=None):
                return ActionResult.OK

        engine._stack = [RespectClick()]
        engine._tracer = None
        logs = []
        engine.log_msg.connect(logs.append)
        out = await engine._order_queue_by_column(
            [UserRecord(nick="a"), UserRecord(nick="b")])
        self.assertEqual([u.nick for u in out], ["a", "b"])
        self.assertTrue(any("Order" in m for m in logs))


class TestSingleTargetEdges(EngineCase):
    def _stack(self, engine, block):
        block.block_id = "CLICK_USER"
        block.use_person_from_memory = True
        engine._stack = [block]
        engine.selected_nick = "tgt"

    async def test_ok_plus_stop_returns_stopped_without_mark(self):
        engine = self.make([UserRecord(nick="tgt")])
        engine._tracer = RunTracer("t", log_dir="logs")
        try:
            completions = []
            engine.user_complete.connect(
                lambda n, ok: completions.append((n, ok)))

            class StopOk(BaseAction):
                block_id = "CUSTOM_FIND"
                name = "x"
                icon = "x"

                def __init__(self):
                    super().__init__(pre_delay_ms=0)

                async def execute(self, nick, cdp, eng=None):
                    eng.stop()
                    return ActionResult.OK

            blk = StopOk()
            self._stack(engine, blk)
            out = await engine._run_single_target_cycle(False, False)
            self.assertEqual(out, "stopped")
            self.assertEqual(self.memory.marked, [])
            self.assertEqual(completions, [("tgt", False)])
        finally:
            engine._tracer.close()

    async def test_skip_and_fail_stay_worked_without_mark(self):
        for result in (ActionResult.SKIP, ActionResult.FAIL):
            engine = self.make([UserRecord(nick="tgt")])
            engine._tracer = RunTracer("t", log_dir="logs")
            try:
                blk = RecordingBlock(result=result)
                self._stack(engine, blk)
                out = await engine._run_single_target_cycle(False, False)
                self.assertEqual(out, "worked")
                self.assertEqual(self.memory.marked, [])
            finally:
                engine._tracer.close()
                engine._tracer = None

    async def test_cancelled_propagates(self):
        engine = self.make([UserRecord(nick="tgt")])
        engine._tracer = RunTracer("t", log_dir="logs")
        try:
            blk = RecordingBlock()
            self._stack(engine, blk)

            async def boom(user, has_skip):
                raise asyncio.CancelledError()

            engine._execute_for_user = boom
            with self.assertRaises(asyncio.CancelledError):
                await engine._run_single_target_cycle(False, False)
        finally:
            engine._tracer.close()

    async def test_run_stopped_defence_returns_stopped(self):
        engine = self.make([UserRecord(nick="tgt")])
        engine._tracer = RunTracer("t", log_dir="logs")
        try:
            blk = RecordingBlock()
            self._stack(engine, blk)

            async def leak(user, has_skip):
                raise RunStopped()

            engine._execute_for_user = leak
            out = await engine._run_single_target_cycle(False, False)
            self.assertEqual(out, "stopped")
        finally:
            engine._tracer.close()


class TestTakeEdges(EngineCase):
    async def test_choose_raise_is_contained(self):
        engine = self.make([UserRecord(nick="a")])
        engine._tracer = RunTracer("t", log_dir="logs")
        try:
            class BadTake:
                block_id = "TAKE_PERSON"
                enabled = True
                mode_phrase = "x"

                def choose(self, rows, eng=None):
                    raise RuntimeError("choose down")

            engine._stack = [BadTake()]
            self.assertFalse(await engine._run_take_phase())
        finally:
            engine._tracer.close()

    async def test_choose_stop_propagates(self):
        engine = self.make([UserRecord(nick="a")])
        engine._tracer = RunTracer("t", log_dir="logs")
        try:
            class StopTake:
                block_id = "TAKE_PERSON"
                enabled = True

                def choose(self, rows, eng=None):
                    raise RunStopped()

            engine._stack = [StopTake()]
            with self.assertRaises(RunStopped):
                await engine._run_take_phase()
        finally:
            engine._tracer.close()

    async def test_get_all_cancel_propagates(self):
        engine = self.make()

        class CancelMem(FakeMemory):
            async def get_all(self):
                raise asyncio.CancelledError()

        engine._memory = CancelMem()
        with self.assertRaises(asyncio.CancelledError):
            await engine._run_take_phase()


class TestRunListEdges(EngineCase):
    async def test_pre_stopped_user_list_runs_nothing(self):
        engine = self.make([UserRecord(nick="a")])
        engine._tracer = RunTracer("t", log_dir="logs")
        try:
            blk = RecordingBlock()
            engine._stack = [blk]
            engine._stop_requested = True
            out = await engine._run_user_list([UserRecord(nick="a")], False,
                                              standalone=False)
            self.assertEqual(out, "stopped")
            self.assertEqual(blk.calls, [])
        finally:
            engine._tracer.close()

    async def test_execute_leak_returns_stopped(self):
        engine = self.make([UserRecord(nick="a")])
        engine._tracer = RunTracer("t", log_dir="logs")
        try:
            engine._stack = [RecordingBlock()]

            async def leak(user, has_skip):
                raise RunStopped()

            engine._execute_for_user = leak
            out = await engine._run_user_list([UserRecord(nick="a")], False,
                                              standalone=False)
            self.assertEqual(out, "stopped")
        finally:
            engine._tracer.close()

    async def test_standalone_stop_has_no_user_signal(self):
        engine = self.make([])
        engine._tracer = RunTracer("t", log_dir="logs")
        try:
            completions = []
            engine.user_complete.connect(
                lambda n, ok: completions.append((n, ok)))

            class StopOk(BaseAction):
                block_id = "CUSTOM_FIND"
                name = "x"
                icon = "x"

                def __init__(self):
                    super().__init__(pre_delay_ms=0)

                async def execute(self, nick, cdp, eng=None):
                    eng.stop()
                    return ActionResult.OK

            engine._stack = [StopOk()]
            out = await engine._run_standalone_user(False)
            self.assertEqual(out, "stopped")
            self.assertEqual(completions, [])
        finally:
            engine._tracer.close()


class TestGateAndTracerEdges(EngineCase):
    async def test_pre_cycle_post_barrier_stop(self):
        engine = self.make([UserRecord(nick="a")])
        engine._stack = [RecordingBlock()]
        engine._tracer = RunTracer("t", log_dir="logs")
        try:
            engine._paused = True
            engine._stop_requested = False

            async def stop_soon():
                await asyncio.sleep(0.05)
                engine._stop_requested = True

            task = asyncio.ensure_future(engine._pre_cycle_gate(1, 1))
            await asyncio.gather(task, stop_soon())
            self.assertEqual(task.result(), "stopped")
        finally:
            engine._tracer.close()

    async def test_failing_tracer_is_contained(self):
        engine = self.make([UserRecord(nick="a")])
        engine._stack = [RecordingBlock()]

        class BadTracer:
            def note(self, record):
                raise OSError("disk full")

            def close(self):
                pass

        engine._tracer = BadTracer()
        # None of these may raise because the tracer failed.
        self.assertEqual(engine._note_stopped(), "stopped")
        out = await engine._finish_single_user(UserRecord(nick="a"), "stop",
                                               standalone=False)
        self.assertEqual(out, "stopped")
        await engine._finalize_run("worked", None)
        self.assertFalse(engine.is_running)


class TestExecuteEdges(EngineCase):
    async def test_already_running_warns_and_returns(self):
        engine = self.make([UserRecord(nick="a")])
        logs = []
        engine.log_msg.connect(logs.append)
        engine._running = True
        await engine.execute()
        self.assertTrue(any("Already running" in m for m in logs))

    async def test_cancel_with_tracer_none_still_raises(self):
        engine = self.make([UserRecord(nick="a")])

        class DropTracerCancel(BaseAction):
            block_id = "CUSTOM_FIND"
            name = "x"
            icon = "x"

            def __init__(self):
                super().__init__(pre_delay_ms=0)

            async def execute(self, nick, cdp, eng=None):
                eng._tracer = None
                raise asyncio.CancelledError()

        engine._stack = [DropTracerCancel()]
        with self.assertRaises(asyncio.CancelledError):
            await engine.execute()
        self.assertFalse(engine.is_running)

    async def test_cancel_with_failing_tracer_note_still_raises(self):
        engine = self.make([UserRecord(nick="a")])

        class BadNote:
            def note(self, record):
                raise OSError("disk full")

            def close(self):
                pass

        class DropTracerCancel(BaseAction):
            block_id = "CUSTOM_FIND"
            name = "x"
            icon = "x"

            def __init__(self):
                super().__init__(pre_delay_ms=0)

            async def execute(self, nick, cdp, eng=None):
                eng._tracer = BadNote()
                raise asyncio.CancelledError()

        engine._stack = [DropTracerCancel()]
        with self.assertRaises(asyncio.CancelledError):
            await engine.execute()
        self.assertFalse(engine.is_running)

    async def test_two_cycle_repeat_continues_then_ends_empty(self):
        engine = self.make([UserRecord(nick="a")])
        engine._tracer = RunTracer("t", log_dir="logs")
        try:
            logs = []
            engine.log_msg.connect(logs.append)
            blk = RecordingBlock()
            blk.block_id = "CLICK_USER"
            engine._stack = [blk]

            class TwoLoops:
                block_id = "REPEAT_LOOP"
                enabled = True
                repeat_count = 2

            engine._stack.append(TwoLoops())
            done, outcome = await engine._run_all_cycles(
                engine._repeat_cycles())
            self.assertTrue(done)
            self.assertEqual(outcome, "empty")
            # Cycle 1 worked the user, cycle 2 found the queue empty.
            self.assertEqual(blk.calls, ["a"])
            self.assertTrue(any("No users found" in m for m in logs))
        finally:
            engine._tracer.close()

    async def test_guarded_run_stopped_defence(self):
        engine = self.make([UserRecord(nick="a")])
        engine._tracer = RunTracer("t", log_dir="logs")
        try:
            async def leak():
                raise RunStopped()

            engine._execute_cycle = leak
            self.assertEqual(await engine._execute_cycle_guarded(),
                             "stopped")
        finally:
            engine._tracer.close()

    async def test_cycle_single_target_run_stopped_defence(self):
        engine = self.make([UserRecord(nick="tgt")])
        engine._tracer = RunTracer("t", log_dir="logs")
        try:
            blk = RecordingBlock()
            blk.block_id = "CLICK_USER"
            blk.use_person_from_memory = True
            engine._stack = [blk]
            engine.selected_nick = "tgt"

            async def leak(has_skip, take_matched):
                raise RunStopped()

            engine._run_single_target_cycle = leak
            self.assertEqual(await engine._execute_cycle(), "stopped")
        finally:
            engine._tracer.close()

    async def test_note_stopped_with_tracer_none(self):
        engine = self.make()
        engine._tracer = None
        self.assertEqual(engine._note_stopped(), "stopped")


class TestFinalizeEdges(EngineCase):
    def _hook_engine(self, hook_exc):
        engine = self.make([UserRecord(nick="a")])

        class BadHook:
            async def post_run(self, eng, outcome):
                raise hook_exc

        engine._hooks = BadHook()
        return engine

    async def test_post_hook_raise_with_tracer_none(self):
        engine = self._hook_engine(RuntimeError("hook down"))
        engine._tracer = None
        await engine._finalize_run("worked", None)
        self.assertFalse(engine.is_running)

    async def test_post_hook_raise_with_failing_tracer(self):
        engine = self._hook_engine(RuntimeError("hook down"))

        class BadNote:
            def note(self, record):
                raise OSError("disk full")

            def close(self):
                pass

        engine._tracer = BadNote()
        await engine._finalize_run("worked", None)
        self.assertFalse(engine.is_running)

    async def test_cancel_with_state_reset_failure(self):
        engine = self.make([UserRecord(nick="a")])
        engine._tracer = None
        engine._running = True

        def bad_reset():
            raise RuntimeError("state down")

        engine._state.reset = bad_reset
        with self.assertRaises(asyncio.CancelledError):
            await engine._finalize_run("worked", asyncio.CancelledError())
        self.assertFalse(engine.is_running)


class TestQueueEdges(EngineCase):
    async def test_label_filter_raise_allows(self):
        engine = self.make()

        def bad_filter(nick):
            raise RuntimeError("filter down")

        engine.label_filter = bad_filter
        self.assertTrue(engine.label_allows("a"))

    async def test_filter_announce_without_reason(self):
        engine = self.make()
        engine._tracer = RunTracer("t", log_dir="logs")
        try:
            debugs = []
            engine.debug_msg.connect(lambda m, l: debugs.append(m))
            engine.label_filter = lambda n: n != "rude"
            engine.label_reason = None
            kept = engine.filter_by_labels(
                [UserRecord(nick="nice"), UserRecord(nick="rude")],
                announce=True)
            self.assertEqual([u.nick for u in kept], ["nice"])
            self.assertTrue(any("rude" in m for m in debugs))
        finally:
            engine._tracer.close()

    async def test_queue_order_with_scroll_parse(self):
        engine = self.make()

        class ScrollParse:
            block_id = "SCROLL_PARSE"
            enabled = True

        engine._stack = [ScrollParse()]
        order = engine.queue_order([UserRecord(nick="b"),
                                    UserRecord(nick="a")])
        self.assertEqual(sorted(order), ["a", "b"])

    async def test_order_ranked_with_tracer(self):
        mem = FakeMemory([UserRecord(nick="b", first_seen="2026-09-01"),
                          UserRecord(nick="a", first_seen="2026-09-02")])
        engine = self.make()
        engine._memory = mem

        class RespectClick(BaseAction):
            block_id = "CLICK_USER"
            name = "Click User"
            icon = "👤"

            def __init__(self):
                super().__init__(pre_delay_ms=0)
                self.respect_order = True

            async def execute(self, nick, cdp, eng=None):
                return ActionResult.OK

        engine._stack = [RespectClick()]
        engine._tracer = RunTracer("t", log_dir="logs")
        try:
            out = await engine._order_queue_by_column(
                [UserRecord(nick="a"), UserRecord(nick="b")])
            self.assertEqual([u.nick for u in out], ["a", "b"])
        finally:
            engine._tracer.close()

    async def test_single_target_no_take_match(self):
        engine = self.make()
        engine._tracer = RunTracer("t", log_dir="logs")
        try:
            class Take:
                block_id = "TAKE_PERSON"
                enabled = True

            engine._stack = [Take()]
            out = await engine._run_single_target_cycle(False, False)
            self.assertEqual(out, "empty")
        finally:
            engine._tracer.close()

    async def test_single_target_no_memory_nick(self):
        engine = self.make()
        engine._tracer = RunTracer("t", log_dir="logs")
        try:
            engine._stack = [RecordingBlock()]
            engine.selected_nick = ""
            out = await engine._run_single_target_cycle(False, False)
            self.assertEqual(out, "empty")
        finally:
            engine._tracer.close()

    async def test_take_get_all_generic_raise_returns_false(self):
        engine = self.make()

        class BadMem(FakeMemory):
            async def get_all(self):
                raise RuntimeError("list down")

        engine._memory = BadMem()
        engine._tracer = RunTracer("t", log_dir="logs")
        try:
            engine._stack = [RecordingBlock()]
            self.assertFalse(await engine._run_take_phase())
        finally:
            engine._tracer.close()


class TestRetryEdges(EngineCase):
    async def test_retry_pre_stopped_never_calls_op(self):
        from services.run.error_recovery import RetryPolicy
        policy = RetryPolicy()
        calls = []

        async def op():
            calls.append(1)

        with self.assertRaises(RunStopped):
            await policy.retry_with_backoff(op, is_stopping=lambda: True)
        self.assertEqual(calls, [])

    async def test_retry_raising_predicate_is_contained(self):
        from services.run.error_recovery import RetryPolicy
        policy = RetryPolicy()

        def bad():
            raise RuntimeError("predicate down")

        async def op():
            return "ok"

        self.assertEqual(
            await policy.retry_with_backoff(op, is_stopping=bad), "ok")

    async def test_sleep_stop_aware_edges(self):
        from services.run.error_recovery import _sleep_stop_aware
        await _sleep_stop_aware("bad", None)
        await _sleep_stop_aware(None, None)
        await _sleep_stop_aware(0.06, lambda: False)

        def bad():
            raise RuntimeError("predicate down")

        await _sleep_stop_aware(0.06, bad)

    async def test_collect_run_stopped_clears_ctx(self):
        engine = self.make()
        engine._tracer = RunTracer("t", log_dir="logs")
        try:
            class Scroll:
                block_id = "SCROLL_PARSE"
                display_name = "Scroll & Parse"

                async def run_pipeline(self, *args, **kwargs):
                    raise AssertionError("must not run when pre-stopped")

            engine._stop_requested = True
            with self.assertRaises(RunStopped):
                await engine._run_collect_phase(Scroll())
            self.assertEqual(engine._ctx, {})
        finally:
            engine._tracer.close()

    async def test_collect_cancelled_clears_ctx(self):
        engine = self.make()
        engine._tracer = RunTracer("t", log_dir="logs")
        try:
            class Scroll:
                block_id = "SCROLL_PARSE"
                display_name = "Scroll & Parse"

                async def run_pipeline(self, *args, **kwargs):
                    raise asyncio.CancelledError()

            with self.assertRaises(asyncio.CancelledError):
                await engine._run_collect_phase(Scroll())
            self.assertEqual(engine._ctx, {})
        finally:
            engine._tracer.close()

    async def test_collect_failed_reraises_stop(self):
        engine = self.make()
        blk = RecordingBlock()
        with self.assertRaises(RunStopped):
            await engine._collect_failed(blk, RunStopped())
        with self.assertRaises(asyncio.CancelledError):
            await engine._collect_failed(blk, asyncio.CancelledError())

    async def test_step_failed_reraises_stop(self):
        engine = self.make()
        blk = RecordingBlock()
        with self.assertRaises(RunStopped):
            await engine._step_failed(blk, "a", RunStopped())

    async def test_action_hook_stop_propagates(self):
        engine = self.make([UserRecord(nick="a")])
        engine._tracer = RunTracer("t", log_dir="logs")
        try:
            engine._stack = [RecordingBlock()]

            async def bad_hook(block, nick, status):
                raise RunStopped()

            engine._call_action_hook = bad_hook
            # Passes through _execute_for_user; _run_user_list maps it.
            with self.assertRaises(RunStopped):
                await engine._execute_for_user(UserRecord(nick="a"), False)
        finally:
            engine._tracer.close()


ActionRegistry._classes.clear()
ActionRegistry._classes.update(_REGISTRY_SNAPSHOT)

if __name__ == "__main__":
    unittest.main(verbosity=2)
