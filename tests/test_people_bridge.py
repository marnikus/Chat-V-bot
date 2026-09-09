"""D7 — PeopleBridge wire contract (design IDs P-1..P-9).

`tests/test_people_undo.py` pins the undo semantics of every people
mutation. This file pins the WIRE layer around them:

  P-1  refresh_users → users_updated (rows with nick/order/labels/
       messaged) + stats_updated, matching the sqlite content
  P-2  delete_user (the SLOT) announces via users_deleted(nicks, count)
  P-3  delete_users with corrupt / non-list JSON: error log, no raise,
       nothing deleted (C-1)
  P-4  delete_users multi → ONE undo entry, one users_deleted with all
       nicks and the exact count
  P-5  set_user_messaged toggles + undo reverts
  P-6  reset_messaged clears every flag + undo restores them
  P-7  clear_memory empties the table + undo restores everybody
  P-8  engine live signals (person_found/removed/marked) are forwarded
       and trigger a refresh
  P-9  users_updated rows carry the assigned label ids (C-3)

Run:  python -m pytest tests/test_people_bridge.py
"""

import asyncio
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtCore import QObject, Signal  # noqa: E402

from backend.bridge import Bridge  # noqa: E402

from bridge_harness import (Recorder, TempWorld, make_bare, rec,  # noqa: E402
                            seed)


class QtPeopleEngine(QObject):
    """An engine that quacks like ActionEngine for the people hooks."""
    person_found = Signal(str)
    person_removed = Signal(str)
    person_marked = Signal(str)
    stack_complete = Signal()


class PeopleCase(unittest.TestCase):
    def setUp(self):
        self.world = TempWorld()
        self.addCleanup(self.world.__exit__, None, None, None)
        self.engine = QtPeopleEngine()
        self.br = make_bare(engine=self.engine, config=self.world.config)
        # build the bridge NOW (the real constructor is eager): the engine
        # people-hooks connect in __init__, not on first use
        from bridge.people_bridge import PeopleBridge
        self.br._bridge(PeopleBridge)
        self.users = Recorder(self.br.users_updated)
        self.stats = Recorder(self.br.stats_updated)
        self.deleted = Recorder(self.br.users_deleted)

    def mem(self):
        return self.br._ctx.memory

    async def setup_memory(self, *records):
        from backend.user_memory import UserMemory
        mem = UserMemory(self.world.path("users.db"))
        await mem.init()
        self.br._memory = mem
        await seed(mem, *records)
        return mem

    def people_rows(self, payload_json):
        return json.loads(payload_json)

    # ── P-1: the refresh payload ─────────────────────────────────
    def test_P1_refresh_announces_rows_and_stats(self):
        async def go():
            mem = await self.setup_memory(rec("Anna"), rec("Boris"))
            self.br.refresh_users()
            await asyncio.sleep(0.08)
            self.assertEqual(len(self.users.calls), 1)
            rows = self.people_rows(self.users.calls[0])
            self.assertEqual({r["nick"] for r in rows},
                             {"Anna", "Boris"})
            for row in rows:
                for key in ("nick", "gender", "messaged", "order", "labels"):
                    self.assertIn(key, row)
                self.assertIsInstance(row["labels"], list)
            self.assertEqual(len(self.stats.calls), 1)
            stats = json.loads(self.stats.calls[0])
            self.assertIsInstance(stats, dict)
            await mem.close()
        asyncio.run(go())

    def test_P1b_empty_memory_still_announces(self):
        async def go():
            mem = await self.setup_memory()
            self.br.refresh_users()
            await asyncio.sleep(0.08)
            self.assertEqual(json.loads(self.users.calls[0]), [])
            await mem.close()
        asyncio.run(go())

    # ── P-2 / P-3 / P-4: deletions over the wire ─────────────────
    def test_P2_delete_user_slot_announces_and_pushes_undo(self):
        async def go():
            mem = await self.setup_memory(rec("Anna"), rec("Boris"))
            self.br.delete_user("Anna")
            await asyncio.sleep(0.08)
            self.assertEqual(len(self.deleted.calls), 1)
            nicks, count = self.deleted.calls[0]
            self.assertIn("Anna", json.loads(nicks))
            self.assertEqual(count, 1)
            names = {u.nick for u in await mem.get_all()}
            self.assertEqual(names, {"Boris"})
            history, _ = self.br._get_global_history()
            self.assertTrue(any(e["kind"] == "people" for e in history),
                            "the deletion is undoable")
            await mem.close()
        asyncio.run(go())

    def test_P3_delete_users_corrupt_payload_is_safe(self):
        async def go():
            mem = await self.setup_memory(rec("Anna"))
            for bad in ('{corrupt', '"a string"', '5'):
                self.deleted.clear()
                self.br.delete_users(bad)
                await asyncio.sleep(0.05)
                self.assertEqual(self.deleted.calls, [])
            names = {u.nick for u in await mem.get_all()}
            self.assertEqual(names, {"Anna"}, "nothing was deleted")
            history, _ = self.br._get_global_history()
            self.assertEqual([e for e in history
                              if e["kind"] == "people"], [])
            await mem.close()
        asyncio.run(go())

    def test_P4_delete_many_is_one_announce_one_undo(self):
        async def go():
            mem = await self.setup_memory(rec("Anna"), rec("Boris"),
                                          rec("Cara"))
            self.br.delete_users(json.dumps(["Anna", "Boris"]))
            await asyncio.sleep(0.08)
            self.assertEqual(len(self.deleted.calls), 1)
            nicks, count = self.deleted.calls[0]
            self.assertEqual(sorted(json.loads(nicks)), ["Anna", "Boris"])
            self.assertEqual(count, 2)
            self.assertEqual({u.nick for u in await mem.get_all()}, {"Cara"})
            entries = [e for e in self.br._get_global_history()[0]
                       if e["kind"] == "people"]
            self.assertEqual(len(entries), 1, "ONE entry for one action")
            self.assertEqual(len(entries[0]["value"]["before"]), 3)
            self.assertEqual(len(entries[0]["value"]["after"]), 1)
            await mem.close()
        asyncio.run(go())

    # ── P-5 / P-6 / P-7: flags and wipes ─────────────────────────
    def test_P5_set_messaged_toggles_and_is_undoable(self):
        async def go():
            mem = await self.setup_memory(rec("Anna"))
            self.br.set_user_messaged("Anna", True)
            await asyncio.sleep(0.08)
            rows = {u.nick: u for u in await mem.get_all()}
            self.assertTrue(rows["Anna"].messaged)
            self.assertGreaterEqual(len(self.users.calls), 1,
                                    "the table refreshed after the edit")
            # the LAST payload reflects the post-state (C-3)
            rows_json = self.people_rows(self.users.calls[-1])
            anna = next(r for r in rows_json if r["nick"] == "Anna")
            self.assertTrue(anna["messaged"])
            self.users.clear()
            self.br.undo()
            await asyncio.sleep(0.08)
            rows = {u.nick: u for u in await mem.get_all()}
            self.assertFalse(rows["Anna"].messaged, "Ctrl+Z reverts")
            await mem.close()
        asyncio.run(go())

    def test_P6_reset_messaged_clears_every_flag(self):
        async def go():
            mem = await self.setup_memory(rec("Anna", messaged=True),
                                          rec("Boris", messaged=True))
            self.br.reset_messaged()
            await asyncio.sleep(0.08)
            rows = {u.nick: u for u in await mem.get_all()}
            self.assertFalse(any(u.messaged for u in rows.values()))
            self.br.undo()
            await asyncio.sleep(0.08)
            rows = {u.nick: u for u in await mem.get_all()}
            self.assertTrue(rows["Anna"].messaged)
            self.assertTrue(rows["Boris"].messaged)
            await mem.close()
        asyncio.run(go())

    def test_P7_clear_memory_wipes_and_undo_restores(self):
        async def go():
            mem = await self.setup_memory(rec("Anna"), rec("Boris"))
            self.br.clear_memory()
            await asyncio.sleep(0.08)
            self.assertEqual(await mem.get_all(), [])
            self.br.undo()
            await asyncio.sleep(0.08)
            names = {u.nick for u in await mem.get_all()}
            self.assertEqual(names, {"Anna", "Boris"})
            await mem.close()
        asyncio.run(go())

    # ── P-8: live engine signals ─────────────────────────────────
    def test_P8_engine_person_signals_forward_and_refresh(self):
        async def go():
            mem = await self.setup_memory(rec("Anna"))
            found = Recorder(self.br.person_found)
            removed = Recorder(self.br.person_removed)
            self.engine.person_found.emit('{"nick": "Newcomer"}')
            self.engine.person_removed.emit('{"nick": "Anna"}')
            await asyncio.sleep(0.08)
            self.assertEqual(found.calls, ['{"nick": "Newcomer"}'])
            self.assertEqual(removed.calls, ['{"nick": "Anna"}'])
            self.assertGreaterEqual(len(self.users.calls), 2,
                                    "each live event refreshed the table")
            await mem.close()
        asyncio.run(go())

    # ── P-9: labels ride along in the rows ───────────────────────
    def test_P9_rows_carry_label_ids(self):
        async def go():
            mem = await self.setup_memory(rec("Anna"))
            lid = json.loads(self.br.label_create("vip", ""))["id"]
            self.br.label_assign("Anna", lid)
            self.br.refresh_users()
            await asyncio.sleep(0.08)
            rows = self.people_rows(self.users.calls[-1])
            anna = next(r for r in rows if r["nick"] == "Anna")
            self.assertEqual([l["id"] for l in anna["labels"]], [lid])
            await mem.close()
        asyncio.run(go())


if __name__ == "__main__":
    unittest.main()
