"""Unit coverage for services.db_media_scan (strict scan + URI)."""

import os
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))))

from services.db_media_scan import (  # noqa: E402
    MediaScanResult, scan_world_media, sqlite_ro_uri)


def make_db(path, *, with_media=True, version="6", rows=(), extra_sql=()):
    conn = sqlite3.connect(path)
    try:
        if with_media:
            conn.execute("CREATE TABLE IF NOT EXISTS media("
                         "id INTEGER PRIMARY KEY, url TEXT, kind TEXT, "
                         "state TEXT, cache_path TEXT, owner TEXT)")
        conn.execute("CREATE TABLE IF NOT EXISTS schema_meta("
                     "key TEXT PRIMARY KEY, value TEXT)")
        if version is not None:
            conn.execute("INSERT OR REPLACE INTO schema_meta(key,value) "
                         "VALUES('schema_version',?)", (version,))
        for url, cache_path in rows:
            conn.execute("INSERT INTO media(url, state, cache_path) "
                         "VALUES(?,?,?)", (url, "cached", cache_path))
        for sql in extra_sql:
            conn.execute(sql)
        conn.commit()
    finally:
        conn.close()
    return path


class TestScanUnit(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="scan_unit_")

    def tmp(self, name):
        return os.path.join(self.dir, name)

    async def test_missing_file_incomplete(self):
        res = await scan_world_media(os.path.join(self.dir, "nope.db"))
        self.assertFalse(res.complete)
        self.assertEqual(res.reason, "missing_file")
        self.assertEqual(res.references, frozenset())

    async def test_empty_file_complete_empty(self):
        p = self.tmp("empty.db")
        open(p, "wb").close()
        res = await scan_world_media(p)
        self.assertTrue(res.complete)
        self.assertEqual(res.reason, "ok")
        self.assertEqual(res.references, frozenset())

    async def test_getsize_oserror_falls_through(self):
        p = make_db(self.tmp("a.db"), rows=[("u", "/tmp/x.jpg")])
        with mock.patch("os.path.getsize", side_effect=OSError("boom")):
            res = await scan_world_media(p)
        self.assertTrue(res.complete)
        self.assertIn(os.path.abspath("/tmp/x.jpg"), res.references)

    async def test_valid_empty_complete(self):
        p = make_db(self.tmp("b.db"), rows=[])
        res = await scan_world_media(p)
        self.assertTrue(res.complete)
        self.assertEqual(res.reason, "ok")
        self.assertEqual(res.references, frozenset())
        self.assertEqual(res.schema_version, "6")

    async def test_valid_with_refs(self):
        p = make_db(self.tmp("c.db"),
                    rows=[("u1", "/tmp/a.jpg"), ("u2", "  /tmp/b.jpg  "),
                          ("u3", ""), ("u4", None) if False else ("u4", "/tmp/c.jpg")])
        res = await scan_world_media(p)
        self.assertTrue(res.complete)
        self.assertIn(os.path.abspath("/tmp/a.jpg"), res.references)
        self.assertIn(os.path.abspath("/tmp/b.jpg"), res.references)

    async def test_missing_media_table_incomplete(self):
        conn = sqlite3.connect(self.tmp("n.db"))
        try:
            conn.execute("CREATE TABLE t(x TEXT)")
            conn.commit()
        finally:
            conn.close()
        res = await scan_world_media(self.tmp("n.db"))
        self.assertFalse(res.complete)
        self.assertEqual(res.reason, "missing_media_table")

    async def test_missing_schema_meta_still_complete(self):
        # media present, schema_meta missing → legacy-complete, version None
        p = self.tmp("m.db")
        conn = sqlite3.connect(p)
        try:
            conn.execute("CREATE TABLE media(id INTEGER PRIMARY KEY, "
                         "url TEXT, state TEXT, cache_path TEXT)")
            conn.execute("INSERT INTO media(url, state, cache_path) "
                         "VALUES('u','cached','/tmp/z.jpg')")
            conn.commit()
        finally:
            conn.close()
        res = await scan_world_media(p)
        self.assertTrue(res.complete)
        self.assertIsNone(res.schema_version)

    async def test_unsupported_schema_incomplete(self):
        p = make_db(self.tmp("v.db"), version="99", rows=[])
        res = await scan_world_media(p)
        self.assertFalse(res.complete)
        self.assertEqual(res.reason, "unsupported_schema")
        self.assertEqual(res.schema_version, "99")

    async def test_corrupt_file_incomplete(self):
        p = self.tmp("corrupt.db")
        with open(p, "wb") as fh:
            fh.write(b"not-sqlite" * 100)
        res = await scan_world_media(p)
        self.assertFalse(res.complete)
        self.assertIn(res.reason, ("corrupt", "io_error", "query_error"))

    async def test_media_without_cache_path_column_query_error(self):
        p = self.tmp("q.db")
        conn = sqlite3.connect(p)
        try:
            conn.execute("CREATE TABLE media(id INTEGER PRIMARY KEY, url TEXT)")
            conn.execute("CREATE TABLE schema_meta(key TEXT PRIMARY KEY, "
                         "value TEXT)")
            conn.commit()
        finally:
            conn.close()
        res = await scan_world_media(p)
        self.assertFalse(res.complete)
        # SELECT cache_path fails → query_error (or missing column)
        self.assertIn(res.reason, ("query_error", "corrupt", "io_error"))

    async def test_locked_via_mock(self):
        p = make_db(self.tmp("l.db"), rows=[])
        with mock.patch("aiosqlite.connect",
                        side_effect=Exception("database is locked")):
            res = await scan_world_media(p)
        self.assertFalse(res.complete)
        self.assertEqual(res.reason, "locked")

    async def test_busy_via_mock(self):
        p = make_db(self.tmp("b2.db"), rows=[])
        with mock.patch("aiosqlite.connect",
                        side_effect=Exception("database is busy")):
            res = await scan_world_media(p)
        self.assertFalse(res.complete)
        self.assertEqual(res.reason, "locked")

    async def test_no_such_table_outer(self):
        p = make_db(self.tmp("o.db"), rows=[])
        with mock.patch("aiosqlite.connect",
                        side_effect=Exception("no such table: media")):
            res = await scan_world_media(p)
        self.assertFalse(res.complete)
        self.assertEqual(res.reason, "missing_media_table")

    async def test_not_a_database_outer(self):
        p = make_db(self.tmp("o2.db"), rows=[])
        with mock.patch("aiosqlite.connect",
                        side_effect=Exception("file is not a database")):
            res = await scan_world_media(p)
        self.assertFalse(res.complete)
        self.assertEqual(res.reason, "corrupt")

    async def test_malformed_outer(self):
        p = make_db(self.tmp("o3.db"), rows=[])
        with mock.patch("aiosqlite.connect",
                        side_effect=Exception("database disk image is malformed")):
            res = await scan_world_media(p)
        self.assertFalse(res.complete)
        self.assertEqual(res.reason, "corrupt")

    async def test_generic_io_error_outer(self):
        p = make_db(self.tmp("o4.db"), rows=[])
        with mock.patch("aiosqlite.connect",
                        side_effect=OSError("disk gone")):
            res = await scan_world_media(p)
        self.assertFalse(res.complete)
        self.assertEqual(res.reason, "io_error")

    async def test_whitespace_cache_path_skipped(self):
        # whitespace-only passes SQL <>'' but is empty after strip.
        p = make_db(self.tmp("ws.db"), rows=[("u", "   ")])
        res = await scan_world_media(p)
        self.assertTrue(res.complete)
        self.assertEqual(res.references, frozenset())

    async def test_locked_during_media_query_inner(self):
        p = make_db(self.tmp("li.db"),
                    rows=[("u", "/tmp/keep.jpg")])

        real_connect = __import__("aiosqlite").connect

        class FailCursor:
            async def fetchall(self):
                raise Exception("database is locked")

            async def fetchone(self):  # pragma: no cover - not used here
                return None

        class WrapConn:
            def __init__(self, conn):
                self._conn = conn
                self._n = 0

            async def __aenter__(self):
                await self._conn.__aenter__()
                return self

            async def __aexit__(self, *a):
                return await self._conn.__aexit__(*a)

            async def execute(self, sql, *a, **k):
                self._n += 1
                if "cache_path FROM media" in sql:
                    raise Exception("database is locked")
                return await self._conn.execute(sql, *a, **k)

        def fake_connect(*a, **k):
            return WrapConn(real_connect(*a, **k))

        with mock.patch("aiosqlite.connect", side_effect=fake_connect):
            res = await scan_world_media(p)
        self.assertFalse(res.complete)
        self.assertEqual(res.reason, "locked")

    def test_uri_escaping(self):
        uri = sqlite_ro_uri("/tmp/my world \u00e9.db")
        self.assertIn("file:", uri)
        self.assertIn("mode=ro", uri)
        self.assertNotIn(" ", uri, "spaces must be encoded")
        uri2 = sqlite_ro_uri("/tmp/we?ird#name%.db")
        # ? and # in filename must be encoded, only final ?mode=ro stays
        self.assertTrue(uri2.endswith("?mode=ro"))
        body = uri2[len("file:"):-len("?mode=ro")]
        self.assertNotIn("?", body)
        self.assertNotIn("#", body)
        self.assertIn("%3F", body)
        self.assertIn("%23", body)


if __name__ == "__main__":
    unittest.main(verbosity=2)
