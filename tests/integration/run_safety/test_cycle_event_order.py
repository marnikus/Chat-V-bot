"""Area C2 — cycle event ordering (signals/tracer/progress effect traces).

Parent design: docs/SAFETY_REFACTOR_AREA_C_IMPL_DESIGN_2026-09-10.md §5.
Task list: docs/SAFETY_REFACTOR_AREA_C_2026-09-10.md C2.

Pins the observable narrative the C2 extraction must preserve: block order,
per-user signals, progress increments and tracer `type` sequences (volatile
`ts`/`run_id` normalised). Non-stop scenarios pass before and after; stop
scenarios fail before C1.
"""

import asyncio
import glob
import json
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
from services.run.hooks import STANDALONE_NICK  # noqa: E402
from stores.user_memory import UserRecord  # noqa: E402


class RecordingBlock(BaseAction):
    block_id = "CUSTOM_FIND"
    name = "Find & Click"
    icon = "🔎"

    def __init__(self, tag="step", result=ActionResult.OK, **kw):
        super().__init__(pre_delay_ms=0)
        self.tag = tag
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
        self.events = {"user_complete": [], "marked": [], "step": [],
                       "started": []}
        self.engine.user_complete.connect(
            lambda n, ok: self.events["user_complete"].append((n, ok)))
        self.engine.person_marked.connect(
            lambda n: self.events["marked"].append(n))
        self.engine.step_complete.connect(
            lambda n, u: self.events["step"].append((n, u)))
        self.engine.step_started.connect(
            lambda i, b, u: self.events["started"].append((i, b, u)))
        return self.engine

    def tracer_types(self):
        traces = glob.glob(os.path.join("logs", "run_trace_*.jsonl"))
        self.assertEqual(len(traces), 1, "exactly one trace per run")
        with open(traces[0], encoding="utf-8") as fh:
            records = [json.loads(line) for line in fh]
        for rec in records:
            self.assertIn("run_id", rec)
            self.assertIn("ts", rec)
        return [r["type"] for r in records]


class TestEventOrder(EngineCase):
    async def test_two_users_two_blocks_narrative(self):
        engine = self.make([UserRecord(nick="u1"), UserRecord(nick="u2")])
        a = RecordingBlock(tag="A")
        b = RecordingBlock(tag="B")
        engine._stack = [a, b]
        await engine.execute()
        self.assertEqual(a.calls, ["u1", "u2"])
        self.assertEqual(b.calls, ["u1", "u2"])
        self.assertEqual(self.events["user_complete"],
                         [("u1", True), ("u2", True)])
        self.assertEqual(self.events["marked"], ["u1", "u2"])
        self.assertEqual(engine.progress.done, 2)
        self.assertEqual(engine.progress.total, 2)
        kinds = self.tracer_types()
        self.assertEqual(kinds[0], "run_start")
        self.assertEqual(kinds[-1], "run_end")
        self.assertIn("step_start", kinds)
        self.assertIn("step_end", kinds)

    async def test_standalone_narrative(self):
        engine = self.make([])
        block = RecordingBlock(tag="solo")
        engine._stack = [block]
        await engine.execute()
        self.assertEqual(block.calls, [STANDALONE_NICK])
        self.assertEqual(self.events["user_complete"], [])
        self.assertEqual(self.events["marked"], [])
        self.assertEqual(engine.progress.done, 1)
        kinds = self.tracer_types()
        self.assertIn("run_mode", kinds)

    async def test_fail_then_next_user_narrative(self):
        engine = self.make([UserRecord(nick="u1"), UserRecord(nick="u2")])

        class FailOnce(BaseAction):
            block_id = "CUSTOM_FIND"
            name = "Find & Click"
            icon = "🔎"

            def __init__(self):
                super().__init__(pre_delay_ms=0)
                self.calls = []

            async def execute(self, user_nick, cdp, engine=None):
                self.calls.append(user_nick)
                if user_nick == "u1":
                    return ActionResult.FAIL
                return ActionResult.OK

        block = FailOnce()
        engine._stack = [block]
        await engine.execute()
        self.assertEqual(self.events["user_complete"],
                         [("u1", False), ("u2", True)])
        self.assertEqual(self.events["marked"], ["u2"])
        self.assertEqual(engine.progress.failed, 1)
        self.assertEqual(engine.progress.done, 1)

    async def test_stop_after_first_user_narrative(self):
        engine = self.make([UserRecord(nick="u1"), UserRecord(nick="u2")])

        class StopOnU1(BaseAction):
            block_id = "CUSTOM_FIND"
            name = "Find & Click"
            icon = "🔎"

            def __init__(self):
                super().__init__(pre_delay_ms=0)
                self.calls = []

            async def execute(self, user_nick, cdp, engine=None):
                self.calls.append(user_nick)
                if user_nick == "u1":
                    engine.stop()
                return ActionResult.OK

        first = StopOnU1()
        second = RecordingBlock(tag="tail")
        engine._stack = [first, second]
        await engine.execute()
        self.assertEqual(first.calls, ["u1"])
        self.assertEqual(second.calls, [],
                         "no block may start after stop")
        self.assertEqual(self.events["user_complete"], [("u1", False)])
        self.assertEqual(self.events["marked"], [])
        kinds = self.tracer_types()
        self.assertIn("run_end", kinds)


ActionRegistry._classes.clear()
ActionRegistry._classes.update(_REGISTRY_SNAPSHOT)

if __name__ == "__main__":
    unittest.main(verbosity=2)
