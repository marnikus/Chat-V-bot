"""Schema validation + repair on open (Bugs 1 & 5 of 2026-09-08).

Every database file the app is pointed at — history.db, chat.db, chat2.db —
must open into the SAME canonical schema:

  * a fresh file is created complete (creation ↔ validation parity);
  * an older file is widened in place (missing columns are added);
  * a pre-persons `messages` table (no `person_id` — the shape behind the
    endless "⚠ no such column: person_id" on every connect) is rebuilt with
    its rows attributed to persons, and the NEXT open is silent;
  * rows that cannot be attributed are quarantined, never destroyed;
  * `schema_meta.schema_version` is stamped and compared.

Per AGENT_RULES RULE 8 this drives the REAL HistoryDB against real SQLite
files in a temp dir.

Run with:  python3 tests/test_db_schema_migration.py
"""

import asyncio
import os
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.history_db import (SCHEMA_VERSION, TABLE_COLUMNS,  # noqa: E402
                                HistoryDB)


class TempCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "chat.db")

    async def open(self, path=None, **kwargs):
        db = HistoryDB(path or self.path, **kwargs)
        await db.init()
        self.addAsyncCleanup(db.close)
        return db


class TestFreshDatabase(TempCase):
    async def test_every_table_matches_the_canonical_columns(self):
        """Creation and validation read the SAME definition — no drift."""
        db = await self.open()
        for table, columns in TABLE_COLUMNS.items():
            rows = await db.fetchall(f"PRAGMA table_info({table})")
            self.assertEqual([r[1] for r in rows], [c for c, _ in columns],
                             f"{table} must be created exactly canonical")
        self.assertIn("person_id",
                      [c for c, _ in TABLE_COLUMNS["messages"]])

    async def test_the_version_is_stamped(self):
        db = await self.open()
        self.assertEqual(await db.get_meta("schema_version"), SCHEMA_VERSION)

    async def test_reopening_a_fresh_db_is_silent_and_safe(self):
        await self.open()
        db = await self.open()          # a second open must not raise
        self.assertEqual(await db.get_meta("schema_version"), SCHEMA_VERSION)


class TestLegacyMessagesWithoutPersonId(TempCase):
    def _make_pre_persons_db(self, with_nick=True, rows=True):
        """A file in the shape behind "no such column: person_id"."""
        conn = sqlite3.connect(self.path)
        nick_col = ",\n            nick TEXT NOT NULL DEFAULT ''" \
            if with_nick else ""
        conn.execute(
            "CREATE TABLE messages ("
            " id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " ord INTEGER NOT NULL,"
            " fp TEXT NOT NULL,"
            " direction TEXT NOT NULL,"
            " my_nick TEXT NOT NULL DEFAULT '',"
            " kind TEXT NOT NULL DEFAULT 'text',"
            " text TEXT NOT NULL DEFAULT '',"
            " text_lc TEXT NOT NULL DEFAULT '',"
            " ts_display TEXT NOT NULL DEFAULT '',"
            " day TEXT NOT NULL DEFAULT ''"
            f"{nick_col})")
        if rows:
            for i in range(3):
                cols = ["ord", "fp", "direction", "my_nick", "kind", "text",
                        "text_lc", "ts_display", "day"]
                values = [i + 1, f"fp{i}", "in", "Me", "text", f"line {i}",
                          f"line {i}", f"1{i}:0{i}", "2026-09-01"]
                if with_nick:
                    cols.append("nick")
                    values.append("Svetik25")
                marks = ",".join("?" for _ in cols)
                conn.execute(
                    f"INSERT INTO messages({', '.join(cols)}) "
                    f"VALUES({marks})", values)
        conn.commit()
        conn.close()

    async def test_the_rebuild_attributes_rows_and_persons(self):
        self._make_pre_persons_db()
        db = await self.open()
        rows = await db.fetchall(
            "SELECT person_id, text FROM messages ORDER BY ord")
        self.assertEqual(len(rows), 3, "every legacy row survives")
        persons = await db.fetchall("SELECT nick FROM persons")
        self.assertEqual([p[0] for p in persons], ["Svetik25"])
        person_ids = {r[0] for r in rows}
        self.assertEqual(person_ids, {1}, "all rows belong to that person")
        # identity was recomputed: dedupe can never re-import these twice
        keys = await db.fetchall("SELECT dup_key FROM messages")
        self.assertTrue(all(k[0] for k in keys))

    async def test_the_next_open_is_silent(self):
        """The warning that fired on EVERY connect is gone for good."""
        self._make_pre_persons_db()
        await self.open()
        db = await self.open()          # must not raise, must not rebuild again
        rows = await db.fetchall("SELECT COUNT(*) FROM messages")
        self.assertEqual(rows[0][0], 3)
        leftovers = await db.fetchall(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name LIKE 'messages_legacy_%'")
        self.assertEqual(leftovers, [], "the quarantine table is dropped")

    async def test_unattributable_rows_are_quarantined_not_destroyed(self):
        self._make_pre_persons_db(with_nick=False)
        db = await self.open()
        # the app keeps working with an empty archive
        self.assertEqual((await db.fetchall(
            "SELECT COUNT(*) FROM messages"))[0][0], 0)
        # the original bytes are still on disk, in the quarantine table
        names = [r[0] for r in await db.fetchall(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name LIKE 'messages_legacy_%'")]
        self.assertEqual(len(names), 1, "the quarantine table is kept")
        kept = await db.fetchall(f"SELECT text FROM {names[0]}")
        self.assertEqual([r[0] for r in kept],
                         ["line 0", "line 1", "line 2"])


class TestMissingColumnsAreAdded(TempCase):
    async def test_an_old_media_table_gains_its_late_columns(self):
        conn = sqlite3.connect(self.path)
        conn.executescript("""
            CREATE TABLE schema_meta (key TEXT PRIMARY KEY, value TEXT);
            CREATE TABLE persons (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nick TEXT NOT NULL UNIQUE,
                nick_lc TEXT NOT NULL);
            CREATE TABLE media (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT NOT NULL UNIQUE,
                kind TEXT NOT NULL DEFAULT 'image',
                state TEXT NOT NULL DEFAULT 'pending');
        """)
        conn.execute("INSERT INTO media(url) VALUES('https://x/y.gif')")
        conn.commit()
        conn.close()
        db = await self.open()
        rows = await db.fetchall("PRAGMA table_info(media)")
        names = {r[1] for r in rows}
        for col, _decl in TABLE_COLUMNS["media"]:
            self.assertIn(col, names)
        # the pre-existing row survives the widening
        self.assertEqual((await db.fetchall(
            "SELECT COUNT(*) FROM media"))[0][0], 1)

    async def test_a_file_that_cannot_be_repaired_fails_one_clear_open(self):
        """A file that stays incomplete fails ONE open with a clear message
        — never a different 'no such column' on every later query. The
        repair step is stubbed out to fabricate that situation."""
        db = HistoryDB(self.path)

        async def broken_repair():
            conn = sqlite3.connect(self.path)
            conn.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY)")
            conn.commit()
            conn.close()

        db._repair_tables = broken_repair
        with self.assertRaises(RuntimeError) as ctx:
            await db.init()
        self.assertIn("incomplete schema", str(ctx.exception))
        self.assertIn("person_id", str(ctx.exception))


class TestVersionGuard(TempCase):
    async def test_a_newer_file_warns_but_opens(self):
        db = await self.open()
        await db.set_meta("schema_version", "99")
        await db.commit()
        await db.close()
        db2 = await self.open()
        self.assertEqual(await db2.get_meta("schema_version"), SCHEMA_VERSION)


if __name__ == "__main__":
    unittest.main()
