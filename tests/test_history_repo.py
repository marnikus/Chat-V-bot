"""Message archive — WRITE path (milestone M1).

The archive (history.db) is a SEPARATE store from the People list: it is
append-only, all-time, keyed by the partner's nick, and no filter/purge of
the People table may ever touch it (proposed RULE 14).

What these tests lock down:

  * schema + person identity (normalised nick, one row per nick, merge on
    re-appearance — never a duplicate);
  * append is IDEMPOTENT — replaying the same batch, re-running a
    bootstrap, or overlapping a delta inserts nothing new;
  * suffix alignment finds where the previous collection stopped, and an
    unrecoverable overlap is recorded as an explicit `gaps` row instead of
    silently swallowing the hole;
  * `ord` is monotonic per conversation (the only ordering the preview
    uses), while HH:MM-only timestamps are resolved to days by walking the
    list backwards;
  * counters, my_nicks (my nick can differ per session) and cursors;
  * tombstone / restore / hard delete / merge.

Run with:  python3 tests/test_history_repo.py
"""

import asyncio
import os
import sys
import tempfile
import unittest
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.history_db import HistoryDB  # noqa: E402
from backend.history_models import MessageRecord, fingerprint  # noqa: E402
from backend.history_repo import HistoryRepo  # noqa: E402

NOW = datetime(2026, 9, 6, 18, 30, 0)


def run(coro):
    return asyncio.run(coro)


def rec(text="hi", direction="in", from_nick="Nick", time="17:31",
        kind="text", media=None, occ=0, idx=0):
    payload = media["url"] if media else text
    return MessageRecord(
        fp=fingerprint(direction, from_nick, time, kind, payload, occ),
        direction=direction, from_nick=from_nick, kind=kind, text=text,
        media_url=(media or {}).get("url", ""),
        media_kind=(media or {}).get("kind", ""),
        ts_display=time, occ=occ, idx=idx)


def convo(n, start=0):
    """n alternating messages with distinct text."""
    out = []
    for i in range(start, start + n):
        out.append(rec(text=f"m{i}",
                       direction="out" if i % 2 else "in",
                       from_nick="Me" if i % 2 else "Nick",
                       time="17:%02d" % (i % 60), idx=i))
    return out


class ArchiveCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.dir = tempfile.mkdtemp()
        self.db = HistoryDB(os.path.join(self.dir, "history.db"))
        await self.db.init()
        self.repo = HistoryRepo(self.db, session_id="s1")

    async def asyncTearDown(self):
        await self.db.close()


class TestSchema(ArchiveCase):
    async def test_tables_and_version_exist(self):
        rows = await self.db.fetchall(
            "SELECT name FROM sqlite_master WHERE type='table'")
        names = {r[0] for r in rows}
        for t in ("persons", "messages", "media", "cursors", "gaps",
                  "schema_meta"):
            self.assertIn(t, names)
        self.assertEqual(await self.db.get_meta("schema_version"), "1")

    async def test_reopening_an_existing_db_is_safe(self):
        await self.repo.append("Nick", convo(3), my_nick="Me", now=NOW)
        await self.db.close()
        db2 = HistoryDB(self.db.path)
        await db2.init()
        repo2 = HistoryRepo(db2)
        stats = await repo2.get_person("Nick")
        self.assertEqual(stats["message_count"], 3)
        await db2.close()


class TestPersonIdentity(ArchiveCase):
    async def test_nick_is_normalised_and_unique(self):
        a = await self.repo.ensure_person("  На работе 25 ")
        b = await self.repo.ensure_person("На работе 25")
        self.assertEqual(a, b)
        person = await self.repo.get_person("На работе 25")
        self.assertEqual(person["nick"], "На работе 25")

    async def test_same_nick_across_sessions_continues_one_history(self):
        await self.repo.append("Nick", convo(2), my_nick="Me1", now=NOW)
        await self.repo.reset_cursor("Nick")            # new session, fresh DOM
        await self.repo.append("Nick", convo(2, start=10), my_nick="Me2",
                               now=NOW)
        person = await self.repo.get_person("Nick")
        self.assertEqual(person["message_count"], 4)
        self.assertEqual(sorted(person["my_nicks"]), ["Me1", "Me2"])
        rows = await self.db.fetchall("SELECT COUNT(*) FROM persons")
        self.assertEqual(rows[0][0], 1)

    async def test_case_differences_are_not_merged_but_are_flagged(self):
        await self.repo.append("Nick", convo(1), now=NOW)
        await self.repo.append("NICK", convo(1), now=NOW)
        rows = await self.db.fetchall("SELECT COUNT(*) FROM persons")
        self.assertEqual(rows[0][0], 2)
        dupes = await self.repo.possible_duplicates()
        self.assertEqual(len(dupes), 1)
        self.assertEqual(sorted(dupes[0]["nicks"]), ["NICK", "Nick"])


class TestAppendAndDedupe(ArchiveCase):
    async def test_first_append_stores_everything_in_order(self):
        res = await self.repo.append("Nick", convo(5), my_nick="Me", now=NOW)
        self.assertEqual(res.added, 5)
        self.assertFalse(res.gap)
        ords = [r[0] for r in await self.db.fetchall(
            "SELECT ord FROM messages ORDER BY id")]
        self.assertEqual(ords, [1, 2, 3, 4, 5])

    async def test_replaying_the_same_batch_adds_nothing(self):
        batch = convo(5)
        await self.repo.append("Nick", batch, now=NOW)
        res = await self.repo.append("Nick", batch, now=NOW)
        self.assertEqual(res.added, 0)
        self.assertEqual(res.skipped, 5)
        self.assertFalse(res.gap)   # a perfect overlap is not a gap

    async def test_overlapping_resync_appends_only_the_tail(self):
        await self.repo.append("Nick", convo(5), now=NOW)
        res = await self.repo.append("Nick", convo(8), now=NOW)  # 5 old + 3 new
        self.assertEqual(res.added, 3)
        person = await self.repo.get_person("Nick")
        self.assertEqual(person["message_count"], 8)

    async def test_identical_text_in_the_same_minute_stays_distinct(self):
        batch = [rec(text="ok", time="17:31", occ=0, idx=0),
                 rec(text="ok", time="17:31", occ=1, idx=1),
                 rec(text="ok", time="17:31", occ=2, idx=2)]
        res = await self.repo.append("Nick", batch, now=NOW)
        self.assertEqual(res.added, 3)
        again = await self.repo.append("Nick", batch, now=NOW)
        self.assertEqual(again.added, 0)     # …and still idempotent

    async def test_live_delta_without_alignment_is_appended(self):
        await self.repo.append("Nick", convo(5), now=NOW)
        delta = convo(2, start=5)
        res = await self.repo.append("Nick", delta, align=False,
                                     expect_idx=5, now=NOW)
        self.assertEqual(res.added, 2)
        self.assertFalse(res.gap)

    async def test_live_delta_that_skipped_dom_nodes_records_a_gap(self):
        await self.repo.append("Nick", convo(5), now=NOW)
        delta = convo(1, start=40)           # idx jumped from 4 to 40
        res = await self.repo.append("Nick", delta, align=False,
                                     expect_idx=5, now=NOW)
        self.assertTrue(res.gap)
        gaps = await self.db.fetchall("SELECT reason FROM gaps")
        self.assertEqual(len(gaps), 1)

    async def test_lost_alignment_appends_all_and_records_a_gap(self):
        await self.repo.append("Nick", convo(5), now=NOW)
        # the site trimmed its buffer: nothing in common with what we stored
        res = await self.repo.append("Nick", convo(3, start=100), now=NOW)
        self.assertEqual(res.added, 3)
        self.assertTrue(res.gap)
        reasons = [r[0] for r in await self.db.fetchall("SELECT reason FROM gaps")]
        self.assertEqual(reasons, ["alignment_lost"])

    async def test_empty_batch_is_a_no_op_not_a_gap(self):
        await self.repo.append("Nick", convo(3), now=NOW)
        res = await self.repo.append("Nick", [], now=NOW)
        self.assertEqual((res.added, res.skipped, res.gap), (0, 0, False))


class TestOrderingAndTime(ArchiveCase):
    async def test_days_are_resolved_by_walking_backwards(self):
        batch = [rec(text="late", time="23:58", idx=0),
                 rec(text="past midnight", time="00:04", idx=1),
                 rec(text="now", time="01:00", idx=2)]
        await self.repo.append("Nick", batch,
                               now=datetime(2026, 9, 6, 1, 30))
        rows = await self.db.fetchall(
            "SELECT text, ts_resolved, ts_exact FROM messages ORDER BY ord")
        self.assertTrue(rows[0][1].startswith("2026-09-05"))   # yesterday
        self.assertTrue(rows[1][1].startswith("2026-09-06"))
        self.assertTrue(rows[2][1].startswith("2026-09-06"))
        self.assertEqual(rows[0][2], 0)   # never claims to be exact

    async def test_same_text_on_two_days_is_two_rows(self):
        one = [rec(text="Привет", time="09:00", idx=0)]
        await self.repo.append("Nick", one, now=datetime(2026, 9, 5, 9, 5))
        await self.repo.reset_cursor("Nick")
        res = await self.repo.append("Nick", one,
                                     now=datetime(2026, 9, 6, 9, 5))
        self.assertEqual(res.added, 1)

    async def test_ord_keeps_growing_across_appends(self):
        await self.repo.append("Nick", convo(3), now=NOW)
        await self.repo.append("Nick", convo(3, start=3), align=False, now=NOW)
        ords = [r[0] for r in await self.db.fetchall(
            "SELECT ord FROM messages ORDER BY ord")]
        self.assertEqual(ords, [1, 2, 3, 4, 5, 6])


class TestCountersAndCursor(ArchiveCase):
    async def test_direction_and_media_counters(self):
        batch = [rec(text="a", direction="in", idx=0),
                 rec(text="", direction="out", from_nick="Me", kind="gif",
                     media={"url": "https://x/y.gif", "kind": "gif"}, idx=1),
                 rec(text="b", direction="out", from_nick="Me", idx=2)]
        await self.repo.append("Nick", batch, my_nick="Me", now=NOW)
        person = await self.repo.get_person("Nick")
        self.assertEqual(person["message_count"], 3)
        self.assertEqual(person["in_count"], 1)
        self.assertEqual(person["out_count"], 2)
        self.assertEqual(person["media_count"], 1)

    async def test_media_rows_are_registered_and_linked(self):
        batch = [rec(text="", kind="gif",
                     media={"url": "https://x/y.gif", "kind": "gif"}, idx=0)]
        await self.repo.append("Nick", batch, now=NOW)
        rows = await self.db.fetchall(
            "SELECT m.kind, md.url, md.state FROM messages m "
            "JOIN media md ON md.id = m.media_id")
        self.assertEqual(rows[0][0], "gif")
        self.assertEqual(rows[0][1], "https://x/y.gif")
        self.assertEqual(rows[0][2], "pending")

    async def test_cursor_tracks_the_resume_point(self):
        await self.repo.append("Nick", convo(4), dom_count=4,
                               head_sig="H", tail_sig="T", now=NOW)
        pid = await self.repo.ensure_person("Nick")
        cur = await self.repo.get_cursor(pid)
        self.assertEqual(cur["last_ord"], 4)
        self.assertEqual(cur["dom_count"], 4)
        self.assertEqual(cur["head_sig"], "H")
        self.assertEqual(cur["tail_sig"], "T")
        self.assertEqual(len(cur["tail_fps"]), 4)
        self.assertTrue(cur["bootstrapped"])

    async def test_tail_fingerprints_are_capped(self):
        await self.repo.append("Nick", convo(260), now=NOW)
        pid = await self.repo.ensure_person("Nick")
        cur = await self.repo.get_cursor(pid)
        self.assertLessEqual(len(cur["tail_fps"]), 200)
        self.assertEqual(cur["last_ord"], 260)

    async def test_reset_cursor_does_not_delete_messages(self):
        await self.repo.append("Nick", convo(3), now=NOW)
        await self.repo.reset_cursor("Nick")
        pid = await self.repo.ensure_person("Nick")
        cur = await self.repo.get_cursor(pid)
        self.assertEqual(cur["tail_fps"], [])
        self.assertFalse(cur["bootstrapped"])
        person = await self.repo.get_person("Nick")
        self.assertEqual(person["message_count"], 3)   # archive untouched


class TestLifecycle(ArchiveCase):
    async def test_tombstone_hides_and_restore_brings_back(self):
        await self.repo.append("Nick", convo(3), now=NOW)
        self.assertTrue(await self.repo.delete_person("Nick"))
        person = await self.repo.get_person("Nick")
        self.assertIsNotNone(person["deleted_at"])
        rows = await self.db.fetchall("SELECT COUNT(*) FROM messages")
        self.assertEqual(rows[0][0], 3)          # messages survive a tombstone
        self.assertTrue(await self.repo.restore_person("Nick"))
        person = await self.repo.get_person("Nick")
        self.assertIsNone(person["deleted_at"])

    async def test_hard_delete_removes_messages(self):
        await self.repo.append("Nick", convo(3), now=NOW)
        await self.repo.delete_person("Nick", hard=True)
        self.assertIsNone(await self.repo.get_person("Nick"))
        rows = await self.db.fetchall("SELECT COUNT(*) FROM messages")
        self.assertEqual(rows[0][0], 0)

    async def test_merge_moves_messages_and_drops_duplicates(self):
        await self.repo.append("nick", convo(3), my_nick="Me", now=NOW)
        await self.repo.append("Nick", convo(3), my_nick="Me", now=NOW)
        moved = await self.repo.merge_persons("nick", "Nick")
        self.assertEqual(moved, 0)     # identical content deduped away
        self.assertIsNone(await self.repo.get_person("nick"))
        person = await self.repo.get_person("Nick")
        self.assertEqual(person["message_count"], 3)

    async def test_merge_keeps_distinct_content(self):
        await self.repo.append("nick", convo(2), now=NOW)
        await self.repo.append("Nick", convo(2, start=50), now=NOW)
        moved = await self.repo.merge_persons("nick", "Nick")
        self.assertEqual(moved, 2)
        person = await self.repo.get_person("Nick")
        self.assertEqual(person["message_count"], 4)
        ords = [r[0] for r in await self.db.fetchall(
            "SELECT ord FROM messages ORDER BY ord")]
        self.assertEqual(ords, [1, 2, 3, 4])       # ord re-sequenced


if __name__ == "__main__":
    unittest.main(verbosity=2)
