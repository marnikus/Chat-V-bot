"""Undo must put a deleted person BACK into the database — and say so
honestly when it cannot (bug report: "Undo Fails to Restore Deleted
Person", 2026-09-11).

The data layer is tombstone-based (RULE 14): a soft delete hides the
person row + their messages under one operation token; the undo of a
`delete_person` entry runs `repo.restore_person(nick, token)`.  What was
broken around it:

  * the restore result was IGNORED — a refused restore (tombstone no
    longer matches, row gone) left the person hidden forever while the
    user had already been told "archive restored";
  * (JS side, see tests/test_userdb_refresh_ui.js) the DB view could be
    frozen on a stale page, so even a successful restore never showed.

This file pins the DB half through the REAL bridge slot + REAL undo
service + REAL repo + REAL SQLite:

  * delete → undo puts the person AND their messages back (list_persons);
  * a zero-message person comes back too (0-row restore path);
  * undo → redo → undo stays consistent;
  * a refused restore surfaces an ERROR line + an `undo_failed` event —
    never a silent false success;
  * a redo of a delete whose person vanished warns the same way.

Run with:  python3 tests/test_userdb_undo_restore.py
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
from core.events import LogMessage, UserDbChanged  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_chat_parser_delta import FakePage, raw  # noqa: E402


class ConnectedPage(FakePage):
    is_connected = True


class RestoreCase(unittest.IsolatedAsyncioTestCase):
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
        # bus observers: the log lines + the UserDbChanged payloads
        self.bus = br._ctx.bus
        self.log_lines = []
        self.bus.subscribe(LogMessage, lambda e: self.log_lines.append(
            (e.level, e.message)))
        self.db_events = []
        self.bus.subscribe(UserDbChanged, lambda e: self.db_events.append(
            json.loads(e.payload)))
        self.wire = []
        br.userdb_changed.connect(lambda p: self.wire.append(json.loads(p)))

    async def asyncTearDown(self):
        await self.service.close()

    # ── helpers ──────────────────────────────────────────────────
    async def seed(self, nick="Mloni", count=5):
        self.page.partner = nick
        self.page.messages = [raw(f"m{i}", from_nick=nick, idx=i)
                              for i in range(count)]
        await self.service.collector.tick()

    async def visible(self, nick="Mloni"):
        page = await self.query.page(nick, limit=100)
        return [item["text"] for item in page["items"]]

    async def in_db(self, nick="Mloni"):
        page = await self.query.list_persons(limit=200)
        return nick in [p["nick"] for p in page["items"]]

    def error_lines(self):
        return [m for (level, m) in self.log_lines if level == "error"]

    def undo_failed_events(self):
        return [e for e in self.db_events if e.get("action") == "undo_failed"]

    async def wait_failed(self, timeout=3.0):
        """Wait until an `undo_failed` event lands (re-polls the filter —
        a snapshot list would never grow)."""
        step, waited = 0.01, 0.0
        while not self.undo_failed_events() and waited < timeout:
            await asyncio.sleep(step)
            waited += step
        self.assertTrue(self.undo_failed_events(),
                        "no undo_failed event arrived")

    async def _wait_new(self, events, timeout=3.0):
        """Wait until `events` grows past now (marker — the list itself is
        a bad condition, it is non-empty after the first event)."""
        marker = len(events)
        step, waited = 0.01, 0.0
        while len(events) <= marker and waited < timeout:
            await asyncio.sleep(step)
            waited += step
        self.assertGreater(len(events), marker, "no change event arrived")

    async def delete_and_wait(self, nick="Mloni"):
        self.assertTrue(self.bridge.history_delete_person(nick, False))
        await self._wait_new(self.wire)
        return self.wire[-1]

    async def undo_and_wait(self):
        result = json.loads(self.bridge.undo())
        await self._wait_new(self.db_events)
        self.assertTrue(any(e.get("action") in ("undo", "redo", "undo_failed")
                            for e in self.db_events))
        return result

    async def redo_and_wait_drain(self):
        self.bridge.redo()
        await self._wait_new(self.db_events)

    async def undo_and_wait_drain(self):
        """Wait for the undo/redo work that was already scheduled."""
        await self._wait_new(self.db_events)

    async def erase_row(self, nick="Mloni"):
        """Simulate intervening state: the person row is gone for good."""
        rows = await self.service.db.fetchall(
            "SELECT id FROM persons WHERE nick=?", (nick,))
        for row in rows:
            await self.service.db.execute(
                "DELETE FROM messages WHERE person_id=?", (row[0],))
        await self.service.db.execute(
            "DELETE FROM persons WHERE nick=?", (nick,))
        await self.service.db.commit()

    async def restamp_tombstone(self, nick="Mloni", foreign="foreign-token"):
        """Simulate intervening state: something re-stamped the rows."""
        rows = await self.service.db.fetchall(
            "SELECT id FROM persons WHERE nick=?", (nick,))
        self.assertTrue(rows, "the tombstoned row must exist")
        for row in rows:
            await self.service.db.execute(
                "UPDATE messages SET deleted_at=? WHERE person_id=?",
                (foreign, row[0]))
            await self.service.db.execute(
                "UPDATE persons SET deleted_at=? WHERE id=?",
                (foreign, row[0]))
        await self.service.db.commit()


# ═════════════════════════════════════════════════════════════════
# the restore itself
# ═════════════════════════════════════════════════════════════════
class TestPersonRestore(RestoreCase):
    async def test_delete_then_undo_puts_the_person_and_history_back(self):
        """The reported repro: delete → Ctrl+Z → the person is visible
        again in the database view's data (list_persons) with all
        messages."""
        await self.seed(count=5)
        await self.delete_and_wait()
        self.assertFalse(await self.in_db())
        result = await self.undo_and_wait()
        self.assertEqual(result["kind"], "archive")
        self.assertTrue(await self.in_db(),
                        "undo must re-show the person in the database")
        self.assertEqual(len(await self.visible()), 5,
                         "their whole history comes back too")
        self.assertEqual(self.error_lines(), [],
                         "a clean restore logs no errors")

    async def test_a_person_without_messages_comes_back_too(self):
        """Zero-row restore path: no messages under the token, yet the
        person row must un-tombstone (the HRP-13 guard must not misfire
        when token == the person's own stamp)."""
        await self.repo.ensure_person("Mloni")
        await self.delete_and_wait()
        self.assertFalse(await self.in_db())
        await self.undo_and_wait()
        self.assertTrue(await self.in_db(),
                        "a zero-message person is restored as well")
        self.assertEqual(await self.visible(), [])

    async def test_undo_redo_undo_stays_consistent(self):
        await self.seed(count=4)
        await self.delete_and_wait()
        self.assertFalse(await self.in_db())
        await self.undo_and_wait()
        self.assertTrue(await self.in_db())
        self.bridge.redo()
        await self.undo_and_wait_drain()
        self.assertFalse(await self.in_db(), "redo re-hides the person")
        await self.undo_and_wait()
        self.assertTrue(await self.in_db(), "and the next undo restores")
        self.assertEqual(len(await self.visible()), 4)

    async def test_undo_of_a_message_delete_still_works(self):
        """Regression: the restore plumbing change must not break the
        plain message-delete undo (restore_deleted happy path)."""
        await self.seed(count=5)
        page = await self.query.page("Mloni", limit=100)
        victim = page["items"][2]
        self.assertTrue(self.bridge.history_delete_message(
            "Mloni", str(victim["id"])))
        await self._wait_new(self.wire)
        self.assertEqual(len(await self.visible()), 4)
        self.bridge.undo()
        await self.undo_and_wait_drain()
        self.assertEqual(len(await self.visible()), 5)
        self.assertEqual(self.error_lines(), [])


# ═════════════════════════════════════════════════════════════════
# honest failures — never a silent false success
# ═════════════════════════════════════════════════════════════════
class TestHonestFailures(RestoreCase):
    async def test_refused_restore_surfaces_an_error(self):
        """HRP-13: the tombstone no longer matches the undo token
        (state changed after the delete). The person stays hidden AND
        the user is told exactly that — no 'archive restored' lie."""
        await self.seed(count=5)
        await self.delete_and_wait()
        await self.restamp_tombstone()
        self.bridge.undo()
        await self.wait_failed()
        self.assertFalse(await self.in_db(),
                         "a refused restore must not half-restore")
        self.assertEqual(len(await self.visible()), 0,
                         "the messages stay hidden too")
        self.assertTrue(any("Mloni" in m for m in self.error_lines()),
                        "the failure must appear as an error line: %r"
                        % self.log_lines)
        failed = self.undo_failed_events()[0]
        self.assertEqual(failed["nick"], "Mloni")
        self.assertEqual(failed["op"], "delete_person")
        # the wire must carry the same action so the UI can react
        self.assertTrue(any(e.get("action") == "undo_failed"
                            for e in self.wire))

    async def test_missing_person_row_surfaces_an_error(self):
        """The row is gone for good (purged / world switched): undo must
        fail loudly, not swallow the False return."""
        await self.seed(count=5)
        await self.delete_and_wait()
        await self.erase_row()
        self.bridge.undo()
        await self.wait_failed()
        self.assertTrue(any("Mloni" in m for m in self.error_lines()),
                        "missing row must be an error line: %r"
                        % self.log_lines)
        self.assertIn("no longer exists",
                      self.undo_failed_events()[0].get("reason", ""))

    async def test_redo_into_a_vanished_person_fails_loudly(self):
        """delete → undo → row vanishes → redo: re-deleting a person who
        no longer exists must surface, not crash, not claim success."""
        await self.seed(count=3)
        await self.delete_and_wait()
        await self.undo_and_wait()
        self.assertTrue(await self.in_db())
        await self.erase_row()
        self.bridge.redo()
        await self.wait_failed()
        self.assertTrue(any("Mloni" in m for m in self.error_lines()))

    async def test_undo_of_message_delete_with_purged_rows_warns(self):
        """The hidden rows were purged while hidden: nothing can come
        back — a warning says so, the person stays intact."""
        await self.seed(count=5)
        page = await self.query.page("Mloni", limit=100)
        token = await self.repo.soft_delete_message(
            "Mloni", page["items"][0]["id"])
        self.assertTrue(token)
        # record the op on the timeline the same way the bridge does
        self.bridge._ctx.undo.push("archive", {
            "op": "delete_message", "nick": "Mloni", "token": token,
            "message_id": int(page["items"][0]["id"])})
        await self.repo.purge_deleted("Mloni")
        self.bridge.undo()
        await self.undo_and_wait_drain()
        person = await self.repo.get_person("Mloni")
        self.assertIsNotNone(person, "the person row survives")
        self.assertEqual(len(await self.visible()), 4,
                         "the other four messages stay visible")
        self.assertTrue(
            any(level == "warn" and "0 messages" in m
                for (level, m) in self.log_lines),
            "0-row restore of a real token must warn: %r"
            % self.log_lines)
        self.assertEqual(self.error_lines(), [],
                         "re-collected/purged content is not an error "
                         "when the person still exists")


if __name__ == "__main__":
    unittest.main(verbosity=2)
