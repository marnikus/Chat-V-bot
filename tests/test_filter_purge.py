"""Regression tests: filtered-out people must never live in the list.

The reported bug: stop a run, start it again, and the list grows — including
men, despite a "must be female" filter.

Three causes, each covered here:
  A. the engine persisted ``result.all_people`` (everyone SEEN) instead of
     ``result.collected`` (everyone that PASSED), so rejected people were
     written straight into the users table;
  B. nothing ever removed a rejected person, so anything stored by (A) — or by
     an earlier run under a laxer filter — survived forever;
  C. Stop was only checked in the per-user loop, so pressing it mid-scroll let
     the parser run to completion and persist everything anyway.

Run with:  python3 tests/test_filter_purge.py
"""

import asyncio
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from actions.scroll_parse import ScrollParse  # noqa: E402
from backend.action_engine import ActionEngine  # noqa: E402
from backend.person_filter import PersonFilter  # noqa: E402
from backend.scroll_parser import ScrollParser  # noqa: E402
from backend.user_memory import UserMemory, UserRecord  # noqa: E402
from tests.test_collect_visual_and_live_refresh import HighlightCDP  # noqa: E402
from tests.test_scroll_parse_pipeline import person  # noqa: E402


def run(coro):
    return asyncio.run(coro)


MIXED = [[person("Anna"), person("Boris", female=False)],
         [person("Zoe"), person("Igor", female=False)]]


class MemHarness:
    """Real UserMemory on a throwaway DB."""

    def __init__(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.memory = UserMemory(os.path.join(self._tmp.name, "t.db"))

    async def __aenter__(self):
        await self.memory.init()
        return self.memory

    async def __aexit__(self, *exc):
        await self.memory.close()
        self._tmp.cleanup()

    def close(self):
        self._tmp.cleanup()


def stack(**over):
    cfg = {"block_id": "SCROLL_PARSE", "scroll_pause_ms": 0,
           "load_timeout_ms": 20, "min_new_users": 0, "pre_delay_ms": 0,
           "confirm_pause_ms": 0}
    cfg.update(over)
    return [cfg]


async def nicks_in(memory):
    return sorted(u.nick for u in await memory.get_all())


# ── CAUSE A ──────────────────────────────────────────────────────
class TestOnlyPassingPeopleArePersisted(unittest.TestCase):
    def test_rejected_people_are_never_stored(self):
        async def go():
            async with MemHarness() as mem:
                eng = ActionEngine(cdp=HighlightCDP(MIXED, page_height=100),
                                   memory=mem, criteria=None)
                eng.load_stack(stack())
                await eng.execute()
                return await nicks_in(mem)

        cwd = os.getcwd()
        os.chdir(tempfile.mkdtemp())
        try:
            self.assertEqual(run(go()), ["Anna", "Zoe"],
                             "men must never reach the users table")
        finally:
            os.chdir(cwd)

    def test_rerunning_does_not_grow_the_list(self):
        """The exact reported symptom: stop, re-run, list grows with men."""
        async def go():
            async with MemHarness() as mem:
                snapshots = []
                for _ in range(3):
                    eng = ActionEngine(
                        cdp=HighlightCDP(MIXED, page_height=100),
                        memory=mem, criteria=None)
                    eng.load_stack(stack(min_new_users=1))
                    await eng.execute()
                    snapshots.append(await nicks_in(mem))
                return snapshots

        cwd = os.getcwd()
        os.chdir(tempfile.mkdtemp())
        try:
            snaps = run(go())
        finally:
            os.chdir(cwd)
        for snap in snaps:
            self.assertNotIn("Boris", snap)
            self.assertNotIn("Igor", snap)
        self.assertLessEqual(len(snaps[-1]), 2)


# ── CAUSE B ──────────────────────────────────────────────────────
class TestRejectedPeopleArePurged(unittest.TestCase):
    def test_preexisting_rejected_records_are_destroyed(self):
        """Damage left by an earlier / laxer run must be cleaned up."""
        async def go():
            async with MemHarness() as mem:
                for nick, gender in (("Boris", "male"), ("Igor", "male"),
                                     ("Anna", "female")):
                    await mem.upsert_user(UserRecord(nick=nick, gender=gender,
                                                     guest=True))
                before = await nicks_in(mem)
                eng = ActionEngine(cdp=HighlightCDP(MIXED, page_height=100),
                                   memory=mem, criteria=None)
                removed = []
                eng.person_removed.connect(
                    lambda p: removed.append(json.loads(p)))
                eng.load_stack(stack())
                await eng.execute()
                return before, await nicks_in(mem), removed

        cwd = os.getcwd()
        os.chdir(tempfile.mkdtemp())
        try:
            before, after, removed = run(go())
        finally:
            os.chdir(cwd)
        self.assertEqual(before, ["Anna", "Boris", "Igor"])
        self.assertEqual(after, ["Anna", "Zoe"], "the list must SHRINK")
        self.assertEqual(sorted(r["nick"] for r in removed), ["Boris", "Igor"])
        self.assertTrue(all(r["reason"] for r in removed),
                        "each purge must say why")

    def test_tightening_the_filter_shrinks_the_list(self):
        async def go():
            async with MemHarness() as mem:
                # lax run: accept everyone
                eng = ActionEngine(cdp=HighlightCDP(MIXED, page_height=100),
                                   memory=mem, criteria=None)
                eng.load_stack(stack(filter_female="any", filter_guest="any",
                                     filter_registered="any",
                                     filter_anonymous="any"))
                await eng.execute()
                lax = await nicks_in(mem)
                # strict run: women only
                eng2 = ActionEngine(cdp=HighlightCDP(MIXED, page_height=100),
                                    memory=mem, criteria=None)
                eng2.load_stack(stack())
                await eng2.execute()
                return lax, await nicks_in(mem)

        cwd = os.getcwd()
        os.chdir(tempfile.mkdtemp())
        try:
            lax, strict = run(go())
        finally:
            os.chdir(cwd)
        self.assertIn("Boris", lax, "the lax run should have accepted men")
        self.assertEqual(strict, ["Anna", "Zoe"],
                         "tightening the filter must purge the men")

    def test_purge_can_be_disabled_but_they_are_still_not_added(self):
        async def go():
            async with MemHarness() as mem:
                await mem.upsert_user(UserRecord(nick="Boris", gender="male"))
                eng = ActionEngine(cdp=HighlightCDP(MIXED, page_height=100),
                                   memory=mem, criteria=None)
                eng.load_stack(stack(purge_rejected=False))
                await eng.execute()
                return await nicks_in(mem)

        cwd = os.getcwd()
        os.chdir(tempfile.mkdtemp())
        try:
            after = run(go())
        finally:
            os.chdir(cwd)
        self.assertIn("Boris", after, "purging was disabled, so he remains")
        self.assertNotIn("Igor", after, "but new rejects are never added")

    def test_reject_callback_fires_with_a_reason(self):
        cdp = HighlightCDP([[person("Anna"), person("Boris", female=False)]])
        seen = []
        parser = ScrollParser(cdp=cdp, pause_ms=0, poll_ms=1,
                              load_timeout_ms=20, person_filter=PersonFilter(),
                              confirm_pause_ms=0, highlight_enabled=False,
                              on_reject=lambda rec, why: seen.append(
                                  (rec.nick, why)) or True)
        res = run(parser.collect())
        self.assertEqual(seen, [("Boris", "not female")])
        self.assertEqual(res.purged, ["Boris"])
        self.assertEqual([p.nick for p in res.collected], ["Anna"])

    def test_a_failing_purge_never_kills_the_parse(self):
        def boom(rec, why):
            raise RuntimeError("db on fire")

        cdp = HighlightCDP([[person("Anna"), person("Boris", female=False)]])
        parser = ScrollParser(cdp=cdp, pause_ms=0, poll_ms=1,
                              load_timeout_ms=20, person_filter=PersonFilter(),
                              confirm_pause_ms=0, highlight_enabled=False,
                              on_reject=boom)
        res = run(parser.collect())
        self.assertEqual([p.nick for p in res.collected], ["Anna"])

    def test_engine_purge_survives_a_storage_failure(self):
        class Broken:
            async def delete_user(self, nick): raise RuntimeError("db down")

        eng = ActionEngine(cdp=None, memory=Broken(), criteria=None)
        self.assertFalse(run(eng.person_rejected(UserRecord(nick="B"), "nope")))

    def test_engine_purge_reports_only_real_deletions(self):
        class Mem:
            def __init__(self): self.hits = []
            async def delete_user(self, nick):
                self.hits.append(nick)
                return nick == "Boris"      # Igor was never stored

        mem = Mem()
        eng = ActionEngine(cdp=None, memory=mem, criteria=None)
        emitted = []
        eng.person_removed.connect(lambda p: emitted.append(json.loads(p)))
        self.assertTrue(run(eng.person_rejected(UserRecord(nick="Boris"), "x")))
        self.assertFalse(run(eng.person_rejected(UserRecord(nick="Igor"), "x")))
        self.assertEqual(mem.hits, ["Boris", "Igor"])
        self.assertEqual([e["nick"] for e in emitted], ["Boris"])


# ── CAUSE C ──────────────────────────────────────────────────────
class TestStopHaltsCollection(unittest.TestCase):
    def test_stop_interrupts_the_scroll_loop(self):
        pages = [[person(f"W{i}")] for i in range(40)]
        cdp = HighlightCDP(pages, page_height=10)
        flag = {"stop": False}
        parser = ScrollParser(cdp=cdp, pause_ms=0, poll_ms=1,
                              load_timeout_ms=20, person_filter=PersonFilter(),
                              confirm_pause_ms=0, highlight_enabled=False,
                              should_stop=lambda: flag["stop"],
                              on_collect=lambda r, c: flag.__setitem__(
                                  "stop", len(c) >= 3))
        res = run(parser.collect())
        self.assertTrue(res.stopped)
        self.assertLess(len(res.collected), 40)

    def test_stop_is_honoured_during_the_lazy_load_wait(self):
        """A stop must not have to wait out the full load timeout."""
        cdp = HighlightCDP([[person("Anna")], [person("Zoe")]], load_delay=99)
        parser = ScrollParser(cdp=cdp, pause_ms=0, poll_ms=1,
                              load_timeout_ms=5000,
                              person_filter=PersonFilter(),
                              confirm_pause_ms=0, highlight_enabled=False,
                              should_stop=lambda: True)
        res = run(parser.collect())
        self.assertTrue(res.stopped)

    def test_stopped_run_queues_nobody(self):
        async def go():
            async with MemHarness() as mem:
                pages = [[person(f"W{i}")] for i in range(30)]
                eng = ActionEngine(cdp=HighlightCDP(pages, page_height=10),
                                   memory=mem, criteria=None)
                eng.load_stack(stack(scroll_pause_ms=5))
                eng.person_found.connect(lambda p: eng.stop())
                await eng.execute()
                return await nicks_in(mem)

        cwd = os.getcwd()
        os.chdir(tempfile.mkdtemp())
        try:
            after = run(go())
        finally:
            os.chdir(cwd)
        self.assertLess(len(after), 30, "stop must cut the run short")

    def test_engine_exposes_the_stop_predicate(self):
        eng = ActionEngine(cdp=None, memory=None, criteria=None)
        self.assertFalse(eng.is_stopping())
        eng.stop()
        self.assertTrue(eng.is_stopping())


class TestBlockWiring(unittest.TestCase):
    def test_block_wires_both_engine_hooks(self):
        cdp = HighlightCDP([[person("Anna"), person("Boris", female=False)]])
        purged, added = [], []

        class Eng:
            criteria = None
            def report(self, m, l="info"): pass
            def is_stopping(self): return False
            async def person_collected(self, rec, coll): added.append(rec.nick)
            async def person_rejected(self, rec, why):
                purged.append((rec.nick, why))
                return True

        block = ScrollParse(scroll_pause_ms=0, load_timeout_ms=20,
                            min_new_users=0, pre_delay_ms=0,
                            confirm_pause_ms=0, highlight_enabled=False)
        run(block.run_pipeline(cdp, Eng()))
        self.assertEqual(added, ["Anna"])
        self.assertEqual(purged, [("Boris", "not female")])

    def test_purge_rejected_round_trips_through_presets(self):
        block = ScrollParse(purge_rejected=False)
        d = block.to_dict()
        self.assertIn("purge_rejected", d)
        self.assertIn("purge_rejected", block.config_schema())
        self.assertFalse(
            ScrollParse(**{k: v for k, v in d.items()
                           if k != "block_id"}).purge_rejected)
        self.assertTrue(ScrollParse().purge_rejected, "on by default")

    def test_disabled_purge_detaches_the_callback(self):
        block = ScrollParse(purge_rejected=False)
        parser = block.build_parser(None, on_reject=lambda r, w: True)
        self.assertIsNone(parser._on_reject)


class TestInvariant(unittest.TestCase):
    def test_table_only_ever_holds_people_passing_the_filter(self):
        """The overall invariant, across a stop/re-run cycle."""
        async def go():
            async with MemHarness() as mem:
                await mem.upsert_user(UserRecord(nick="Boris", gender="male"))
                for i in range(3):
                    eng = ActionEngine(
                        cdp=HighlightCDP(MIXED, page_height=100),
                        memory=mem, criteria=None)
                    eng.load_stack(stack(min_new_users=1))
                    if i == 1:                       # stop mid-way once
                        eng.person_found.connect(lambda p: eng.stop())
                    await eng.execute()
                return await mem.get_all()

        cwd = os.getcwd()
        os.chdir(tempfile.mkdtemp())
        try:
            people = run(go())
        finally:
            os.chdir(cwd)
        for u in people:
            self.assertEqual(u.gender, "female",
                             f"{u.nick} does not pass the filter")


if __name__ == "__main__":
    unittest.main(verbosity=2)
