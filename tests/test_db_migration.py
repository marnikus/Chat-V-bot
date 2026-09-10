"""Re-homing a legacy install into one-DB-per-world — once, and safely.

Phase 3 of the redesign (docs/archive/2026-09-08-one-db-one-world/DB_CREATION_DELETION_REDESIGN_DESIGN_2026-09-08.md, D6): pre-unified installs keep the people queue in a separate
`chatbot.db`, person labels in config.json, and world-bound undo entries
in config's timeline. The startup hook `HistoryService.migrate_install()`
re-homes all of that into the active world file — and it must be:

  * **idempotent** — safe to run on every start, work happens once;
  * **non-destructive** — the legacy queue file is renamed out (never
    deleted), same-nick rows the world already has win over legacy ones;
  * **world-only** — labels import only into a world that has none of
    its own, and the queue merge only ever feeds the world that owns the
    session (no data is copied between two world files — R6).

Per AGENT_RULES RULE 8 this drives the REAL HistoryService and UserMemory
against real SQLite files in a temp folder.

Run with:  python3 tests/test_db_migration.py
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.config_manager import ConfigManager  # noqa: E402
from backend.history_service import HistoryService  # noqa: E402
from backend.label_store import LabelStore  # noqa: E402
from backend.user_memory import UserMemory  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_chat_parser_delta import FakePage  # noqa: E402


class ConnectedPage(FakePage):
    is_connected = True


class MigrationCase(unittest.IsolatedAsyncioTestCase):
    """A pre-unified install: a `chatbot.db` queue file full of people."""

    async def asyncSetUp(self):
        self.dir = tempfile.mkdtemp()
        self.cfg = ConfigManager(os.path.join(self.dir, "config.json"))
        media_cfg = dict(self.cfg.get("history", "media", default={}) or {})
        media_cfg["cache_dir"] = os.path.join(self.dir, "saved_media")
        self.cfg.set("history", "media", media_cfg)
        self.page = ConnectedPage([])
        self.world_path = os.path.join(self.dir, "history.db")
        self.legacy_path = os.path.join(self.dir, "chatbot.db")
        await self._make_legacy_queue(["Ann", "Bob"])
        self.memory = None                 # bound by the tests, like main.py
        self.service = HistoryService(cdp=self.page, config=self.cfg,
                                      db_path=self.world_path,
                                      memory=None)
        await self.service.init()          # no memory → nothing to migrate yet

    async def asyncTearDown(self):
        await self.service.close()
        if self.memory is not None:
            await self.memory.close()

    async def _make_legacy_queue(self, nicks):
        """The queue file exactly as the pre-redesign app left it."""
        import aiosqlite
        from backend.user_memory import _SCHEMA
        async with aiosqlite.connect(self.legacy_path) as conn:
            await conn.executescript(_SCHEMA)
            for i, nick in enumerate(nicks, start=1):
                await conn.execute(
                    "INSERT INTO users(nick, gender, registered, anonymous,"
                    " guest, first_seen, last_seen, messaged) "
                    "VALUES(?, 'unknown', 1, 0, 0, ?, ?, 0)",
                    (nick, f"2026-01-0{i + 1}T10:00:00",
                     f"2026-01-0{i + 1}T12:00:00"))
            await conn.commit()

    def bind_memory(self):
        """What the upgraded main.py does when the legacy file exists."""
        self.memory = UserMemory(self.legacy_path)
        self.service.memory = self.memory
        return self.memory

    async def read_world(self, path, sql, args=()):
        """An INDEPENDENT read-only view of a world file on disk."""
        import aiosqlite
        async with aiosqlite.connect(f"file:{os.path.abspath(path)}?mode=ro",
                                     uri=True) as conn:
            cur = await conn.execute(sql, args)
            return await cur.fetchall()


class TestQueueMerge(MigrationCase):
    async def test_the_legacy_queue_is_merged_into_the_world(self):
        self.bind_memory()
        # a same-nick row the world already has must WIN over the legacy one
        await self.service.db.execute(
            "INSERT INTO users(nick, notes) VALUES('Ann','world row wins')")
        await self.service.db.commit()

        report = await self.service.migrate_install()
        self.assertTrue(report["queue_merged"])
        self.assertFalse(os.path.exists(self.legacy_path),
                         "the retired file leaves the .db space (renamed out)")
        renamed = [n for n in os.listdir(self.dir)
                   if n.startswith("chatbot.db.migrated-")]
        self.assertTrue(renamed, "the legacy file is preserved, not deleted")
        self.assertEqual(os.path.abspath(self.memory.db_path),
                         os.path.abspath(self.world_path),
                         "the queue connection now follows the world")

        rows = await self.read_world(
            self.world_path, "SELECT notes FROM users WHERE nick='Ann'")
        self.assertEqual([r[0] for r in rows], ["world row wins"],
                         "the world's own row is never overwritten")
        self.assertEqual(len(await self.memory.get_all()), 2,
                         "the merged queue has both people")

    async def test_migrating_twice_changes_nothing(self):
        self.bind_memory()
        first = await self.service.migrate_install()
        self.assertTrue(first["queue_merged"])
        again = await self.service.migrate_install()
        self.assertFalse(any(again.values()),
                         f"a second start must be a no-op: {again}")
        self.assertEqual(len(await self.memory.get_all()), 2)
        self.assertEqual(
            len([n for n in os.listdir(self.dir)
                 if n.startswith("chatbot.db.migrated-")]), 1,
            "the file is renamed exactly once")

    async def test_a_missing_legacy_file_is_not_an_error(self):
        os.unlink(self.legacy_path)
        self.bind_memory()               # points at the (now gone) file
        report = await self.service.migrate_install()
        self.assertFalse(report["queue_merged"])
        # the world is untouched and the connection is not left at a ghost
        rows = await self.read_world(self.world_path, "SELECT COUNT(*) FROM users")
        self.assertEqual(rows[0][0], 0)


class TestLabelImport(MigrationCase):
    async def test_config_labels_import_into_an_empty_world_once(self):
        store = LabelStore(self.cfg, db=self.service.db)
        self.service.bind_labels(store)
        self.cfg.set("labels", {
            "defs": [{"id": "l1", "name": "VIP", "color": "#ff0000"}],
            "assign": {"Ann": ["l1"]},
            "next_id": 2,
        })
        report = await self.service.migrate_install()
        self.assertTrue(report["labels_imported"])
        rows = await self.read_world(self.world_path, "SELECT name FROM labels")
        self.assertEqual([r[0] for r in rows], ["VIP"])
        rows = await self.read_world(
            self.world_path, "SELECT nick, label_id FROM label_assigns")
        self.assertEqual(rows, [("Ann", "l1")])
        self.assertTrue(
            await self.service.get_meta_flag("labels_migrated_from_config"))
        again = await self.service.migrate_install()
        self.assertFalse(again["labels_imported"],
                         "the meta flag stops the import on later starts")

    async def test_a_world_with_its_own_labels_keeps_them(self):
        store = LabelStore(self.cfg, db=self.service.db)
        self.service.bind_labels(store)
        store.create("Mine", "#00ff00")
        await store.flush_to_db()
        self.cfg.set("labels", {
            "defs": [{"id": "x1", "name": "FromConfig", "color": "#0000ff"}],
        })
        report = await self.service.migrate_install()
        self.assertFalse(report["labels_imported"],
                         "never clobber a world that already has labels")
        rows = await self.read_world(self.world_path, "SELECT name FROM labels")
        self.assertEqual([r[0] for r in rows], ["Mine"])


class TestRecentListPruning(MigrationCase):
    async def test_ghost_paths_leave_the_recent_list(self):
        real = os.path.join(self.dir, "real.db")
        with open(real, "wb") as fh:
            fh.write(b"not important")
        ghost = os.path.join(self.dir, "ghost.db")
        self.cfg.set_state(db_recent=[ghost, real])
        report = await self.service.migrate_install()
        self.assertTrue(report["recent_pruned"])
        kept = self.cfg.get_state("db_recent")
        self.assertNotIn(ghost, kept,
                         "a remembered-but-gone file is a ghost — it leaves")
        self.assertIn(real, kept)
        again = await self.service.migrate_install()
        self.assertFalse(again["recent_pruned"])


class TestUndoRehome(MigrationCase):
    async def test_world_bound_undo_moves_into_the_world_file(self):
        self.cfg.set_state(undo_history=[
            {"kind": "stack", "value": {"a": 1}},
            {"kind": "people", "value": {"before": [], "after": []}},
            {"kind": "grid", "value": {"b": 2}},
        ])
        report = await self.service.migrate_install()
        self.assertTrue(report["undo_rehomed"])
        rows = await self.read_world(
            self.world_path, "SELECT seq, kind FROM undo_history ORDER BY seq")
        self.assertEqual(rows, [(2, "people")],
                         "only the world-bound entry moves — into the file")
        kept = self.cfg.get_state("undo_history")
        self.assertEqual([e["kind"] for e in kept], ["stack", "grid"],
                         "config keeps the app-level half")
        self.assertEqual([e["seq"] for e in kept], [1, 3],
                         "seqs keep the original interleaving")
        self.assertTrue(await self.service.get_meta_flag("undo_migrated_v6"))
        again = await self.service.migrate_install()
        self.assertFalse(again["undo_rehomed"])
        rows = await self.read_world(
            self.world_path, "SELECT COUNT(*) FROM undo_history")
        self.assertEqual(rows[0][0], 1, "a second start re-homes nothing")

    async def test_app_only_timeline_stays_in_config(self):
        self.cfg.set_state(undo_history=[
            {"kind": "stack", "value": {"a": 1}},
            {"kind": "grid", "value": {"b": 2}},
        ])
        report = await self.service.migrate_install()
        self.assertFalse(report["undo_rehomed"])
        rows = await self.read_world(
            self.world_path, "SELECT COUNT(*) FROM undo_history")
        self.assertEqual(rows[0][0], 0,
                         "app-level entries are not a world's data")
        self.assertEqual(len(self.cfg.get_state("undo_history")), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
