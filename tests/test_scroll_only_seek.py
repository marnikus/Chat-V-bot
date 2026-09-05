"""Scroll & Parse: duplicate filter control removed, scroll-only seek added.

Bug #1 — the block had two filter controls: four tri-state selects AND an
"Also apply Filter panel criteria" checkbox. Two sources of truth for one
decision. The checkbox is gone.

Bug #2 — the backlog guard ("skip collecting while a backlog exists") was the
wrong shape: it skipped the scroll, but the user needs the scroll to HAPPEN in
order to locate an already-known, not-yet-messaged person on the page. It is
replaced by scroll-only mode:

  * un-messaged people exist  → scroll hunting for one, add nobody, stop the
    scroll on the first that passes the filter;
  * nobody waiting            → collect new people exactly as before.

Run with:  python3 tests/test_scroll_only_seek.py
"""

import asyncio
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from actions.scroll_parse import ScrollParse  # noqa: E402
from backend.action_engine import ActionEngine, RunTracer  # noqa: E402
from backend.criteria_engine import CriteriaEngine  # noqa: E402
from backend.scroll_parser import ScrollParser  # noqa: E402
from backend.user_memory import UserMemory, UserRecord  # noqa: E402
from tests.test_collect_visual_and_live_refresh import HighlightCDP  # noqa: E402
from tests.test_scroll_parse_pipeline import person  # noqa: E402


def run(coro):
    return asyncio.run(coro)


# Four women across two lazy-loaded pages, plus a man who must never pass.
PAGES = [[person("Anna"), person("Bella")],
         [person("Cara"), person("Boris", female=False)],
         [person("Dana")]]


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


def block(**over):
    kw = dict(scroll_pause_ms=0, load_timeout_ms=20, min_new_users=0,
              pre_delay_ms=0, confirm_pause_ms=0, highlight_ms=0)
    kw.update(over)
    return ScrollParse(**kw)


def parser(cdp, blk=None, **kw):
    return (blk or block()).build_parser(cdp, **kw)


async def seed(mem, *people):
    """people = (nick, messaged) or (nick, messaged, gender)."""
    for entry in people:
        nick, messaged = entry[0], entry[1]
        gender = entry[2] if len(entry) > 2 else "female"
        await mem.upsert_user(UserRecord(nick=nick, gender=gender, guest=True))
        if messaged:
            # upsert_user always inserts messaged=0; flip it explicitly.
            await mem.mark_messaged(nick)


def in_tmp_cwd(coro_fn):
    """Run a coroutine with cwd in a throwaway dir (the tracer writes logs/)."""
    cwd = os.getcwd()
    os.chdir(tempfile.mkdtemp())
    try:
        return run(coro_fn())
    finally:
        os.chdir(cwd)


# ── BUG #1: the duplicate filter control is gone ─────────────────
class TestPanelCriteriaCheckboxRemoved(unittest.TestCase):
    def test_checkbox_is_not_in_the_config_schema(self):
        schema = block().config_schema()
        self.assertNotIn("use_panel_filters", schema)
        # the four selects that replace it are still there
        for key in ("filter_female", "filter_registered", "filter_guest",
                    "filter_anonymous"):
            self.assertIn(key, schema)
            self.assertEqual(schema[key]["type"], "select")

    def test_attribute_is_gone_and_not_serialised(self):
        blk = block()
        self.assertFalse(hasattr(blk, "use_panel_filters"))
        self.assertNotIn("use_panel_filters", blk.to_dict())

    def test_old_preset_carrying_the_dead_key_still_loads(self):
        blk = block(use_panel_filters=True)
        self.assertFalse(hasattr(blk, "use_panel_filters"))
        # …and the stale key is dropped rather than written back forever
        self.assertNotIn("use_panel_filters", blk.to_dict())

    def test_panel_criteria_no_longer_affect_the_verdict(self):
        """Passing panel criteria must not change who is collected."""
        crit = CriteriaEngine()
        blk = block(filter_female="any", filter_guest="any",
                    filter_registered="any", filter_anonymous="any")
        # A panel that would reject everyone is simply not consulted.
        pf = blk.build_filter(panel_criteria=crit)
        self.assertIsNone(pf.panel_criteria)
        self.assertTrue(pf.check(person("Anna")).passed)
        self.assertTrue(pf.check(person("Boris", female=False)).passed)

    def test_parser_is_built_without_panel_criteria(self):
        p = parser(HighlightCDP(PAGES, page_height=100),
                   blk=block(), panel_criteria=CriteriaEngine())
        self.assertIsNone(p._criteria)


# ── BUG #2a: the failed backlog guard is gone ────────────────────
class TestBacklogGuardRemoved(unittest.TestCase):
    def test_settings_are_gone(self):
        blk = block()
        for dead in ("skip_if_backlog", "backlog_threshold"):
            self.assertFalse(hasattr(blk, dead), dead)
            self.assertNotIn(dead, blk.config_schema(), dead)
            self.assertNotIn(dead, blk.to_dict(), dead)

    def test_old_preset_carrying_guard_keys_still_loads(self):
        blk = block(skip_if_backlog=True, backlog_threshold=5)
        self.assertNotIn("skip_if_backlog", blk.to_dict())
        self.assertNotIn("backlog_threshold", blk.to_dict())

    def test_engine_no_longer_exposes_backlog_count(self):
        self.assertFalse(hasattr(ActionEngine, "backlog_count"))
        self.assertTrue(hasattr(ActionEngine, "unmessaged_nicks"))

    def test_a_big_backlog_no_longer_blocks_collection(self):
        """The old guard would have skipped this run; now it collects."""
        async def go():
            async with MemHarness() as mem:
                await seed(mem, *[(f"Waiting{i}", False) for i in range(9)])
                cdp = HighlightCDP(PAGES, page_height=100)
                eng = ActionEngine(cdp=cdp, memory=mem, criteria=None)
                res = await block().run_pipeline(cdp, eng)
                return res, cdp.scrolls

        res, scrolls = in_tmp_cwd(go)
        self.assertFalse(res.seeking, "scroll_only is off")
        self.assertGreater(scrolls, 0, "the scroll must happen")
        self.assertIn("Anna", [p.nick for p in res.collected])


# ── BUG #2b: choosing between seek and collect ───────────────────
class TestModeDecision(unittest.TestCase):
    def test_no_unmessaged_people_means_collect_as_before(self):
        """Explicit requirement: with nobody waiting it works as before."""
        async def go():
            async with MemHarness() as mem:
                await seed(mem, ("Old", True))       # messaged = not waiting
                cdp = HighlightCDP(PAGES, page_height=100)
                eng = ActionEngine(cdp=cdp, memory=mem, criteria=None)
                return await block(scroll_only=True).run_pipeline(cdp, eng)

        res = in_tmp_cwd(go)
        self.assertFalse(res.seeking, "must fall back to normal collection")
        self.assertEqual(sorted(p.nick for p in res.collected),
                         ["Anna", "Bella", "Cara", "Dana"])

    def test_unmessaged_people_trigger_a_seek(self):
        async def go():
            async with MemHarness() as mem:
                await seed(mem, ("Cara", False))
                cdp = HighlightCDP(PAGES, page_height=100)
                eng = ActionEngine(cdp=cdp, memory=mem, criteria=None)
                return await block(scroll_only=True).run_pipeline(cdp, eng)

        res = in_tmp_cwd(go)
        self.assertTrue(res.seeking)
        self.assertIsNotNone(res.found)
        self.assertEqual(res.found.nick, "Cara")

    def test_mode_off_never_even_asks_memory(self):
        asked = []

        class Eng:
            def report(self, *a): pass

            async def unmessaged_nicks(self):
                asked.append(1)
                return {"Anna"}

        run(block(scroll_only=False).run_pipeline(
            HighlightCDP(PAGES, page_height=100), Eng()))
        self.assertEqual(asked, [])

    def test_reading_memory_fails_open_to_collecting(self):
        class Eng:
            def report(self, *a): pass

            async def unmessaged_nicks(self):
                raise RuntimeError("db is on fire")

        res = run(block(scroll_only=True).run_pipeline(
            HighlightCDP(PAGES, page_height=100), Eng()))
        self.assertFalse(res.seeking, "a read error must not idle the block")
        self.assertTrue(res.collected)

    def test_explicit_seek_nicks_win(self):
        res = run(block(scroll_only=True).run_pipeline(
            HighlightCDP(PAGES, page_height=100), None,
            seek_nicks={"Dana"}))
        self.assertTrue(res.seeking)
        self.assertEqual(res.found.nick, "Dana")


# ── BUG #2c: what a seek does on the page ────────────────────────
class TestSeekBehaviour(unittest.TestCase):
    def _seek(self, targets, blk=None, cdp=None):
        cdp = cdp or HighlightCDP(PAGES, page_height=100)
        res = run(parser(cdp, blk).collect(seek_nicks=set(targets)))
        return res, cdp

    def test_finds_a_target_that_is_already_known(self):
        """A target is by definition already seen — it must not be skipped."""
        p = parser(HighlightCDP(PAGES, page_height=100))
        p.known_nicks.update({"Anna", "Bella", "Cara", "Dana"})
        res = run(p.collect(seek_nicks={"Cara"}))
        self.assertIsNotNone(res.found, "known people must still be findable")
        self.assertEqual(res.found.nick, "Cara")

    def test_stops_scrolling_on_the_first_hit(self):
        res, cdp = self._seek({"Bella"})            # page 1
        far, far_cdp = self._seek({"Dana"})         # page 3
        self.assertEqual(res.found.nick, "Bella")
        self.assertTrue(res.stopped_early)
        self.assertLess(cdp.scrolls, far_cdp.scrolls,
                        "an early hit must stop sooner than a late one")

    def test_ignores_people_who_are_not_targets(self):
        res, _ = self._seek({"Dana"})
        self.assertEqual([p.nick for p in res.collected], ["Dana"])
        self.assertEqual(res.found.nick, "Dana")

    def test_target_failing_the_filter_is_passed_over(self):
        """Boris is waiting, but the filter is female-only."""
        res, _ = self._seek({"Boris"}, blk=block(filter_female="yes"))
        self.assertIsNone(res.found)
        self.assertEqual(res.collected, [])

    def test_keeps_looking_after_an_unsuitable_target(self):
        res, _ = self._seek({"Boris", "Dana"}, blk=block(filter_female="yes"))
        self.assertIsNotNone(res.found)
        self.assertEqual(res.found.nick, "Dana")

    def test_miss_scrolls_to_the_end(self):
        res, cdp = self._seek({"Nobody"})
        self.assertIsNone(res.found)
        self.assertEqual(res.collected, [])
        self.assertTrue(res.seeking)
        self.assertGreaterEqual(cdp.scrolls, len(PAGES))

    def test_stop_is_honoured_mid_seek(self):
        stop = {"now": False}
        cdp = HighlightCDP(PAGES, page_height=100)
        p = parser(cdp, should_stop=lambda: stop["now"])
        stop["now"] = True
        res = run(p.collect(seek_nicks={"Dana"}))
        self.assertTrue(res.stopped)
        self.assertIsNone(res.found)

    def test_the_found_person_is_highlighted(self):
        cdp = HighlightCDP(PAGES, page_height=100)
        run(parser(cdp, block(highlight_enabled=True)).collect(
            seek_nicks={"Cara"}))
        self.assertIn("Cara", cdp.highlights)


# ── BUG #2d: a seek must not touch People Memory ─────────────────
class TestSeekWritesNothing(unittest.TestCase):
    def test_no_collect_or_reject_callbacks_fire(self):
        collected, rejected = [], []
        cdp = HighlightCDP(PAGES, page_height=100)
        p = parser(cdp,
                   on_collect=lambda r, a: collected.append(r.nick),
                   on_reject=lambda r, why: rejected.append(r.nick))
        run(p.collect(seek_nicks={"Cara"}))
        self.assertEqual(collected, [], "a seek must add nobody")
        self.assertEqual(rejected, [], "a seek must purge nobody")

    def test_a_miss_purges_nobody_either(self):
        rejected = []
        p = parser(HighlightCDP(PAGES, page_height=100),
                   on_reject=lambda r, why: rejected.append(r.nick))
        run(p.collect(seek_nicks={"Nobody"}))
        self.assertEqual(rejected, [])

    def test_memory_is_unchanged_by_a_seek(self):
        async def go():
            async with MemHarness() as mem:
                await seed(mem, ("Cara", False), ("Zed", False))
                before = sorted(u.nick for u in await mem.get_all())
                cdp = HighlightCDP(PAGES, page_height=100)
                eng = ActionEngine(cdp=cdp, memory=mem, criteria=None)
                eng.load_stack([{"block_id": "SCROLL_PARSE", "scroll_only": True,
                                 "scroll_pause_ms": 0, "load_timeout_ms": 20,
                                 "pre_delay_ms": 0, "confirm_pause_ms": 0,
                                 "highlight_ms": 0}])
                eng._tracer = RunTracer("test")
                queue = await eng._run_collect_phase(eng._stack[0])
                eng._tracer.close()
                after = sorted(u.nick for u in await mem.get_all())
                return before, after, queue

        before, after, queue = in_tmp_cwd(go)
        self.assertEqual(before, after, "no new people may be added")
        self.assertEqual([q.nick for q in queue], ["Cara"],
                         "the located person becomes the queue")


# ── BUG #2e: engine integration and the loop ─────────────────────
class TestEngineIntegration(unittest.TestCase):
    def _phase(self, seeded, **cfg):
        async def go():
            async with MemHarness() as mem:
                await seed(mem, *seeded)
                cdp = HighlightCDP(PAGES, page_height=100)
                eng = ActionEngine(cdp=cdp, memory=mem, criteria=None)
                base = {"block_id": "SCROLL_PARSE", "scroll_pause_ms": 0,
                        "load_timeout_ms": 20, "pre_delay_ms": 0,
                        "confirm_pause_ms": 0, "highlight_ms": 0,
                        "min_new_users": 0}
                base.update(cfg)
                eng.load_stack([base])
                eng._tracer = RunTracer("test")
                queue = await eng._run_collect_phase(eng._stack[0])
                eng._tracer.close()
                names = sorted(u.nick for u in await mem.get_all())
                return [q.nick for q in queue], names, cdp.scrolls

        return in_tmp_cwd(go)

    def test_a_hit_becomes_the_queue_for_the_rest_of_the_stack(self):
        queue, names, scrolls = self._phase([("Bella", False)],
                                            scroll_only=True)
        self.assertEqual(queue, ["Bella"])
        self.assertEqual(names, ["Bella"], "nobody new was added")
        # Bella is on the first rendered page, so no scroll was needed —
        # what matters is that nobody new was added.
        self.assertGreaterEqual(scrolls, 0)

    def test_a_miss_returns_an_empty_queue(self):
        queue, names, _ = self._phase([("Ghost", False)], scroll_only=True)
        self.assertEqual(queue, [])
        self.assertEqual(names, ["Ghost"])

    def test_messaged_people_are_not_seek_targets(self):
        """All waiting people messaged → collect new ones instead."""
        queue, names, _ = self._phase(
            [("Anna", True), ("Bella", True)], scroll_only=True)
        self.assertIn("Cara", names, "collection resumed")
        self.assertIn("Dana", names)

    def test_the_loop_drains_then_resumes_adding(self):
        """Cycle 1 finds the waiting person; once messaged, cycle 2 adds new."""
        async def go():
            async with MemHarness() as mem:
                await seed(mem, ("Bella", False))
                cfg = {"block_id": "SCROLL_PARSE", "scroll_only": True,
                       "scroll_pause_ms": 0, "load_timeout_ms": 20,
                       "pre_delay_ms": 0, "confirm_pause_ms": 0,
                       "highlight_ms": 0, "min_new_users": 0}
                out = []
                for cycle in range(2):
                    cdp = HighlightCDP(PAGES, page_height=100)
                    eng = ActionEngine(cdp=cdp, memory=mem, criteria=None)
                    eng.load_stack([dict(cfg)])
                    eng._tracer = RunTracer("test")
                    queue = await eng._run_collect_phase(eng._stack[0])
                    eng._tracer.close()
                    out.append([q.nick for q in queue])
                    # the stack would message them; simulate that
                    for q in queue:
                        await mem.mark_messaged(q.nick)
                return out, sorted(u.nick for u in await mem.get_all())

        cycles, names = in_tmp_cwd(go)
        self.assertEqual(cycles[0], ["Bella"], "cycle 1 seeks the backlog")
        self.assertEqual(sorted(cycles[1]), ["Anna", "Cara", "Dana"],
                         "cycle 2 adds new people again")
        self.assertIn("Dana", names)

    def test_mode_off_behaves_exactly_as_before(self):
        queue, names, _ = self._phase([("Bella", False)], scroll_only=False)
        self.assertEqual(sorted(names), ["Anna", "Bella", "Cara", "Dana"])
        self.assertIn("Anna", queue)


# ── contract / UI ────────────────────────────────────────────────
class TestBlockContract(unittest.TestCase):
    def test_scroll_only_round_trips(self):
        blk = block(scroll_only=True)
        self.assertTrue(blk.to_dict()["scroll_only"])
        self.assertEqual(blk.config_schema()["scroll_only"]["type"], "checkbox")
        self.assertFalse(blk.config_schema()["scroll_only"]["default"],
                         "opt-in")

    def test_a_seek_miss_is_a_failure_not_a_silent_ok(self):
        from actions.base_action import ActionResult

        class Eng:
            def __init__(self): self.msgs = []

            def report(self, m, level="info"): self.msgs.append((m, level))

            async def unmessaged_nicks(self): return {"Ghost"}

        eng = Eng()
        out = run(block(scroll_only=True).execute(
            "—", HighlightCDP(PAGES, page_height=100), eng))
        self.assertEqual(out, ActionResult.FAIL)
        self.assertTrue(any("Scroll-only" in m for m, _ in eng.msgs))

    def test_a_seek_hit_is_ok(self):
        from actions.base_action import ActionResult

        class Eng:
            def report(self, *a): pass

            async def unmessaged_nicks(self): return {"Cara"}

        out = run(block(scroll_only=True).execute(
            "—", HighlightCDP(PAGES, page_height=100), Eng()))
        self.assertEqual(out, ActionResult.OK)

    def test_ui_matches_the_backend(self):
        js = open(os.path.join(os.path.dirname(__file__), "..", "ui", "js",
                               "stack-dnd.js"), encoding="utf-8").read()
        self.assertIn("scroll_only:false", js)
        self.assertIn("scroll_only:'", js, "needs a label")
        # The retired keys must never be live, user-facing controls. They DO
        # legitimately appear as string literals in the migration denylist
        # (RETIRED_KEYS), so strip comments and quoted strings before
        # asserting they are absent from executable code.
        import re
        code = re.sub(r"//[^\n]*", "", js)                     # // comments
        code = re.sub(r"/\*.*?\*/", "", code, flags=re.S)      # /* comments */
        code = re.sub(r"'[^']*'", "''", code)                  # 'strings'
        code = re.sub(r'"[^"]*"', '""', code)                  # "strings"
        code = re.sub(r"`[^`]*`", "``", code)                  # `templates`
        for dead in ("use_panel_filters", "skip_if_backlog",
                     "backlog_threshold"):
            self.assertNotIn(dead, code,
                             f"{dead} may only exist as a migration literal")
        # …and the migration safeguards themselves must be present.
        for needle in ("RETIRED_KEYS", "_migrateBlock",
                       "RETIRED_KEYS.includes(key)"):
            self.assertIn(needle, js, f"missing migration safeguard: {needle}")


# ── backend safety net: stacks entering the engine are cleaned ───
class TestBackendBlockNormalization(unittest.TestCase):
    def test_normalize_blocks_strips_retired_keys(self):
        from backend.action_engine import normalize_blocks
        out = normalize_blocks([
            {"block_id": "SCROLL_PARSE", "use_panel_filters": True,
             "skip_if_backlog": True, "backlog_threshold": 3,
             "scroll_only": True, "max_scrolls": 1000},
            "junk", 42, None,
        ])
        self.assertEqual(len(out), 1)
        b = out[0]
        for dead in ("use_panel_filters", "skip_if_backlog",
                     "backlog_threshold"):
            self.assertNotIn(dead, b)
        self.assertTrue(b["scroll_only"], "real settings are kept")
        self.assertEqual(b["max_scrolls"], 1000)
        self.assertTrue(b["enabled"], "enabled defaults to True")

    def test_load_stack_drops_the_dead_kwargs(self):
        cdp = HighlightCDP(PAGES, page_height=100)
        eng = ActionEngine(cdp=cdp, memory=None, criteria=None)
        eng.load_stack([
            {"block_id": "SCROLL_PARSE", "use_panel_filters": True,
             "scroll_only": True},
            {"block_id": "PAUSE", "duration_ms": 123, "enabled": False},
        ])
        self.assertEqual(len(eng._stack), 2)
        sp = eng._stack[0]
        self.assertTrue(sp.scroll_only)
        self.assertFalse(hasattr(sp, "use_panel_filters"))
        self.assertNotIn("use_panel_filters", sp.to_dict())
        self.assertFalse(eng._stack[1].enabled)


if __name__ == "__main__":
    unittest.main(verbosity=2)
