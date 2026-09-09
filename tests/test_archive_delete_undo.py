"""Removing things from the message history — and getting them back.

Three destructive actions the user asked for, all reversible with the ONE
global Ctrl+Z (AGENT_RULES RULE 12):

  1. remove a person WITH their entire history (they leave the People list
     too, and one undo restores both halves);
  2. remove ONE message from a conversation;
  3. clear a whole conversation but KEEP the person in the database.

They are implemented as soft deletes: rows are stamped with one operation
token (RULE 14 — the archive is append-only, a tombstone hides a row), so
the undo entry never has to carry message bodies and the reversal is a
single UPDATE.

Per AGENT_RULES RULE 8 this drives the REAL repo, the REAL query layer and
the REAL bridge slots against a real SQLite file.

Run with:  python3 tests/test_archive_delete_undo.py
"""

import asyncio
import json
import os
import sys
import tempfile
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QObject  # noqa: E402

from backend.bridge import Bridge  # noqa: E402
from backend.config_manager import ConfigManager  # noqa: E402
from backend.history_service import HistoryService  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_chat_parser_delta import FakePage, raw  # noqa: E402


class ConnectedPage(FakePage):
    is_connected = True


async def wait_for(box, timeout=3.0):
    step, waited = 0.01, 0.0
    while not box and waited < timeout:
        await asyncio.sleep(step)
        waited += step
    return box


class ArchiveCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.dir = tempfile.mkdtemp()
        self.cfg = ConfigManager(os.path.join(self.dir, "config.json"))
        self.page = ConnectedPage([])
        self.service = HistoryService(
            cdp=self.page, config=self.cfg,
            db_path=os.path.join(self.dir, "history.db"))
        await self.service.init()
        self.service.collector.configure(my_nick="Me")
        self.repo = self.service.repo
        self.query = self.service.query
        br = Bridge.__new__(Bridge)
        QObject.__init__(br)
        br._config = self.cfg
        br._engine = types.SimpleNamespace(load_stack=lambda _b: None)
        br._memory = None
        br._presets = None
        br.attach_history(self.service)
        self.bridge = br
        self.changed = []
        br.userdb_changed.connect(lambda p: self.changed.append(json.loads(p)))

    async def asyncTearDown(self):
        await self.service.close()

    async def seed(self, nick="Nick", count=5):
        self.page.partner = nick
        self.page.messages = [raw(f"m{i}", from_nick=nick, idx=i)
                              for i in range(count)]
        await self.service.collector.tick()

    async def visible(self, nick="Nick"):
        page = await self.query.page(nick, limit=100)
        return [item["text"] for item in page["items"]]

    async def stored_rows(self):
        rows = await self.service.db.fetchall("SELECT COUNT(*) FROM messages")
        return rows[0][0]


# ═════════════════════════════════════════════════════════════════
# the repository
# ═════════════════════════════════════════════════════════════════
class TestSoftDeletes(ArchiveCase):
    async def test_one_message_disappears_from_the_conversation(self):
        await self.seed(count=5)
        page = await self.query.page("Nick", limit=100)
        victim = page["items"][2]
        token = await self.repo.soft_delete_message("Nick", victim["id"])
        self.assertTrue(token, "a delete must return its operation token")
        left = await self.visible()
        self.assertNotIn(victim["text"], left)
        self.assertEqual(len(left), 4)

    async def test_the_row_is_hidden_not_erased(self):
        await self.seed(count=5)
        page = await self.query.page("Nick", limit=100)
        await self.repo.soft_delete_message("Nick", page["items"][0]["id"])
        self.assertEqual(await self.stored_rows(), 5,
                         "the archive is append-only: the row is tombstoned")

    async def test_restoring_brings_exactly_that_message_back(self):
        await self.seed(count=5)
        page = await self.query.page("Nick", limit=100)
        victim = page["items"][1]
        token = await self.repo.soft_delete_message("Nick", victim["id"])
        await self.repo.restore_deleted("Nick", token)
        self.assertIn(victim["text"], await self.visible())
        self.assertEqual(len(await self.visible()), 5)

    async def test_clearing_a_chat_keeps_the_person(self):
        await self.seed(count=5)
        token = await self.repo.soft_delete_history("Nick")
        self.assertTrue(token)
        self.assertEqual(await self.visible(), [])
        person = await self.repo.get_person("Nick")
        self.assertIsNotNone(person, "the person stays in the database")
        self.assertFalse(person.get("deleted_at"))

    async def test_a_cleared_chat_comes_back_whole(self):
        await self.seed(count=5)
        result = await self.service.reset_conversation("Nick")
        self.assertEqual(await self.stored_rows(), 0)
        await self.service.undo_conversation_reset("Nick", result["snapshot"])
        self.assertEqual(len(await self.visible()), 5)

    async def test_deleting_a_person_erases_them_and_their_message_tracking(self):
        await self.seed(count=5)
        token = self.repo.new_op_token()
        await self.repo.delete_person("Nick", hard=False, token=token)
        listed = await self.query.list_persons(limit=50)
        self.assertNotIn("Nick", [p["nick"] for p in listed["items"]])
        self.assertEqual(await self.stored_rows(), 0, "the active archive must forget the messages")
        self.assertIsNone(await self.repo.get_person("Nick"))

    async def test_restoring_a_person_restores_their_messages_too(self):
        await self.seed(count=5)
        result = await self.service.reset_conversation("Nick", delete_person=True)
        await self.service.undo_conversation_reset("Nick", result["snapshot"])
        listed = await self.query.list_persons(limit=50)
        self.assertIn("Nick", [p["nick"] for p in listed["items"]])
        self.assertEqual(len(await self.visible()), 5)

    async def test_restoring_only_touches_its_own_operation(self):
        """Two deletes, one undo: the other delete must stay in force."""
        await self.seed(count=5)
        page = await self.query.page("Nick", limit=100)
        first = await self.repo.soft_delete_message("Nick", page["items"][0]["id"])
        second = await self.repo.soft_delete_message("Nick", page["items"][1]["id"])
        self.assertNotEqual(first, second, "each delete gets its own token")
        await self.repo.restore_deleted("Nick", second)
        left = await self.visible()
        self.assertEqual(len(left), 4)
        self.assertNotIn(page["items"][0]["text"], left)
        self.assertIn(page["items"][1]["text"], left)

    async def test_the_counters_follow_the_visible_messages(self):
        await self.seed(count=5)
        stats = await self.query.person_stats("Nick")
        self.assertEqual(stats["messages"], 5)
        result = await self.service.reset_conversation("Nick")
        stats = await self.query.person_stats("Nick")
        self.assertEqual(stats["messages"], 0)
        await self.service.undo_conversation_reset("Nick", result["snapshot"])
        stats = await self.query.person_stats("Nick")
        self.assertEqual(stats["messages"], 5)

    async def test_a_deleted_message_never_comes_back_by_collecting_again(self):
        """Re-collecting the same page must not resurrect a hidden message."""
        await self.seed(count=5)
        page = await self.query.page("Nick", limit=100)
        await self.repo.soft_delete_message("Nick", page["items"][2]["id"])
        await self.service.collector.tick()
        self.assertEqual(len(await self.visible()), 4)
        self.assertEqual(await self.stored_rows(), 5, "no duplicate rows")

    async def test_purging_finally_erases_the_hidden_rows(self):
        await self.seed(count=5)
        for row in (await self.query.page("Nick"))["items"]:
            await self.repo.soft_delete_message("Nick", row["id"])
        gone = await self.repo.purge_deleted("Nick")
        self.assertEqual(gone, 5)
        self.assertEqual(await self.stored_rows(), 0)

    async def test_search_does_not_return_deleted_messages(self):
        await self.seed(count=5)
        page = await self.query.page("Nick", limit=100)
        victim = page["items"][3]
        await self.repo.soft_delete_message("Nick", victim["id"])
        found = await self.query.search_person("Nick", victim["text"])
        self.assertEqual(found["items"], [])


# ═════════════════════════════════════════════════════════════════
# the bridge slots + the global timeline
# ═════════════════════════════════════════════════════════════════
class TestDeleteSlots(ArchiveCase):
    async def test_deleting_one_message_is_one_undo_step(self):
        await self.seed(count=5)
        page = await self.query.page("Nick", limit=100)
        victim = page["items"][2]
        self.assertTrue(self.bridge.history_delete_message("Nick",
                                                           str(victim["id"])))
        await wait_for(self.changed)
        self.assertEqual(len(await self.visible()), 4)
        history, index = self.bridge._get_global_history()
        self.assertEqual([e["kind"] for e in history], ["archive"])
        self.assertEqual(history[0]["value"]["op"], "delete_message")
        self.assertEqual(index, 0)

    async def test_undo_restores_that_message(self):
        await self.seed(count=5)
        page = await self.query.page("Nick", limit=100)
        victim = page["items"][2]
        self.bridge.history_delete_message("Nick", str(victim["id"]))
        await wait_for(self.changed)
        self.changed.clear()
        result = json.loads(self.bridge.undo())
        self.assertEqual(result["kind"], "archive")
        await wait_for(self.changed)
        self.assertIn(victim["text"], await self.visible())

    async def test_redo_removes_it_again(self):
        await self.seed(count=5)
        page = await self.query.page("Nick", limit=100)
        victim = page["items"][2]
        self.bridge.history_delete_message("Nick", str(victim["id"]))
        await wait_for(self.changed)
        self.bridge.undo()
        await asyncio.sleep(0.15)
        self.bridge.redo()
        await asyncio.sleep(0.15)
        self.assertNotIn(victim["text"], await self.visible())

    async def test_clearing_the_chat_keeps_the_person_and_is_undoable(self):
        await self.seed(count=5)
        self.assertTrue(self.bridge.history_clear_person("Nick"))
        await wait_for(self.changed)
        self.assertEqual(await self.visible(), [])
        self.assertIsNotNone(await self.repo.get_person("Nick"))
        self.changed.clear()
        self.bridge.undo()
        await wait_for(self.changed)
        self.assertEqual(len(await self.visible()), 5)

    async def test_deleting_the_person_removes_them_from_the_list(self):
        await self.seed(count=5)
        self.assertTrue(self.bridge.history_delete_person("Nick", False))
        await wait_for(self.changed)
        listed = await self.query.list_persons(limit=50)
        self.assertNotIn("Nick", [p["nick"] for p in listed["items"]])

    async def test_undoing_a_person_delete_restores_the_conversation(self):
        await self.seed(count=5)
        self.bridge.history_delete_person("Nick", False)
        await wait_for(self.changed)
        self.changed.clear()
        self.bridge.undo()
        await wait_for(self.changed)
        listed = await self.query.list_persons(limit=50)
        self.assertIn("Nick", [p["nick"] for p in listed["items"]])
        self.assertEqual(len(await self.visible()), 5)

    async def test_an_empty_nick_is_refused_without_touching_anything(self):
        await self.seed(count=5)
        self.assertFalse(self.bridge.history_delete_person("   ", False))
        self.assertFalse(self.bridge.history_clear_person(""))
        self.assertFalse(self.bridge.history_delete_message("Nick", "0"))
        self.assertEqual(self.bridge._get_global_history()[0], [])

    async def test_deletes_share_the_timeline_with_the_other_panels(self):
        await self.seed(count=5)
        self.bridge.push_global_history("stack", json.dumps([]))
        self.bridge.history_clear_person("Nick")
        await wait_for(self.changed)
        kinds = [e["kind"] for e in self.bridge._get_global_history()[0]]
        self.assertEqual(kinds, ["stack", "archive"])
        self.assertEqual(json.loads(self.bridge.undo())["kind"], "archive")

    async def test_the_ui_is_told_what_happened(self):
        await self.seed(count=5)
        self.bridge.history_clear_person("Nick")
        await wait_for(self.changed)
        self.assertEqual(self.changed[-1]["action"], "cleared")
        self.assertEqual(self.changed[-1]["nick"], "Nick")


class TestUiWiring(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        base = os.path.join(os.path.dirname(__file__), "..", "ui")
        def read(*parts):
            with open(os.path.join(base, *parts), encoding="utf-8") as fh:
                return fh.read()

        cls.html = read("index.html")
        cls.store = read("js", "history-store.js")
        cls.view = read("js", "history-view.js")
        cls.db = read("js", "history-db.js")

    def test_a_message_row_carries_a_delete_button(self):
        self.assertIn("msg-del", self.view)
        self.assertIn("onDeleteMessage", self.view)
        self.assertIn("onDeleteMessage", self.store)

    def test_the_history_window_can_clear_a_chat_and_remove_a_person(self):
        self.assertIn("historyClearBtn", self.html)
        self.assertIn("historyDeletePersonBtn", self.html)
        self.assertIn("history_clear_person", self.store)
        self.assertIn("history_delete_person", self.store)

    def test_the_storage_table_offers_both_removals(self):
        self.assertIn("history_clear_person", self.db)
        self.assertIn("history_delete_person", self.db)

    def test_the_wording_tells_the_user_it_is_undoable(self):
        self.assertIn("Ctrl+Z", self.store)
        self.assertIn("Ctrl+Z", self.db)


if __name__ == "__main__":
    unittest.main(verbosity=2)
