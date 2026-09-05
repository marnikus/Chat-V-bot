"""People-list actions are recorded in the global undo/redo history.

Every user-driven people-list edit must be undoable with a single Ctrl+Z:
  * deleting one person (row 🗑 Delete),
  * deleting the selection,
  * Clear ALL users,
  * changing a person's status (✔ Done / ↩ Undo),
  * Reset messaged flags (the user's "resetting the list").

Entries are {kind:"people", value:{before:[rows], after:[rows]}} so the tip
people entry can be reversed in one step no matter what stack/grid edits
surround it in the shared timeline. Undo applies the BEFORE half, redo the
AFTER half; the SQLite table is restored from the snapshot.

Run with:  python3 tests/test_people_undo.py
"""

import asyncio
import json
import os
import sys
import tempfile
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.bridge import Bridge  # noqa: E402
from backend.config_manager import ConfigManager  # noqa: E402
from backend.user_memory import UserMemory, UserRecord  # noqa: E402

UI_DIR = os.path.join(os.path.dirname(__file__), "..", "ui")


def run(coro):
    return asyncio.run(coro)


class Harness:
    """Real UserMemory + a Bridge object wired to it, no Qt app needed."""

    def __init__(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.memory = UserMemory(os.path.join(self._tmp.name, "users.db"))
        cfg = ConfigManager(os.path.join(self._tmp.name, "config.json"))
        self.cfg = cfg
        br = Bridge.__new__(Bridge)
        from PySide6.QtCore import QObject
        QObject.__init__(br)
        br._memory = self.memory
        br._config = cfg
        br._engine = types.SimpleNamespace(load_stack=lambda blocks: None)
        br._presets = None
        self.bridge = br
        self.logs = []
        br.log_message.connect(lambda m, _lvl: self.logs.append(m))

    async def __aenter__(self):
        await self.memory.init()
        return self

    async def __aexit__(self, *exc):
        await self.memory.close()
        self._tmp.cleanup()


def rec(nick, messaged=False, gender="female", message_count=0,
        last_messaged=None, notes=""):
    return UserRecord(nick=nick, gender=gender, guest=True,
                      messaged=messaged, message_count=message_count,
                      last_messaged=last_messaged, notes=notes)


async def seed(mem, *people):
    for p in people:
        await mem.upsert_user(p)
        if p.messaged:
            await mem.mark_messaged(p.nick)


def last_entry(bridge):
    history, _ = bridge._get_global_history()
    return history[-1] if history else None


async def settle():
    """Let the async snapshot-restore coroutines run to completion."""
    await asyncio.sleep(0.05)


class TestPeopleDeleteUndo(unittest.TestCase):
    def test_delete_one_is_recorded_and_undo_restores(self):
        async def go():
            async with Harness() as h:
                await seed(h.memory, rec("Anna"), rec("Bella"),
                           rec("Cara", messaged=True))
                # mark_messaged (inside seed) sets its own timestamp/count, so
                # pin the columns the snapshot must preserve afterwards.
                await h.memory._db.execute(
                    "UPDATE users SET message_count=2, notes='x', "
                    "last_messaged='2026-09-01T10:00:00' WHERE nick='Cara'")
                await h.memory._db.commit()
                await h.bridge._do_delete_one("Anna")

                entry = last_entry(h.bridge)
                self.assertIsNotNone(entry)
                self.assertEqual(entry["kind"], "people")
                before = entry["value"]["before"]
                after = entry["value"]["after"]
                self.assertTrue(any(r["nick"] == "Anna" for r in before))
                self.assertFalse(any(r["nick"] == "Anna" for r in after))
                # rows keep every column so the restore is faithful
                cara = next(r for r in after if r["nick"] == "Cara")
                self.assertTrue(cara["messaged"])
                self.assertEqual(cara["message_count"], 2)
                self.assertEqual(cara["last_messaged"], "2026-09-01T10:00:00")
                self.assertEqual(cara["notes"], "x")

                names = {u.nick for u in await h.memory.get_all()}
                self.assertNotIn("Anna", names)

                raw = h.bridge.undo()
                result = json.loads(raw)
                self.assertEqual(result["kind"], "people")
                self.assertTrue(any(r["nick"] == "Anna" for r in result["value"]))
                await settle()
                names = {u.nick for u in await h.memory.get_all()}
                self.assertIn("Anna", names, "undo must restore the deleted person")

                raw = h.bridge.redo()
                result = json.loads(raw)
                self.assertEqual(result["kind"], "people")
                await settle()
                names = {u.nick for u in await h.memory.get_all()}
                self.assertNotIn("Anna", names, "redo must delete again")
        run(go())

    def test_delete_unknown_person_pushes_nothing(self):
        async def go():
            async with Harness() as h:
                await seed(h.memory, rec("Anna"))
                await h.bridge._do_delete_one("Ghost")
                self.assertIsNone(last_entry(h.bridge), "no-op must not record")
        run(go())

    def test_delete_selected_is_undoable(self):
        async def go():
            async with Harness() as h:
                await seed(h.memory, rec("Anna"), rec("Bella"), rec("Cara"))
                await h.bridge._do_delete_many(["Anna", "Cara"])
                entry = last_entry(h.bridge)
                self.assertEqual(entry["kind"], "people")
                after_nicks = {r["nick"] for r in entry["value"]["after"]}
                self.assertEqual(after_nicks, {"Bella"})

                h.bridge.undo()
                await settle()
                names = {u.nick for u in await h.memory.get_all()}
                self.assertEqual(names, {"Anna", "Bella", "Cara"})
        run(go())

    def test_clear_all_is_undoable(self):
        async def go():
            async with Harness() as h:
                await seed(h.memory, rec("Anna"), rec("Bella", messaged=True))
                await h.bridge._do_clear()
                names = {u.nick for u in await h.memory.get_all()}
                self.assertEqual(names, set())

                h.bridge.undo()
                await settle()
                names = {u.nick for u in await h.memory.get_all()}
                self.assertEqual(names, {"Anna", "Bella"}, "clear-all must undo")
        run(go())


class TestPeopleStatusUndo(unittest.TestCase):
    def test_status_toggle_is_undoable_and_redoable(self):
        async def go():
            async with Harness() as h:
                await seed(h.memory, rec("Anna"))
                await h.bridge._do_set_messaged("Anna", True)
                entry = last_entry(h.bridge)
                self.assertEqual(entry["kind"], "people")
                after = entry["value"]["after"]
                self.assertTrue(after[0]["messaged"])

                h.bridge.undo()
                await settle()
                rows = await h.memory.get_all()
                self.assertFalse(rows[0].messaged, "undo must clear the flag")

                h.bridge.redo()
                await settle()
                rows = await h.memory.get_all()
                self.assertTrue(rows[0].messaged, "redo must set the flag again")
        run(go())

    def test_reset_messaged_is_undoable(self):
        async def go():
            async with Harness() as h:
                await seed(h.memory, rec("Anna", messaged=True),
                           rec("Bella", messaged=True), rec("Cara"))
                await h.bridge._do_reset()
                entry = last_entry(h.bridge)
                self.assertEqual(entry["kind"], "people")
                # all back to new
                self.assertTrue(all(not r["messaged"]
                                    for r in entry["value"]["after"]))

                h.bridge.undo()
                await settle()
                rows = {u.nick: u.messaged for u in await h.memory.get_all()}
                self.assertTrue(rows["Anna"] and rows["Bella"])
                self.assertFalse(rows["Cara"])
        run(go())


class TestPeopleHistoryCoexists(unittest.TestCase):
    def test_people_entries_share_the_one_timeline(self):
        async def go():
            async with Harness() as h:
                await seed(h.memory, rec("Anna"))
                h.bridge._push_global("stack", [{"block_id": "PAUSE"}])
                await h.bridge._do_delete_one("Anna")
                history, index = h.bridge._get_global_history()
                kinds = [e["kind"] for e in history]
                self.assertEqual(kinds, ["stack", "people"])
                self.assertEqual(index, 1)

                # one Ctrl+Z reverts the delete even though a stack edit is
                # interleaved below it in the timeline
                raw = h.bridge.undo()
                result = json.loads(raw)
                self.assertEqual(result["kind"], "people")
                self.assertTrue(any(r["nick"] == "Anna" for r in result["value"]))
                self.assertEqual(result["index"], 0)
                await settle()
                names = {u.nick for u in await h.memory.get_all()}
                self.assertIn("Anna", names)

                # redo moves forward again
                raw = h.bridge.redo()
                result = json.loads(raw)
                self.assertEqual(result["kind"], "people")
                self.assertEqual(result["index"], 1)
                await settle()
                names = {u.nick for u in await h.memory.get_all()}
                self.assertNotIn("Anna", names)
        run(go())

    def test_people_history_survives_a_config_reload(self):
        async def go():
            h = Harness()
            async with h:
                await seed(h.memory, rec("Anna"))
                await h.bridge._do_delete_one("Anna")
                # a fresh Bridge over the SAME config file must keep the entry
                cfg2 = ConfigManager(h.cfg._path)
                br2 = Bridge.__new__(Bridge)
                from PySide6.QtCore import QObject
                QObject.__init__(br2)
                br2._memory = h.memory
                br2._config = cfg2
                br2._engine = types.SimpleNamespace(load_stack=lambda blocks: None)
                history, index = br2._get_global_history()
                kinds = [e["kind"] for e in history]
                self.assertEqual(kinds, ["people"],
                                 "people entries must survive a restart")
                self.assertEqual(index, 0)
                raw = br2.undo()
                result = json.loads(raw)
                self.assertEqual(result["kind"], "people")
                await settle()
                names = {u.nick for u in await h.memory.get_all()}
                self.assertIn("Anna", names, "restored after restart + undo")
        run(go())


class TestPeopleUndoFrontend(unittest.TestCase):
    """Structural checks that the shipped UI speaks the people history."""

    def setUp(self):
        with open(os.path.join(UI_DIR, "js", "app.js"), encoding="utf-8") as fh:
            self.app = fh.read()
        with open(os.path.join(UI_DIR, "js", "user-table.js"),
                  encoding="utf-8") as fh:
            self.table = fh.read()

    def test_app_accepts_people_kind_in_load_and_apply(self):
        self.assertIn("entry.kind === 'people'", self.app)
        self.assertIn("result.kind === 'people'", self.app)
        self.assertIn("_peopleRowsOf", self.app)

    def test_app_keeps_mirror_in_sync_from_server(self):
        self.assertIn("_syncGlobalHistory", self.app)
        self.assertIn("history_changed", self.app)

    def test_no_confirmation_dialogs_on_remove_or_reset(self):
        self.assertNotIn("PresetsUI.confirm", self.table)
        # actions call the bridge directly
        for call in ("App.bridge.delete_user(nick);",
                     "App.bridge.delete_users(JSON.stringify(nicks));",
                     "App.bridge.clear_memory();",
                     "App.bridge.reset_messaged();",
                     "App.bridge.set_user_messaged(nick, !u.messaged);"):
            self.assertIn(call, self.table, call)


if __name__ == "__main__":
    unittest.main(verbosity=2)
