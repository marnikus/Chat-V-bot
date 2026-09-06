"""Pick Person block — pick a saved person and remember its nick as {{nick}}.

FEATURE —
  * a Pick Person (TAKE_PERSON) block chooses a person from the People list
    by a radio rule and remembers the nick (engine.selected_nick), which
    every later {{nick}} field resolves to;
  * rules: any RANDOM un-messaged (Status New), any RANDOM already-messaged
    (Status Done), or exactly the person with Order (#) = 1;
  * the block itself never clicks anything;
  * when the rule has no matching person it warns and skips, leaving any
    previous selection untouched;
  * engine runs it once per cycle (Repeat Loop re-picks each cycle), never
    once per queued user.

Run with:  python3 tests/test_take_person.py
"""

import asyncio
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from actions.base_action import BaseAction, ActionResult  # noqa: E402
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


class Consumer(BaseAction):
    """Records what its {{nick}}-bearing match_text looked like when it ran."""
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


async def pin_first_seen(mem, nick, iso):
    await mem._db.execute(
        "UPDATE users SET first_seen=? WHERE nick=?", (iso, nick))
    await mem._db.commit()


# ── the pick rules in isolation ──────────────────────────────────
class FakeEngine:
    """queue_order returns exactly the order it was given (the # column)."""
    def __init__(self, order):
        self._order = list(order)

    def queue_order(self, rows):
        return list(self._order)


class TestPickRules(unittest.TestCase):
    async def _rows(self):
        async with MemHarness() as mem:
            await seed(mem, rec("Anna"), rec("Bella"),
                       rec("Cara", messaged=True))
            return await mem.get_all()

    def test_random_new_returns_a_new_person(self):
        async def go():
            rows = await self._rows()
            blk = TakePerson()
            nick = blk.choose(rows, FakeEngine([]))
            return nick
        for _ in range(10):
            self.assertIn(run(go()), {"Anna", "Bella"})

    def test_random_done_returns_a_done_person(self):
        async def go():
            rows = await self._rows()
            blk = TakePerson(pick_mode="random_done")
            return blk.choose(rows, FakeEngine([]))
        for _ in range(10):
            self.assertEqual(run(go()), "Cara")

    def test_order_first_is_exactly_queue_order_number_1(self):
        async def go():
            rows = await self._rows()
            # queue_order is the # column; #1 = its first nick
            blk = TakePerson(pick_mode="order_first")
            return blk.choose(rows, FakeEngine(["Bella", "Anna"]))
        self.assertEqual(run(go()), "Bella")

    def test_empty_pool_returns_none(self):
        async def go():
            async with MemHarness() as mem:
                await seed(mem, rec("Cara", messaged=True))
                rows = await mem.get_all()
                return (TakePerson().choose(rows, FakeEngine([])),
                        TakePerson(pick_mode="random_done").choose(
                            rows, FakeEngine([])))
        new_none, done_nick = run(go())
        self.assertIsNone(new_none)
        self.assertEqual(done_nick, "Cara")

    def test_default_mode_is_random_new(self):
        self.assertEqual(TakePerson().pick_mode, "random_new")

    def test_settings_round_trip(self):
        blk = TakePerson(pick_mode="order_first")
        d = blk.to_dict()
        again = TakePerson(**{k: v for k, v in d.items()
                              if k != "block_id"})
        self.assertEqual(again.pick_mode, "order_first")

    def test_schema_exposes_pick_mode(self):
        schema = TakePerson().config_schema()
        self.assertIn("pick_mode", schema)
        self.assertEqual(schema["pick_mode"]["type"], "select")


# ── engine integration ───────────────────────────────────────────
class TestEnginePickPerson(unittest.TestCase):
    def test_random_new_sets_nick_and_feeds_later_nick_fields(self):
        async def go():
            async with MemHarness() as mem:
                await seed(mem, rec("Anna"), rec("Bella"),
                           rec("Cara", messaged=True))
                take = TakePerson()
                consumer = Consumer(match_text="hi {{nick}}")
                eng = ActionEngine(cdp=None, memory=mem, criteria=None)
                eng._stack = [take, consumer]
                await eng.execute(None)
                return eng.selected_nick, consumer.seen
        nick, seen = in_tmp_cwd(go)
        self.assertIn(nick, {"Anna", "Bella"})
        # ran for each queued New person, but the pick happened ONCE (the
        # same remembered nick in every iteration, not re-randomized)
        self.assertEqual(len(seen), 2)
        self.assertEqual({s for _, s in seen}, {"hi " + nick})
        # nothing was clicked by the block itself
        self.assertTrue(all(u in {"Anna", "Bella"} for u, _ in seen))

    def test_random_done_works_in_a_standalone_stack(self):
        async def go():
            async with MemHarness() as mem:
                await seed(mem, rec("Cara", messaged=True))
                take = TakePerson(pick_mode="random_done")
                consumer = Consumer(match_text="to {{nick}}")
                eng = ActionEngine(cdp=None, memory=mem, criteria=None)
                eng._stack = [take, consumer]
                await eng.execute(None)
                return eng.selected_nick, consumer.seen
        nick, seen = in_tmp_cwd(go)
        self.assertEqual(nick, "Cara")
        self.assertEqual(seen, [("—", "to Cara")],
                         "standalone run remembers the picked Done person")

    def test_order_first_picks_exactly_number_1(self):
        async def go():
            async with MemHarness() as mem:
                await seed(mem, rec("Anna"), rec("Bella"),
                           rec("Cara", messaged=True))
                await pin_first_seen(mem, "Anna", "2026-09-01T10:00:00")
                await pin_first_seen(mem, "Bella", "2026-09-02T10:00:00")
                take = TakePerson(pick_mode="order_first")
                consumer = Consumer(match_text="msg {{nick}}")
                eng = ActionEngine(cdp=None, memory=mem, criteria=None)
                expected = eng.queue_order(await mem.get_all())[0]
                self.assertEqual(expected, "Bella",
                                 "precondition: #1 is Bella")
                eng._stack = [take, consumer]
                await eng.execute(None)
                return eng.selected_nick, consumer.seen
        nick, seen = in_tmp_cwd(go)
        self.assertEqual(nick, "Bella")
        self.assertEqual({s for _, s in seen}, {"msg Bella"})

    def test_no_match_warns_and_skips_without_clearing_selection(self):
        async def go():
            async with MemHarness() as mem:
                # One New person, NO Done person: a random_done block cannot
                # match. A preceding order_first block already remembered
                # "Anna" in THIS run — the no-match must keep it.
                await seed(mem, rec("Anna"))
                take_first = TakePerson(pick_mode="order_first")
                take_done = TakePerson(pick_mode="random_done")
                consumer = Consumer(match_text="go {{nick}}")
                eng = ActionEngine(cdp=None, memory=mem, criteria=None)
                logs = []
                eng.log_msg.connect(lambda m: logs.append(m))
                eng._stack = [take_first, take_done, consumer]
                await eng.execute(None)
                return (eng.selected_nick, consumer.seen, logs)
        nick, seen, logs = in_tmp_cwd(go)
        self.assertEqual(nick, "Anna",
                         "a no-match rule must NOT clear a nick remembered "
                         "earlier in the same run")
        self.assertTrue(seen, "the run still continues")
        self.assertTrue(any("already-messaged" in m and "no " in m
                            for m in logs),
                        "a warning must be logged")

    def test_disabled_pick_block_does_nothing(self):
        async def go():
            async with MemHarness() as mem:
                await seed(mem, rec("Anna"))
                take = TakePerson()
                take.enabled = False
                eng = ActionEngine(cdp=None, memory=mem, criteria=None)
                eng._stack = [take]
                await eng.execute(None)
                return eng.selected_nick
        nick = in_tmp_cwd(go)
        self.assertEqual(nick, "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
