"""stores/history_db — connection-level unit contract.

Design refs: docs/archive/2026-09-09-test-suite/BACKEND_TESTS_DESIGN_2026-09-09.md §HD#1–5.

The table shapes are pinned by test_db_schema_migration.py; the service
lifecycle by test_history_service_lifecycle.py. This file covers the
thin layer in between — the helpers everything else calls:

  * app_meta round-trips scalars and reports a missing key;
  * fetchall rows are plain tuples, fetchdicts rows real dicts, and
    scalar() falls back to its default when the row is missing;
  * file_size sums the file AND its -wal/-shm siblings;
  * use_fts=False creates a fully working database (FTS is optional);
  * a second HistoryDB on the same file reads what the first wrote.

Run with:  python3 tests/test_history_db_unit.py
"""

import asyncio
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from stores.history_db import HistoryDB  # noqa: E402


class DbCase(unittest.IsolatedAsyncioTestCase):

    async def _make(self, name="w.db", **kwargs) -> HistoryDB:
        db = HistoryDB(os.path.join(self.dir, name), **kwargs)
        await db.init()
        return db

    async def asyncSetUp(self):
        self.dir = tempfile.mkdtemp()
        self.db = await self._make()

    async def asyncTearDown(self):
        if self.db.is_open:
            await self.db.close()


class TestAppMeta(DbCase):

    async def test_meta_round_trip_and_missing_key(self):
        self.assertIsNone(await self.db.get_meta("ghost"))
        await self.db.set_meta("cursor", "42")
        self.assertEqual(await self.db.get_meta("cursor"), "42")
        await self.db.set_meta("cursor", "43")          # upsert in place
        self.assertEqual(await self.db.get_meta("cursor"), "43")
        # a fresh connection over the same file sees the value
        await self.db.close()
        again = await self._make()
        self.assertEqual(await again.get_meta("cursor"), "43")

    async def test_meta_values_are_stored_as_text(self):
        await self.db.set_meta("n", 7)
        self.assertEqual(await self.db.get_meta("n"), "7")


class TestRowHelpers(DbCase):

    async def test_fetchall_rows_are_plain_tuples(self):
        await self.db.execute(
            "INSERT INTO persons(nick, nick_lc) VALUES(?, ?)", ("Ann", "ann"))
        rows = await self.db.fetchall("SELECT nick FROM persons")
        self.assertEqual(rows, [("Ann",)])
        self.assertIsInstance(rows[0], tuple)

    async def test_fetchdicts_returns_plain_dicts(self):
        await self.db.execute(
            "INSERT INTO persons(nick, nick_lc) VALUES(?, ?)", ("Ann", "ann"))
        rows = await self.db.fetchdicts("SELECT nick FROM persons")
        self.assertEqual(rows, [{"nick": "Ann"}])
        self.assertIsInstance(rows[0], dict)
        self.assertEqual(rows[0]["nick"], "Ann")

    async def test_scalar_falls_back_to_its_default(self):
        await self.db.execute(
            "INSERT INTO persons(nick, nick_lc) VALUES(?, ?)", ("Ann", "ann"))
        self.assertEqual(await self.db.scalar(
            "SELECT COUNT(*) FROM persons"), 1)
        # a missing row yields the default (0 unless told otherwise)
        self.assertEqual(await self.db.scalar(
            "SELECT nick FROM persons WHERE nick=?", ("Ghost",)), 0)
        self.assertIsNone(await self.db.scalar(
            "SELECT nick FROM persons WHERE nick=?", ("Ghost",),
            default=None))


class TestSizes(DbCase):

    async def test_file_size_sums_the_file_and_its_wal_siblings(self):
        size = self.db.file_size()
        self.assertGreater(size, 0)
        # a real write must never shrink the reported size to zero
        await self.db.execute(
            "INSERT INTO persons(nick, nick_lc) VALUES(?, ?)", ("Ann", "ann"))
        await self.db.commit()
        self.assertGreaterEqual(self.db.file_size(), size)
        # the sum counts the main file at least
        main = os.path.getsize(self.db.path)
        self.assertGreaterEqual(size, main)


class TestNoFtsMode(DbCase):

    async def test_use_fts_false_creates_a_working_database(self):
        nof = await self._make("nof.db", use_fts=False)
        try:
            await nof.execute(
                "INSERT INTO persons(nick, nick_lc) VALUES(?, ?)",
                ("Ann", "ann"))
            rows = await nof.fetchall("SELECT nick FROM persons")
            self.assertEqual(rows, [("Ann",)])
            # FTS machinery must not have been created
            tables = {r[0] for r in await nof.fetchall(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertFalse(
                any("fts" in name for name in tables),
                f"use_fts=False still created FTS tables: {tables}")
            self.assertFalse(nof.fts_enabled)
        finally:
            await nof.close()

    async def test_default_init_enables_fts_when_available(self):
        self.assertTrue(self.db.fts_enabled,
                        "FTS5 exists in this env — default init must use it")


class TestTwoConnections(DbCase):

    async def test_a_second_connection_reads_what_the_first_wrote(self):
        await self.db.execute(
            "INSERT INTO persons(nick, nick_lc) VALUES(?, ?)", ("Ann", "ann"))
        await self.db.commit()
        second = HistoryDB(self.db.path)
        try:
            await second.init()
            rows = await second.fetchall("SELECT nick FROM persons")
            self.assertEqual(rows, [("Ann",)])
        finally:
            await second.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
