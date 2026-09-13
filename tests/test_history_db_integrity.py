"""stores/history_db — query helpers, lifecycle, hostile inputs.

Design refs: docs/archive/2026-09-09-test-suite/STORES_TEST_DESIGN_2026-09-09.md §13 (HDB-01–17).

test_history_db_unit.py pins meta/fetch-shapes/WAL-size/FTS-flag, and
test_db_schema_migration.py pins the repair paths. This file pins the thin
layer in between that every caller trusts: open/close/init lifecycle,
execute/executemany/fetchone/scalar semantics, parameter binding (no string
interpolation, ever), version comparison, and what a corrupt or newer file
does to the handle — a failed open must never leave a half-open zombie.

Run with:  python3 tests/test_history_db_integrity.py
"""

import asyncio
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from stores.history_db import (  # noqa: E402
    SCHEMA_VERSION,
    HistoryDB,
    _version_tuple,
)


class DbCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.dir = tempfile.mkdtemp()
        self.dbs = []

    async def _open(self, name="w.db", **kwargs):
        db = HistoryDB(os.path.join(self.dir, name), **kwargs)
        self.dbs.append(db)
        await db.init()
        return db

    async def asyncTearDown(self):
        for db in self.dbs:
            try:
                await db.close()
            except Exception:
                pass


class TestLifecycle(DbCase):
    async def test_open_close_states(self):  # HDB-01
        db = HistoryDB(os.path.join(self.dir, "a.db"))
        self.assertFalse(db.is_open)
        with self.assertRaises(RuntimeError):
            db.conn
        await db.init()
        self.dbs.append(db)
        self.assertTrue(db.is_open)
        self.assertIsNotNone(db.conn)
        await db.close()
        await db.close()  # idempotent
        self.assertFalse(db.is_open)

    async def test_double_init_is_safe(self):  # HDB-02
        db = await self._open()
        await db.set_meta("k", "v")
        await db.init()  # reconnect, no duplicate tables, no error
        self.assertTrue(db.is_open)
        await db.commit()
        self.assertEqual(await db.get_meta("k"), "v")

    async def test_query_after_close_is_a_clear_error(self):  # HDB-17
        db = await self._open()
        await db.close()
        with self.assertRaises(RuntimeError):
            await db.fetchall("SELECT 1")


class TestQueryHelpers(DbCase):
    async def test_execute_commit_fetchone_round_trip(self):  # HDB-03
        db = await self._open()
        db2 = await self._open("w.db")  # second conn first: init() writes
        await db.execute("CREATE TABLE t(a TEXT)")
        await db.commit()
        await db.execute("INSERT INTO t(a) VALUES(?)", ("x",))
        # uncommitted: invisible to a second connection …
        self.assertIsNone(await db2.fetchone("SELECT a FROM t"))
        await db.commit()
        # … committed: visible everywhere
        row = await db2.fetchone("SELECT a FROM t")
        self.assertEqual(tuple(row), ("x",))

    async def test_executemany_inserts_in_order(self):  # HDB-04
        db = await self._open()
        await db.execute("CREATE TABLE t(a TEXT)")
        await db.executemany("INSERT INTO t(a) VALUES(?)",
                             [("a",), ("b",), ("c",)])
        await db.commit()
        self.assertEqual(await db.fetchall("SELECT a FROM t ORDER BY rowid"),
                         [("a",), ("b",), ("c",)])

    async def test_fetchone_and_scalar_empty_shapes(self):  # HDB-05
        db = await self._open()
        self.assertIsNone(await db.fetchone(
            "SELECT value FROM schema_meta WHERE key='ghost'"))
        self.assertEqual(await db.scalar(
            "SELECT value FROM schema_meta WHERE key='ghost'", (), "dflt"),
                         "dflt")
        self.assertEqual(await db.scalar("SELECT 1 + 1"), 2)

    async def test_params_are_bound_not_interpolated(self):  # HDB-06
        db = await self._open()
        await db.execute("CREATE TABLE t(a TEXT)")
        await db.execute("INSERT INTO t(a) VALUES(?)", ("real",))
        await db.commit()
        evil = "' OR '1'='1"
        rows = await db.fetchall("SELECT a FROM t WHERE a=?", (evil,))
        self.assertEqual(rows, [])  # a literal string, matching nothing
        rows = await db.fetchall("SELECT a FROM t WHERE a=?", ("real",))
        self.assertEqual(rows, [("real",)])
        # and the classic multi-statement smuggle is one literal too
        await db.execute("INSERT INTO t(a) VALUES(?)", ("x'); DROP TABLE t;--",))
        await db.commit()
        self.assertEqual(await db.scalar("SELECT COUNT(*) FROM t"), 2)

    async def test_meta_overwrite_and_unicode(self):  # HDB-07
        db = await self._open()
        await db.set_meta("k", "v1")
        await db.set_meta("k", "v2–🎉")
        await db.commit()
        self.assertEqual(await db.get_meta("k"), "v2–🎉")

    async def test_db_fetch_legacy_on_missing_table_raises(self):  # HDB-14 (pin)
        db = await self._open()
        # db_fetch_legacy is a private repair helper whose callers
        # guarantee the table: a missing table is a loud OperationalError,
        # not a silent empty list. (Design HDB-14 decided SPEC.)
        import sqlite3
        with self.assertRaises(sqlite3.OperationalError):
            await db.db_fetch_legacy("no_such_table", ["id"])

    async def test_table_columns_of_missing_table_is_none(self):  # HDB-15
        db = await self._open()
        self.assertIsNone(await db._table_columns("no_such_table"))
        self.assertIn("id", await db._table_columns("persons"))


class TestVersions(DbCase):
    def test_numeric_version_compare(self):  # HDB-08
        self.assertGreater(_version_tuple("10"), _version_tuple("9"))
        self.assertGreater(_version_tuple("1.10"), _version_tuple("1.9"))
        self.assertEqual(_version_tuple("6"), (6,))
        self.assertEqual(_version_tuple("xx"), (0,))  # garbage never raises
        self.assertEqual(_version_tuple(None), (0,))

    async def test_corrupt_file_fails_one_clear_open(self):  # HDB-09
        bad = os.path.join(self.dir, "bad.db")
        with open(bad, "wb") as fh:
            fh.write(b"this is not a sqlite file at all" * 10)
        db = HistoryDB(bad)
        self.dbs.append(db)
        with self.assertRaises(RuntimeError):
            await db.init()
        # no half-open zombie left behind
        self.assertFalse(db.is_open)
        with self.assertRaises(RuntimeError):
            await db.get_meta("schema_version")

    async def test_newer_file_opens_and_takes_the_current_stamp(self):  # HDB-10
        db = await self._open()
        await db.set_meta("schema_version", "99")
        await db.commit()
        await db.close()
        db2 = HistoryDB(os.path.join(self.dir, "w.db"))
        self.dbs.append(db2)
        await db2.init()  # warns, but opens (pinned by schema suite too)
        self.assertEqual(await db2.get_meta("schema_version"), SCHEMA_VERSION)
        # … and the database actually works afterwards
        self.assertIsNotNone(await db2.fetchone("SELECT COUNT(*) FROM persons"))

    async def test_no_fts_file_has_no_fts_tables(self):  # HDB-11
        db = await self._open("nofts.db", use_fts=False)
        self.assertFalse(db.fts_enabled)
        tables = {r[0] for r in await db.fetchall(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertNotIn("messages_fts", tables)
        self.assertEqual(await db.get_meta("fts"), "0")
        # plain writes/reads are unaffected
        await db.execute("INSERT INTO persons(nick, nick_lc) VALUES(?,?)",
                         ("Ann", "ann"))
        await db.commit()
        self.assertEqual(await db.scalar("SELECT COUNT(*) FROM persons"), 1)


class TestFilesAndConcurrency(DbCase):
    async def test_file_size_covers_a_working_db(self):  # HDB-12
        db = await self._open()
        main = os.path.getsize(os.path.join(self.dir, "w.db"))
        self.assertGreater(db.file_size(), 0)
        self.assertGreaterEqual(db.file_size(), main)

    async def test_interleaved_writers_both_land(self):  # HDB-13
        db1 = await self._open()
        db2 = HistoryDB(os.path.join(self.dir, "w.db"))
        self.dbs.append(db2)
        await db2.init()
        await db1.execute("INSERT INTO schema_meta(key, value) VALUES(?,?)",
                          ("from1", "a"))
        await db1.commit()
        await db2.execute("INSERT INTO schema_meta(key, value) VALUES(?,?)",
                          ("from2", "b"))
        await db2.commit()
        self.assertEqual(await db1.get_meta("from1"), "a")
        self.assertEqual(await db1.get_meta("from2"), "b")
        self.assertEqual(await db2.get_meta("from1"), "a")

    async def test_concurrent_commits_never_tear_a_row(self):  # HDB-13b
        db1 = await self._open()
        db2 = HistoryDB(os.path.join(self.dir, "w.db"))
        self.dbs.append(db2)
        await db2.init()

        async def put(db, key):
            await db.execute("INSERT INTO schema_meta(key, value) VALUES(?,?)",
                             (key, key))
            await db.commit()

        await asyncio.gather(*[put(db1, f"k{i}") for i in range(10)],
                             *[put(db2, f"j{i}") for i in range(10)])
        self.assertEqual(await db1.scalar(
            "SELECT COUNT(*) FROM schema_meta WHERE key LIKE 'k%'"), 10)
        self.assertEqual(await db1.scalar(
            "SELECT COUNT(*) FROM schema_meta WHERE key LIKE 'j%'"), 10)


class TestNormaliseNick(unittest.TestCase):
    def test_collapses_whitespace_keeps_case(self):  # HDB-16 (SPEC pin)
        norm = HistoryDB.normalise_nick
        self.assertEqual(norm("  Ann   Lee "), "Ann Lee")
        self.assertEqual(norm("Ann"), "Ann")  # case preserved here …
        self.assertEqual(norm(""), "")
        self.assertEqual(norm("   "), "")
        self.assertEqual(norm(None), "")
        # … the case-folded form lives in persons.nick_lc, not here


if __name__ == "__main__":
    unittest.main()
