"""Click User "Respect the Order (#) column" checkbox.

FEATURE — a Click User block may request that a run process its Status-New
people strictly in the Order (#) column sequence (#1 first, then #2 … N) —
the exact order the People table derives from `ActionEngine.queue_order` —
instead of whichever people/order the page happened to show that run
(the effectively-random first New person under scroll-only seek, or the
partial page-visible subset under collect).

  * checkbox OFF (default)  — behaviour is identical to today;
  * checkbox ON             — the engine replaces the per-cycle queue with
    the current un-messaged People rows in Order (#) sequence. Every
    Status-New person is still processed; people whose click fails (not on
    the page right now) are simply retried by a later cycle/run, exactly
    like any other per-person failure. An EMPTY queue stays empty — when
    the page had nobody to click, memory-only rows must not turn into a run
    of failing clicks.

Run with:  python3 tests/test_click_user_order.py
"""

import asyncio
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from actions.base_action import BaseAction, ActionResult  # noqa: E402
from actions.click_user import ClickUser  # noqa: E402
from actions.scroll_parse import ScrollParse  # noqa: E402
from backend.action_engine import ActionEngine  # noqa: E402
from backend.criteria_engine import CriteriaEngine  # noqa: E402
from backend.user_memory import UserMemory, UserRecord  # noqa: E402
from tests.test_collect_visual_and_live_refresh import HighlightCDP  # noqa: E402
from tests.test_scroll_parse_pipeline import person  # noqa: E402


def run(coro):
    return asyncio.run(coro)


class RecordingClick(BaseAction):
    """Stands in for CLICK_USER: OK per user, records the nick order.

    Mirrors the real block's `respect_order` setting so the engine can read
    it (the real ClickUser needs a real page to click, impossible here).
    """
    block_id = "CLICK_USER"
    name = "Click User"
    icon = "👤"

    def __init__(self, respect_order=False, enabled=True, **kw):
        super().__init__(pre_delay_ms=0)
        self.respect_order = bool(respect_order)
        self.enabled = bool(enabled)
        self.calls = []

    async def execute(self, user_nick, cdp, engine=None):
        self.calls.append(user_nick)
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


def in_tmp_cwd(coro_fn):
    """Run a coroutine with cwd in a throwaway dir (the tracer writes logs/)."""
    cwd = os.getcwd()
    os.chdir(tempfile.mkdtemp())
    try:
        return run(coro_fn())
    finally:
        os.chdir(cwd)


def engine_for(mem, cdp):
    return ActionEngine(cdp=cdp, memory=mem, criteria=None)


# ── the block setting itself ─────────────────────────────────────
class TestBlockSetting(unittest.TestCase):
    def test_default_is_off(self):
        self.assertFalse(ClickUser().respect_order)

    def test_checkbox_in_schema(self):
        schema = ClickUser().config_schema()
        self.assertIn("respect_order", schema)
        self.assertEqual(schema["respect_order"]["type"], "checkbox")
        self.assertFalse(schema["respect_order"]["default"])

    def test_to_dict_round_trips(self):
        for value in (True, False):
            blk = ClickUser(respect_order=value)
            self.assertEqual(blk.to_dict()["respect_order"], value)
        blk = ClickUser()
        blk.respect_order = True
        self.assertTrue(ClickUser(**blk.to_dict()).respect_order)


# ── seek mode: page order vs Order (#) column order ──────────────
# Page shows Dana first, then Cara, Bella … Anna LAST; the # column of the
# enabled Scroll & Parse block is alphabetical: Anna=#1 … Dana=#4.
PAGES = [[person("Dana"), person("Cara")],
         [person("Bella"), person("Boris", female=False)],
         [person("Anna")]]


def scroll_block(**over):
    kw = dict(scroll_only=True, scroll_pause_ms=0, load_timeout_ms=20,
              min_new_users=0, pre_delay_ms=0, confirm_pause_ms=0,
              highlight_ms=0, highlight_enabled=True,
              filter_female="yes", filter_registered="any", filter_guest="any",
              filter_anonymous="any")
    kw.update(over)
    return ScrollParse(**kw)


class TestRespectOrderSeekMode(unittest.TestCase):
    async def _run(self, mem, click):
        cdp = HighlightCDP(PAGES, page_height=100)
        eng = engine_for(mem, cdp)
        eng._stack = [scroll_block(), click]
        await eng.execute(None)
        rows = {u.nick: u for u in await mem.get_all()}
        return cdp, rows

    def test_off_clicks_the_first_new_person_the_page_shows(self):
        """Unchanged behaviour: seek stops at Dana (page order), not #1."""

        async def go():
            async with MemHarness() as mem:
                for nick in ("Anna", "Bella", "Cara", "Dana"):
                    await mem.upsert_user(
                        UserRecord(nick=nick, gender="female", guest=True))
                click = RecordingClick()
                await self._run(mem, click)
                return click.calls

        calls = in_tmp_cwd(go)
        self.assertEqual(calls, ["Dana"],
                         "OFF must keep messaging the single found person")

    def test_on_runs_everyone_in_order_column_sequence(self):
        async def go():
            async with MemHarness() as mem:
                for nick in ("Anna", "Bella", "Cara", "Dana"):
                    await mem.upsert_user(
                        UserRecord(nick=nick, gender="female", guest=True))
                click = RecordingClick(respect_order=True)
                cdp, rows = await self._run(mem, click)
                return click.calls, rows, cdp.scrolls

        calls, rows, _ = in_tmp_cwd(go)
        self.assertEqual(calls, ["Anna", "Bella", "Cara", "Dana"],
                         "#1 must be clicked first even though the page shows "
                         "Dana first; everyone is still processed")
        self.assertTrue(all(u.messaged for u in rows.values()),
                        "each processed person must be marked messaged")

    def test_on_messaged_people_are_excluded(self):
        """Status-New only: Cara is already Done, so she has no # and no run."""
        async def go():
            async with MemHarness() as mem:
                for nick in ("Anna", "Bella", "Cara", "Dana"):
                    await mem.upsert_user(
                        UserRecord(nick=nick, gender="female", guest=True))
                await mem.mark_messaged("Cara")
                click = RecordingClick(respect_order=True)
                await self._run(mem, click)
                return click.calls

        calls = in_tmp_cwd(go)
        self.assertEqual(calls, ["Anna", "Bella", "Dana"])

    def test_on_disabled_click_user_has_no_effect(self):
        """Only an ENABLED Click User with the checkbox may reorder."""
        async def go():
            async with MemHarness() as mem:
                for nick in ("Anna", "Bella", "Cara", "Dana"):
                    await mem.upsert_user(
                        UserRecord(nick=nick, gender="female", guest=True))
                off_disabled = RecordingClick(respect_order=True, enabled=False)
                plain = RecordingClick(respect_order=False)
                cdp = HighlightCDP(PAGES, page_height=100)
                eng = engine_for(mem, cdp)
                eng._stack = [scroll_block(), off_disabled, plain]
                await eng.execute(None)
                return off_disabled.calls, plain.calls

        disabled_calls, plain_calls = in_tmp_cwd(go)
        self.assertEqual(disabled_calls, [])
        self.assertEqual(plain_calls, ["Dana"],
                         "OFF click user keeps the seek-mode single hit")

    def test_on_empty_page_stays_empty(self):
        """Nobody on the page → no click storm from memory-only people."""
        async def go():
            async with MemHarness() as mem:
                # Waiting, but present on NO page of the current list.
                await mem.upsert_user(
                    UserRecord(nick="Offline", gender="female", guest=True))
                click = RecordingClick(respect_order=True)
                cdp = HighlightCDP(PAGES, page_height=100)
                eng = engine_for(mem, cdp)
                eng._stack = [scroll_block(), click]
                outcome = await eng.execute(None)
                return click.calls, outcome

        calls, _ = in_tmp_cwd(go)
        self.assertEqual(calls, [],
                         "an absent-only queue must not be clicked into")

    def test_on_repeat_loop_ends_cleanly_after_backlog_done(self):
        async def go():
            async with MemHarness() as mem:
                for nick in ("Anna", "Bella", "Cara", "Dana"):
                    await mem.upsert_user(
                        UserRecord(nick=nick, gender="female", guest=True))
                click = RecordingClick(respect_order=True)
                cdp = HighlightCDP(PAGES, page_height=100)
                eng = engine_for(mem, cdp)
                eng._stack = [scroll_block(), click]
                eng._repeat_cycles = lambda: 4   # pretend a Repeat Loop marker
                await eng.execute(None)
                return click.calls

        calls = in_tmp_cwd(go)
        self.assertEqual(calls, ["Anna", "Bella", "Cara", "Dana"],
                         "a Repeat Loop must stop once no Status-New person "
                         "is left — no re-messaging or empty cycles")


# ── no Scroll & Parse block: get_queue path ──────────────────────
class TestRespectOrderMemoryQueue(unittest.TestCase):
    def test_on_uses_the_stable_column_order(self):
        """Without Scroll & Parse the # order is newest-first, nick A–Z on
        ties — so equal first_seen rows run alphabetically, not by DB row."""
        async def go():
            async with MemHarness() as mem:
                for nick in ("Zoe", "Anna", "Mia"):
                    await mem.upsert_user(
                        UserRecord(nick=nick, gender="female", guest=True))
                # Pin ALL three to one first_seen so the raw SQL queue order
                # (no tie-break) is free to differ from the # column order.
                for nick in ("Zoe", "Anna", "Mia"):
                    await mem._db.execute(
                        "UPDATE users SET first_seen='2026-09-06T10:00:00' "
                        "WHERE nick=?", (nick,))
                await mem._db.commit()
                click = RecordingClick(respect_order=True)
                cdp = HighlightCDP([[]], page_height=100)  # unused: no scroll
                eng = engine_for(mem, cdp)
                # The # column BEFORE the run — the order it promises.
                column = eng.queue_order(await mem.get_all())
                eng._stack = [click]
                await eng.execute(None)
                return click.calls, column

        calls, column = in_tmp_cwd(go)
        self.assertEqual(calls, list(column),
                         "the run must follow the # column exactly")
        self.assertEqual(calls, ["Anna", "Mia", "Zoe"],
                         "equal timestamps break ties A–Z, never flickering")


# ── collect mode: partial page ≠ full list ───────────────────────
class TestRespectOrderCollectMode(unittest.TestCase):
    def test_on_queues_stored_new_people_ranked_with_the_seen_ones(self):
        """The scroll sees only the current page subset; the #-order queue
        ranks the whole Status-New list, keeping the seen people in order."""
        async def go():
            async with MemHarness() as mem:
                # 4 waiting; page shows 3 of them, sorted #-order anyway.
                for nick in ("Anna", "Bella", "Cara", "Dana"):
                    await mem.upsert_user(
                        UserRecord(nick=nick, gender="female", guest=True))
                await mem.mark_messaged("Anna")     # not waiting any more
                click = RecordingClick(respect_order=True)
                blk = scroll_block(scroll_only=False)
                cdp = HighlightCDP(PAGES, page_height=100)
                eng = engine_for(mem, cdp)
                eng._stack = [blk, click]
                await eng.execute(None)
                rows = {u.nick: u for u in await mem.get_all()}
                return click.calls, rows

        calls, rows = in_tmp_cwd(go)
        # # column (enabled Scroll & Parse → A–Z among un-messaged):
        # Bella #1, Cara #2, Dana #3.  Anna is messaged → excluded.
        self.assertEqual(calls, ["Bella", "Cara", "Dana"])
        self.assertTrue(rows["Bella"].messaged and rows["Cara"].messaged
                        and rows["Dana"].messaged)


if __name__ == "__main__":
    unittest.main(verbosity=2)
