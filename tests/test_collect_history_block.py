"""The COLLECT_HISTORY action block (milestone M4).

"Create the Action Block to parse full current msg history and add new
lines of msg if new upcoming — add this data to DB for this Nick."

The block shares the parser and the repository with the passive collector
(one implementation, two triggers) and follows the house rules:

  * RULE 3 — every setting is a plain attribute that round-trips;
  * RULE 4 — "nothing new" is an OK/informational result, "not a private
    tab" is a failure. They must never look the same;
  * RULE 5 — progress is reported per chunk while it runs;
  * RULE 7 — a stop is reported as stopped, not as failed.

Run with:  python3 tests/test_collect_history_block.py
"""

import asyncio
import os
import sys
import tempfile
import types
import unittest
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from actions.base_action import ActionResult, get_action_class  # noqa: E402
from actions.collect_history import CollectHistory  # noqa: E402
from backend.chat_parser import ChatParser  # noqa: E402
from backend.history_db import HistoryDB  # noqa: E402
from backend.history_repo import HistoryRepo  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_chat_parser_delta import FakePage, raw  # noqa: E402

NOW = datetime(2026, 9, 6, 18, 30, 0)
UI_DIR = os.path.join(os.path.dirname(__file__), "..", "ui")


class FakeEngine:
    def __init__(self, history=None, selected_nick=""):
        self.history = history
        self.selected_nick = selected_nick
        self.lines = []
        self._stop = False

    def report(self, message, level="info"):
        self.lines.append((level, message))

    def is_stopping(self):
        return self._stop

    def text(self):
        return " | ".join(m for _l, m in self.lines)


class BlockCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.dir = tempfile.mkdtemp()
        self.db = HistoryDB(os.path.join(self.dir, "history.db"))
        await self.db.init()
        self.repo = HistoryRepo(self.db, session_id="s")
        self.page = FakePage([raw(f"m{i}", idx=i) for i in range(6)])
        self.parser = ChatParser(self.page, chunk_size=3, chunk_pause_ms=0)
        self.service = types.SimpleNamespace(repo=self.repo,
                                             parser=self.parser,
                                             enabled=True)
        self.engine = FakeEngine(history=self.service)

    async def asyncTearDown(self):
        await self.db.close()

    def block(self, **kw):
        kw.setdefault("pre_delay_ms", 0)
        kw.setdefault("chunk_pause_ms", 0)
        blk = CollectHistory(**kw)
        blk.now = lambda: NOW
        return blk


class TestRegistration(unittest.TestCase):
    def test_block_is_registered(self):
        self.assertIs(get_action_class("COLLECT_HISTORY"), CollectHistory)
        self.assertTrue(CollectHistory.name)
        self.assertTrue(CollectHistory.icon)

    def test_settings_round_trip_through_to_dict(self):
        blk = CollectHistory(target="memory_nick", mode="full",
                             require_private=False, max_messages=123,
                             chunk_size=17, download_media=False,
                             fail_if_empty=True, pre_delay_ms=0)
        data = blk.to_dict()
        self.assertEqual(data["block_id"], "COLLECT_HISTORY")
        self.assertEqual(data["target"], "memory_nick")
        self.assertEqual(data["mode"], "full")
        self.assertEqual(data["max_messages"], 123)
        clone = CollectHistory(**{k: v for k, v in data.items()
                                  if k != "block_id"})
        self.assertEqual(clone.to_dict(), data)

    def test_unknown_legacy_keys_still_load(self):
        blk = CollectHistory(retired_option=1, pre_delay_ms=0)
        self.assertTrue(blk.enabled)

    def test_config_schema_describes_every_control(self):
        schema = CollectHistory().config_schema()
        for key in ("target", "mode", "require_private", "max_messages",
                    "chunk_size", "download_media", "fail_if_empty"):
            self.assertIn(key, schema)

    def test_ui_mirrors_the_block(self):
        with open(os.path.join(UI_DIR, "js", "stack-dnd.js"),
                  encoding="utf-8") as fh:
            src = fh.read()
        self.assertIn("COLLECT_HISTORY", src)


class TestExecution(BlockCase):
    async def test_archives_the_open_conversation(self):
        res = await self.block().execute("", self.page, self.engine)
        self.assertEqual(res, ActionResult.OK)
        person = await self.repo.get_person("Nick")
        self.assertEqual(person["message_count"], 6)
        self.assertIn("6", self.engine.text())
        self.assertIn("Nick", self.engine.text())

    async def test_second_run_reports_nothing_new_as_ok(self):
        await self.block().execute("", self.page, self.engine)
        engine2 = FakeEngine(history=self.service)
        res = await self.block().execute("", self.page, engine2)
        self.assertEqual(res, ActionResult.OK)
        self.assertIn("No new messages", engine2.text())

    async def test_nothing_new_can_be_made_a_failure_on_purpose(self):
        await self.block().execute("", self.page, self.engine)
        engine2 = FakeEngine(history=self.service)
        res = await self.block(fail_if_empty=True).execute("", self.page,
                                                           engine2)
        self.assertEqual(res, ActionResult.FAIL)

    async def test_appends_only_new_lines_on_a_later_run(self):
        await self.block().execute("", self.page, self.engine)
        self.page.append(raw("m6", idx=6))
        engine2 = FakeEngine(history=self.service)
        res = await self.block().execute("", self.page, engine2)
        self.assertEqual(res, ActionResult.OK)
        person = await self.repo.get_person("Nick")
        self.assertEqual(person["message_count"], 7)
        self.assertIn("1", engine2.text())

    async def test_reports_progress_while_it_runs(self):
        await self.block(chunk_size=2).execute("", self.page, self.engine)
        progress = [m for _l, m in self.engine.lines if "/" in m]
        self.assertGreaterEqual(len(progress), 2)

    async def test_not_a_private_tab_fails_loudly(self):
        self.page.tab = "room"
        res = await self.block().execute("", self.page, self.engine)
        self.assertEqual(res, ActionResult.FAIL)
        self.assertIn("not a private chat", self.engine.text().lower())
        rows = await self.db.fetchall("SELECT COUNT(*) FROM messages")
        self.assertEqual(rows[0][0], 0)

    async def test_room_tab_can_be_allowed_explicitly(self):
        self.page.tab = "room"
        res = await self.block(require_private=False).execute(
            "", self.page, self.engine)
        self.assertEqual(res, ActionResult.OK)

    async def test_memory_target_uses_the_remembered_nick(self):
        self.engine.selected_nick = "Nick"
        res = await self.block(target="memory_nick").execute(
            "", self.page, self.engine)
        self.assertEqual(res, ActionResult.OK)
        self.assertIsNotNone(await self.repo.get_person("Nick"))

    async def test_memory_target_without_a_nick_fails(self):
        res = await self.block(target="memory_nick").execute(
            "", self.page, self.engine)
        self.assertEqual(res, ActionResult.FAIL)
        self.assertIn("no nick", self.engine.text().lower())

    async def test_memory_target_never_files_under_the_wrong_person(self):
        self.engine.selected_nick = "SomebodyElse"
        res = await self.block(target="memory_nick").execute(
            "", self.page, self.engine)
        self.assertEqual(res, ActionResult.FAIL)
        self.assertIn("mismatch", self.engine.text().lower())
        self.assertIsNone(await self.repo.get_person("SomebodyElse"))

    async def test_missing_archive_service_is_a_clear_failure(self):
        engine = FakeEngine(history=None)
        res = await self.block().execute("", self.page, engine)
        self.assertEqual(res, ActionResult.FAIL)
        self.assertIn("archive", engine.text().lower())

    async def test_stop_is_reported_as_stopped_not_failed(self):
        page = FakePage([raw(f"m{i}", idx=i) for i in range(40)])
        parser = ChatParser(page, chunk_size=5, chunk_pause_ms=0)
        self.service.parser = parser
        engine = FakeEngine(history=self.service)
        calls = {"n": 0}

        def stopping():
            calls["n"] += 1
            return calls["n"] > 2

        engine.is_stopping = stopping
        res = await self.block(chunk_size=5).execute("", page, engine)
        self.assertEqual(res, ActionResult.OK)
        self.assertIn("stopped", engine.text().lower())
        rows = await self.db.fetchall("SELECT COUNT(*) FROM messages")
        self.assertGreater(rows[0][0], 0)
        self.assertLess(rows[0][0], 40)

    async def test_disabled_archive_is_reported(self):
        self.service.enabled = False
        res = await self.block().execute("", self.page, self.engine)
        self.assertEqual(res, ActionResult.FAIL)
        self.assertIn("disabled", self.engine.text().lower())

    async def test_max_messages_is_respected(self):
        page = FakePage([raw(f"m{i}", idx=i) for i in range(30)])
        self.service.parser = ChatParser(page, chunk_size=5, chunk_pause_ms=0)
        await self.block(max_messages=10).execute("", page, self.engine)
        rows = await self.db.fetchall("SELECT COUNT(*) FROM messages")
        self.assertEqual(rows[0][0], 10)


if __name__ == "__main__":
    unittest.main(verbosity=2)
