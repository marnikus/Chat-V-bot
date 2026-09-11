"""stores/history_repo — delete/restore/purge, merge, rename, resolve_days.

Design refs: docs/archive/2026-09-09-test-suite/BACKEND_TESTS_DESIGN_2026-09-09.md §HR#1–6.

The existing write-path suite covers append/align/backfill. This file
pins the undo/erasure lifecycle and the identity machinery:

  * soft delete → restore is an EXACT reversal (rows, counts, order);
    restoring twice is a no-op; a foreign token touches nothing;
  * purge is the ONLY path that removes bytes, and only for its person;
  * soft person-delete brings rows AND person back; a hard delete is
    final (restore_person reports False);
  * merge folds duplicates by identity, empties the source, keeps the
    survivor's ord sequence contiguous;
  * a nick rename is adopted ONLY with matching pane/signature evidence;
  * resolve_days walks HH:MM stamps backwards across midnight.

Run with:  python3 tests/test_history_repo_lifecycle.py
"""

import os
import sys
import tempfile
import unittest
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.history_db import HistoryDB  # noqa: E402
from backend.history_models import MessageRecord, fingerprint  # noqa: E402
from backend.history_repo import HistoryRepo  # noqa: E402
from stores.history_repo import resolve_days  # noqa: E402
from backend.history_query import HistoryQuery  # noqa: E402

NOW = datetime(2026, 9, 6, 18, 30, 0)


def rec(text, direction="in", from_nick="Nick", time="17:31", occ=0, idx=0):
    return MessageRecord(
        fp=fingerprint(direction, from_nick, time, "text", text, occ),
        direction=direction, from_nick=from_nick, kind="text", text=text,
        ts_display=time, occ=occ, idx=idx)


class RepoCase(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        self.dir = tempfile.mkdtemp()
        self.db = HistoryDB(os.path.join(self.dir, "history.db"))
        await self.db.init()
        self.repo = HistoryRepo(self.db, session_id="s1")
        self.q = HistoryQuery(self.db)

    async def asyncTearDown(self):
        await self.db.close()

    async def seed(self, nick="Nick", n=4, time="17:31"):
        batch = [rec(f"line {i}", from_nick=nick, time=time, idx=i)
                 for i in range(n)]
        await self.repo.append(nick, batch, my_nick="Me", now=NOW)

    async def visible_texts(self, nick):
        page = await self.q.page(nick, limit=500)
        return [i["text"] for i in page["items"]]


# ══════════════════════════════════════════════════════════════════
# HR#1 — one soft delete and its exact reversal
# ══════════════════════════════════════════════════════════════════
class TestSoftDeleteRestore(RepoCase):

    async def test_delete_one_message_and_restore_it_exactly(self):
        await self.seed(n=4)
        person = await self.repo.get_person("Nick")
        rows = await self.db.fetchall(
            "SELECT id, text FROM messages WHERE person_id=? ORDER BY ord",
            (person["id"],))
        victim_id = rows[1][0]

        token = await self.repo.soft_delete_message("Nick", victim_id)
        self.assertTrue(token, "a successful delete returns its token")
        self.assertEqual(await self.visible_texts("Nick"),
                         ["line 0", "line 2", "line 3"])
        self.assertEqual(await self.repo.deleted_count("Nick"), 1)

        restored = await self.repo.restore_deleted("Nick", token)
        self.assertEqual(restored, 1)
        self.assertEqual(await self.visible_texts("Nick"),
                         ["line 0", "line 1", "line 2", "line 3"])
        self.assertEqual(await self.repo.deleted_count("Nick"), 0)

        # exact reversal: restoring the same token again touches nothing
        self.assertEqual(await self.repo.restore_deleted("Nick", token), 0)
        # a token from another operation must not restore this row
        token2 = await self.repo.soft_delete_message("Nick", victim_id)
        self.assertEqual(await self.repo.restore_deleted("Nick",
                                                         "other-token"), 0)
        self.assertEqual(await self.repo.deleted_count("Nick"), 1)
        await self.repo.restore_deleted("Nick", token2)

    async def test_delete_on_an_unknown_person_is_a_noop(self):
        self.assertEqual(await self.repo.soft_delete_message("Ghost", 1), "")
        self.assertEqual(await self.repo.soft_delete_history("Ghost"), "")
        self.assertEqual(await self.repo.restore_deleted("Ghost", "t"), 0)

    async def test_clear_history_hides_everything_and_resets_identity(self):
        await self.seed(n=4)
        token = await self.repo.soft_delete_history("Nick")
        self.assertTrue(token)
        self.assertEqual(await self.visible_texts("Nick"), [])
        self.assertEqual(await self.repo.deleted_count("Nick"), 4)
        # Bug 3 (2026-09-08): hidden rows must lose their dup identity so
        # a re-visit re-collects instead of staying "already stored"
        rows = await self.db.fetchall(
            "SELECT dup_key FROM messages WHERE deleted_at=? AND dup_key=''",
            (token,))
        self.assertEqual(len(rows), 4)
        restored = await self.repo.restore_deleted("Nick", token)
        self.assertEqual(restored, 4)
        self.assertEqual(await self.visible_texts("Nick"),
                         ["line 0", "line 1", "line 2", "line 3"])


# ══════════════════════════════════════════════════════════════════
# HR#2 / HR#3 — purge and person deletion
# ══════════════════════════════════════════════════════════════════
class TestPurgeAndPersonDelete(RepoCase):

    async def test_purge_is_scoped_to_its_person(self):
        await self.seed("Nick", n=3)
        await self.seed("Bea", n=2)
        await self.repo.soft_delete_history("Nick")
        self.assertEqual(await self.repo.deleted_count("Nick"), 3)
        purged = await self.repo.purge_deleted("Nick")
        self.assertEqual(purged, 3)
        self.assertEqual(await self.repo.deleted_count("Nick"), 0)
        self.assertEqual(await self.repo.deleted_count("Bea"), 0)
        self.assertEqual(await self.visible_texts("Bea"),
                         ["line 0", "line 1"], "purge touched another person")
        # purging twice is zero
        self.assertEqual(await self.repo.purge_deleted("Nick"), 0)

    async def test_purge_without_a_nick_sweeps_every_tombstone(self):
        await self.seed("Nick", n=2)
        await self.seed("Bea", n=2)
        await self.repo.soft_delete_history("Nick")
        await self.repo.soft_delete_history("Bea")
        self.assertEqual(await self.repo.deleted_count(), 4)
        self.assertEqual(await self.repo.purge_deleted(), 4)
        self.assertEqual(await self.repo.deleted_count(), 0)

    async def test_purge_without_a_nick_erases_tombstoned_people(self):
        """“Empty trash” takes the whole tombstone, not just the messages."""
        await self.seed("Nick", n=2)
        await self.seed("Bea", n=2)
        await self.repo.delete_person("Nick", hard=False,
                                      token=self.repo.new_op_token())
        self.assertEqual(await self.repo.purge_deleted(), 2)
        self.assertIsNone(await self.repo.get_person("Nick"),
                          "the tombstoned person must be gone, not just hidden")
        self.assertIsNotNone(await self.repo.get_person("Bea"),
                             "a living person must survive the sweep")
        self.assertEqual(await self.visible_texts("Bea"), ["line 0", "line 1"])

    async def test_purge_of_one_nick_leaves_the_other_tombstone(self):
        await self.seed("Nick", n=2)
        await self.seed("Bea", n=2)
        await self.repo.delete_person("Bea", hard=False,
                                      token=self.repo.new_op_token())
        self.assertEqual(await self.repo.purge_deleted("Nick"), 0)
        self.assertIsNotNone(await self.repo.get_person("Bea"),
                             "purging one nick must not empty the whole trash")
        self.assertEqual(await self.repo.purge_deleted("ghost"), 0,
                         "a nick nobody has purges nothing")

    async def test_soft_person_delete_restores_person_and_rows(self):
        await self.seed("Nick", n=3)
        token = await self.repo.soft_delete_history("Nick")
        await self.repo.delete_person("Nick", hard=False, token=token)
        page = await self.q.page("Nick")
        # the person row still exists (tombstoned) so `missing` stays
        # False — but every read shows an empty conversation
        self.assertEqual(page["items"], [],
                         "a deleted person's rows leaked into a read")
        self.assertEqual(page["total"], 0)
        self.assertTrue(await self.repo.restore_person("Nick"))
        page = await self.q.page("Nick")
        self.assertFalse(page["missing"])
        self.assertEqual(len(page["items"]), 3,
                         "restore must bring the rows back in order")
        self.assertEqual([i["ord"] for i in page["items"]], [1, 2, 3])

    async def test_hard_delete_is_final(self):
        await self.seed("Nick", n=2)
        self.assertTrue(await self.repo.delete_person("Nick", hard=True))
        self.assertIsNone(await self.repo.get_person("Nick"))
        self.assertFalse(await self.repo.restore_person("Nick"),
                         "a hard-deleted person cannot come back")
        rows = await self.db.fetchall("SELECT COUNT(*) FROM messages")
        self.assertEqual(rows[0][0], 0)


# ══════════════════════════════════════════════════════════════════
# HR#4 — merge
# ══════════════════════════════════════════════════════════════════
class TestMerge(RepoCase):

    async def test_merge_moves_folds_and_empties_the_source(self):
        # two records of "Ann" plus one identical line already on "Anna"
        await self.repo.append("Ann", [rec("hello", from_nick="Ann", idx=0),
                                       rec("from Ann only",
                                           from_nick="Ann", idx=1)],
                               my_nick="Me", now=NOW)
        await self.repo.append("Anna", [rec("hello", from_nick="Ann", idx=0)],
                               my_nick="Me", now=NOW)
        moved = await self.repo.merge_persons("Ann", "Anna")
        # 1 actually moved: the duplicate "hello" row loses the UPDATE
        # race against the target's existing identity (UNIQUE index) and
        # is swept with the source — folding, not doubling.
        self.assertEqual(moved, 1)
        self.assertIsNone(await self.repo.get_person("Ann"),
                          "the source person must be gone")
        page = await self.q.page("Anna", limit=500)
        texts = sorted(i["text"] for i in page["items"])
        self.assertEqual(texts, ["from Ann only", "hello"],
                         "the duplicate 'hello' must fold, not double")
        ords = [i["ord"] for i in page["items"]]
        self.assertEqual(ords, [1, 2], "the survivor must stay contiguous")

    async def test_merge_with_self_or_a_stranger_is_zero(self):
        await self.seed("Nick", n=2)
        self.assertEqual(await self.repo.merge_persons("Nick", "Nick"), 0)
        self.assertEqual(await self.repo.merge_persons("Ghost", "Nick"), 0)
        self.assertEqual(await self.repo.merge_persons("Nick", "Ghost"), 0)


# ══════════════════════════════════════════════════════════════════
# HR#5 — rename adoption
# ══════════════════════════════════════════════════════════════════
class TestRename(RepoCase):

    async def bootstrap(self, nick="Nick", n=5):
        await self.seed(nick, n=n)
        person = await self.repo.get_person(nick)
        await self.db.execute(
            "UPDATE cursors SET bootstrapped=1, head_sig=?, tail_sig=?, "
            "head_any=?, tail_any=?, dom_count=? WHERE person_id=?",
            ("HEAD", "TAIL", "ANYH", "ANYT", n, person["id"]))
        await self.db.commit()

    async def test_rename_adopts_the_archive_with_matching_evidence(self):
        await self.bootstrap()
        ok = await self.repo.rename_if_same_conversation(
            "Nick", "NewNick", head_sig="HEAD", tail_sig="TAIL",
            dom_count=5, pane_same=True)
        self.assertTrue(ok)
        person = await self.repo.get_person("NewNick")
        self.assertIsNotNone(person)
        self.assertIsNone(await self.repo.get_person("Nick"))
        rows = await self.db.fetchall(
            "SELECT DISTINCT from_nick FROM messages")
        self.assertEqual(rows[0][0], "NewNick",
                         "the stored lines must follow the new nick")

    async def test_rename_refuses_without_evidence(self):
        await self.bootstrap()
        # different pane
        self.assertFalse(await self.repo.rename_if_same_conversation(
            "Nick", "A1", head_sig="HEAD", tail_sig="TAIL",
            dom_count=5, pane_same=False))
        # signature mismatch
        self.assertFalse(await self.repo.rename_if_same_conversation(
            "Nick", "A2", head_sig="WRONG", tail_sig="TAIL",
            dom_count=5, pane_same=True))
        # dom_count changed
        self.assertFalse(await self.repo.rename_if_same_conversation(
            "Nick", "A3", head_sig="HEAD", tail_sig="TAIL",
            dom_count=99, pane_same=True))
        # the target nick is already a person
        await self.seed("Busy", n=1)
        self.assertFalse(await self.repo.rename_if_same_conversation(
            "Nick", "Busy", head_sig="HEAD", tail_sig="TAIL",
            dom_count=5, pane_same=True))
        # nothing above may have renamed Nick
        self.assertIsNotNone(await self.repo.get_person("Nick"))
        self.assertIsNone(await self.repo.get_person("A1"))


# ══════════════════════════════════════════════════════════════════
# HR#6 — resolve_days (midnight walk)
# ══════════════════════════════════════════════════════════════════
class TestResolveDays(unittest.TestCase):

    def test_rollover_at_midnight(self):
        now = datetime(2026, 9, 6, 0, 10)          # just after midnight
        days = resolve_days(["23:59", "00:05"], now)
        # the list is oldest → newest: 23:59 belongs to Sep 5, 00:05 to Sep 6
        self.assertEqual(days, ["2026-09-05", "2026-09-06"])

    def test_a_lone_future_minute_belongs_to_yesterday(self):
        now = datetime(2026, 9, 6, 9, 0)
        days = resolve_days(["09:05"], now)
        self.assertEqual(days, ["2026-09-05"])

    def test_same_minute_stays_the_same_day(self):
        now = datetime(2026, 9, 6, 12, 0)
        self.assertEqual(resolve_days(["11:59", "12:00", "12:00"], now),
                         ["2026-09-06", "2026-09-06", "2026-09-06"])

    def test_two_midnight_crossings(self):
        """The day decrements only when the clock INCREASES walking
        backwards: 00:04→00:01 decreases, so both are Sep 6."""
        now = datetime(2026, 9, 6, 0, 5)
        days = resolve_days(["22:00", "23:30", "00:01", "00:04"], now)
        self.assertEqual(days, ["2026-09-05", "2026-09-05",
                                "2026-09-06", "2026-09-06"])

    def test_garbage_stamps_take_the_current_day(self):
        now = datetime(2026, 9, 6, 12, 0)
        self.assertEqual(resolve_days(["?", "12:00"], now),
                         ["2026-09-06", "2026-09-06"])
        self.assertEqual(resolve_days([], now), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
