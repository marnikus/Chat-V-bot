"""End-to-end: the user's exact scenario from the 2026-09-08 bug report.

    🔧 Connected to chat.db … ⚠ no such column: person_id
    🔧 Connected to history.db / chat2.db …
    🧹 History of "Svetik25❤️" cleared …
    → messages are never re-collected, Radar says "Added 25 / In archive 0"

This drives the REAL HistoryService + DbManager + Bridge across THREE
database files with switches in between, and asserts:

  * every open is silent — no "no such column" ever reaches the log;
  * chat.db / history.db / chat2.db all carry the complete, identical
    schema (the canonical column list, one schema version);
  * after 🧹 Clear the next tick re-collects the conversation and the
    counters tell the truth (added == alive rows in the DB);
  * data survives switches (the collector parks, the file re-opens).

Run with:  python3 tests/test_db_switch_e2e.py
"""

import asyncio
import json
import logging
import os
import sys
import tempfile
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QObject  # noqa: E402

from backend.bridge import Bridge  # noqa: E402
from backend.config_manager import ConfigManager  # noqa: E402
from services.db_service import DbManager  # noqa: E402
from stores.history_db import SCHEMA_VERSION, TABLE_COLUMNS  # noqa: E402
from services.history import HistoryService  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_chat_parser_delta import FakePage, raw  # noqa: E402

PARTNER = "Svetik25❤️"
ME = "Пошлый01"


class ConnectedPage(FakePage):
    is_connected = True


async def wait_for(box, timeout=3.0):
    step, waited = 0.01, 0.0
    while not box and waited < timeout:
        await asyncio.sleep(step)
        waited += step
    return box


class DbSwitchFlow(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.dir = tempfile.mkdtemp()
        self.cfg = ConfigManager(os.path.join(self.dir, "config.json"))
        self.page = ConnectedPage([])
        self.service = HistoryService(
            cdp=self.page, config=self.cfg,
            db_path=os.path.join(self.dir, "history.db"))
        await self.service.init()
        self.service.collector.configure(my_nick=ME)
        self.manager = DbManager(config=self.cfg, service=self.service,
                                 root=self.dir)
        br = Bridge.__new__(Bridge)
        QObject.__init__(br)
        br._config = self.cfg
        br._engine = types.SimpleNamespace(load_stack=lambda _b: None)
        br._memory = None
        br._presets = None
        br.attach_history(self.service)
        self.bridge = br
        self.warnings = []
        self.logs = []
        self.changed = []

        def capture_emit(record):
            self.warnings.append(record.getMessage())

        class Capture(logging.Handler):
            def emit(self, record, _emit=capture_emit):
                _emit(record)

        capture = Capture()
        capture.setLevel(logging.WARNING)
        logging.getLogger("chatbot").addHandler(capture)
        self.addAsyncCleanup(
            lambda: logging.getLogger("chatbot").removeHandler(capture))
        br.userdb_changed.connect(
            lambda p: self.changed.append(json.loads(p)))
        br.log_message.connect(
            lambda msg, level: self.logs.append((level, msg)))

    async def asyncTearDown(self):
        await self.service.close()

    async def create_and_connect(self, name):
        result = await self.manager.create(name)
        self.assertTrue(result.get("ok"),
                        f"creating {name} failed: {result.get('error')}")
        return result["path"]

    async def seed(self, count=25):
        self.page.partner = PARTNER
        self.page.messages = [raw(f"m{i}", from_nick=PARTNER, idx=i)
                              for i in range(count)]
        await self.service.collector.tick()

    async def visible(self, nick=PARTNER):
        page = await self.service.page(nick, limit=500)
        return page["items"]

    def assert_no_schema_errors(self):
        bad = [w for w in self.warnings if "no such column" in w]
        self.assertEqual(bad, [],
                         "a schema error reached the log: %s" % bad[:3])

    async def assert_canonical(self, path):
        """The file on disk carries the full canonical schema + version."""
        import sqlite3
        conn = sqlite3.connect(path)
        try:
            for table, columns in TABLE_COLUMNS.items():
                rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
                self.assertEqual([r[1] for r in rows],
                                 [c for c, _ in columns],
                                 f"{path}: {table} not canonical")
            row = conn.execute(
                "SELECT value FROM schema_meta WHERE key='schema_version'"
            ).fetchone()
            self.assertEqual(row and row[0], SCHEMA_VERSION)
        finally:
            conn.close()


# ═════════════════════════════════════════════════════════════════
class TestTheUserScenario(DbSwitchFlow):
    async def test_connect_clear_switch_recollect(self):
        # 🔧 Connected to chat.db — created through the DB window
        chat_db = await self.create_and_connect("chat.db")
        self.assertEqual(os.path.basename(self.service.db.path), "chat.db")
        await self.assert_canonical(chat_db)

        # a conversation is collected (25 lines, like the Radar showed)
        await self.seed(count=25)
        payload = self.service.collector.state_payload()
        self.assertEqual(payload["sync_added"], 25)
        self.assertEqual(payload["total"], 25)

        # 🧹 History of "Svetik25❤️" cleared — the person stays
        self.bridge.history_clear_person(PARTNER)
        await wait_for(self.changed)
        self.assertEqual(await self.visible(), [])
        person = await self.service.repo.get_person(PARTNER)
        self.assertIsNotNone(person, "the person stays in the database")
        self.assert_no_schema_errors()

        # the next scan re-collects the chat "as if visiting first time"
        await self.service.collector.tick()
        payload = self.service.collector.state_payload()
        self.assertEqual(payload["sync_added"], 25,
                         "all 25 messages are re-collected")
        self.assertEqual(payload["total"], 25,
                         "and the Radar's 'In archive' says so truthfully")
        items = await self.visible()
        self.assertEqual(len(items), 25)
        self.assertTrue(all(item["text"] for item in items),
                        "every row carries its message text (Bug 2)")

        # 🔧 Connected to chat2.db — the switch must be silent
        chat2_db = await self.create_and_connect("chat2.db")
        await self.assert_canonical(chat2_db)
        self.assertEqual(await self.visible(), [],
                         "a fresh database starts empty")

        # …and back to chat.db — the archive is still there
        await self.manager.load(chat_db)
        items = await self.visible()
        self.assertEqual(len(items), 25)
        self.assert_no_schema_errors()

    async def test_a_pre_persons_file_now_opens_and_heals(self):
        """The actual 'chat.db' the user had: messages WITHOUT person_id.
        Opening it must repair it in place and NEVER log the column error
        again."""
        import sqlite3
        legacy = os.path.join(self.dir, "chat.db")
        conn = sqlite3.connect(legacy)
        conn.executescript("""
            CREATE TABLE messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ord INTEGER NOT NULL,
                fp TEXT NOT NULL,
                direction TEXT NOT NULL,
                my_nick TEXT NOT NULL DEFAULT '',
                kind TEXT NOT NULL DEFAULT 'text',
                text TEXT NOT NULL DEFAULT '',
                text_lc TEXT NOT NULL DEFAULT '',
                ts_display TEXT NOT NULL DEFAULT '',
                day TEXT NOT NULL DEFAULT '',
                nick TEXT NOT NULL DEFAULT '',
                UNIQUE(ord));
        """)
        for i in range(3):
            conn.execute(
                "INSERT INTO messages(ord, fp, direction, my_nick, kind,"
                " text, text_lc, ts_display, day, nick) "
                "VALUES(?,?,?,?,?,?,?,?,?,?)",
                (i + 1, f"fp{i}", "in", ME, "text", f"line {i}", f"line {i}",
                 f"1{i}:00", "2026-09-01", PARTNER))
        conn.commit()
        conn.close()

        opened = await self.manager.load(legacy, create=False)
        self.assertTrue(opened.get("ok"),
                        f"opening the legacy file failed: {opened}")
        rows = await self.service.db.fetchall(
            "SELECT person_id, text FROM messages ORDER BY ord")
        self.assertEqual([r[1] for r in rows],
                         ["line 0", "line 1", "line 2"],
                         "the legacy rows survived the rebuild")
        person = await self.service.repo.get_person(PARTNER)
        self.assertIsNotNone(person)
        self.assertEqual({r[0] for r in rows}, {int(person["id"])})
        self.assert_no_schema_errors()

        # reconnection (the user's log re-connected constantly) is silent
        await self.service.db.close()
        reopened = HistoryService(
            cdp=self.page, config=self.cfg, db_path=legacy)
        await reopened.init()
        rows = await reopened.db.fetchall("SELECT COUNT(*) FROM messages")
        self.assertEqual(rows[0][0], 3)
        await reopened.close()
        self.assert_no_schema_errors()


if __name__ == "__main__":
    unittest.main()
