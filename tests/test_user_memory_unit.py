"""stores/user_memory — queue store contract (direct unit tests).

Design refs: docs/BACKEND_TESTS_DESIGN_2026-09-09.md §UM#1–5.

test_click_user_memory covers the ENGINE side. This file pins the store
itself — the data structure every run trusts:

  * upsert is idempotent per nick (update, never a duplicate) and
    reports "new" vs "known";
  * operations on a missing nick are safe no-ops / False, never raises;
  * get_queue is exactly the unmessaged users, newest-discovered first;
  * set_messaged flips one row; replace_all restores an exact snapshot;
  * the queue travels with its world file (switch_db) and survives a
    close/reopen.

Run with:  python3 tests/test_user_memory_unit.py
"""

import asyncio
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.user_memory import UserMemory, UserRecord  # noqa: E402


def urec(nick, gender="f", registered=False, guest=True):
    return UserRecord(nick=nick, gender=gender, registered=registered,
                      anonymous=False, guest=guest)


class MemCase(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        self.dir = tempfile.mkdtemp()
        self.path_a = os.path.join(self.dir, "world_a.db")
        self.path_b = os.path.join(self.dir, "world_b.db")
        self.mem = UserMemory(self.path_a)
        await self.mem.init()

    async def asyncTearDown(self):
        await self.mem.close()

    async def nicks(self, users):
        return [u.nick for u in users]


class TestUpsert(MemCase):

    async def test_upsert_is_idempotent_per_nick(self):
        self.assertEqual(await self.mem.upsert_user(urec("Ann")), "new")
        self.assertEqual(await self.mem.upsert_user(urec("Ann")), "known")
        self.assertEqual(len(await self.mem.get_all()), 1)
        # the update path must refresh attributes, not duplicate
        await self.mem.upsert_user(urec("Ann", gender="m"))
        rows = await self.mem.get_all()
        self.assertEqual(rows[0].gender, "m")

    async def test_upsert_many_counts(self):
        new, known = await self.mem.upsert_many(
            [urec("A"), urec("B"), urec("A")])
        self.assertEqual((new, known), (2, 1))
        self.assertEqual(len(await self.mem.get_all()), 2)


class TestMissingNickSafety(MemCase):

    async def test_operations_on_a_missing_nick_never_raise(self):
        await self.mem.mark_messaged("Ghost")           # silent no-op
        self.assertFalse(await self.mem.set_messaged("Ghost", True))
        self.assertFalse(await self.mem.delete_user("Ghost"))
        self.assertIsNone(await self.mem.get_user("Ghost"))
        self.assertEqual(await self.mem.delete_users(["Ghost", ""]), 0)
        self.assertEqual(await self.mem.delete_users([]), 0)


class TestQueue(MemCase):

    async def test_queue_is_unmessaged_newest_first(self):
        await self.mem.upsert_user(urec("Old"))
        await asyncio.sleep(0.01)
        await self.mem.upsert_user(urec("New"))
        await self.mem.mark_messaged("Old")
        queue = await self.mem.get_queue()
        self.assertEqual(await self.nicks(queue), ["New"],
                         "messaged people leave the queue")
        stats = await self.mem.get_stats()
        self.assertEqual(await self.mem.count_unmessaged(), 1)
        self.assertEqual(stats.get("total", stats.get("all", 0)), 2)

    async def test_set_messaged_flips_one_row_back(self):
        await self.mem.upsert_many([urec("A"), urec("B")])
        self.assertTrue(await self.mem.set_messaged("A", True))
        self.assertEqual(await self.nicks(await self.mem.get_queue()), ["B"])
        self.assertTrue(await self.mem.set_messaged("A", False))
        self.assertEqual(len(await self.mem.get_queue()), 2)

    async def test_reset_messaged_requeues_everybody(self):
        await self.mem.upsert_many([urec("A"), urec("B")])
        await self.mem.mark_messaged("A")
        await self.mem.mark_messaged("B")
        self.assertEqual(await self.mem.get_queue(), [])
        await self.mem.reset_messaged()
        self.assertEqual(len(await self.mem.get_queue()), 2)


class TestSnapshot(MemCase):

    async def test_replace_all_restores_an_exact_snapshot(self):
        await self.mem.upsert_many([urec("A"), urec("B")])
        await self.mem.mark_messaged("A")
        rows = [r.to_dict() if hasattr(r, "to_dict") else vars(r)
                for r in await self.mem.get_all()]
        await self.mem.clear_all()
        self.assertEqual(await self.mem.get_all(), [])
        restored = await self.mem.replace_all(rows)
        self.assertEqual(await self.nicks(await self.mem.get_all()),
                         ["A", "B"])
        self.assertEqual((await self.mem.get_all())[0].messaged, 1,
                         "the snapshot's messaged flag must survive")


class TestWorldSwitch(MemCase):

    async def test_queue_travels_with_its_world(self):
        await self.mem.upsert_user(urec("Ava"))
        await self.mem.switch_db(self.path_b)
        self.assertEqual(self.mem.db_path, self.path_b)
        self.assertEqual(await self.mem.get_all(), [],
                         "world A's queue leaked into world B")
        await self.mem.upsert_user(urec("Bea"))
        await self.mem.switch_db(self.path_a)
        self.assertEqual(await self.nicks(await self.mem.get_all()), ["Ava"])
        # B kept its own row too
        await self.mem.switch_db(self.path_b)
        self.assertEqual(await self.nicks(await self.mem.get_all()), ["Bea"])

    async def test_data_survives_a_close_and_reopen(self):
        await self.mem.upsert_user(urec("Ann"))
        await self.mem.mark_messaged("Ann")
        await self.mem.close()
        fresh = UserMemory(self.path_a)
        await fresh.init()
        rows = await fresh.get_all()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].messaged, 1)
        await fresh.close()

    async def test_switch_to_an_empty_path_is_refused(self):
        with self.assertRaises(ValueError):
            await self.mem.switch_db("")


if __name__ == "__main__":
    unittest.main(verbosity=2)
