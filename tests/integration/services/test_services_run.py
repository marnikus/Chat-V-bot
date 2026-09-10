"""services/run_service — loop, state, error recovery.

Extends tests/test_engine_standalone_run.py (standalone / empty-queue
regressions) with the loop/state/recovery contract:

  * pause/resume interleaves with per-user execution;
  * stop is honoured between blocks and users, and while paused;
  * one failing/raising block fails that user but the run recovers and
    continues with the next user;
  * Repeat Loop runs N cycles and Stop ends it;
  * live-collection hooks (person_collected / person_rejected /
    unmessaged_nicks / mark_person_messaged) are safe and typed.

Run with:  python3 tests/integration/services/test_services_run.py
"""

import asyncio
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))

from actions.base_action import ActionResult, BaseAction  # noqa: E402
from services.run import (ActionEngine, STANDALONE_NICK,  # noqa: E402
                                  normalize_blocks)
from stores.user_memory import UserRecord  # noqa: E402


class RecordingBlock(BaseAction):
    block_id = "CUSTOM_FIND"
    name = "Find & Click"
    icon = "🔎"

    def __init__(self, result=ActionResult.OK, pre_delay_ms=0,
                 raise_first_n=0, fail_first_n=0, **kw):
        super().__init__(pre_delay_ms=0)
        self.calls = []
        self._result = result
        self._raise_first_n = int(raise_first_n or 0)
        self._fail_first_n = int(fail_first_n or 0)

    async def execute(self, user_nick, cdp, engine=None):
        self.calls.append(user_nick)
        n = len(self.calls)
        if n <= self._raise_first_n:
            raise RuntimeError("block exploded")
        if n <= self._fail_first_n:
            return ActionResult.FAIL
        return self._result


class RepeatBlock(BaseAction):
    block_id = "REPEAT_LOOP"
    name = "Repeat Loop"
    icon = "🔁"

    def __init__(self, repeat_count=2, **kw):
        super().__init__(pre_delay_ms=0)
        self.repeat_count = repeat_count
        self.calls = []

    async def execute(self, user_nick, cdp, engine=None):
        return ActionResult.OK


class ScrollBlock(BaseAction):
    block_id = "SCROLL_PARSE"
    name = "Scroll & Parse"
    icon = "📜"

    def __init__(self, **kw):
        super().__init__(pre_delay_ms=0)
        self.enabled = True

    async def execute(self, user_nick, cdp, engine=None):
        return ActionResult.OK


class FakeMemory:
    def __init__(self, users=None):
        self._users = list(users or [])
        self.marked = []
        self.upserts = []
        self.deleted = []
        self.fail_upsert = False
        self.fail_get_all = False

    async def get_queue(self):
        return [u for u in self._users if not u.messaged]

    async def get_all(self):
        if self.fail_get_all:
            raise RuntimeError("cannot read")
        return list(self._users)

    async def upsert_user(self, user):
        if self.fail_upsert:
            raise RuntimeError("cannot write")
        self.upserts.append(user.nick)
        self._users.append(user)

    async def mark_messaged(self, nick):
        self.marked.append(nick)

    async def delete_user(self, nick):
        self.deleted.append(nick)
        for u in list(self._users):
            if u.nick == nick:
                self._users.remove(u)
                return True
        return False


def run_in_tmp(coro):
    """Run a coroutine with CWD in a temp dir (run traces stay out of repo)."""
    old = os.getcwd()
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        try:
            return asyncio.run(coro())
        finally:
            os.chdir(old)


class EngineCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.old = os.getcwd()
        self.tmp = tempfile.TemporaryDirectory()
        os.chdir(self.tmp.name)

    def tearDown(self):
        os.chdir(self.old)
        self.tmp.cleanup()

    def make(self, users=None):
        self.memory = FakeMemory(users)
        self.engine = ActionEngine(cdp=None, memory=self.memory, criteria=None)
        self.logs = []
        self.debug = []
        self.completes = []
        self.user_done = []
        self.started = []
        self.marked = []
        self.stack_complete = []
        self.engine.log_msg.connect(lambda m: self.logs.append(m))
        self.engine.debug_msg.connect(lambda m, l: self.debug.append((m, l)))
        self.engine.step_complete.connect(lambda n, u: self.completes.append((n, u)))
        self.engine.user_complete.connect(lambda n, ok: self.user_done.append((n, ok)))
        self.engine.step_started.connect(lambda i, b, u: self.started.append((i, b, u)))
        self.engine.person_marked.connect(lambda n: self.marked.append(n))
        self.engine.stack_complete.connect(lambda: self.stack_complete.append(True))
        return self.engine


class TestPauseResume(EngineCase):
    async def test_pause_mid_run_waits_between_users_then_resumes(self):
        engine = self.make([UserRecord(nick="a"), UserRecord(nick="b")])
        gate = asyncio.Event()
        block = RecBlock()
        block.gate = gate
        engine._stack = [block]

        async def controller():
            while not block.calls:
                await asyncio.sleep(0.01)
            engine.pause()               # pause right after user a started
            gate.set()

        task = asyncio.ensure_future(engine.execute())
        await controller()
        await asyncio.sleep(0.35)
        self.assertEqual(block.calls, ["a"],
                         "a paused run must not touch the next user")
        self.assertTrue(engine.is_running)
        engine.resume()
        await task
        self.assertEqual(block.calls, ["a", "b"])
        self.assertFalse(engine.is_running)

    async def test_a_new_run_clears_a_stale_pause(self):
        # The Run press resets control flags: a pause/stop requested while
        # idle must not silently freeze the next run.
        engine = self.make([UserRecord(nick="a")])
        block = RecordingBlock()
        engine._stack = [block]
        engine.pause()
        self.assertTrue(engine._paused)
        await engine.execute()
        self.assertEqual(block.calls, ["a"], "a fresh run starts unpaused")

    async def test_stop_while_paused_exits_the_wait(self):
        engine = self.make([UserRecord(nick="a"), UserRecord(nick="b")])
        gate = asyncio.Event()
        block = RecBlock()
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
        self.assertEqual(block.calls, ["a"], "paused before the next user")
        engine.stop()                    # Stop wins over Pause
        await asyncio.wait_for(task, timeout=3)
        self.assertFalse(engine.is_running)
        self.assertEqual(block.calls, ["a"],
                         "stopping while paused must not run user b")
        self.assertEqual(self.stack_complete, [True])
        self.assertTrue(any("stopped" in m.lower() for m, _ in self.debug))


class RecBlock(BaseAction):
    """A block that waits on a gate so Stop can land inside execution."""

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


class TestStop(EngineCase):
    async def test_stop_skips_remaining_users(self):
        engine = self.make([UserRecord(nick="a"), UserRecord(nick="b"),
                            UserRecord(nick="c")])
        gate = asyncio.Event()
        block = RecBlock()
        block.gate = gate
        engine._stack = [block]

        async def stopper():
            while not gate.is_set() and not block.calls:
                await asyncio.sleep(0.01)
            engine.stop()
            gate.set()

        await asyncio.gather(engine.execute(), stopper())
        self.assertEqual(block.calls, ["a"], "stop must skip the remaining users")
        self.assertEqual(len(self.stack_complete), 1)
        self.assertFalse(engine.is_running)
        self.assertTrue(any("stopped" in m.lower() for m, _ in self.debug))

    async def test_a_new_run_clears_a_stale_stop(self):
        engine = self.make([UserRecord(nick="a"), UserRecord(nick="b")])
        block = RecordingBlock()
        engine._stack = [block]
        engine.stop()          # requested while idle, before the run
        await engine.execute()
        self.assertEqual(block.calls, ["a", "b"],
                         "a fresh Run must clear the stale Stop request")
        self.assertEqual(self.stack_complete, [True])
        self.assertFalse(engine.is_running)


class TestErrorRecovery(EngineCase):
    async def test_a_raising_block_fails_that_user_next_user_still_runs(self):
        engine = self.make([UserRecord(nick="a"), UserRecord(nick="b")])
        boom = RecordingBlock(raise_first_n=1)  # raises only for user a
        ok = RecordingBlock()
        engine._stack = [boom, ok]
        await engine.execute()
        self.assertEqual(self.user_done, [("a", False), ("b", True)],
                         "user a fails, user b must still complete")
        self.assertEqual(self.memory.marked, ["b"], "only the successful user is marked")
        errors = [m for m, _ in self.debug if "raised" in m or "FAILED" in m]
        self.assertTrue(errors)

    async def test_fail_result_stops_the_user_but_not_the_run(self):
        engine = self.make([UserRecord(nick="a"), UserRecord(nick="b")])
        fail = RecordingBlock(fail_first_n=1)   # FAIL for a, OK for b
        ok = RecordingBlock()
        engine._stack = [fail, ok]
        await engine.execute()
        self.assertEqual(self.user_done, [("a", False), ("b", True)])
        # the failing user stops at the failing block: ok ran only for b
        self.assertEqual(ok.calls, ["b"])
        self.assertEqual(fail.calls, ["a", "b"])   # ran for both, FAILed for a

    async def test_skip_result_stops_that_user_too(self):
        engine = self.make([UserRecord(nick="a")])
        skip = RecordingBlock(result=ActionResult.SKIP)
        engine._stack = [skip]
        await engine.execute()
        self.assertEqual(self.user_done, [("a", False)])


class UserBlock(BaseAction):
    """A user-scoped block (CLICK_USER) — never runs in standalone mode."""

    block_id = "CLICK_USER"
    name = "Click User"
    icon = "👤"

    def __init__(self, **kw):
        super().__init__(pre_delay_ms=0)
        self.calls = []

    async def execute(self, user_nick, cdp, engine=None):
        self.calls.append(user_nick)
        return ActionResult.OK


class TestRepeatLoop(EngineCase):
    def repeat_engine(self, count=3, block=None, users=None):
        engine = self.make(users if users is not None
                           else [UserRecord(nick="a")])
        block = block or RecordingBlock()
        marker = RepeatBlock(repeat_count=count)
        engine._stack = [marker, block]
        return engine, block

    async def test_repeat_cycles_run_n_times(self):
        engine, block = self.repeat_engine(count=3)
        await engine.execute()
        self.assertEqual(block.calls, ["a"] * 3)
        self.assertEqual(engine._repeat_cycles(), 3)
        self.assertTrue(any("Repeat Loop" in m for m in self.logs))
        self.assertEqual(self.memory.marked, ["a"] * 3)

    async def test_repeat_stops_midway(self):
        gate = asyncio.Event()
        block = RecBlock()
        block.gate = gate
        engine, block = self.repeat_engine(count=5, block=block)

        async def stopper():
            while not gate.is_set() and not block.calls:
                await asyncio.sleep(0.01)
            engine.stop()
            gate.set()

        await asyncio.gather(engine.execute(), stopper())
        self.assertLess(len(block.calls), 5)
        self.assertGreaterEqual(len(block.calls), 1)
        self.assertFalse(engine.is_running)
        self.assertTrue(any("stopped" in m.lower() for m, _ in self.debug))

    async def test_repeat_with_empty_queue_and_user_blocks_stops_after_one_cycle(self):
        engine, block = self.repeat_engine(count=5, block=UserBlock(), users=[])
        await engine.execute()
        self.assertEqual(block.calls, [], "a user-scoped stack never runs standalone")
        self.assertTrue(any("No users found" in m for m in self.logs))


class TestLiveHooks(EngineCase):
    async def test_person_collected_upserts_and_emits(self):
        engine = self.make()
        found = []
        engine.person_found.connect(lambda p: found.append(json.loads(p)))
        record = UserRecord(nick="Zoe", gender="female", registered=True)
        await engine.person_collected(record, collected=[record])
        self.assertEqual(self.memory.upserts, ["Zoe"])
        self.assertEqual(found[0]["nick"], "Zoe")
        self.assertEqual(found[0]["collected"], 1)
        self.assertTrue(found[0]["registered"])

    async def test_person_collected_survives_memory_failure(self):
        engine = self.make()
        engine._memory.fail_upsert = True
        found = []
        engine.person_found.connect(lambda p: found.append(p))
        await engine.person_collected(UserRecord(nick="X"), collected=[])
        # the hook must still emit person_found (no raise)
        self.assertEqual(len(found), 1)

    async def test_unmessaged_nicks(self):
        engine = self.make([UserRecord(nick="old", messaged=True),
                            UserRecord(nick="new", messaged=False)])
        nicks = await engine.unmessaged_nicks()
        self.assertEqual(nicks, {"new"})

    async def test_unmessaged_nicks_fails_open_on_error(self):
        engine = self.make()
        engine._memory.fail_get_all = True
        self.assertEqual(await engine.unmessaged_nicks(), set())

    async def test_person_rejected_deletes_and_emits(self):
        engine = self.make([UserRecord(nick="Bad")])
        removed = []
        engine.person_removed.connect(lambda p: removed.append(json.loads(p)))
        ok = await engine.person_rejected(UserRecord(nick="Bad"), reason="male")
        self.assertTrue(ok)
        self.assertEqual(self.memory.deleted, ["Bad"])
        self.assertEqual(removed[0]["nick"], "Bad")
        self.assertEqual(removed[0]["reason"], "male")
        self.assertTrue(any("Removed" in m for m, _ in self.debug))

    async def test_person_rejected_absent_row_returns_false(self):
        engine = self.make()
        self.assertFalse(await engine.person_rejected(
            UserRecord(nick="Ghost"), reason="x"))


class TestMessagedStatus(EngineCase):
    async def test_mark_person_messaged_statuses(self):
        engine = self.make([UserRecord(nick="Anna", messaged=False),
                            UserRecord(nick="Done", messaged=True)])
        self.assertEqual(await engine.mark_person_messaged("Anna"), "ok")
        self.assertEqual(await engine.mark_person_messaged("Done"), "already")
        self.assertEqual(await engine.mark_person_messaged("Ghost"), "missing")
        self.assertEqual(await engine.mark_person_messaged(""), "missing")
        self.assertEqual(self.marked, ["Anna"])

    async def test_mark_person_messaged_error_when_memory_breaks(self):
        engine = self.make([UserRecord(nick="Anna")])
        engine._memory.fail_get_all = True
        self.assertEqual(await engine.mark_person_messaged("Anna"), "error")


class TestQueueOrder(EngineCase):
    def test_no_scroll_block_orders_newest_first_with_nick_ties(self):
        engine = self.make()
        users = [UserRecord(nick="b", first_seen="2026-09-01"),
                 UserRecord(nick="A", first_seen="2026-09-02"),
                 UserRecord(nick="done", messaged=True,
                            first_seen="2026-09-03")]
        self.assertEqual(engine.queue_order(users), ["A", "b"])

    def test_scroll_block_switches_to_sort_people(self):
        engine = self.make()
        engine._stack = [ScrollBlock()]
        users = [UserRecord(nick="Zoe", first_seen="2026-09-02"),
                 UserRecord(nick="Anna", first_seen="2026-09-01"),
                 UserRecord(nick="Done", messaged=True)]
        self.assertEqual(engine.queue_order(users), ["Anna", "Zoe"])

    def test_disabled_scroll_block_uses_queue_order(self):
        engine = self.make()
        block = ScrollBlock()
        block.enabled = False
        engine._stack = [block]
        users = [UserRecord(nick="old", first_seen="2026-09-01"),
                 UserRecord(nick="new", first_seen="2026-09-02")]
        self.assertEqual(engine.queue_order(users), ["new", "old"])


class TestLabelGuard(EngineCase):
    def test_label_allows_fails_open(self):
        engine = self.make()
        self.assertTrue(engine.label_allows("x"))                # no filter
        engine.label_filter = lambda n: False
        self.assertFalse(engine.label_allows("x"))
        engine.label_filter = lambda n: (_ for _ in ()).throw(RuntimeError())
        self.assertTrue(engine.label_allows("x"), "a broken guard must fail open")

    def test_filter_by_labels_and_announce(self):
        engine = self.make()
        engine.label_filter = lambda n: n != "rude"
        engine.label_reason = lambda n: "excluded label"
        users = [UserRecord(nick="nice"), UserRecord(nick="rude"),
                 UserRecord(nick="ok")]
        kept = engine.filter_by_labels(users, announce=True)
        self.assertEqual([u.nick for u in kept], ["nice", "ok"])
        msg = " ".join(m for m, _ in self.debug)
        self.assertIn("Label filter skipped 1 person(s): rude (excluded label)",
                      msg)

    def test_filter_without_guard_returns_the_same_items(self):
        engine = self.make()
        users = [UserRecord(nick="a")]
        self.assertEqual(engine.filter_by_labels(users), users)


class TestBlocksAndNick(EngineCase):
    async def test_load_stack_normalizes_and_skips_unknown(self):
        engine = self.make()
        engine.load_stack([
            {"block_id": "NOT_A_REAL_BLOCK"},
            {"block_id": "PAUSE", "pause_ms": 1},
            "garbage",
            None,
            {"block_id": "PAUSE", "enabled": False, "pause_ms": 2},
        ])
        stack = engine.get_stack()
        self.assertEqual(len(stack), 2, "unknown ids and non-dicts are dropped")
        self.assertEqual([s["enabled"] for s in stack], [True, False])

    async def test_disabled_block_never_executes(self):
        engine = self.make([UserRecord(nick="a")])
        run = RecordingBlock()
        skip = RecordingBlock()
        skip.enabled = False
        engine._stack = [skip, run]
        await engine.execute()
        self.assertEqual(skip.calls, [])
        self.assertEqual(run.calls, ["a"])
        self.assertTrue(any("Skipped disabled block" in m for m, _ in self.debug))

    async def test_expand_nick_restores_attrs(self):
        engine = self.make()
        block = RecordingBlock()
        block.selector = 'li:has-text("{{nick}}")'
        block._internal = "{{nick}}"       # private attrs must not be touched
        changed = engine._expand_nick_on_block(block, "Zoe")
        self.assertEqual(block.selector, 'li:has-text("Zoe")')
        self.assertEqual(block._internal, "{{nick}}")
        self.assertEqual(changed, {"selector": 'li:has-text("{{nick}}")'})
        engine._restore_block_attrs(block, changed)
        self.assertEqual(block.selector, 'li:has-text("{{nick}}")')

    async def test_note_selected_ignores_empties(self):
        engine = self.make()
        engine.note_selected("Zoe")
        self.assertEqual(engine.selected_nick, "Zoe")
        engine.note_selected("")
        engine.note_selected(None)
        self.assertEqual(engine.selected_nick, "Zoe")

    async def test_take_phase_keeps_previous_selection_on_empty_match(self):
        engine = self.make([UserRecord(nick="Anna"), UserRecord(nick="Zoe")])
        engine._stack = []

        class NoMatch:
            block_id = "TAKE_PERSON"
            enabled = True
            mode_phrase = "Status-New person"

            def choose(self, rows, eng):   # contract: sync, Optional[str]
                return None

        engine._stack = [NoMatch()]
        engine.note_selected("Zoe")
        matched = await engine._run_take_phase()
        self.assertFalse(matched)
        self.assertEqual(engine.selected_nick, "Zoe")
        self.assertTrue(any("no Status-New person" in m for m in self.logs))


class TestRunGuards(EngineCase):
    async def test_already_running_is_refused(self):
        engine = self.make([UserRecord(nick="a")])
        gate = asyncio.Event()
        block = RecBlock()
        block.gate = gate
        engine._stack = [block]
        first = asyncio.ensure_future(engine.execute())
        while not block.calls:
            await asyncio.sleep(0.01)
        await engine.execute()      # second call — must not start a second run
        self.assertTrue(engine.is_running, "the first run still owns the engine")
        gate.set()
        await first
        self.assertEqual(block.calls, ["a"], "only one run happened")
        self.assertTrue(any("Already running" in m for m in self.logs))

    async def test_all_disabled_runs_nothing_and_marks_nobody(self):
        """B5 regression: an all-disabled stack used to report the user as
        completed, so the cycle marked them 'messaged' — the New queue was
        consumed without any block running."""
        engine = self.make([UserRecord(nick="a")])
        block = RecordingBlock()
        block.enabled = False
        engine._stack = [block]
        await engine.execute()
        self.assertEqual(self.user_done, [("a", False)])
        self.assertEqual(self.memory.marked, [])
        self.assertFalse(self.memory._users[0].messaged)


class TestNormalize(unittest.TestCase):
    def test_normalize_blocks_keeps_concrete_settings(self):
        clean = normalize_blocks([{"block_id": "PAUSE", "pause_ms": 9,
                                   "use_panel_filters": True, "_x": 1}])
        self.assertEqual(len(clean), 1)
        self.assertEqual(clean[0]["pause_ms"], 9)
        self.assertNotIn("use_panel_filters", clean[0])
        self.assertNotIn("_x", clean[0])
        self.assertTrue(clean[0]["enabled"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
