"""Repeat Loop block: the whole stack runs N cycles per Run press.

Without a Repeat Loop marker (or when it is disabled / count ≤ 1) the engine
behaves exactly as before — one cycle. With an enabled marker the collect
phase + per-user messaging repeat, so a single Run keeps harvesting instead
of stopping after the first pass.

Run with:  python3 tests/test_repeat_loop.py
"""

import asyncio
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from actions.base_action import ActionResult, BaseAction  # noqa: E402
from backend.action_engine import (  # noqa: E402
    STANDALONE_NICK,
    USER_SCOPED_BLOCKS,
    ActionEngine,
    get_action_class,
)
from backend.user_memory import UserMemory, UserRecord  # noqa: E402
from actions.repeat_loop import RepeatLoop  # noqa: E402

UI_DIR = os.path.join(os.path.dirname(__file__), "..", "ui")


def run(coro):
    return asyncio.run(coro)


def run_sync(coro):
    """Run a coroutine with the trace-file cwd moved out of the repo."""
    with tempfile.TemporaryDirectory() as tmp:
        cwd = os.getcwd()
        os.chdir(tmp)
        try:
            return asyncio.run(coro)
        finally:
            os.chdir(cwd)


class NeedsUserBlock(BaseAction):
    """Stands in for CLICK_USER: runs per user, records calls."""
    block_id = "CLICK_USER"
    name = "Click User"
    icon = "👤"

    def __init__(self, **kw):
        super().__init__(pre_delay_ms=0)
        self.calls = []

    async def execute(self, user_nick, cdp, engine=None):
        self.calls.append(user_nick)
        return ActionResult.OK


class StopAfterFirstCallBlock(BaseAction):
    """Runs once then asks the engine to stop (Stop button behaviour)."""
    block_id = "CUSTOM_FIND"
    name = "Find & Click"
    icon = "🔎"

    def __init__(self, **kw):
        super().__init__(pre_delay_ms=0)
        self.calls = []

    async def execute(self, user_nick, cdp, engine=None):
        self.calls.append(user_nick)
        engine.stop()
        return ActionResult.OK


class RecordingStandaloneBlock(BaseAction):
    block_id = "CUSTOM_FIND"
    name = "Find & Click"
    icon = "🔎"

    def __init__(self, **kw):
        super().__init__(pre_delay_ms=0)
        self.calls = []

    async def execute(self, user_nick, cdp, engine=None):
        self.calls.append(user_nick)
        return ActionResult.OK


class FakeMemory:
    def __init__(self, queue=None):
        self._queue = list(queue or [])
        self.marked = []

    async def get_queue(self):
        return list(self._queue)

    async def mark_messaged(self, nick):
        self.marked.append(nick)

    async def upsert_user(self, user):
        pass


class BatchMemory:
    """Models Scroll & Parse delivering a fresh small batch every cycle:
    each get_queue() call hands out the next batch of un-messaged people."""

    def __init__(self, batches):
        self._batches = [list(b) for b in batches]
        self.marked = []

    async def get_queue(self):
        return list(self._batches.pop(0)) if self._batches else []

    async def mark_messaged(self, nick):
        self.marked.append(nick)

    async def upsert_user(self, user):
        pass


class MemoryHarness:
    def __init__(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.memory = UserMemory(os.path.join(self._tmp.name, "t.db"))

    async def __aenter__(self):
        await self.memory.init()
        return self.memory

    async def __aexit__(self, *exc):
        await self.memory.close()
        self._tmp.cleanup()


def build_engine(memory):
    engine = ActionEngine(cdp=None, memory=memory, criteria=None)
    logs = []
    engine.log_msg.connect(lambda m: logs.append(("log", m)))
    engine.debug_msg.connect(lambda m, l: logs.append(("debug", m, l)))
    return engine, logs


def cycle_logs(logs):
    return [e[1] for e in logs if e[0] == "log" and len(e) >= 2
            and "Cycle" in e[1]]


class TestRepeatLoopQueueMode(unittest.TestCase):
    def test_two_cycles_drain_two_batches_in_one_run(self):
        async def go():
            async with MemoryHarness() as mem:
                for nick in ("alice", "bob", "carla", "dave"):
                    await mem.upsert_user(
                        UserRecord(nick=nick, gender="female", guest=True))
                block = NeedsUserBlock()
                engine, logs = build_engine(mem)
                engine._stack = [block, RepeatLoop(repeat_count=2)]

                await engine.execute(None)

                self.assertEqual(sorted(block.calls),
                                 ["alice", "bob", "carla", "dave"],
                                 "both cycles must message the full queue")
                banners = cycle_logs(logs)
                self.assertTrue(any(b.startswith("🔁 Cycle 1/2") for b in banners))
                self.assertTrue(any(b.startswith("🔁 Cycle 2/2") for b in banners))
                self.assertTrue(any(
                    e[1].startswith("🔁 Repeat Loop: the stack will run 2 cycles")
                    for e in logs if e[0] == "log"))
        run(go())

    def test_without_marker_runs_once(self):
        async def go():
            async with MemoryHarness() as mem:
                for nick in ("alice", "bob"):
                    await mem.upsert_user(
                        UserRecord(nick=nick, gender="female", guest=True))
                block = NeedsUserBlock()
                engine, _ = build_engine(mem)
                engine._stack = [block]
                await engine.execute(None)
                self.assertEqual(sorted(block.calls), ["alice", "bob"])
        run(go())

    def test_disabled_marker_means_one_cycle(self):
        async def go():
            async with MemoryHarness() as mem:
                await mem.upsert_user(
                    UserRecord(nick="alice", gender="female", guest=True))
                block = NeedsUserBlock()
                engine, logs = build_engine(mem)
                engine._stack = [block, RepeatLoop(repeat_count=9,
                                                   enabled=False)]
                await engine.execute(None)
                self.assertEqual(block.calls, ["alice"])
                self.assertEqual(cycle_logs(logs), [],
                                 "disabled marker must not loop")
        run(go())

    def test_repeat_count_one_means_one_cycle(self):
        async def go():
            async with MemoryHarness() as mem:
                await mem.upsert_user(
                    UserRecord(nick="alice", gender="female", guest=True))
                block = NeedsUserBlock()
                engine, logs = build_engine(mem)
                engine._stack = [block, RepeatLoop(repeat_count=1)]
                await engine.execute(None)
                self.assertEqual(block.calls, ["alice"])
                self.assertEqual(cycle_logs(logs), [])
        run(go())

    def test_empty_queue_ends_the_loop_early(self):
        async def go():
            async with MemoryHarness() as mem:  # empty table
                block = NeedsUserBlock()
                engine, logs = build_engine(mem)
                engine._stack = [block, RepeatLoop(repeat_count=5)]
                await engine.execute(None)
                self.assertEqual(block.calls, [])
                text = " ".join(str(e[1]) for e in logs)
                self.assertEqual(text.count("No users in queue"), 1,
                                 "only one empty-queue warning, not five")
                self.assertIn("Repeat Loop ends the run", text)
        run(go())


class TestRepeatLoopBatches(unittest.TestCase):
    def test_each_cycle_processes_its_own_fresh_batch(self):
        """Scroll & Parse collects a small batch per cycle; each cycle must
        work the people found in that cycle, not re-run the whole memory."""
        block = NeedsUserBlock()
        memory = BatchMemory([[UserRecord(nick="alice"),
                               UserRecord(nick="bob")],
                              [UserRecord(nick="carla"),
                               UserRecord(nick="dave")]])
        engine, logs = build_engine(memory)
        engine._stack = [block, RepeatLoop(repeat_count=2)]
        run_sync(engine.execute(None))
        self.assertEqual(block.calls, ["alice", "bob", "carla", "dave"],
                         "cycle 1 works batch 1, cycle 2 works batch 2")
        self.assertEqual(sorted(memory.marked),
                         ["alice", "bob", "carla", "dave"])
        text = " ".join(str(e[1]) for e in logs)
        self.assertNotIn("No users in queue", text,
                         "both batches were found — no empty-queue stop")


class TestRepeatLoopStandalone(unittest.TestCase):
    def test_standalone_stack_repeats_n_times(self):
        block = RecordingStandaloneBlock()
        engine, logs = build_engine(FakeMemory(queue=[]))
        engine._stack = [block, RepeatLoop(repeat_count=3)]
        run_sync(engine.execute(None))
        self.assertEqual(block.calls, [STANDALONE_NICK] * 3)
        banners = cycle_logs(logs)
        self.assertTrue(any(b.startswith("🔁 Cycle 1/3") for b in banners))
        self.assertTrue(any(b.startswith("🔁 Cycle 3/3") for b in banners))

    def test_stop_between_cycles_is_honoured(self):
        block = StopAfterFirstCallBlock()
        engine, _ = build_engine(FakeMemory(queue=[]))
        engine._stack = [block, RepeatLoop(repeat_count=5)]
        run_sync(engine.execute(None))
        self.assertEqual(block.calls, [STANDALONE_NICK],
                         "stop requested inside cycle 1 must end the run")


class TestRepeatLoopBlockContract(unittest.TestCase):
    def test_registered_and_round_trips(self):
        cls = get_action_class("REPEAT_LOOP")
        self.assertIsNotNone(cls, "REPEAT_LOOP must be registered")
        self.assertIs(cls, RepeatLoop)
        blk = RepeatLoop(repeat_count=4)
        d = blk.to_dict()
        self.assertEqual(d["block_id"], "REPEAT_LOOP")
        self.assertEqual(d["repeat_count"], 4)
        self.assertTrue(d["enabled"])
        self.assertEqual(blk.config_schema()["repeat_count"]["default"], 2)

    def test_engine_load_stack_instantiates_it(self):
        engine = ActionEngine(cdp=None, memory=FakeMemory(), criteria=None)
        engine.load_stack([{"block_id": "REPEAT_LOOP", "repeat_count": 6,
                            "enabled": True}])
        self.assertEqual(len(engine._stack), 1)
        self.assertEqual(engine._stack[0].repeat_count, 6)
        self.assertEqual(engine._repeat_cycles(), 6)

    def test_not_a_user_scoped_block(self):
        """Repeat Loop is a driver marker (like PAUSE), not a per-person step."""
        self.assertNotIn("REPEAT_LOOP", USER_SCOPED_BLOCKS)

    def test_repeat_cycles_defaults(self):
        engine = ActionEngine(cdp=None, memory=FakeMemory(), criteria=None)
        self.assertEqual(engine._repeat_cycles(), 1, "no marker → once")
        engine._stack = [RepeatLoop(repeat_count=0)]       # clamped to 1
        self.assertEqual(engine._repeat_cycles(), 1)
        engine._stack = [RepeatLoop(repeat_count="3")]
        self.assertEqual(engine._repeat_cycles(), 3)
        engine._stack = [RepeatLoop(repeat_count=2, enabled=False)]
        self.assertEqual(engine._repeat_cycles(), 1, "disabled → once")

    def test_ui_offers_the_block_with_a_cycle_setting(self):
        with open(os.path.join(UI_DIR, "js", "stack-dnd.js"),
                  encoding="utf-8") as fh:
            js = fh.read()
        self.assertIn("block_id:'REPEAT_LOOP'", js)
        self.assertIn("repeat_count:2", js)
        self.assertIn("Number of loop cycles", js)


if __name__ == "__main__":
    unittest.main(verbosity=2)
