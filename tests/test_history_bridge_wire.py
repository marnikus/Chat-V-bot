"""D4 — HistoryBridge wire contract, the gaps (design IDs H-2*, H-8..H-14).

`tests/test_history_bridge.py` pins reads/paging/crossing/search/stats/
delete+restore/media. This file pins what it does not:

  H-2b interleaved answers carry the payload of THEIR req_id
  H-4b `around` (jump-to-message) returns a window + stats + my_nick
  H-8  clear_history hides messages but KEEPS the person + cursor floor,
       pushes an undo entry, emits userdb_changed {action:"cleared"}
  H-9  delete_message removes ONE message; a second call on the same id
       pushes no second undo entry
  H-10 every slot without a running archive answers via history_error
       (or False) — never raises (fresh-profile safety, C-1)
  H-12 merge folds the source person's rows into the target
  H-13 purge erases previously soft-deleted messages for good
  H-14 corrupt options/query JSON still answers with defaults
  H-15 userdb_page enriches items with `labels` (empty when none)

Run:  python -m pytest tests/test_history_bridge_wire.py
"""

import asyncio
import json
import os
import sys
import tempfile
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtCore import QObject  # noqa: E402

from backend.bridge import Bridge  # noqa: E402
from backend.config_manager import ConfigManager  # noqa: E402
from backend.history_service import HistoryService  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_chat_parser_delta import FakePage, raw  # noqa: E402
from test_history_bridge import ConnectedPage, wait_for  # noqa: E402


class WireCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.dir = tempfile.mkdtemp()
        self.cfg = ConfigManager(os.path.join(self.dir, "config.json"))
        self.page = ConnectedPage([raw(f"m{i}", idx=i) for i in range(8)])
        self.service = HistoryService(
            cdp=self.page, config=self.cfg,
            db_path=os.path.join(self.dir, "history.db"))
        await self.service.init()
        self.service.collector.configure(my_nick="Me")
        br = Bridge.__new__(Bridge)
        QObject.__init__(br)
        br._config = self.cfg
        br._engine = types.SimpleNamespace(load_stack=lambda blocks: None)
        br._memory = None
        br._presets = None
        br.attach_history(self.service)
        self.bridge = br
        self.errors = []
        br.history_error.connect(lambda s, m: self.errors.append((s, m)))
        self.changed = []
        br.userdb_changed.connect(lambda p: self.changed.append(json.loads(p)))

    async def asyncTearDown(self):
        await self.service.close()

    async def seed(self, nick="Nick", count=8):
        self.page.partner = nick
        self.page.messages = [raw(f"m{i}", from_nick=nick, idx=i)
                              for i in range(count)]
        await self.service.collector.tick()

    async def ask(self, slot, *args, signal=None):
        box = []
        signal.connect(lambda *a: box.append(a))
        slot(*args)
        await wait_for(box)
        self.assertTrue(box, "the bridge never answered")
        return box[-1]

    # ── H-2b: interleaved answers match their own request ────────
    async def test_H2b_interleaved_payloads_match_their_ids(self):
        await self.seed("Anna", count=3)
        self.page.partner = "Boris"
        self.page.messages = [raw(f"b{i}", from_nick="Boris", idx=i)
                              for i in range(5)]
        await self.service.collector.tick()
        box = []
        self.bridge.history_page_ready.connect(lambda *a: box.append(a))
        self.bridge.history_open("A", "Anna", "{}")
        self.bridge.history_open("B", "Boris", "{}")
        while len(box) < 2:
            await asyncio.sleep(0.01)
        by_id = {req: json.loads(payload) for req, payload in box[:2]}
        self.assertEqual(by_id["A"]["nick"], "Anna")
        self.assertEqual(by_id["B"]["nick"], "Boris")
        self.assertEqual(by_id["A"]["req_id"], "A")
        self.assertEqual(by_id["B"]["req_id"], "B")

    # ── H-4b: jump-to-message window ─────────────────────────────
    async def test_H4b_around_returns_window_with_stats(self):
        await self.seed(count=20)
        _req, payload = await self.ask(
            self.bridge.history_page, "j1", "Nick",
            json.dumps({"around": 10, "radius": 3}),
            signal=self.bridge.history_page_ready)
        data = json.loads(payload)
        ords = [item["ord"] for item in data["items"]]
        self.assertIn(10, ords, "the anchor row must be in the window")
        self.assertLessEqual(max(ords) - min(ords), 7,
                             "radius bounds the window")
        self.assertIn("stats", data)
        self.assertEqual(data["my_nick"], "Me")

    # ── H-8: clear keeps the person ──────────────────────────────
    async def test_H8_clear_person_keeps_person_clears_messages(self):
        await self.seed(count=6)
        self.assertTrue(self.bridge.history_clear_person("Nick"))
        await wait_for(self.changed)
        page = await self.service.page("Nick")
        self.assertEqual(page["items"], [], "messages must be hidden")
        person = await self.service.repo.get_person("Nick")
        self.assertIsNotNone(person, "the person must survive a clear")
        # the collector treats the chat as never-collected (Bug 3 fix):
        # cursor floor survives so re-collection starts after the past
        cursor = await self.service.repo.get_cursor("Nick")
        self.assertIsNotNone(cursor)
        entry = [e for e in self.bridge._get_global_history()[0]
                 if e["kind"] == "archive"]
        self.assertTrue(any(e["value"].get("op") == "clear_history"
                            for e in entry), "clear must be undoable")
        self.assertEqual(self.changed[-1]["action"], "cleared")
        self.assertTrue(self.changed[-1]["ok"])

    # ── H-9: single-message delete ───────────────────────────────
    async def test_H9_delete_message_is_precise(self):
        await self.seed(count=5)
        page = await self.service.page("Nick")
        victim = page["items"][2]
        self.assertTrue(self.bridge.history_delete_message(
            "Nick", str(victim["id"])))
        await wait_for(self.changed)
        page2 = await self.service.page("Nick")
        ids = [item["id"] for item in page2["items"]]
        self.assertNotIn(victim["id"], ids)
        self.assertEqual(len(ids), 4, "siblings must survive")
        entries = [e for e in self.bridge._get_global_history()[0]
                   if e["kind"] == "archive"]
        self.assertEqual(len(entries), 1)
        # deleting the same id again must not push a second entry
        self.bridge.history_delete_message("Nick", str(victim["id"]))
        await asyncio.sleep(0.05)
        entries = [e for e in self.bridge._get_global_history()[0]
                   if e["kind"] == "archive"]
        self.assertEqual(len(entries), 1, "no-op delete pushes nothing")

    # ── H-10: no archive attached ────────────────────────────────
    async def test_H10_every_slot_is_safe_without_an_archive(self):
        br = Bridge.__new__(Bridge)
        QObject.__init__(br)
        br._config = self.cfg
        br._engine = None
        errors = []
        br.history_error.connect(lambda s, m: errors.append(s))
        # reads: no raise; the error SIGNAL is the answer (report, don't
        # crash) — every read slot must emit history_error with its scope
        scopes = ["history_open", "history_page", "history_search",
                  "history_stats", "userdb_page", "userdb_stats",
                  "media_path", "detect_my_nick"]
        calls = [lambda: br.history_open("r", "Nick", "{}"),
                 lambda: br.history_page("r", "Nick", "{}"),
                 lambda: br.history_search("r", "{}"),
                 lambda: br.history_stats("r", "Nick"),
                 lambda: br.userdb_page("r", "{}"),
                 lambda: br.userdb_stats("r"),
                 lambda: br.media_path("r", "x"),
                 lambda: br.detect_my_nick("r")]
        for scope, call in zip(scopes, calls):
            errors.clear()
            call()
            await asyncio.sleep(0.02)
            self.assertIn(scope, errors,
                          f"{scope} must report the missing archive")
        # mutations return False
        self.assertFalse(br.history_delete_person("Nick"))
        self.assertFalse(br.history_clear_person("Nick"))
        self.assertFalse(br.history_delete_message("Nick", "1"))
        self.assertFalse(br.history_purge_deleted("Nick"))
        self.assertFalse(br.history_restore_person("Nick"))
        self.assertFalse(br.history_merge("A", "B"))
        self.assertEqual(br.media_folder("Nick"), "")
        # settings fall back to config persistence (merged over defaults)
        br.save_history_settings('{"page_size": 7}')
        settings = json.loads(br.get_history_settings())
        self.assertEqual(settings["page_size"], 7)
        self.assertIn("preview", settings, "defaults survive the merge")

    # ── H-12: merge folds rows into the target ───────────────────
    async def test_H12_merge_moves_rows_and_removes_source(self):
        await self.seed("Anna", count=3)
        self.page.partner = "Boris"
        self.page.messages = [raw(f"b{i}", from_nick="Boris", idx=i)
                              for i in range(4)]
        await self.service.collector.tick()
        self.assertTrue(self.bridge.history_merge("Anna", "Boris"))
        await wait_for(self.changed)
        boris = await self.service.page("Boris")
        self.assertEqual(len(boris["items"]), 7, "3 rows folded in")
        self.assertEqual(await self.service.repo.get_person("Anna"), None,
                         "the source person is gone")
        self.assertEqual(self.changed[-1]["action"], "merged")
        self.assertEqual(self.changed[-1]["moved"], 3)

    # ── H-13: purge erases soft-deleted rows for good ────────────
    async def test_H13_purge_makes_deletion_permanent(self):
        await self.seed(count=5)
        page = await self.service.page("Nick")
        victim = page["items"][1]
        self.bridge.history_delete_message("Nick", str(victim["id"]))
        await asyncio.sleep(0.05)
        self.changed.clear()
        self.assertTrue(self.bridge.history_purge_deleted("Nick"))
        await wait_for(self.changed)
        self.assertEqual(self.changed[-1]["action"], "purged")
        self.assertEqual(self.changed[-1]["count"], 1)
        # a purged message cannot be restored by undo of the soft delete
        entries = [e for e in self.bridge._get_global_history()[0]
                   if e["kind"] == "archive"]
        token = entries[-1]["value"]["token"]
        restored = await self.service.repo.restore_deleted("Nick", token)
        self.assertEqual(restored, 0, "purged rows are gone for good")

    # ── H-14: corrupt option JSON still answers ──────────────────
    async def test_H14_corrupt_json_answers_with_defaults(self):
        await self.seed(count=4)
        _r, payload = await self.ask(self.bridge.history_open, "r", "Nick",
                                     "{corrupt",
                                     signal=self.bridge.history_page_ready)
        data = json.loads(payload)
        self.assertEqual(len(data["items"]), 4)
        _r2, payload2 = await self.ask(self.bridge.history_search, "r2",
                                       "{corrupt",
                                       signal=self.bridge.history_search_ready)
        data2 = json.loads(payload2)
        self.assertIn("scope", data2)
        self.assertEqual(self.errors, [])

    # ── H-15: userdb items carry a labels array ──────────────────
    async def test_H15_userdb_items_carry_labels(self):
        await self.seed(count=3)
        _r, payload = await self.ask(self.bridge.userdb_page, "u", "{}",
                                     signal=self.bridge.userdb_page_ready)
        data = json.loads(payload)
        self.assertGreaterEqual(len(data["items"]), 1)
        for item in data["items"]:
            self.assertIn("labels", item)
            self.assertIsInstance(item["labels"], list)
        self.assertEqual(data["my_nick"], "Me")

    # ── H-16: detect_my_nick answers via the stats signal ────────
    async def test_H16_detect_my_nick_echoes_req_id(self):
        await self.seed(count=2)
        _req, payload = await self.ask(self.bridge.detect_my_nick, "d1",
                                       signal=self.bridge.history_stats_ready)
        data = json.loads(payload)
        self.assertEqual(data["req_id"], "d1")
        self.assertIn("detected", data)


if __name__ == "__main__":
    unittest.main()
