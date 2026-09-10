"""Clearing a history must re-arm the collector (Bug 3 of 2026-09-08).

The old behaviour: 🧹 Clear hid the rows but left the resume cursor and
every `dup_key` in place, so the collector answered "No new messages"
forever and nothing was ever re-collected.

The new contract:

  * clear → the person stays, the cursor resets ("already collected"
    markers gone), the NEXT tick re-collects the whole conversation;
  * the counters tell the truth: "Added" equals the alive rows in the DB;
  * hidden rows can never absorb a write (no "added" into deleted rows);
  * Ctrl+Z after a re-collection does not resurrect duplicates;
  * a single deleted message still never comes back by collecting.

Per AGENT_RULES RULE 8 this drives the REAL service, repo, query layer and
collector against a real SQLite file and a CDP-shaped fake page.

Run with:  python3 tests/test_recollect_after_clear.py
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
from services.history import HistoryService  # noqa: E402

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


class RecollectCase(unittest.IsolatedAsyncioTestCase):
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

    async def seed(self, nick="Svetik25", count=5):
        self.page.partner = nick
        self.page.messages = [raw(f"m{i}", from_nick=nick, idx=i)
                              for i in range(count)]
        await self.service.collector.tick()

    async def visible(self, nick="Svetik25"):
        page = await self.query.page(nick, limit=100)
        return [item["text"] for item in page["items"]]

    async def stored_rows(self):
        rows = await self.service.db.fetchall("SELECT COUNT(*) FROM messages")
        return rows[0][0]

    async def cursor(self, nick="Svetik25"):
        person = await self.repo.get_person(nick)
        return await self.repo.get_cursor(int(person["id"]))


# ═════════════════════════════════════════════════════════════════
# the clear → re-collect cycle
# ═════════════════════════════════════════════════════════════════
class TestClearRecollects(RecollectCase):
    async def test_clearing_resets_the_collected_markers(self):
        await self.seed()
        cursor = await self.cursor()
        self.assertTrue(cursor["bootstrapped"])
        token = await self.repo.soft_delete_history("Svetik25")
        self.assertTrue(token)
        cursor = await self.cursor()
        self.assertFalse(cursor["bootstrapped"],
                         "the 'already collected' marker must reset")
        self.assertFalse(cursor["full_scan_complete"])
        self.assertEqual(cursor["tail_keys"], [])
        self.assertEqual(cursor["head_any"], "")

    async def test_the_next_tick_recollects_the_whole_chat(self):
        await self.seed()
        await self.repo.soft_delete_history("Svetik25")
        self.assertEqual(await self.visible(), [])
        await self.service.collector.tick()
        texts = await self.visible()
        self.assertEqual(len(texts), 5,
                         "the conversation is re-collected as if first visit")
        self.assertEqual(sorted(texts),
                         sorted(f"m{i}" for i in range(5)))

    async def test_recollect_stores_no_hidden_duplicates(self):
        await self.seed()
        await self.repo.soft_delete_history("Svetik25")
        await self.service.collector.tick()
        # the hidden tombstones stay until Ctrl+Z (or purge) resolves them;
        # what matters is what the user can SEE and that undo collapses them
        self.assertEqual(await self.stored_rows(), 10)
        self.assertEqual(len(await self.visible()), 5)

    async def test_the_person_and_their_nicks_survive_the_clear(self):
        await self.seed()
        await self.service.collector.tick()          # my_nicks recorded
        person = await self.repo.get_person("Svetik25")
        self.assertTrue(person.get("my_nicks"))
        await self.repo.soft_delete_history("Svetik25")
        person = await self.repo.get_person("Svetik25")
        self.assertIsNotNone(person)
        self.assertFalse(person.get("deleted_at"))
        self.assertTrue(person.get("my_nicks"),
                        "observation data (my nicks) is NOT cleared")

    async def test_clear_with_no_messages_still_re_arms(self):
        await self.seed()
        await self.repo.purge_deleted("Svetik25")     # rows fully gone
        person = await self.repo.get_person("Svetik25")
        self.assertIsNotNone(person)
        self.bridge.history_clear_person("Svetik25")
        await wait_for(self.changed)
        cursor = await self.cursor()
        self.assertFalse(cursor["bootstrapped"])

    async def test_the_bridge_clear_resets_the_cursor_and_pokes_the_radar(self):
        await self.seed()
        collector = self.service.collector
        collector.person_cleared("Svetik25")          # direct poke first
        self.bridge.history_clear_person("Svetik25")
        await wait_for(self.changed)
        cursor = await self.cursor()
        self.assertFalse(cursor["bootstrapped"])
        actions = [c.get("action") for c in self.changed]
        self.assertIn("cleared", actions)
        self.assertEqual(collector.state_payload()["total"], 0,
                         "the Radar must not keep showing the old total")

    async def test_an_app_restart_between_clear_and_recollect(self):
        """Re-opening the file must NOT re-arm the hidden rows' identity:
        the released dup_keys stay released, so the promised re-collection
        still happens after a restart."""
        await self.seed()
        await self.repo.soft_delete_history("Svetik25")
        from stores.history_db import HistoryDB
        await self.service.db.close()
        db2 = HistoryDB(self.service.db.path)
        await db2.init()
        keys = await db2.fetchall(
            "SELECT dup_key FROM messages WHERE deleted_at<>''")
        self.assertEqual([k[0] for k in keys], [""] * 5,
                         "hidden tombstones stay identity-released")
        await db2.close()
        # the collector works against the same reopened file
        db3 = HistoryDB(self.service.db.path)
        await db3.init()
        self.service.repo.db = db3
        self.service.query.db = db3
        self.service.media.db = db3
        self.service.db = db3
        try:
            await self.service.collector.tick()
            self.assertEqual(len(await self.visible()), 5,
                             "re-collection happens after the restart too")
        finally:
            await db3.close()


# ═════════════════════════════════════════════════════════════════
# counters (Bug 4: "Added 25" vs "In archive 0")
# ═════════════════════════════════════════════════════════════════
class TestCountersTellTheTruth(RecollectCase):
    async def test_recollected_added_equals_the_alive_rows(self):
        await self.seed()
        await self.repo.soft_delete_history("Svetik25")
        await self.service.collector.tick()
        payload = self.service.collector.state_payload()
        self.assertEqual(payload["sync_added"], 5)
        self.assertEqual(payload["total"], 5,
                         "'In archive' must equal what the DB really holds")

    async def test_hidden_rows_are_never_filled_or_counted(self):
        """A media-recovery pass must not count writes into hidden rows."""
        await self.seed(count=2)
        await self.repo.soft_delete_history("Svetik25")
        person = await self.repo.get_person("Svetik25")
        pid = int(person["id"])
        self.assertFalse(await self.repo.has_repairable_media(pid))
        stats = await self.repo.recover_media(pid, [], media=None)
        self.assertEqual(stats["scanned"], 0,
                         "hidden rows must not enter the repair pass")

    async def test_an_empty_slot_is_filled_not_duplicated(self):
        """A line parsed before its text rendered (empty row) is healed in
        place when the real text arrives — not stored twice (Bug 2)."""
        empty = raw("", from_nick="Svetik25", time="10:00")
        await self.repo.append("Svetik25", [empty], my_nick="Me",
                               align=False)
        rows = await self.service.db.fetchall(
            "SELECT id, text FROM messages ORDER BY id")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][1], "", "the too-early parse stored an empty row")
        real = raw("Привет :-*", from_nick="Svetik25", time="10:00")
        await self.repo.append("Svetik25", [real], my_nick="Me",
                               align=False)
        rows = await self.service.db.fetchall(
            "SELECT id, text FROM messages ORDER BY id")
        self.assertEqual(len(rows), 1, "the empty slot must be filled, "
                         "not left behind next to a duplicate")
        self.assertEqual(rows[0][1], "Привет :-*")


# ═════════════════════════════════════════════════════════════════
# undo after re-collection
# ═════════════════════════════════════════════════════════════════
class TestUndoAfterRecollect(RecollectCase):
    async def test_undo_after_a_recollect_does_not_duplicate(self):
        await self.seed()
        token = await self.repo.soft_delete_history("Svetik25")
        await self.service.collector.tick()           # re-collected
        restored = await self.repo.restore_deleted("Svetik25", token)
        self.assertEqual(restored, 0,
                         "every line is already visible again")
        self.assertEqual(await self.visible(), [f"m{i}" for i in range(5)])
        self.assertEqual(await self.stored_rows(), 5,
                         "the stale tombstones collapsed — no doubles")

    async def test_undo_before_a_recollect_brings_everything_back(self):
        await self.seed()
        token = await self.repo.soft_delete_history("Svetik25")
        restored = await self.repo.restore_deleted("Svetik25", token)
        self.assertEqual(restored, 5)
        self.assertEqual(await self.visible(), [f"m{i}" for i in range(5)])
        keys = [r[0] for r in await self.service.db.fetchall(
            "SELECT dup_key FROM messages")]
        self.assertTrue(all(keys), "restored rows carry their identity again")

    async def test_undo_after_partial_recollect_fills_only_the_gap(self):
        await self.seed(count=4)
        token = await self.repo.soft_delete_history("Svetik25")
        # only two of the four lines are back in the DOM when the tick runs
        self.page.messages = [raw("m0", from_nick="Svetik25", idx=0),
                              raw("m1", from_nick="Svetik25", idx=1)]
        await self.service.collector.tick()
        restored = await self.repo.restore_deleted("Svetik25", token)
        self.assertEqual(restored, 2,
                         "only the lines the collector did NOT bring back")
        texts = await self.visible()
        self.assertEqual(sorted(texts), ["m0", "m1", "m2", "m3"])
        self.assertEqual(await self.stored_rows(), 4)

    async def test_a_single_deleted_message_stays_deleted(self):
        await self.seed()
        page = await self.query.page("Svetik25", limit=100)
        victim = page["items"][2]
        token = await self.repo.soft_delete_message("Svetik25", victim["id"])
        self.assertTrue(token)
        await self.service.collector.tick()
        self.assertNotIn(victim["text"], await self.visible())
        self.assertEqual(await self.stored_rows(), 5,
                         "single-message identity is kept — no new row")

    async def test_deleting_the_person_keeps_recollection_working(self):
        await self.seed()
        await self.repo.delete_person("Svetik25")
        cursor = await self.cursor()
        self.assertFalse(cursor["bootstrapped"])
        person = await self.repo.get_person("Svetik25")
        self.assertTrue(person.get("deleted_at"))
        # the tick re-collects onto the (still tombstoned) person without
        # duplicating the hidden rows
        await self.service.collector.tick()
        self.assertEqual(await self.stored_rows(), 10)
        restored = await self.repo.restore_person("Svetik25")
        self.assertTrue(restored)
        self.assertEqual(await self.visible(), [f"m{i}" for i in range(5)])
        self.assertEqual(await self.stored_rows(), 5,
                         "restore collapsed the re-collected doubles")


# ═════════════════════════════════════════════════════════════════
# the partner uses a different name now (bug report's "diff name" case)
# ═════════════════════════════════════════════════════════════════
class TestPartnerRename(RecollectCase):
    async def test_same_conversation_under_a_new_title_renames_the_person(self):
        await self.seed(nick="Svetik25")
        person_before = await self.repo.get_person("Svetik25")
        # the partner renamed IN THE OPEN PANE; the site re-renders every
        # line accordingly (the agent reports the same pane element)
        self.page.pane_same = True
        self.page.partner = "Svetochka❤️"
        self.page.messages = [raw(f"m{i}", from_nick="Svetochka❤️", idx=i)
                              for i in range(5)]
        await self.service.collector.tick()
        renamed = await self.repo.get_person("Svetochka❤️")
        self.assertIsNotNone(renamed, "the new nick exists")
        self.assertEqual(int(renamed["id"]), int(person_before["id"]),
                         "it IS the old person row, renamed in place")
        gone = await self.repo.get_person("Svetik25")
        self.assertIsNone(gone, "the old nick is no longer a separate person")
        self.assertEqual(len(await self.visible("Svetochka❤️")), 5,
                         "history continues — nothing forks or duplicates")
        self.assertEqual(await self.stored_rows(), 5)

    async def test_a_genuinely_new_person_is_not_merged(self):
        await self.seed(nick="Svetik25")
        person_before = await self.repo.get_person("Svetik25")
        # a different conversation in a DIFFERENT pane: the user switched
        # tabs, so the agent reports a new pane element
        self.page.pane_same = False
        self.page.partner = "Angelochenek"
        self.page.messages = [raw(f"other{i}", from_nick="Angelochenek",
                                  idx=i) for i in range(5)]
        await self.service.collector.tick()
        other = await self.repo.get_person("Angelochenek")
        self.assertIsNotNone(other)
        self.assertNotEqual(int(other["id"]), int(person_before["id"]))
        self.assertIsNotNone(await self.repo.get_person("Svetik25"))

    async def test_identical_content_in_another_pane_is_not_a_rename(self):
        """Two different people saying the same words at the same minute in
        different panes must never be merged (the pane check is what
        disambiguates a rename from a conversation switch)."""
        await self.seed(nick="Anna")
        self.page.pane_same = False
        self.page.partner = "Olga"
        self.page.messages = [raw(f"m{i}", from_nick="Olga", idx=i)
                              for i in range(5)]
        await self.service.collector.tick()
        olga = await self.repo.get_person("Olga")
        anna = await self.repo.get_person("Anna")
        self.assertIsNotNone(olga)
        self.assertIsNotNone(anna, "Anna must survive as her own person")
        self.assertNotEqual(int(olga["id"]), int(anna["id"]))

    async def test_own_nick_rename_is_adopted_and_collecting_continues(self):
        await self.seed(nick="Svetik25")
        # the user themselves now appears as "Пошлый01" — the configured
        # "Me" is stale and must not make the gate refuse the chat
        self.page.me = "Пошлый01"
        self.page.messages = ([raw(f"m{i}", from_nick="Svetik25", idx=i)
                               for i in range(5)]
                              + [raw("новое", direction="out", from_nick="Пошлый01",
                                          idx=5)])
        await self.service.collector.tick()
        self.assertEqual(self.service.collector.my_nick, "Пошлый01")
        page = await self.query.page("Svetik25", limit=100)
        texts = [item["text"] for item in page["items"]]
        self.assertIn("новое", texts, "collecting continues after the rename")
        self.assertEqual(len(texts), 6)

    async def test_own_nick_rename_with_old_outbound_lines_still_collects(self):
        await self.seed(nick="Svetik25")
        # outbound history still shows the OLD nick; the pane self-reports
        # the NEW one — the old value must not look like a "stranger"
        self.page.me = "Пошлый01"
        self.page.messages = ([raw(f"m{i}", from_nick="Svetik25", idx=i)
                               for i in range(5)]
                              + [raw("старое", direction="out", from_nick="Me",
                                          idx=5)])
        await self.service.collector.tick()
        page = await self.query.page("Svetik25", limit=100)
        self.assertEqual(len(page["items"]), 6,
                         "the gate accepted the pane's 'me' over the stale "
                         "configured nick")


if __name__ == "__main__":
    unittest.main()
