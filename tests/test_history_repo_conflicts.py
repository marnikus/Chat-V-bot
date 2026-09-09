"""stores/history_repo — CRUD, version conflict, lifecycle edges.

Design refs: docs/STORES_TEST_DESIGN_2026-09-09.md §14 (HRP-01–22).

test_history_repo.py (29) + test_history_repo_lifecycle.py (16) pin append
idempotency, overlap, gaps, days, ord, counters, soft/hard delete, merge
and rename. This file pins what they do not: the pure-function contracts
(align_batch LAST-occurrence, resolve_days shape), concurrent same-batch
appends (the collector heartbeat vs a manual Collect press), prepend ord
shifting, gap persistence, token semantics (wrong token, double restore),
merge/delete edge cases, and the empty-safe query surface.

Run with:  python3 tests/test_history_repo_conflicts.py
"""

import asyncio
import os
import sys
import tempfile
import unittest
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from stores.history_db import HistoryDB  # noqa: E402
from stores.history_models import MessageRecord  # noqa: E402
from stores.history_repo import (  # noqa: E402
    HistoryRepo,
    align_batch,
    resolve_days,
)

NOW = datetime(2026, 9, 9, 12, 0, 0)


def rec(text, ts="10:01", nick="Ann", direction="in", idx=0, occ=0,
        kind="text"):
    return MessageRecord(direction=direction, from_nick=nick,
                         ts_display=ts, kind=kind, text=text, occ=occ,
                         idx=idx)


class RepoCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.dir = tempfile.mkdtemp()
        self.db = HistoryDB(os.path.join(self.dir, "h.db"))
        await self.db.init()
        self.repo = HistoryRepo(self.db)

    async def asyncTearDown(self):
        await self.db.close()

    async def ords(self, nick):
        person = await self.repo.get_person(nick)
        rows = await self.db.fetchdicts(
            "SELECT ord, text FROM messages WHERE person_id=? ORDER BY ord",
            (person["id"],))
        return [(r["ord"], r["text"]) for r in rows]

    async def dup_keys(self, nick):
        person = await self.repo.get_person(nick)
        rows = await self.db.fetchall(
            "SELECT dup_key FROM messages WHERE person_id=? AND dup_key<>''",
            (person["id"],))
        return [r[0] for r in rows]


class TestPureFunctions(unittest.TestCase):
    def test_align_finds_the_last_occurrence(self):  # HRP-01
        alg = align_batch(["x", "a", "b", "a", "b"], ["a", "b"])
        self.assertTrue(alg.matched)
        self.assertEqual(alg.start, 5)  # after the LAST [a, b], not index 3
        alg = align_batch(["a", "b", "c"], ["b", "c"])
        self.assertEqual(alg.start, 3)
        self.assertEqual(alg.overlap, 2)

    def test_align_empty_shapes(self):  # HRP-02
        self.assertEqual(align_batch([], ["a"]).start, 0)
        self.assertEqual(align_batch(["a"], []).start, 0)
        self.assertTrue(align_batch([], []).matched)
        lost = align_batch(["a", "b"], ["x", "y"])
        self.assertEqual((lost.start, lost.gap), (0, True))
        self.assertEqual(lost.reason, "alignment_lost")

    def test_resolve_days_shape_and_monotonicity(self):  # HRP-03
        days = resolve_days(["23:58", "00:01", "00:05", "garbage"],
                            datetime(2026, 9, 9, 0, 10))
        self.assertEqual(len(days), 4)
        for day in days:
            datetime.strptime(day, "%Y-%m-%d")  # strict YYYY-MM-DD
        self.assertEqual(days, sorted(days))  # non-decreasing forward
        self.assertEqual(days[-1], "2026-09-09")  # garbage takes today


class TestAppendConflicts(RepoCase):
    async def test_empty_batch_is_a_typed_noop(self):  # HRP-04
        res = await self.repo.append("Ann", [], now=NOW)
        self.assertEqual((res.added, res.skipped, res.gap), (0, 0, False))
        self.assertGreater(res.person_id, 0)

    async def test_concurrent_same_batch_appends_stay_unique(self):  # HRP-05
        batch = [rec("one", "10:01", idx=0), rec("two", "10:02", idx=1),
                 rec("three", "10:03", idx=2)]
        first, second = await asyncio.gather(
            self.repo.append("Ann", batch, now=NOW),
            self.repo.append("Ann", batch, now=NOW))
        self.assertEqual(first.added + second.added, 3)
        keys = await self.dup_keys("Ann")
        self.assertEqual(len(keys), 3)
        self.assertEqual(len(set(keys)), 3)
        self.assertEqual([o for o, _ in await self.ords("Ann")], [1, 2, 3])

    async def test_prepend_shifts_existing_ord(self):  # HRP-06
        await self.repo.append("Ann", [rec("new1", "10:03", idx=2),
                                       rec("new2", "10:04", idx=3)], now=NOW)
        res = await self.repo.append("Ann", [rec("old1", "10:01", idx=0),
                                             rec("old2", "10:02", idx=1)],
                                     now=NOW, prepend=True)
        self.assertEqual(res.added, 2)
        self.assertEqual(await self.ords("Ann"),
                         [(1, "old1"), (2, "old2"), (3, "new1"), (4, "new2")])

    async def test_prepend_of_dupes_moves_nothing(self):  # HRP-07
        await self.repo.append("Ann", [rec("a", "10:01", idx=0)], now=NOW)
        before = await self.ords("Ann")
        res = await self.repo.append("Ann", [rec("a", "10:01", idx=0)],
                                     now=NOW, prepend=True)
        self.assertEqual(res.added, 0)
        self.assertEqual(await self.ords("Ann"), before)

    async def test_recorded_gap_survives_later_appends(self):  # HRP-08
        await self.repo.append("Ann", [rec("a", "10:01", idx=0)], now=NOW)
        await self.repo.record_gap("Ann", 1, "cap", "detail-1")
        await self.repo.append("Ann", [rec("a", "10:01", idx=0),
                                       rec("b", "10:02", idx=1)], now=NOW)
        gaps = await self.db.fetchdicts(
            "SELECT reason, detail FROM gaps ORDER BY id")
        self.assertIn({"reason": "cap", "detail": "detail-1"},
                      [{"reason": g["reason"], "detail": g["detail"]}
                       for g in gaps])


class TestTokenSemantics(RepoCase):
    async def _one_message_id(self, nick="Ann"):
        await self.repo.append(nick, [rec("a", "10:01", idx=0),
                                      rec("b", "10:02", idx=1)], now=NOW)
        person = await self.repo.get_person(nick)
        rows = await self.db.fetchall(
            "SELECT id FROM messages WHERE person_id=? ORDER BY ord",
            (person["id"],))
        return person, rows[0][0]

    async def test_wrong_token_restores_nothing(self):  # HRP-09
        person, mid = await self._one_message_id()
        token = await self.repo.soft_delete_message("Ann", mid)
        self.assertTrue(token)
        self.assertEqual(await self.repo.restore_deleted("Ann", "wrong"), 0)
        self.assertEqual(await self.repo.deleted_count("Ann"), 1)
        self.assertEqual(await self.repo.restore_deleted("Ann", token), 1)
        self.assertEqual(await self.repo.deleted_count("Ann"), 0)

    async def test_double_restore_is_a_noop(self):  # HRP-10
        _, mid = await self._one_message_id()
        token = await self.repo.soft_delete_message("Ann", mid)
        self.assertEqual(await self.repo.restore_deleted("Ann", token), 1)
        self.assertEqual(await self.repo.restore_deleted("Ann", token), 0)
        keys = await self.dup_keys("Ann")
        self.assertEqual(len(keys), len(set(keys)))

    async def test_purge_only_touches_tombstones(self):  # HRP-11
        _, mid = await self._one_message_id()
        await self.repo.soft_delete_message("Ann", mid)
        self.assertEqual(await self.repo.purge_deleted("Ann"), 1)
        self.assertEqual(await self.ords("Ann"), [(2, "b")])
        self.assertEqual(await self.repo.purge_deleted("Ann"), 0)

    async def test_person_delete_and_restore_round_trip(self):  # HRP-12
        await self.repo.append("Ann", [rec("a", "10:01", idx=0),
                                       rec("b", "10:02", idx=1)], now=NOW)
        self.assertTrue(await self.repo.delete_person("Ann"))
        person = await self.repo.get_person("Ann")
        self.assertTrue(person["deleted"])
        self.assertEqual(person["message_count"], 0)
        self.assertTrue(await self.repo.restore_person("Ann"))
        person = await self.repo.get_person("Ann")
        self.assertFalse(person["deleted"])
        self.assertEqual(await self.ords("Ann"), [(1, "a"), (2, "b")])
        self.assertEqual(person["message_count"], 2)

    async def test_restore_person_with_wrong_token_refuses(self):  # HRP-13
        await self.repo.append("Ann", [rec("a", "10:01", idx=0)], now=NOW)
        await self.repo.delete_person("Ann")
        self.assertFalse(await self.repo.restore_person("Ann",
                                                        token="wrong"))
        person = await self.repo.get_person("Ann")
        self.assertTrue(person["deleted"])  # still deleted, rows still hidden
        self.assertEqual(await self.repo.deleted_count("Ann"), 1)
        # … and the original token still works afterwards
        self.assertTrue(await self.repo.restore_person("Ann"))
        self.assertEqual(await self.repo.deleted_count("Ann"), 0)

    async def test_merge_keeps_tombstones_hidden(self):  # HRP-14
        person, mid = await self._one_message_id("Src")
        await self.repo.soft_delete_message("Src", mid)
        await self.repo.append("Dst", [rec("d", "10:05", idx=0)], now=NOW)
        moved = await self.repo.merge_persons("Src", "Dst")
        self.assertEqual(moved, 2)
        dst = await self.repo.get_person("Dst")
        self.assertEqual(dst["message_count"], 2)  # live rows only
        self.assertEqual(await self.repo.deleted_count("Dst"), 1)

    async def test_merge_with_self_or_stranger_is_zero(self):  # HRP-15
        await self.repo.append("Ann", [rec("a", "10:01", idx=0)], now=NOW)
        self.assertEqual(await self.repo.merge_persons("Ann", "Ann"), 0)
        self.assertEqual(await self.repo.merge_persons("Ghost", "Ann"), 0)
        self.assertEqual(await self.repo.merge_persons("Ann", "Ghost"), 0)
        self.assertEqual(len(await self.ords("Ann")), 1)


class TestQueriesAndIdentity(RepoCase):
    async def test_possible_duplicates_groups_case_variants(self):  # HRP-16
        await self.repo.ensure_person("Ann")
        await self.repo.ensure_person("ann")
        await self.repo.ensure_person("  ANN  ")
        await self.repo.ensure_person("Bob")
        groups = await self.repo.possible_duplicates()
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["nick_lc"], "ann")
        self.assertEqual(sorted(groups[0]["nicks"]), ["ANN", "Ann", "ann"])

    async def test_unknown_person_queries(self):  # HRP-17
        self.assertIsNone(await self.repo.get_person("ghost"))
        self.assertIsNone(await self.repo.get_person_by_id(-1))

    async def test_empty_nick_is_refused(self):  # HRP-18
        with self.assertRaises(ValueError):
            await self.repo.ensure_person("")
        with self.assertRaises(ValueError):
            await self.repo.ensure_person("   ")
        self.assertEqual(await self.db.scalar("SELECT COUNT(*) FROM persons"),
                         0)

    async def test_cursor_of_unknown_person_is_empty_shaped(self):  # HRP-19
        cursor = await self.repo.get_cursor(424242)
        self.assertEqual(cursor["person_id"], 424242)
        self.assertEqual(cursor["last_ord"], 0)
        self.assertFalse(cursor["bootstrapped"])

    async def test_repair_probes_are_empty_safe(self):  # HRP-20
        pid = await self.repo.ensure_person("Ann")
        self.assertFalse(await self.repo.has_repairable_media(pid))
        self.assertEqual(await self.repo.recover_media(pid, [], media=None),
                         {"repaired": 0, "requeued": 0, "scanned": 0})
        self.assertEqual(await self.repo.recover_media(0, [], media=None),
                         {"repaired": 0, "requeued": 0, "scanned": 0})

    async def test_reset_cursor_clears_the_backfill_flag(self):  # HRP-21
        # Decided contract: reset_cursor() forgets ALL scan state, including
        # full_scan_complete — the next pass must re-verify from scratch.
        pid = await self.repo.ensure_person("Ann")
        await self.repo.mark_backfilled("Ann")
        cursor = await self.repo.get_cursor(pid)
        self.assertTrue(cursor["full_scan_complete"])
        await self.repo.reset_cursor("Ann")
        cursor = await self.repo.get_cursor(pid)
        self.assertFalse(cursor["full_scan_complete"])
        self.assertEqual(cursor["full_scan_at"], "")

    async def test_op_tokens_are_unique(self):  # HRP-22
        tokens = {HistoryRepo.new_op_token() for _ in range(1000)}
        self.assertEqual(len(tokens), 1000)
        self.assertTrue(all(t for t in tokens))


if __name__ == "__main__":
    unittest.main()
