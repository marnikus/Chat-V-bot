"""stores/user_memory — memory/link/cycle edges.

Design refs: docs/STORES_TEST_DESIGN_2026-09-09.md §15 (UMM-01–15).

test_user_memory_unit.py pins upsert idempotency, queue order, flips,
snapshots, world travel and reopen. This file pins the seams around it:
empty/duplicate batches, hostile nicks (SQL metacharacters must be inert),
stats consistency, partial deletes, replace_all atomicity (a garbage row
must never leave the table half-replaced), the full A→B→A world cycle, a
corrupt world that must not strand the queue, and the close lifecycle.

Run with:  python3 tests/test_user_memory_links.py
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from stores.user_memory import UserMemory, UserRecord  # noqa: E402


def urec(nick, **kw):
    args = {"gender": "f", "registered": False, "guest": True}
    args.update(kw)
    return UserRecord(nick=nick, **args)


class MemCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.dir = tempfile.mkdtemp()
        self.path_a = os.path.join(self.dir, "world_a.db")
        self.path_b = os.path.join(self.dir, "world_b.db")
        self.mem = UserMemory(self.path_a)
        await self.mem.init()

    async def asyncTearDown(self):
        await self.mem.close()


class TestBatches(MemCase):
    async def test_upsert_many_empty_is_zero(self):  # UMM-01
        self.assertEqual(await self.mem.upsert_many([]), (0, 0))
        self.assertEqual(await self.mem.get_all(), [])

    async def test_upsert_many_with_dupes_collapses_to_one_row(self):  # UMM-02
        res = await self.mem.upsert_many([urec("Ann"), urec("Ann")])
        self.assertEqual(res, (1, 1))
        rows = await self.mem.get_all()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].nick, "Ann")

    async def test_hostile_nicks_are_inert_literals(self):  # UMM-03
        evil = "'; DROP TABLE users;--"
        await self.mem.upsert_user(urec(evil))
        await self.mem.upsert_user(urec("🎉" * 20))
        await self.mem.upsert_user(urec("x" * 500))
        # the table survived, rows stored literally
        self.assertIsNotNone(await self.mem.get_user(evil))
        self.assertEqual(await self.mem.count_unmessaged(), 3)
        await self.mem.mark_messaged(evil)
        self.assertEqual((await self.mem.get_user(evil)).message_count, 1)
        # NOTE (seam inconsistency, deliberately not fixed): unlike
        # HistoryRepo.ensure_person (ValueError), upsert_user() does not
        # validate — an empty nick is stored literally. Callers guarantee
        # non-empty DOM nicks, so refusing here could break collection.
        await self.mem.upsert_user(urec(""))
        self.assertIsNotNone(await self.mem.get_user(""))


class TestReads(MemCase):
    async def test_empty_reads(self):  # UMM-04
        self.assertIsNone(await self.mem.get_user("ghost"))
        self.assertEqual(await self.mem.get_all(), [])
        self.assertEqual(await self.mem.get_queue(), [])

    async def test_stats_shape_and_consistency(self):  # UMM-05
        self.assertEqual(await self.mem.get_stats(),
                         {"total": 0, "queued": 0, "done": 0})
        await self.mem.upsert_many([urec("A"), urec("B")])
        await self.mem.mark_messaged("A")
        stats = await self.mem.get_stats()
        self.assertEqual(stats, {"total": 2, "queued": 1, "done": 1})

    async def test_count_matches_queue_length(self):  # UMM-06
        await self.mem.upsert_many([urec("A"), urec("B"), urec("C")])
        await self.mem.mark_messaged("B")
        self.assertEqual(await self.mem.count_unmessaged(),
                         len(await self.mem.get_queue()))

    async def test_mark_messaged_unknown_is_quiet(self):  # UMM-07
        await self.mem.mark_messaged("ghost")  # no raise
        self.assertEqual(await self.mem.count_unmessaged(), 0)


class TestDeletes(MemCase):
    async def test_delete_users_partial_success(self):  # UMM-08
        self.assertEqual(await self.mem.delete_users([]), 0)
        await self.mem.upsert_many([urec("A"), urec("B")])
        self.assertEqual(await self.mem.delete_users(["ghost", "A"]), 1)
        self.assertIsNone(await self.mem.get_user("A"))
        self.assertIsNotNone(await self.mem.get_user("B"))

    async def test_replace_all_empty_empties(self):  # UMM-09
        await self.mem.upsert_many([urec("A")])
        self.assertEqual(await self.mem.replace_all([]), 0)
        self.assertEqual(await self.mem.get_all(), [])

    async def test_replace_all_garbage_is_atomic(self):  # UMM-10
        await self.mem.upsert_many([urec("Keep1"), urec("Keep2")])
        with self.assertRaises((ValueError, AttributeError, TypeError)):
            await self.mem.replace_all([
                {"nick": "New", "message_count": 0},
                {"nick": "Broken", "message_count": "not-a-number"},
            ])
        # all-or-nothing: the original rows are still there, nothing partial
        nicks = sorted(u.nick for u in await self.mem.get_all())
        self.assertEqual(nicks, ["Keep1", "Keep2"])

    async def test_replace_all_none_entry_is_atomic(self):  # UMM-10b
        await self.mem.upsert_user(urec("Keep"))
        with self.assertRaises((ValueError, AttributeError, TypeError)):
            await self.mem.replace_all([{"nick": "New"}, None])
        self.assertEqual([u.nick for u in await self.mem.get_all()], ["Keep"])

    async def test_clear_all_then_reuse(self):  # UMM-11
        await self.mem.upsert_many([urec("A"), urec("B")])
        self.assertEqual(await self.mem.clear_all(), 2)
        self.assertEqual(await self.mem.get_stats(),
                         {"total": 0, "queued": 0, "done": 0})
        await self.mem.upsert_user(urec("Fresh"))
        self.assertEqual(len(await self.mem.get_all()), 1)


class TestWorldsAndLifecycle(MemCase):
    async def test_full_cycle_keeps_both_worlds(self):  # UMM-12
        await self.mem.upsert_user(urec("OnlyA"))
        await self.mem.switch_db(self.path_b)
        self.assertEqual(await self.mem.get_all(), [])
        await self.mem.upsert_user(urec("OnlyB"))
        await self.mem.switch_db(self.path_a)
        self.assertEqual([u.nick for u in await self.mem.get_all()],
                         ["OnlyA"])
        await self.mem.switch_db(self.path_b)
        self.assertEqual([u.nick for u in await self.mem.get_all()],
                         ["OnlyB"])

    async def test_switch_to_corrupt_keeps_old_world(self):  # UMM-13
        await self.mem.upsert_user(urec("Keep"))
        bad = os.path.join(self.dir, "bad.db")
        with open(bad, "wb") as fh:
            fh.write(b"garbage-not-sqlite" * 32)
        with self.assertRaises(Exception):
            await self.mem.switch_db(bad)
        # no half-switched state: old world still connected and readable
        self.assertTrue(self.mem.is_open)
        self.assertEqual(self.mem.db_path, self.path_a)
        self.assertEqual([u.nick for u in await self.mem.get_all()], ["Keep"])

    async def test_switch_to_empty_path_is_refused(self):  # UMM-13b
        with self.assertRaises(ValueError):
            await self.mem.switch_db("   ")
        self.assertEqual(self.mem.db_path, self.path_a)

    async def test_lifecycle(self):  # UMM-14
        mem = UserMemory(os.path.join(self.dir, "lazy.db"))
        self.assertFalse(mem.is_open)
        await mem.init()
        self.assertTrue(mem.is_open)
        await mem.init()  # second init reconnects cleanly, same data
        await mem.upsert_user(urec("A"))
        self.assertEqual(len(await mem.get_all()), 1)
        await mem.close()
        await mem.close()  # idempotent
        self.assertFalse(mem.is_open)
        with self.assertRaises(AttributeError):  # loud, never a hang
            await mem.get_all()

    async def test_set_messaged_edges(self):  # UMM-15
        self.assertFalse(await self.mem.set_messaged("ghost", True))
        await self.mem.upsert_user(urec("A"))
        await self.mem.mark_messaged("A")
        self.assertIsNotNone((await self.mem.get_user("A")).last_messaged)
        self.assertTrue(await self.mem.set_messaged("A", False))
        back = await self.mem.get_user("A")
        self.assertFalse(back.messaged)
        # a "New" person must never show a message time (reset rule)
        self.assertIsNone(back.last_messaged)


if __name__ == "__main__":
    unittest.main()
