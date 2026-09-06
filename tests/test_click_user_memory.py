"""Click User "Use Person from Memory" checkbox.

FEATURE — Click User may act on the person whose nick is saved in this
run's {{nick}} memory instead of working through the queued people list.

  * checkbox OFF (default) — behaviour is identical to today: the engine
    runs the stack once per queued person, Click User clicks that person,
    remembers the nick for later {{nick}} fields, and the person is marked
    messaged after a successful pass;
  * checkbox ON — the engine switches the whole cycle to SINGLE-TARGET
    mode: the stack runs exactly once, the queue is ignored, and Click
    User finds/clicks the person saved in memory (engine.selected_nick —
    set by a Pick Person block or an earlier Click User). After a
    successful pass that person is marked messaged (so Repeat Loop + Pick
    Person advances to a different New person each cycle);
  * ON with no saved nick — the cycle ends safely with a clear warning;
    nothing is clicked, nobody is marked.

Run with:  python3 tests/test_click_user_memory.py
"""

import asyncio
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import actions.click_user as click_user_mod  # noqa: E402
from actions.base_action import BaseAction, ActionResult  # noqa: E402
from actions.click_user import ClickUser  # noqa: E402
from actions.take_person import TakePerson  # noqa: E402
from backend.action_engine import ActionEngine  # noqa: E402
from backend.user_memory import UserMemory, UserRecord  # noqa: E402


def run(coro):
    return asyncio.run(coro)


def in_tmp_cwd(coro_fn):
    """Run a coroutine with cwd in a throwaway dir (the tracer writes logs/)."""
    cwd = os.getcwd()
    os.chdir(tempfile.mkdtemp())
    try:
        return run(coro_fn())
    finally:
        os.chdir(cwd)


class FakeEngine:
    """Engine stand-in for direct block tests (selected_nick + report)."""

    def __init__(self, selected_nick=""):
        self.selected_nick = selected_nick
        self.noted = []
        self.messages = []

    def note_selected(self, nick):
        if nick:
            self.noted.append(nick)
            self.selected_nick = nick

    def report(self, msg, level="info"):
        self.messages.append((msg, level))


class MemHarness:
    def __init__(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.memory = UserMemory(os.path.join(self._tmp.name, "t.db"))

    async def __aenter__(self):
        await self.memory.init()
        return self.memory

    async def __aexit__(self, *exc):
        await self.memory.close()
        self._tmp.cleanup()


def rec(nick, messaged=False):
    return UserRecord(nick=nick, gender="female", guest=True,
                      messaged=messaged)


async def seed(mem, *people):
    for u in people:
        await mem.upsert_user(u)
        if u.messaged:
            await mem.mark_messaged(u.nick)


class StubClick(BaseAction):
    """Stands in for CLICK_USER: records what it was asked to click.

    Mirrors the real block's `use_person_from_memory` setting (and its
    safe behaviour: an empty memory nick FAILs instead of clicking blindly)
    so the engine's single-target mode can be tested without a real page.
    """

    block_id = "CLICK_USER"
    name = "Click User"
    icon = "👤"

    def __init__(self, use_person_from_memory=False, enabled=True, **kw):
        super().__init__(pre_delay_ms=0)
        self.use_person_from_memory = bool(use_person_from_memory)
        self.enabled = bool(enabled)
        self.calls = []

    async def execute(self, user_nick, cdp, engine=None):
        nick = user_nick
        if self.use_person_from_memory:
            nick = getattr(engine, "selected_nick", "") or ""
            if not nick:
                return ActionResult.FAIL   # never click blindly
        self.calls.append(nick)
        if engine is not None:
            note = getattr(engine, "note_selected", None)
            if note is not None:
                note(nick)
        return ActionResult.OK


class Consumer(BaseAction):
    """Records what {{nick}} looked like when it ran (message receiver)."""

    block_id = "CONSUMER"
    name = "Consumer"
    icon = "🧪"

    def __init__(self, match_text="", **kw):
        super().__init__(pre_delay_ms=0)
        self.match_text = match_text
        self.seen = []

    async def execute(self, user_nick, cdp, engine=None):
        self.seen.append((user_nick, self.match_text))
        return ActionResult.OK


# ── the block setting itself ─────────────────────────────────────
class TestBlockSetting(unittest.TestCase):
    def test_default_is_off(self):
        self.assertFalse(ClickUser().use_person_from_memory)

    def test_checkbox_in_schema(self):
        schema = ClickUser().config_schema()
        self.assertIn("use_person_from_memory", schema)
        self.assertEqual(schema["use_person_from_memory"]["type"], "checkbox")
        self.assertFalse(schema["use_person_from_memory"]["default"])

    def test_to_dict_round_trips(self):
        for value in (True, False):
            blk = ClickUser(use_person_from_memory=value)
            self.assertEqual(blk.to_dict()["use_person_from_memory"], value)
        self.assertTrue(
            ClickUser(**ClickUser(use_person_from_memory=True).to_dict())
            .use_person_from_memory)


# ── block target resolution (real ClickUser, runner mocked) ──────
class TestBlockTargetResolution(unittest.TestCase):
    def test_flag_on_clicks_the_saved_nick_not_the_queue_nick(self):
        async def go():
            engine = FakeEngine(selected_nick="Anna")
            blk = ClickUser(use_person_from_memory=True, verify_new_tab=False,
                            pre_delay_ms=0)
            seen = {}
            async def fake_find_and_click_exact(cdp, **kw):
                seen.update(kw)
                return ActionResult.OK
            with mock.patch.object(click_user_mod, "find_and_click_exact",
                                   new=fake_find_and_click_exact):
                result = await blk.execute("Bella", None, engine)
            return result, seen, engine
        result, seen, engine = run(go())
        self.assertEqual(result, ActionResult.OK)
        self.assertEqual(seen["text"], "Anna",
                         "the memory nick must be the click target, not the "
                         "queued user Bella")
        self.assertEqual(engine.noted, ["Anna"])

    def test_flag_off_keeps_the_queue_nick(self):
        async def go():
            engine = FakeEngine(selected_nick="Anna")
            blk = ClickUser(use_person_from_memory=False, verify_new_tab=False,
                            pre_delay_ms=0)
            seen = {}
            async def fake_find_and_click_exact(cdp, **kw):
                seen.update(kw)
                return ActionResult.OK
            with mock.patch.object(click_user_mod, "find_and_click_exact",
                                   new=fake_find_and_click_exact):
                result = await blk.execute("Bella", None, engine)
            return result, seen
        result, seen = run(go())
        self.assertEqual(result, ActionResult.OK)
        self.assertEqual(seen["text"], "Bella")

    def test_flag_on_with_no_memory_fails_without_clicking(self):
        async def go():
            engine = FakeEngine(selected_nick="")
            blk = ClickUser(use_person_from_memory=True, verify_new_tab=False,
                            pre_delay_ms=0)
            calls = []
            async def fake_find_and_click_exact(cdp, **kw):
                calls.append(kw)
                return ActionResult.OK
            with mock.patch.object(click_user_mod, "find_and_click_exact",
                                   new=fake_find_and_click_exact):
                result = await blk.execute("Bella", None, engine)
            return result, calls, engine.messages
        result, calls, messages = run(go())
        self.assertEqual(result, ActionResult.FAIL)
        self.assertEqual(calls, [], "nothing may be clicked without a nick")
        self.assertTrue(any("memory" in m.lower() for m, _ in messages))

    def test_flag_on_with_no_engine_fails_safely(self):
        async def go():
            blk = ClickUser(use_person_from_memory=True, verify_new_tab=False,
                            pre_delay_ms=0)
            calls = []
            async def fake_find_and_click_exact(cdp, **kw):
                calls.append(kw)
                return ActionResult.OK
            with mock.patch.object(click_user_mod, "find_and_click_exact",
                                   new=fake_find_and_click_exact):
                result = await blk.execute("Bella", None, None)
            return result, calls
        result, calls = run(go())
        self.assertEqual(result, ActionResult.FAIL)
        self.assertEqual(calls, [])

    def test_flag_on_failed_click_does_not_remember(self):
        async def go():
            engine = FakeEngine(selected_nick="Anna")
            blk = ClickUser(use_person_from_memory=True, verify_new_tab=False,
                            pre_delay_ms=0)
            async def fake_find_and_click_exact(cdp, **kw):
                return ActionResult.FAIL
            with mock.patch.object(click_user_mod, "find_and_click_exact",
                                   new=fake_find_and_click_exact):
                result = await blk.execute("Bella", None, engine)
            return result, engine.noted
        result, noted = run(go())
        self.assertEqual(result, ActionResult.FAIL)
        self.assertEqual(noted, [])


# ── engine single-target mode ────────────────────────────────────
class TestEngineSingleTargetMode(unittest.TestCase):
    def test_on_runs_once_and_marks_the_picked_person(self):
        """Queue has two New people, but the memory-driven run may only work
        the ONE person Pick Person chose."""
        async def go():
            async with MemHarness() as mem:
                await seed(mem, rec("Anna"), rec("Bella"))
                click = StubClick(use_person_from_memory=True)
                take = TakePerson(pick_mode="order_first")
                eng = ActionEngine(cdp=None, memory=mem, criteria=None)
                eng._stack = [take, click]
                await eng.execute(None)
                rows = {u.nick: u for u in await mem.get_all()}
                return click, rows
        click, rows = in_tmp_cwd(go)
        self.assertEqual(len(click.calls), 1,
                         "the queue must be ignored — exactly one target")
        chosen = click.calls[0]
        self.assertIn(chosen, {"Anna", "Bella"})
        self.assertTrue(rows[chosen].messaged,
                        "the clicked memory person must become Done")
        other = "Bella" if chosen == "Anna" else "Anna"
        self.assertFalse(rows[other].messaged,
                         "the other queued person must stay untouched")

    def test_on_without_any_saved_nick_ends_safely(self):
        """No Pick Person / no earlier click → clear warning, no clicks."""
        async def go():
            async with MemHarness() as mem:
                await seed(mem, rec("Anna"), rec("Bella"))
                click = StubClick(use_person_from_memory=True)
                eng = ActionEngine(cdp=None, memory=mem, criteria=None)
                logs, details = [], []
                eng.log_msg.connect(lambda m: logs.append(m))
                eng.debug_msg.connect(lambda m, lvl: details.append(m))
                eng._stack = [click]
                await eng.execute(None)
                rows = {u.nick: u for u in await mem.get_all()}
                return click.calls, rows, logs + details
        calls, rows, logs = in_tmp_cwd(go)
        self.assertEqual(calls, [])
        self.assertTrue(all(not u.messaged for u in rows.values()))
        self.assertTrue(any("memory" in m.lower() for m in logs),
                        "the reason must be logged clearly")

    def test_off_keeps_the_queue_behaviour(self):
        async def go():
            async with MemHarness() as mem:
                await seed(mem, rec("Anna"), rec("Bella"))
                click = StubClick(use_person_from_memory=False)
                eng = ActionEngine(cdp=None, memory=mem, criteria=None)
                eng._stack = [click]
                await eng.execute(None)
                rows = {u.nick: u for u in await mem.get_all()}
                return click.calls, rows
        calls, rows = in_tmp_cwd(go)
        self.assertEqual(calls, ["Anna", "Bella"],
                         "OFF = today's behaviour: one pass per queued user")
        self.assertTrue(all(u.messaged for u in rows.values()))

    def test_disabled_memory_click_does_not_force_single_target(self):
        async def go():
            async with MemHarness() as mem:
                await seed(mem, rec("Anna"), rec("Bella"))
                off = StubClick(use_person_from_memory=True, enabled=False)
                consumer = Consumer(match_text="hi {{nick}}")
                eng = ActionEngine(cdp=None, memory=mem, criteria=None)
                eng._stack = [off, consumer]
                await eng.execute(None)
                return consumer.seen
        seen = in_tmp_cwd(go)
        self.assertEqual(len(seen), 2,
                         "a disabled block may not change the run mode")

    def test_repeat_loop_advances_to_a_different_person_each_cycle(self):
        """Pick Person re-picks every cycle; each picked person is clicked,
        messaged and marked Done; once nobody New is left the loop ends
        instead of re-messaging the last person."""
        async def go():
            async with MemHarness() as mem:
                await seed(mem, rec("Anna"), rec("Bella"), rec("Cara"))
                click = StubClick(use_person_from_memory=True)
                take = TakePerson(pick_mode="order_first")
                consumer = Consumer(match_text="msg {{nick}}")
                eng = ActionEngine(cdp=None, memory=mem, criteria=None)
                eng._stack = [take, click, consumer]
                eng._repeat_cycles = lambda: 10   # pretend a Repeat Loop marker
                await eng.execute(None)
                rows = {u.nick: u for u in await mem.get_all()}
                return click.calls, [s for _, s in consumer.seen], rows
        calls, texts, rows = in_tmp_cwd(go)
        self.assertEqual(sorted(set(calls)), ["Anna", "Bella", "Cara"],
                         "every New person must be clicked exactly once")
        self.assertEqual(len(calls), 3,
                         "no cycle may re-click an already-Done person")
        self.assertEqual(len(set(texts)), 3)
        self.assertTrue(all(u.messaged for u in rows.values()))


if __name__ == "__main__":
    unittest.main(verbosity=2)
