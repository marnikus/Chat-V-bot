"""Regression tests for the “Tab Main block does nothing” bug.

Root cause: ActionEngine.execute() drove the whole block stack from
``for user in await memory.get_queue()``. With an empty user table the loop
body never ran, so no block executed — and because the stack had no
SCROLL_PARSE block the engine logged the misleading
``▶ Running stack on 0 user(s)`` followed by ``✅ Stack execution complete``,
i.e. total silence with no error.

Run with:  python3 tests/test_engine_standalone_run.py
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
)
from backend.user_memory import UserRecord  # noqa: E402


class RecordingBlock(BaseAction):
    """Stands in for a CUSTOM_FIND block; records every execution."""
    block_id = "CUSTOM_FIND"
    name = "Find & Click"
    icon = "🔎"

    def __init__(self, pre_delay_ms=0, result=ActionResult.OK, **kw):
        super().__init__(pre_delay_ms=0)
        self.custom_name = kw.get("custom_name", "Tab Main")
        self.calls = []
        self._result = result

    async def execute(self, user_nick, cdp, engine=None):
        self.calls.append(user_nick)
        if engine:
            engine.report("🔍 FIND phase: searching tab", "info")
        return self._result


class NeedsUserBlock(BaseAction):
    block_id = "CLICK_USER"
    name = "Click User"
    icon = "👤"

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


def build_engine(memory):
    engine = ActionEngine(cdp=None, memory=memory, criteria=None)
    logs = []
    engine.log_msg.connect(lambda m: logs.append(("log", m, "info")))
    engine.debug_msg.connect(lambda m, l: logs.append(("debug", m, l)))
    return engine, logs


def run(coro):
    with tempfile.TemporaryDirectory() as tmp:
        cwd = os.getcwd()
        os.chdir(tmp)          # keep run-trace files out of the repo
        try:
            return asyncio.run(coro())
        finally:
            os.chdir(cwd)


class TestStandaloneRun(unittest.TestCase):
    def test_user_independent_stack_runs_once_with_empty_queue(self):
        """THE BUG: a lone “Tab Main” Find & Click block must actually run."""
        block = RecordingBlock()
        memory = FakeMemory(queue=[])
        engine, logs = build_engine(memory)
        engine._stack = [block]

        run(lambda: engine.execute(None))

        self.assertEqual(block.calls, [STANDALONE_NICK],
                         "the block must execute exactly once")
        text = " ".join(m for _, m, _ in logs)
        self.assertIn("standalone", text.lower())
        # and it must NOT claim it ran on zero users
        self.assertNotIn("0 user(s)", text)
        # the synthetic user is never written to memory
        self.assertEqual(memory.marked, [])

    def test_empty_queue_with_user_blocks_warns_loudly(self):
        """No silent success when the stack genuinely needs users."""
        block = NeedsUserBlock()
        engine, logs = build_engine(FakeMemory(queue=[]))
        engine._stack = [block]

        run(lambda: engine.execute(None))

        self.assertEqual(block.calls, [])
        warnings = [m for kind, m, lvl in logs if lvl == "warn" or "⚠" in m]
        self.assertTrue(warnings, "an empty queue must produce a visible warning")
        text = " ".join(warnings)
        self.assertIn("CLICK_USER", text)
        self.assertNotIn("0 user(s)", " ".join(m for _, m, _ in logs))

    def test_normal_per_user_run_is_unchanged(self):
        block = RecordingBlock()
        memory = FakeMemory(queue=[UserRecord(nick="alice"),
                                   UserRecord(nick="bob")])
        engine, _ = build_engine(memory)
        engine._stack = [block]

        run(lambda: engine.execute(None))

        self.assertEqual(block.calls, ["alice", "bob"])
        self.assertEqual(memory.marked, ["alice", "bob"])

    def test_failure_is_reported_in_a_standalone_run(self):
        block = RecordingBlock(result=ActionResult.FAIL)
        engine, logs = build_engine(FakeMemory(queue=[]))
        engine._stack = [block]

        run(lambda: engine.execute(None))

        self.assertEqual(block.calls, [STANDALONE_NICK])
        errors = [m for _, m, lvl in logs if lvl == "error"]
        self.assertTrue(errors, "a failing standalone block must log an error")

    def test_empty_stack_is_reported(self):
        engine, logs = build_engine(FakeMemory(queue=[]))
        engine._stack = []

        run(lambda: engine.execute(None))

        text = " ".join(m for _, m, _ in logs)
        self.assertIn("empty", text.lower())

    def test_block_details_reach_the_log_in_a_standalone_run(self):
        """report() from inside the block must still stream to the console."""
        block = RecordingBlock()
        engine, logs = build_engine(FakeMemory(queue=[]))
        engine._stack = [block]

        run(lambda: engine.execute(None))

        self.assertIn("FIND phase", " ".join(m for _, m, _ in logs))

    def test_user_scoped_set_covers_the_message_pipeline(self):
        for bid in ("SCROLL_PARSE", "CLICK_USER", "TYPE_MESSAGE",
                    "CLICK_SEND", "ATTACH_IMAGE", "CONDITIONAL_SKIP"):
            self.assertIn(bid, USER_SCOPED_BLOCKS)
        for bid in ("CUSTOM_FIND", "CLICK_MAIN_TAB", "CLICK_BACK",
                    "WAIT_PAGE_LOAD", "PAUSE"):
            self.assertNotIn(bid, USER_SCOPED_BLOCKS)


class TestSavedTabMainConfig(unittest.TestCase):
    def test_saved_tab_main_preset_is_user_independent(self):
        """The exact block saved in config.json must now be runnable."""
        import json

        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, "config.json"), encoding="utf-8") as fh:
            cfg = json.load(fh)
        saved = next(c["block"] for c in cfg.get("custom_blocks", [])
                     if c.get("name") == "Tab Main")
        self.assertEqual(saved["block_id"], "CUSTOM_FIND")
        self.assertNotIn(saved["block_id"], USER_SCOPED_BLOCKS)

        from actions.custom_find import CustomFind
        block = CustomFind(**{k: v for k, v in saved.items() if k != "block_id"})
        self.assertEqual(block.display_name, "Tab Main")
        self.assertTrue(block.highlight_enabled)
        self.assertTrue(block.selector)


if __name__ == "__main__":
    unittest.main(verbosity=2)
