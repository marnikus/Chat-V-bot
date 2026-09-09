"""D9 — DbBridge contract (design IDs B-1..B-8).

World lifecycle over the wire:

  B-1  db_list → {"active", "items"} (real temp dir with *.db files)
  B-2  db_info(req_id) → db_info_ready(req_id, sizes-payload) (C-2)
  B-3  db_create → file created, db_changed {action:create, ok:true},
       one dbconn undo entry
  B-4  db_create with an empty name → db_changed ok:false, no undo entry
  B-5  db_load(missing) → db_changed ok:false, ACTIVE WORLD UNCHANGED
       (no half-switch, C-1 transaction rule)
  B-6  db_delete of a non-active world removes (trashes) it; the active
       world is untouched
  B-7  db_clean reports on db_changed
  B-8  every db_changed payload is JSON {action, ok, ...}

Run:  python -m pytest tests/test_db_bridge.py
"""

import asyncio
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend.bridge import Bridge  # noqa: E402
from services.db_service import DbManager  # noqa: E402

from bridge_harness import Recorder, TempWorld, make_bare  # noqa: E402


class DbCase(unittest.TestCase):
    def setUp(self):
        self.world = TempWorld()
        self.addCleanup(self.world.__exit__, None, None, None)
        # a seed world the way config points at one
        self.active = os.path.join(self.world.dir, "alpha.db")
        self.world.config.set("history", "db_path", self.active)
        self.br = make_bare(config=self.world.config)
        self.br._dbs = DbManager(config=self.world.config,
                                 root=self.world.dir)
        self.changed = Recorder(self.br.db_changed)
        self.info = Recorder(self.br.db_info_ready)
        # production wiring: the archive service exists before the DB
        # panel is used (main.py order) — create/load/delete then build
        # and open real world files
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from test_chat_parser_delta import FakePage, raw
        from test_history_bridge import ConnectedPage
        from backend.history_service import HistoryService
        self._service = HistoryService(
            cdp=ConnectedPage([]), config=self.world.config,
            db_path=self.active)

        async def _init():
            await self._service.init()
        asyncio.run(_init())
        self.addCleanup(self._close_service)
        self.br.attach_history(self._service)

    def _close_service(self):
        asyncio.run(self._service.close())

    def actions(self):
        return [c.get("action") for c in self.changed.payloads]

    def last_change(self):
        return self.changed.payloads[-1]

    # ── reads ────────────────────────────────────────────────────
    def test_B1_db_list_reports_active_and_items(self):
        payload = json.loads(self.br.db_list())
        self.assertIn("active", payload)
        self.assertIn("items", payload)
        self.assertIsInstance(payload["items"], list)

    def test_B2_db_info_echoes_req_id(self):
        async def go():
            self.br.db_info("req-7")
            await asyncio.sleep(0.15)
        asyncio.run(go())
        self.assertEqual(len(self.info.calls), 1)
        req, payload = self.info.calls[0]
        self.assertEqual(req, "req-7")
        data = json.loads(payload)
        for key in ("path", "name", "exists", "db_bytes", "media_bytes",
                    "total_bytes", "trash_dir"):
            self.assertIn(key, data)

    # ── create ───────────────────────────────────────────────────
    def test_B3_create_makes_the_world_and_announces(self):
        async def go():
            self.assertTrue(self.br.db_create("beta"))
            await asyncio.sleep(0.25)
        asyncio.run(go())
        change = self.last_change()
        self.assertEqual(change.get("action"), "create")
        self.assertTrue(change.get("ok"))
        # the new world exists on disk (next to the active one)
        created = os.path.join(self.world.dir, "beta.db")
        self.assertTrue(os.path.exists(created))
        # one dbconn undo entry records the switch
        history, _ = self.br._get_global_history()
        dbconn = [e for e in history if e["kind"] == "dbconn"]
        self.assertEqual(len(dbconn), 1)
        self.assertEqual(dbconn[0]["value"].get("op"), "create")

    def test_B4_create_empty_name_fails_clean(self):
        async def go():
            self.assertTrue(self.br.db_create("   "))
            await asyncio.sleep(0.25)
        asyncio.run(go())
        change = self.last_change()
        self.assertFalse(change.get("ok"), "empty name must not create")
        history, _ = self.br._get_global_history()
        self.assertEqual([e for e in history if e["kind"] == "dbconn"], [],
                         "failed creates push no undo entry")

    # ── load (transaction rule) ──────────────────────────────────
    def test_B5_load_missing_leaves_active_world_unchanged(self):
        async def go():
            self.assertTrue(self.br.db_load(os.path.join(self.world.dir,
                                                         "ghost.db")))
            await asyncio.sleep(0.25)
        asyncio.run(go())
        change = self.last_change()
        self.assertFalse(change.get("ok"))
        # the transaction rule: the active world is still alpha
        self.assertEqual(self.br.db_manager.active_path(), self.active,
                         "a failed load must not switch worlds")
        history, _ = self.br._get_global_history()
        self.assertEqual([e for e in history if e["kind"] == "dbconn"], [])

    def test_B5b_load_existing_world_switches(self):
        # create beta directly on disk (world files are plain sqlite paths)
        import sqlite3
        beta = os.path.join(self.world.dir, "beta.db")
        sqlite3.connect(beta).close()
        async def go():
            self.assertTrue(self.br.db_load(beta))
            await asyncio.sleep(0.25)
        asyncio.run(go())
        change = self.last_change()
        self.assertTrue(change.get("ok"))
        self.assertEqual(change.get("action"), "load")

    # ── delete ───────────────────────────────────────────────────
    def test_B6_delete_removes_a_world_but_not_the_active_one(self):
        import sqlite3
        beta = os.path.join(self.world.dir, "beta.db")
        sqlite3.connect(beta).close()
        self.assertTrue(os.path.exists(beta))

        async def go():
            self.assertTrue(self.br.db_delete(beta))
            await asyncio.sleep(0.25)
        asyncio.run(go())
        change = self.last_change()
        self.assertEqual(change.get("action"), "delete")
        self.assertTrue(change.get("ok"))
        self.assertFalse(os.path.exists(beta),
                         "the world file is gone (trashed)")
        self.assertTrue(os.path.exists(self.active),
                         "the active world survived")
        # deleting a world records NO undo entry (permanent by design, D4)
        history, _ = self.br._get_global_history()
        self.assertEqual([e for e in history if e["kind"] == "dbconn"], [])

    # ── clean ────────────────────────────────────────────────────
    def test_B7_clean_reports(self):
        async def go():
            self.assertTrue(self.br.db_clean())
            await asyncio.sleep(0.25)
        asyncio.run(go())
        change = self.last_change()
        self.assertEqual(change.get("action"), "clean")

    # ── payload shape ────────────────────────────────────────────
    def test_B8_every_change_payload_is_json_with_action_and_ok(self):
        async def go():
            self.br.db_create("gamma")
            self.br.db_load(os.path.join(self.world.dir, "nope.db"))
            await asyncio.sleep(0.25)
        asyncio.run(go())
        self.assertGreaterEqual(len(self.changed.calls), 2)
        for payload in self.changed.payloads:
            self.assertIn("action", payload)
            self.assertIn("ok", payload)


if __name__ == "__main__":
    unittest.main()
