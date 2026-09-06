"""Mark Person as Messaged block — mark the {{nick}} person Status Done.

FEATURE — a Mark Person as Messaged (MARK_MESSAGED) block flips ONE person
— the nick saved in this run's {{nick}} memory (Pick Person / an earlier
Click User) — to messaged in the People list. It is memory-driven: it never
looks at the queued users.

  * no nick saved this run   → ❌ fail loudly, nothing marked blindly;
  * nick not in the list     → ❌ fail ("if exist in memory");
  * already messaged         → OK, informational (idempotent);
  * marked now               → ✅ + live grid row update (person_marked);
  * Repeat Loop + Pick Person whose pool is exhausted → the cycle ends
    like an empty queue instead of looping over the stale selection.

Run with:  python3 tests/test_mark_person_messaged.py
"""

import asyncio
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from actions.base_action import ActionResult, get_action_class  # noqa: E402
from actions.mark_messaged import MarkMessaged  # noqa: E402
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
    """Engine stand-in: selected_nick + a scripted mark_person_messaged."""

    def __init__(self, selected_nick="", status="ok"):
        self.selected_nick = selected_nick
        self._status = status
        self.marked_calls = []
        self.messages = []

    async def mark_person_messaged(self, nick):
        self.marked_calls.append(nick)
        return self._status

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


# ── the block itself ─────────────────────────────────────────────
class TestBlock(unittest.TestCase):
    def test_registered(self):
        self.assertEqual(get_action_class("MARK_MESSAGED"), MarkMessaged)

    def test_marks_the_saved_nick(self):
        async def go():
            eng = FakeEngine(selected_nick="Anna", status="ok")
            blk = MarkMessaged(pre_delay_ms=0)
            result = await blk.execute("—", None, eng)
            return result, eng
        result, eng = run(go())
        self.assertEqual(result, ActionResult.OK)
        self.assertEqual(eng.marked_calls, ["Anna"],
                         "the memory nick must be the one marked")
        self.assertTrue(any("Anna" in m and "Done" in m for m, _ in
                            eng.messages))

    def test_already_messaged_is_ok_and_idempotent(self):
        async def go():
            eng = FakeEngine(selected_nick="Anna", status="already")
            blk = MarkMessaged(pre_delay_ms=0)
            result = await blk.execute("—", None, eng)
            return result, eng
        result, eng = run(go())
        self.assertEqual(result, ActionResult.OK)
        self.assertTrue(any("already" in m.lower() for m, _ in eng.messages))

    def test_person_not_in_list_fails(self):
        async def go():
            eng = FakeEngine(selected_nick="Ghost", status="missing")
            blk = MarkMessaged(pre_delay_ms=0)
            result = await blk.execute("—", None, eng)
            return result, eng
        result, eng = run(go())
        self.assertEqual(result, ActionResult.FAIL)
        self.assertTrue(any("not in the People list" in m for m, _ in
                            eng.messages))

    def test_read_error_fails(self):
        async def go():
            eng = FakeEngine(selected_nick="Anna", status="error")
            blk = MarkMessaged(pre_delay_ms=0)
            return await blk.execute("—", None, eng)
        self.assertEqual(run(go()), ActionResult.FAIL)

    def test_no_saved_nick_fails_without_marking(self):
        async def go():
            eng = FakeEngine(selected_nick="")
            blk = MarkMessaged(pre_delay_ms=0)
            result = await blk.execute("—", None, eng)
            return result, eng
        result, eng = run(go())
        self.assertEqual(result, ActionResult.FAIL)
        self.assertEqual(eng.marked_calls, [])
        self.assertTrue(any("memory" in m.lower() for m, _ in eng.messages))

    def test_no_engine_fails(self):
        async def go():
            blk = MarkMessaged(pre_delay_ms=0)
            return await blk.execute("—", None, None)
        self.assertEqual(run(go()), ActionResult.FAIL)

    def test_serializes_cleanly(self):
        blk = MarkMessaged(pre_delay_ms=250)
        d = blk.to_dict()
        self.assertEqual(d["block_id"], "MARK_MESSAGED")
        self.assertTrue(MarkMessaged(**{k: v for k, v in d.items()
                                        if k != "block_id"}).enabled)


# ── the engine method (real memory) ──────────────────────────────
class TestEngineMarkMethod(unittest.TestCase):
    def test_marks_a_new_person_and_emits_live_update(self):
        async def go():
            async with MemHarness() as mem:
                await seed(mem, rec("Anna"), rec("Bella", messaged=True))
                eng = ActionEngine(cdp=None, memory=mem, criteria=None)
                marked = []
                eng.person_marked.connect(lambda nick: marked.append(nick))
                status = await eng.mark_person_messaged("Anna")
                rows = {u.nick: u for u in await mem.get_all()}
                return status, rows, marked
        status, rows, marked = in_tmp_cwd(go)
        self.assertEqual(status, "ok")
        self.assertTrue(rows["Anna"].messaged)
        self.assertEqual(marked, ["Anna"])

    def test_already_done_is_idempotent(self):
        async def go():
            async with MemHarness() as mem:
                await seed(mem, rec("Cara", messaged=True))
                eng = ActionEngine(cdp=None, memory=mem, criteria=None)
                marked = []
                eng.person_marked.connect(lambda nick: marked.append(nick))
                status = await eng.mark_person_messaged("Cara")
                return status, marked
        status, marked = in_tmp_cwd(go)
        self.assertEqual(status, "already")
        self.assertEqual(marked, [], "no live update for a no-op")

    def test_unknown_person_is_missing(self):
        async def go():
            async with MemHarness() as mem:
                await seed(mem, rec("Anna"))
                eng = ActionEngine(cdp=None, memory=mem, criteria=None)
                return await eng.mark_person_messaged("Ghost")
        self.assertEqual(in_tmp_cwd(go), "missing")


# ── engine flow ──────────────────────────────────────────────────
class TestEngineFlow(unittest.TestCase):
    def test_standalone_stack_marks_the_picked_person(self):
        """Pick Person chooses one person, Mark flips exactly that one."""
        async def go():
            async with MemHarness() as mem:
                await seed(mem, rec("Cara", messaged=True))
                take = TakePerson(pick_mode="random_done")
                mark = MarkMessaged(pre_delay_ms=0)
                eng = ActionEngine(cdp=None, memory=mem, criteria=None)
                eng._stack = [take, mark]
                steps = []
                eng.step_started.connect(
                    lambda idx, bid, nick: steps.append(bid))
                await eng.execute(None)
                rows = {u.nick: u for u in await mem.get_all()}
                return eng.selected_nick, steps, rows
        nick, steps, rows = in_tmp_cwd(go)
        self.assertEqual(nick, "Cara")
        self.assertIn("MARK_MESSAGED", steps)
        self.assertTrue(rows["Cara"].messaged,
                        "already-Done person stays Done (idempotent)")

    def test_no_match_cycle_ends_like_an_empty_queue(self):
        """Pick Person (random New) with no New person left must not run
        the Mark block against a stale selection — and a Repeat Loop must
        stop instead of looping."""
        async def go():
            async with MemHarness() as mem:
                await seed(mem, rec("Cara", messaged=True))
                take = TakePerson(pick_mode="random_new")
                mark = MarkMessaged(pre_delay_ms=0)
                eng = ActionEngine(cdp=None, memory=mem, criteria=None)
                eng._stack = [take, mark]
                eng._repeat_cycles = lambda: 10   # pretend a Repeat Loop
                logs = []
                eng.log_msg.connect(lambda m: logs.append(m))
                steps = []
                eng.step_started.connect(
                    lambda idx, bid, nick: steps.append(bid))
                await eng.execute(None)
                rows = {u.nick: u for u in await mem.get_all()}
                return steps, rows, logs
        steps, rows, logs = in_tmp_cwd(go)
        self.assertNotIn("MARK_MESSAGED", steps,
                         "no person matched → nothing may be marked")
        self.assertTrue(rows["Cara"].messaged,
                        "the Done person must stay untouched")
        self.assertTrue(any("Pick Person found no one" in m for m in logs))

    def test_nick_from_pick_person_is_marked_in_a_queue_mode_stack(self):
        """In a stack that also drives the queue, Mark marks the MEMORY
        person (picked once per cycle), never the queued user of a step."""
        async def go():
            async with MemHarness() as mem:
                await seed(mem, rec("Anna"), rec("Bella"))
                take = TakePerson(pick_mode="order_first")
                mark = MarkMessaged(pre_delay_ms=0)
                eng = ActionEngine(cdp=None, memory=mem, criteria=None)
                eng._stack = [take, mark]
                marked = []
                eng.person_marked.connect(lambda nick: marked.append(nick))
                await eng.execute(None)
                rows = {u.nick: u for u in await mem.get_all()}
                return eng.selected_nick, rows, marked
        nick, rows, marked = in_tmp_cwd(go)
        self.assertIn(nick, {"Anna", "Bella"})
        self.assertTrue(rows[nick].messaged)


if __name__ == "__main__":
    unittest.main(verbosity=2)
