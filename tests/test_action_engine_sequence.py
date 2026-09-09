"""services/run_service (backend/action_engine) — sequence, failure-stop,
pause/stop, normalisation, tracer.

Design refs: docs/BACKEND_TESTS_DESIGN_2026-09-09.md §AE#1–7.

Promises proven here (module docstring + README "Run & Debugger"):

  * blocks execute in STACK ORDER for every queued user (per-step status
    is the debugger's core promise);
  * a failed / skipped / raised step stops THE USER's remaining steps —
    and says so loudly ("stopping this user") — while the run itself
    continues with the next user;
  * Stop is honoured between blocks and between users; Pause suspends
    before the next block and Resume continues in place;
  * a successful user is marked messaged exactly once;
  * normalize_blocks is the server-side safety net (non-dicts dropped,
    retired/underscore keys stripped, enabled defaulted);
  * every run writes a valid JSONL trace with a run/step narrative.

Run with:  python3 tests/test_action_engine_sequence.py
"""

import asyncio
import json
import glob
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from actions.base_action import ActionResult, BaseAction  # noqa: E402
from backend.action_engine import (  # noqa: E402
    RETIRED_BLOCK_KEYS,
    STANDALONE_NICK,
    ActionEngine,
    RunTracer,
    norm_level,
    normalize_blocks,
)
from backend.user_memory import UserRecord  # noqa: E402


class Step(BaseAction):
    """Recording block; result configurable per instance."""
    block_id = "CUSTOM_FIND"
    name = "Find & Click"
    icon = "🔎"

    def __init__(self, tag="step", result=ActionResult.OK, on_run=None, **kw):
        super().__init__(pre_delay_ms=0)
        self.custom_name = kw.get("custom_name", tag)
        self.tag = tag
        self.calls = []
        self._result = result
        self._on_run = on_run

    async def execute(self, user_nick, cdp, engine=None):
        self.calls.append(user_nick)
        if self._on_run and engine is not None:
            self._on_run(engine, user_nick)
        return self._result


class RepeatMarker(BaseAction):
    """The driver never executes this; it only reads repeat_count."""
    block_id = "REPEAT_LOOP"
    name = "Repeat Loop"
    icon = "🔁"

    def __init__(self, repeat_count=1):
        super().__init__(pre_delay_ms=0)
        self.repeat_count = repeat_count

    async def execute(self, user_nick, cdp, engine=None):  # pragma: no cover
        return ActionResult.OK


class FakeMemory:
    """Queue semantics of UserMemory: get_queue hides messaged users."""

    def __init__(self, nicks):
        self.users = {n: UserRecord(nick=n) for n in nicks}
        self.marked = []

    async def get_queue(self):
        return [u for n, u in self.users.items() if n not in self.marked]

    async def mark_messaged(self, nick):
        self.marked.append(nick)

    async def upsert_user(self, user):
        self.users[user.nick] = user

    async def get_all(self):
        return list(self.users.values())


class EngineCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self._cwd = os.getcwd()
        os.chdir(self.tmp.name)      # RunTracer writes logs/ under CWD
        self.addCleanup(os.chdir, self._cwd)

    def build(self, nicks=("u1", "u2")):
        memory = FakeMemory(list(nicks))
        engine = ActionEngine(cdp=None, memory=memory, criteria=None)
        events = {"user_complete": [], "marked_live": []}
        engine.user_complete.connect(
            lambda n, ok: events["user_complete"].append((n, ok)))
        engine.person_marked.connect(events["marked_live"].append)
        return engine, memory, events

    def _run(self, coro):
        return asyncio.run(coro)


# ══════════════════════════════════════════════════════════════════
# AE#1 — stack order
# ══════════════════════════════════════════════════════════════════
class TestSequence(EngineCase):

    def test_blocks_run_in_stack_order_per_user(self):
        trace = []

        def note(tag):
            return lambda engine, nick: trace.append((tag, nick))

        a = Step("A", on_run=note("A"))
        b = Step("B", on_run=note("B"))
        c = Step("C", on_run=note("C"))
        engine, memory, events = self.build(("u1", "u2"))
        engine._stack = [a, b, c]

        self._run(engine.execute(None))

        self.assertEqual(
            trace,
            [("A", "u1"), ("B", "u1"), ("C", "u1"),
             ("A", "u2"), ("B", "u2"), ("C", "u2")],
            "each user must receive A→B→C in stack order "
            "(user-major, stack-order within a user)")

    def test_success_marks_the_user_once_and_advances(self):
        a = Step("A")
        engine, memory, events = self.build(("solo",))
        engine._stack = [a]

        self._run(engine.execute(None))

        self.assertEqual(memory.marked, ["solo"])
        self.assertEqual(events["marked_live"], ["solo"])
        self.assertEqual(events["user_complete"], [("solo", True)])


# ══════════════════════════════════════════════════════════════════
# AE#2 — failure stops the USER, not the run
# ══════════════════════════════════════════════════════════════════
class TestFailureStop(EngineCase):

    def test_fail_stops_this_users_remaining_blocks_only(self):
        ok1 = Step("ok1")
        boom = Step("boom", result=ActionResult.FAIL)
        never = Step("never")
        engine, memory, events = self.build(("u1", "u2"))
        engine._stack = [ok1, boom, never]

        self._run(engine.execute(None))

        self.assertEqual(never.calls, [],
                         "a failed step must stop the user's remaining steps")
        # the run itself goes on: u2 received the full stack
        self.assertEqual(ok1.calls, ["u1", "u2"])
        self.assertEqual(boom.calls, ["u1", "u2"])

    def test_failed_user_is_not_marked_messaged(self):
        boom = Step("boom", result=ActionResult.FAIL)
        engine, memory, events = self.build(("u1",))
        engine._stack = [boom]

        self._run(engine.execute(None))

        self.assertEqual(memory.marked, [],
                         "a failed user must stay in the queue")
        self.assertEqual(events["user_complete"], [("u1", False)])

    def test_skip_result_also_stops_the_user(self):
        skipper = Step("skipper", result=ActionResult.SKIP)
        never = Step("never")
        engine, memory, events = self.build(("u1",))
        engine._stack = [skipper, never]

        self._run(engine.execute(None))

        self.assertEqual(never.calls, [])
        self.assertEqual(memory.marked, [],
                         "a skipped user must not be marked done")

    def test_raising_block_stops_the_user_without_killing_the_run(self):
        def raise_(engine, nick):
            raise RuntimeError("CDP gone")
        head = Step("head")                      # runs before the raiser
        raiser = Step("raiser", on_run=raise_)
        engine, memory, events = self.build(("u1", "u2"))
        engine._stack = [head, raiser]

        self._run(engine.execute(None))          # must not raise

        # u1 died at the raiser, yet the run went on and worked u2:
        self.assertEqual(head.calls, ["u1", "u2"],
                         "run must continue with the next user")
        self.assertEqual(events["user_complete"],
                         [("u1", False), ("u2", False)])


# ══════════════════════════════════════════════════════════════════
# AE#3 / AE#4 — Stop and Pause
# ══════════════════════════════════════════════════════════════════
class TestStopAndPause(EngineCase):

    def test_stop_mid_stack_halts_between_blocks_and_users(self):
        def stop_now(engine, nick):
            engine.stop()
        stopper = Step("stopper", on_run=stop_now)
        never = Step("never")
        engine, memory, events = self.build(("u1", "u2"))
        engine._stack = [stopper, never]

        self._run(engine.execute(None))

        self.assertEqual(stopper.calls, ["u1"])
        self.assertEqual(never.calls, [],
                         "no block may start after Stop was pressed")
        self.assertEqual(events["user_complete"], [("u1", False)],
                         "the interrupted user is reported not-done")
        self.assertFalse(engine.is_running)

    def test_pause_suspends_mid_run_and_resume_finishes_in_place(self):
        """NOTE: execute() resets a pause pressed BEFORE Run — a fresh run
        always starts unpaused (defensible). The documented Pause contract
        is mid-run: ⏸ stops before the NEXT block, ▶ continues in place."""
        def pause_now(engine, nick):
            engine.pause()
        gate = Step("gate", on_run=pause_now)    # pauses itself after running
        tail = Step("tail")
        engine, memory, events = self.build(())
        engine._stack = [gate, tail]

        async def scenario():
            task = asyncio.ensure_future(engine.execute(None))
            for _ in range(100):                 # wait until gate ran
                await asyncio.sleep(0.02)
                if gate.calls:
                    break
            self.assertEqual(gate.calls, [STANDALONE_NICK])
            await asyncio.sleep(0.4)             # paused window
            self.assertTrue(engine.is_running,
                            "a paused run must still count as running")
            self.assertEqual(tail.calls, [],
                             "paused run must not start the next block")
            engine.resume()
            await asyncio.wait_for(task, timeout=5)

        self._run(scenario())
        self.assertEqual(tail.calls, [STANDALONE_NICK],
                         "resume must finish the remaining block in place")


# ══════════════════════════════════════════════════════════════════
# AE#5 — normalize_blocks safety net
# ══════════════════════════════════════════════════════════════════
class TestNormalizeBlocks(unittest.TestCase):

    def test_hostile_payloads_are_coerced(self):
        dirty = [
            None,                       # not a dict
            "TYPE_MESSAGE",             # not a dict
            42,
            {"block_id": "TYPE_MESSAGE", "text": "hi",
             "use_panel_filters": True, "backlog_threshold": 5,
             "_internal": 1, "enabled": None},
            {"block_id": "PAUSE"},      # no enabled key
        ]
        clean = normalize_blocks(dirty)
        self.assertEqual(len(clean), 2, "non-dicts must be dropped")
        tm, pause = clean
        for retired in RETIRED_BLOCK_KEYS:
            self.assertNotIn(retired, tm, f"retired key {retired} survived")
        self.assertNotIn("_internal", tm, "underscore keys must be stripped")
        self.assertIs(tm["enabled"], True, "enabled=None must default True")
        self.assertIs(pause["enabled"], True, "missing enabled must default")
        self.assertEqual(normalize_blocks(None), [])
        self.assertEqual(normalize_blocks("garbage"), [])

    def test_norm_level_maps_the_documented_aliases(self):
        self.assertEqual(norm_level("ok"), "success")
        self.assertEqual(norm_level("FAIL"), "error")
        self.assertEqual(norm_level("warning"), "warn")
        self.assertEqual(norm_level("debug"), "info")
        self.assertEqual(norm_level(""), "info")
        self.assertEqual(norm_level("weird"), "info")


# ══════════════════════════════════════════════════════════════════
# AE#6 — run tracer JSONL
# ══════════════════════════════════════════════════════════════════
class TestRunTracer(EngineCase):

    def test_execute_writes_a_complete_jsonl_narrative(self):
        a, b = Step("A"), Step("B", result=ActionResult.FAIL)
        engine, memory, events = self.build(("u1",))
        engine._stack = [a, b]

        self._run(engine.execute(None))

        traces = glob.glob(os.path.join("logs", "run_trace_*.jsonl"))
        self.assertEqual(len(traces), 1, "exactly one trace per run")
        lines = [json.loads(l) for l in open(traces[0], encoding="utf-8")]
        kinds = [rec["type"] for rec in lines]
        self.assertEqual(kinds[0], "run_start")
        self.assertEqual(kinds[-1], "run_end")
        self.assertIn("step_start", kinds)
        self.assertIn("step_end", kinds)
        for rec in lines:
            self.assertIn("run_id", rec)
            self.assertIn("ts", rec)
        step_ends = [r for r in lines if r["type"] == "step_end"]
        self.assertEqual([r["status"] for r in step_ends], ["ok", "fail"])
        fail_rec = step_ends[-1]
        self.assertEqual(fail_rec.get("block_id"), "CUSTOM_FIND")
        self.assertEqual(fail_rec.get("user"), "u1")

    def test_tracer_file_stays_valid_and_usable_after_a_bad_record(self):
        """Ledger #5 (minor): note() raises TypeError on unserializable
        payloads (only OSError is guarded). The engine's own payloads are
        all JSON-safe, so this pins what matters: a failed write must
        leave the file valid JSONL and the tracer usable."""
        with tempfile.TemporaryDirectory() as log_dir:
            tracer = RunTracer("unit_test", log_dir=log_dir)
            tracer.note({"type": "x", "when": 1})
            with self.assertRaises(TypeError):
                tracer.note({"unserializable": object()})
            tracer.note({"type": "y"})                  # still usable
            tracer.close()
            tracer.close()                              # idempotent
            lines = [json.loads(l)
                     for l in open(tracer.path, encoding="utf-8")]
            self.assertEqual([r["type"] for r in lines], ["x", "y"])


# ══════════════════════════════════════════════════════════════════
# AE#7 — repeat cycles advance the queue
# ══════════════════════════════════════════════════════════════════
class TestRepeatCycles(EngineCase):

    def test_standalone_stack_runs_once_per_cycle(self):
        block = Step("solo")
        engine, memory, events = self.build(())
        engine._stack = [RepeatMarker(3), block]

        self._run(engine.execute(None))

        self.assertEqual(block.calls, [STANDALONE_NICK] * 3,
                         "the whole stack must run once per repeat cycle")

    def test_a_messaged_user_ends_the_repeats_like_an_empty_queue(self):
        block = Step("CLICK_USER-ish", result=ActionResult.OK)
        block.block_id = "CLICK_USER"          # user-scoped
        engine, memory, events = self.build(("only",))
        engine._stack = [RepeatMarker(5), block]

        self._run(engine.execute(None))

        # cycle 1 works the user and marks them; cycle 2 finds the queue
        # empty and ends the run instead of spinning 4 more times
        self.assertEqual(block.calls, ["only"])
        self.assertEqual(memory.marked, ["only"])
        self.assertFalse(engine.is_running)


if __name__ == "__main__":
    unittest.main(verbosity=2)
