"""Regression tests for the 2026-09-08 DB Connection incident.

Real SQLite files, HistoryService, writer/query/media operations and Bridge
commands; no mocked database implementation. Failure injection is limited to
an I/O boundary or a deliberately paused in-flight operation.

Run: python -m unittest discover -s tests -p 'test_db_connection_safety.py' -v
"""

import asyncio
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import types
import unittest
from datetime import datetime
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from PySide6.QtCore import QObject
from backend.bridge import Bridge
from backend.config_manager import ConfigManager
from backend.db_manager import CREATE_SCHEMA_ERROR, LAST_DATABASE, DbManager
from backend.db_paths import PROTECTED_DATABASE
from backend.history_db import (APPLICATION_ID, ARCHIVE_TABLES, INDEX_SCHEMA,
                                INCOMPATIBLE_SCHEMA, SCHEMA, SCHEMA_VERSION,
                                HistoryDB, SchemaError, inspect_archive)
from backend.history_service import HistoryService
from backend.user_memory import UserMemory
from test_chat_parser_delta import FakePage, raw
from test_db_manager import wait_for

NOW = datetime(2026, 9, 8, 23, 0)
NICK = "_замужняя киса_"
ME = "Пошлый01"


class Page(FakePage):
    is_connected = True


class SafetyCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = self.temp.name
        self.cfg = ConfigManager(os.path.join(self.root, "config.json"))
        self.path = os.path.join(self.root, "history.db")
        settings = self.cfg.get("history")
        settings["db_path"] = self.path
        settings["media"]["cache_dir"] = os.path.join(self.root, "saved_media")
        self.cfg.set("history", settings)
        self.page = Page([], partner=NICK, me=ME)
        self.memory = UserMemory(os.path.join(self.root, "chatbot.db"))
        await self.memory.init()
        self.addAsyncCleanup(self.memory.close)
        self.service = HistoryService(self.page, self.cfg, session_id="regression", memory=self.memory)
        await self.service.init()
        self.addAsyncCleanup(self.service.close)
        self.service.collector.configure(my_nick=ME, auto_backfill=False,
                                         download_media=False, chunk_pause_ms=0)
        self.service.collector.now = lambda: NOW
        self.manager = DbManager(self.cfg, self.service, self.root)

    async def make(self, name="work"):
        result = await self.manager.create(name)
        self.assertTrue(result["ok"], result)
        return result["path"]

    async def seed(self, text="Полный текст\nс новой строкой 😊"):
        self.page.messages = [raw(text, from_nick=NICK, time="18:00")]
        await self.service.collector.tick()

    async def contents(self, path=None):
        if path is None or path == self.service.db.path:
            return await self.service.db.fetchdicts("SELECT * FROM messages ORDER BY ord")
        db = HistoryDB(path)
        try:
            await db.init(allow_create=False)
            return await db.fetchdicts("SELECT * FROM messages ORDER BY ord")
        finally:
            await db.close()

    def names(self):
        return [i["name"] for i in self.manager.list_dbs()]


class TestCreationIsolation(SafetyCase):
    async def test_create_preserves_connection_all_collaborators_gate_cursor_and_settings(self):
        await self.seed()
        old = self.service.db
        settings = self.service.settings()
        before = await self.contents()
        cursor = await self.service.repo.get_cursor(before[0]["person_id"])
        state = self.service.collector.state_payload()
        await self.make()
        self.assertIs(self.service.db, old)
        for collaborator in (self.service.repo, self.service.query, self.service.media):
            self.assertIs(collaborator.db, old)
        self.assertEqual(await self.contents(), before)
        self.assertEqual(await self.service.repo.get_cursor(before[0]["person_id"]), cursor)
        self.assertEqual(self.service.collector.state_payload(), state)
        self.assertEqual(self.service.settings(), settings)
        self.assertEqual(self.cfg.get("history", "db_path"), self.path)
        self.assertTrue(self.service.collector._verified)

    async def test_new_messages_keep_full_text_caption_media_and_metadata_after_create(self):
        await self.seed()
        await self.make()
        self.page.messages += [raw("Подпись\nи текст", direction="out", from_nick=ME,
                                   time="18:01", kind="gif", idx=1,
                                   media={"url": "https://example.test/файл.gif", "kind": "gif"})]
        await self.service.collector.tick()
        rows = await self.contents()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1]["text"], "Подпись\nи текст")
        for key, expected in {"from_nick": ME, "my_nick": ME, "session_id": "regression",
                              "direction": "out", "day": "2026-09-08", "ts_display": "18:01"}.items():
            self.assertEqual(rows[1][key], expected, key)
        media = await self.service.media.get(rows[1]["media_id"])
        self.assertEqual(media["url"], "https://example.test/файл.gif")
        self.assertEqual(media["owner"], NICK)
        self.assertEqual(media["kind"], "gif")

    async def test_create_can_finish_while_a_live_append_is_parked(self):
        entered, release = asyncio.Event(), asyncio.Event()
        original = self.service.repo._media_id

        async def parked(*args, **kwargs):
            entered.set()
            await release.wait()
            return await original(*args, **kwargs)

        old = self.service.db
        with patch.object(self.service.repo, "_media_id", parked):
            write = asyncio.create_task(self.service.repo.append(
                NICK, [raw("in flight", from_nick=NICK)], now=NOW))
            try:
                await asyncio.wait_for(entered.wait(), 3)
                created = await asyncio.wait_for(self.manager.create("parallel"), 3)
                self.assertTrue(created["ok"], created)
                self.assertIs(self.service.db, old)
                self.assertFalse(write.done())
            finally:
                release.set()
                await write
        self.assertEqual((await self.contents())[0]["text"], "in flight")

    async def test_failed_schema_creation_removes_owned_artifacts_not_active_data(self):
        await self.seed()
        old, before = self.service.db, await self.contents()
        recent = self.manager.known_paths()
        with patch.object(HistoryDB, "validate", AsyncMock(side_effect=SchemaError("injected missing person_id"))):
            result = await self.manager.create("bad")
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], CREATE_SCHEMA_ERROR)
        self.assertEqual(self.manager.known_paths(), recent)
        self.assertFalse(os.path.exists(os.path.join(self.root, "bad.db")))
        self.assertFalse(list(Path(self.root).glob(".cvb-*")))
        self.assertIs(self.service.db, old)
        self.assertEqual(await self.contents(), before)
        await self.make("bad")  # failed initialization did not leave a lock/file

    async def test_cancelling_schema_creation_closes_and_removes_stage(self):
        entered, release = asyncio.Event(), asyncio.Event()
        original = HistoryDB._migrate_dup_keys

        async def blocked(db):
            entered.set()
            await release.wait()
            return await original(db)

        with patch.object(HistoryDB, "_migrate_dup_keys", blocked):
            task = asyncio.create_task(self.manager.create("cancelled"))
            await asyncio.wait_for(entered.wait(), 3)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertTrue(self.service.db.is_open)
        self.assertFalse(list(Path(self.root).glob(".cvb-*")))
        self.assertNotIn("cancelled.db", self.names())
        await self.make("cancelled")

    async def test_concurrent_creates_never_overwrite_the_winner(self):
        results = await asyncio.gather(self.manager.create("same"), self.manager.create("same"))
        self.assertEqual(sum(r["ok"] for r in results), 1)
        self.assertTrue(inspect_archive(os.path.join(self.root, "same.db"), full=True))
        self.assertEqual(self.service.db.path, self.path)


class TestSchemaSafety(SafetyCase):
    async def test_new_file_has_the_complete_actual_schema_indexes_references_and_fts(self):
        path = await self.make()
        db = HistoryDB(path)
        try:
            await db.init(allow_create=False)
            await db.validate()
            self.assertEqual(await db.get_meta("schema_version"), SCHEMA_VERSION)
            self.assertEqual(await db.get_meta("storage_kind"), "chat_archive")
            self.assertEqual(await db.scalar("PRAGMA application_id"), APPLICATION_ID)
            for table in ARCHIVE_TABLES:
                self.assertTrue(await db.fetchall(f"PRAGMA table_info({table})"), table)
            for name in ("idx_messages_person_ord", "idx_messages_lc", "idx_messages_alive",
                         "idx_messages_dup_key", "idx_persons_lc", "idx_gaps_person",
                         "idx_media_sha", "idx_media_state"):
                self.assertTrue(await db.scalar("SELECT 1 FROM sqlite_master WHERE name=?", (name,), 0), name)
            refs = await db.fetchall("PRAGMA foreign_key_list(messages)")
            self.assertEqual({r[3] for r in refs}, {"person_id", "media_id"})
            with self.assertRaises(sqlite3.IntegrityError):
                await db.execute("INSERT INTO cursors(person_id) VALUES(900)")
            await db.conn.rollback()
            if db.fts_enabled:
                for trigger in ("messages_ai", "messages_ad", "messages_au"):
                    self.assertTrue(await db.scalar("SELECT 1 FROM sqlite_master WHERE name=?", (trigger,), 0))
        finally:
            await db.close()

    async def assert_refused_without_switch(self, path, detail=""):
        await self.seed()
        old = self.service.db
        before = await self.contents()
        result = await self.manager.load(path)
        self.assertFalse(result["ok"], result)
        self.assertEqual(result["error"], INCOMPATIBLE_SCHEMA)
        if detail:
            self.assertIn(detail, result.get("detail", ""))
        self.assertIs(self.service.db, old)
        self.assertTrue(old.is_open)
        self.assertEqual(await self.contents(), before)
        self.assertEqual(self.cfg.get("history", "db_path"), self.path)
        return result

    async def test_foreign_messages_table_fails_before_any_archive_ddl(self):
        path = os.path.join(self.root, "foreign.db")
        with sqlite3.connect(path) as db:
            db.executescript("CREATE TABLE messages(id INTEGER PRIMARY KEY,user_id INTEGER,text TEXT);")
            db.execute("INSERT INTO messages VALUES(1,12,'do not touch')")
        original = Path(path).read_bytes()
        await self.assert_refused_without_switch(path)
        self.assertEqual(Path(path).read_bytes(), original)
        with sqlite3.connect(path) as db:
            self.assertEqual(db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall(), [("messages",)])

    async def test_missing_person_id_is_not_migrated_with_empty_defaults(self):
        path = os.path.join(self.root, "incomplete.db")
        with sqlite3.connect(path) as db:
            db.executescript(SCHEMA.replace("person_id   INTEGER", "user_id     INTEGER").replace("UNIQUE(person_id, fp", "UNIQUE(user_id, fp"))
        await self.assert_refused_without_switch(path, "person_id")

    async def test_future_version_is_refused_and_not_restamped(self):
        path = await self.make()
        with sqlite3.connect(path) as db:
            db.execute("UPDATE schema_meta SET value='999' WHERE key='schema_version'")
        await self.assert_refused_without_switch(path, "999")
        with sqlite3.connect(path) as db:
            self.assertEqual(db.execute("SELECT value FROM schema_meta WHERE key='schema_version'").fetchone()[0], "999")

    async def test_wrong_existing_index_is_refused(self):
        path = await self.make()
        with sqlite3.connect(path) as db:
            db.executescript("DROP INDEX idx_messages_person_ord; CREATE INDEX idx_messages_person_ord ON messages(ord);")
        await self.assert_refused_without_switch(path, "idx_messages_person_ord")

    async def test_missing_index_is_rebuilt_before_activation(self):
        path = await self.make()
        with sqlite3.connect(path) as db:
            db.execute("DROP INDEX idx_messages_lc")
        loaded = await self.manager.load(path)
        self.assertTrue(loaded["ok"], loaded)
        await self.service.db.validate()

    async def test_zero_byte_and_non_sqlite_targets_are_not_created_on_load(self):
        for name, content in (("zero.db", b""), ("corrupt.db", b"not sqlite at all")):
            path = os.path.join(self.root, name)
            Path(path).write_bytes(content)
            await self.assert_refused_without_switch(path)
            self.assertEqual(Path(path).read_bytes(), content)

    async def test_additive_migration_preserves_old_text_metadata_and_version_contract(self):
        path = await self.make("legacy")
        db = HistoryDB(path)
        await db.init()
        from backend.history_repo import HistoryRepo
        await HistoryRepo(db, session_id="old").append(NICK, [raw("Старый текст", from_nick=NICK)], now=NOW)
        before = (await db.fetchdicts("SELECT * FROM messages"))[0]
        await db.close()
        with sqlite3.connect(path) as old:
            old.execute("ALTER TABLE messages DROP COLUMN text_scan_at")
            old.execute("ALTER TABLE messages DROP COLUMN text_recovered_at")
            old.execute("UPDATE schema_meta SET value='4' WHERE key='schema_version'")
        self.assertTrue((await self.manager.load(path))["ok"])
        after = (await self.contents())[0]
        for key, value in before.items():
            self.assertEqual(after[key], value, key)
        self.assertEqual(await self.service.db.get_meta("schema_version"), SCHEMA_VERSION)

    async def test_orphan_file_is_not_counted_as_an_alternative(self):
        path = await self.make("orphan")
        with sqlite3.connect(path) as db:
            db.execute("PRAGMA foreign_keys=OFF")
            db.execute("INSERT INTO cursors(person_id) VALUES(999)")
        self.assertNotIn("orphan.db", self.names())
        await self.assert_refused_without_switch(path, "foreign key")
        result = await self.manager.delete(self.path)
        self.assertEqual(result["error"], LAST_DATABASE)

    async def test_failed_init_closes_the_partial_connection(self):
        path = os.path.join(self.root, "bad.db")
        with sqlite3.connect(path) as db:
            db.execute("CREATE TABLE messages(id INTEGER)")
        candidate = HistoryDB(path)
        with self.assertRaises(SchemaError):
            await candidate.init(allow_create=False)
        self.assertFalse(candidate.is_open)
        os.rename(path, path + ".renamed")

    async def test_settings_cannot_bypass_validated_load(self):
        path = await self.make()
        settings = self.service.apply_settings({"db_path": path, "preview": {"page_size": 20}})
        self.assertEqual(settings["db_path"], self.path)
        self.assertEqual(self.cfg.get("history", "db_path"), self.path)
        self.assertEqual(settings["preview"]["page_size"], 20)


class TestDeletionAndProtectedStores(SafetyCase):
    async def test_only_chat_archives_are_visible_and_last_delete_is_guarded(self):
        self.cfg.set_state(db_recent=[os.path.join(self.root, "ghost.db"), self.memory._db_path])
        self.assertEqual(self.names(), ["history.db"])
        self.assertFalse(self.manager.list_dbs()[0]["can_delete"])
        before = self.service.db
        result = await self.manager.delete(self.path)
        self.assertEqual(result["error"], LAST_DATABASE)
        self.assertTrue(os.path.isfile(self.path))
        self.assertIs(self.service.db, before)
        self.assertEqual(self.manager.known_paths(), [])

    async def test_delete_forgets_entry_and_stale_paths_stay_gone_after_restart(self):
        path = await self.make()
        result = await self.manager.delete(path)
        self.assertTrue(result["ok"], result)
        self.assertTrue(os.path.isfile(result["backup"]))
        self.assertFalse(os.path.exists(path))
        self.assertNotIn(path, self.manager.known_paths())
        self.assertEqual(self.names(), ["history.db"])
        self.cfg.set_state(db_recent=[path])  # stale older config is also pruned
        reloaded = DbManager(ConfigManager(self.cfg._path), self.service, self.root)
        self.assertEqual([r["name"] for r in reloaded.list_dbs()], ["history.db"])
        self.assertEqual(reloaded.known_paths(), [])

    async def test_inactive_delete_does_not_change_the_live_handle_or_state(self):
        await self.seed()
        path = await self.make()
        old, status = self.service.db, self.service.collector.state_payload()
        result = await self.manager.delete(path)
        self.assertTrue(result["ok"], result)
        self.assertFalse(result["active_changed"])
        self.assertIs(self.service.db, old)
        self.assertEqual(self.service.collector.state_payload(), status)

    async def test_active_delete_chooses_an_archive_not_the_queue_then_writes_continue(self):
        await self.make()
        result = await self.manager.delete(self.path)
        self.assertTrue(result["ok"], result)
        self.assertEqual(os.path.basename(self.service.db.path), "work.db")
        await self.seed("after active delete")
        self.assertEqual((await self.contents())[0]["text"], "after active delete")
        self.assertEqual(self.names(), ["work.db"])
        self.assertFalse(self.manager.list_dbs()[0]["can_delete"])

    async def test_unopenable_fallback_does_not_detach_delete_or_switch_current(self):
        alternate = await self.make()
        old = self.service.db
        original = HistoryDB.init

        async def fail_target(db, **kwargs):
            if db.path == alternate:
                raise OSError("simulated permission failure")
            return await original(db, **kwargs)

        with patch.object(HistoryDB, "init", fail_target):
            result = await self.manager.delete(self.path)
        self.assertFalse(result["ok"], result)
        self.assertIs(self.service.db, old)
        self.assertTrue(old.is_open)
        self.assertTrue(os.path.isfile(self.path))
        self.assertFalse(os.path.exists(self.manager.trash_dir()))

    async def test_failed_move_returns_to_original_archive_and_preserves_files(self):
        await self.seed()
        await self.make()
        with patch.object(self.manager, "_move_to_trash", return_value=""):
            result = await self.manager.delete(self.path)
        self.assertFalse(result["ok"])
        self.assertEqual(self.service.db.path, self.path)
        self.assertTrue(self.service.db.is_open)
        self.assertEqual(len(await self.contents()), 1)
        self.assertEqual(sorted(self.names()), ["history.db", "work.db"])

    async def test_two_simultaneous_deletes_cannot_remove_the_last_database(self):
        other = await self.make()
        results = await asyncio.gather(self.manager.delete(other), self.manager.delete(self.path))
        self.assertEqual(sum(r["ok"] for r in results), 1, results)
        self.assertEqual(len(self.manager.list_dbs()), 1)
        self.assertTrue(self.service.db.is_open)
        await self.seed("still writable")
        self.assertEqual((await self.contents())[0]["text"], "still writable")

    async def test_queue_undo_renamed_queue_and_aliases_are_not_manageable(self):
        await self.make()
        timeline = [{"kind": "people", "value": {"before": [], "after": []}}]
        self.cfg.set_state(undo_history=timeline, undo_history_index=0)
        undo = os.path.join(self.root, "undo_history.db")
        with sqlite3.connect(undo) as db:
            db.executescript("CREATE TABLE undo_history(id INTEGER PRIMARY KEY, payload TEXT);")
            db.execute("INSERT INTO undo_history VALUES(1,'saved user action')")
        renamed = os.path.join(self.root, "renamed.db")
        with sqlite3.connect(renamed) as db:
            db.execute("CREATE TABLE users(id INTEGER PRIMARY KEY,nick TEXT)")
        symlink, hardlink = os.path.join(self.root, "link.db"), os.path.join(self.root, "hard.db")
        os.symlink(self.memory._db_path, symlink)
        os.link(self.memory._db_path, hardlink)
        for path in (self.memory._db_path, undo, renamed, symlink, hardlink):
            before = hashlib.sha256(Path(path).read_bytes()).digest()
            self.assertFalse((await self.manager.load(path))["ok"], path)
            self.assertFalse((await self.manager.delete(path))["ok"], path)
            self.assertEqual(hashlib.sha256(Path(path).read_bytes()).digest(), before)
        self.assertEqual(sorted(self.names()), ["history.db", "work.db"])
        self.assertEqual(self.cfg.get_state("undo_history"), timeline)
        self.assertEqual(self.cfg.get_state("undo_history_index"), 0)

    async def test_reserved_names_cannot_be_created_even_when_file_is_missing(self):
        for name in ("undo.db", "undo_history.db", "chatbot.db"):
            result = await self.manager.create(name)
            self.assertFalse(result["ok"])
            self.assertEqual(result["error"], PROTECTED_DATABASE)

    async def test_direct_service_switch_also_protects_system_store(self):
        old = self.service.db
        with self.assertRaises(ValueError):
            await self.service.switch_db(self.memory._db_path)
        self.assertIs(self.service.db, old)

    async def test_restoring_cannot_overwrite_system_database(self):
        path = await self.make()
        deleted = await self.manager.delete(path)
        before = Path(self.memory._db_path).read_bytes()
        restored = await self.manager.restore_backup(deleted["backup"], self.memory._db_path)
        self.assertFalse(restored["ok"])
        self.assertEqual(Path(self.memory._db_path).read_bytes(), before)


class TestOperationBoundary(SafetyCase):
    async def park_then_switch(self, operation, patch_target, method):
        alternate = await self.make()
        entered, release, validated = asyncio.Event(), asyncio.Event(), asyncio.Event()
        original = getattr(patch_target, method)
        old_db = self.service.db
        validate = HistoryDB.validate

        async def paused(*args, **kwargs):
            entered.set()
            await release.wait()
            return await original(*args, **kwargs)

        async def seen(db):
            await validate(db)
            if db.path == alternate:
                validated.set()

        with patch.object(patch_target, method, paused), patch.object(HistoryDB, "validate", seen):
            task = asyncio.create_task(operation())
            loading = None
            try:
                await asyncio.wait_for(entered.wait(), 3)
                loading = asyncio.create_task(self.manager.load(alternate))
                await asyncio.wait_for(validated.wait(), 3)
                self.assertFalse(loading.done(), "load must drain the whole in-flight operation")
                self.assertIs(self.service.db, old_db)
                self.assertTrue(old_db.is_open)
            finally:
                release.set()
                result = await task
                if loading:
                    self.assertTrue((await loading)["ok"])
        for obj in (self.service.repo, self.service.query, self.service.media):
            self.assertIs(obj.db, self.service.db)
        return result, old_db.path

    async def test_inflight_append_finishes_in_original_database(self):
        result, path = await self.park_then_switch(
            lambda: self.service.repo.append(NICK, [raw("old db", from_nick=NICK)], now=NOW),
            self.service.repo, "_media_id")
        self.assertEqual(result.added, 1)
        self.assertEqual(await self.contents(), [])
        self.assertEqual((await self.contents(path))[0]["text"], "old db")

    async def test_inflight_query_cannot_return_new_database_rows_with_old_person_id(self):
        await self.seed("original page")
        result, _path = await self.park_then_switch(
            lambda: self.service.query.page(NICK), self.service.query, "_person_row")
        self.assertEqual(result["items"][0]["text"], "original page")
        self.assertEqual(await self.contents(), [])

    async def test_manual_collection_is_also_one_archive_operation(self):
        from actions.collect_history import CollectHistory
        self.page.messages = [raw("manual", from_nick=NICK, time="18:00")]
        block = CollectHistory(pre_delay_ms=0, chunk_pause_ms=0, download_media=False)
        block.now = lambda: NOW
        engine = types.SimpleNamespace(history=self.service, report=lambda *_: None, is_stopping=lambda: False)
        result, path = await self.park_then_switch(
            lambda: block.execute("", self.page, engine), self.service.parser, "slice")
        self.assertEqual(result, "ok")
        self.assertEqual((await self.contents(path))[0]["text"], "manual")
        self.assertEqual(await self.contents(), [])

    async def test_live_push_is_also_one_archive_operation(self):
        await self.seed()
        payload = {"tab": "private", "partner": NICK, "title": NICK,
                   "items": [raw("push body", from_nick=NICK, time="18:01", idx=1)]}
        result, path = await self.park_then_switch(
            lambda: self.service.collector.handle_push(payload), self.service.repo, "_media_id")
        self.assertEqual(result, 1)
        self.assertEqual((await self.contents(path))[-1]["text"], "push body")
        self.assertFalse(self.service.collector._verified, "new archive needs a fresh private gate")

    async def test_media_download_cannot_update_same_id_in_another_database(self):
        mid = await self.service.media.register("https://example.test/a.gif", "gif", nick=NICK)
        original_fetch = self.service.media._fetch_one

        async def no_network(row):
            await self.service.db.execute("UPDATE media SET state='failed',fail_reason='original only' WHERE id=?", (row["id"],))
            await self.service.db.commit()
            return False

        self.service.media._fetch_one = no_network
        try:
            result, path = await self.park_then_switch(
                lambda: self.service.media.download_one(mid), self.service.media, "_fetch_one")
        finally:
            self.service.media._fetch_one = original_fetch
        self.assertEqual(result["state"], "failed")
        self.assertEqual(await self.service.db.scalar("SELECT COUNT(*) FROM media"), 0)
        with sqlite3.connect(path) as db:
            self.assertEqual(db.execute("SELECT fail_reason FROM media WHERE id=?", (mid,)).fetchone()[0], "original only")

    async def test_cancelled_append_rolls_back_before_the_next_operation(self):
        entered, release = asyncio.Event(), asyncio.Event()
        original = self.service.repo._ui_record

        async def pause_after_insert(*args, **kwargs):
            entered.set()
            await release.wait()
            return await original(*args, **kwargs)

        with patch.object(self.service.repo, "_ui_record", pause_after_insert):
            task = asyncio.create_task(self.service.repo.append(
                NICK, [raw("cancel me", from_nick=NICK)], now=NOW))
            await asyncio.wait_for(entered.wait(), 3)
            self.assertTrue(self.service.db.conn.in_transaction)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertFalse(self.service.db.conn.in_transaction)
        self.assertEqual(await self.contents(), [])
        await self.seed("after cancellation")
        self.assertEqual((await self.contents())[0]["text"], "after cancellation")

    async def test_switch_preserves_paused_stopped_and_throttled_states(self):
        alternate = await self.make()
        col = self.service.collector
        col.pause()
        col.on_run_started()
        col.stop()
        await self.manager.load(alternate)
        self.assertFalse(col.running)
        self.assertTrue(col.paused)
        self.assertTrue(col.state_payload()["throttled"])
        col._verified, col._nick = True, NICK
        added = await col.handle_push({"partner": NICK, "title": NICK,
                                       "items": [raw("must not save", from_nick=NICK)]})
        self.assertEqual(added, 0)
        self.assertEqual(await self.contents(), [])


class TestBackupsAndUndo(SafetyCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        br = Bridge.__new__(Bridge)
        QObject.__init__(br)
        br._config, br._memory, br._presets = self.cfg, self.memory, None
        br._engine = types.SimpleNamespace(load_stack=lambda _b: None)
        br._dbs = self.manager
        br.attach_history(self.service)
        self.bridge = br
        self.changes, self.archive_changes = [], []
        br.db_changed.connect(lambda raw: self.changes.append(json.loads(raw)))
        br.userdb_changed.connect(lambda raw: self.archive_changes.append(json.loads(raw)))

    async def command(self, method, *args):
        self.changes.clear()
        getattr(self.bridge, method)(*args)
        await wait_for(self.changes)
        self.assertTrue(self.changes, method + " did not complete")
        return self.changes[-1]

    async def test_create_undo_redo_is_file_lifecycle_never_an_implicit_load(self):
        await self.seed()
        original = self.service.db
        made = await self.command("db_create", "work")
        self.assertEqual(self.archive_changes, [], "create must not reload Person History")
        undone = await self.command("undo")
        self.assertTrue(undone["ok"], undone)
        self.assertFalse(os.path.exists(made["path"]))
        self.assertIs(self.service.db, original)
        redone = await self.command("redo")
        self.assertTrue(redone["ok"], redone)
        self.assertTrue(os.path.isfile(made["path"]))
        self.assertIs(self.service.db, original)
        self.assertEqual(len(await self.contents()), 1)
        for _ in range(2):
            self.assertTrue((await self.command("undo"))["ok"])
            self.assertTrue((await self.command("redo"))["ok"])
        history, index = self.bridge._get_global_history()
        self.assertEqual(len(history), 1)
        self.assertEqual(index, 0)

    async def test_inactive_delete_restore_redo_keeps_current_database(self):
        other = await self.make()
        old = self.service.db
        deleted = await self.command("db_delete", other)
        restored = await self.command("undo")
        self.assertTrue(restored["ok"], restored)
        self.assertIs(self.service.db, old)
        self.assertIn("work.db", self.names())
        self.assertTrue((await self.command("redo"))["ok"])
        self.assertNotIn("work.db", self.names())
        self.assertNotEqual(self.bridge._get_global_history()[0][0]["value"]["backup"], deleted["backup"])
        self.assertTrue((await self.command("undo"))["ok"])
        self.assertIs(self.service.db, old)

    async def test_active_delete_undo_restores_and_reactivates_original(self):
        await self.seed()
        await self.make()
        self.assertTrue((await self.command("db_delete", self.path))["ok"])
        self.assertTrue((await self.command("undo"))["ok"])
        self.assertEqual(self.service.db.path, self.path)
        self.assertEqual(len(await self.contents()), 1)

    async def test_clean_refuses_failed_backup_without_deleting_any_rows(self):
        await self.seed()
        before = await self.contents()
        with patch.object(self.manager, "_copy_to_trash", AsyncMock(return_value="")):
            result = await self.manager.clean()
        self.assertFalse(result["ok"])
        self.assertEqual(await self.contents(), before)

    async def test_clean_undo_uses_consistent_wal_snapshot_and_keeps_handle_open(self):
        await self.seed()
        self.assertGreater(os.path.getsize(self.path + "-wal"), 0)
        before = await self.contents()
        result = await self.manager.clean()
        self.assertTrue(result["ok"], result)
        with sqlite3.connect(result["backup"]) as db:
            self.assertEqual(db.execute("SELECT text FROM messages").fetchone()[0], before[0]["text"])
            self.assertEqual(db.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        old = self.service.db
        restored = await self.manager.restore_backup(result["backup"], self.path)
        self.assertTrue(restored["ok"], restored)
        self.assertIs(self.service.db, old)
        self.assertEqual(await self.contents(), before)
        self.assertFalse(self.service.collector._verified)

    async def test_corrupt_restore_is_refused_before_current_archive_is_touched(self):
        await self.seed()
        backup = os.path.join(self.manager.trash_dir(), "bad.db")
        os.makedirs(os.path.dirname(backup))
        Path(backup).write_bytes(b"broken backup")
        old, before = self.service.db, await self.contents()
        result = await self.manager.restore_backup(backup, self.path)
        self.assertFalse(result["ok"])
        self.assertIs(self.service.db, old)
        self.assertEqual(await self.contents(), before)

    async def test_failed_db_action_emits_error_without_history_reset_or_undo_entry(self):
        path = os.path.join(self.root, "wrong.db")
        Path(path).write_bytes(b"not sqlite")
        result = await self.command("db_load", path)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], INCOMPATIBLE_SCHEMA)
        self.assertEqual(self.archive_changes, [])
        self.assertEqual(self.bridge._get_global_history()[0], [])
    async def test_undo_cannot_race_an_inflight_database_action(self):
        entered, release = asyncio.Event(), asyncio.Event()
        original = self.manager.create

        async def delayed(name):
            entered.set()
            await release.wait()
            return await original(name)

        with patch.object(self.manager, "create", delayed):
            self.changes.clear()
            self.bridge.db_create("work")
            try:
                await asyncio.wait_for(entered.wait(), 3)
                self.assertEqual(self.bridge.undo(), "null")
                self.assertEqual(self.bridge.redo(), "null")
            finally:
                release.set()
                await wait_for(self.changes)
        self.assertEqual(getattr(self.bridge, "_db_actions_pending"), 0)
        self.assertEqual(self.bridge._get_global_history()[1], 0)

    async def test_stale_queued_row_id_is_not_reused_after_archive_switch(self):
        await self.seed()
        alternate = await self.make()
        await self.manager.load(alternate)
        await self.seed("keep new archive row")
        new_id = (await self.contents())[0]["id"]
        await self.manager.load(self.path)
        self.assertEqual((await self.contents())[0]["id"], new_id)
        ran = []

        async def stale_delete():
            ran.append(True)
            await self.service.repo.soft_delete_message(NICK, new_id)

        async with self.service.db.operation_lock:
            self.bridge._run_async("history_delete_message", stale_delete())
            await asyncio.sleep(0)  # the old UI request now waits on the lock
            await self.manager.load(alternate)
        await asyncio.sleep(0)      # let that waiter observe the changed generation
        self.assertEqual(ran, [], "old row IDs must be discarded, not applied to the new file")
        self.assertEqual((await self.service.query.page(NICK))["total"], 1)
        self.assertEqual((await self.contents())[0]["text"], "keep new archive row")

    async def test_last_database_undo_failure_does_not_advance_global_history(self):
        made = await self.command("db_create", "work")
        # Simulate an external state change not represented in the timeline.
        await self.manager.load(made["path"])
        await self.manager.delete(self.path)
        result = await self.command("undo")
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], LAST_DATABASE)
        self.assertEqual(self.bridge._get_global_history()[1], 0)
        self.assertTrue(self.service.db.is_open)
        self.assertEqual(self.service.db.path, made["path"])

    async def test_unexpected_action_error_finishes_and_reports_failure(self):
        with patch.object(self.manager, "create", AsyncMock(side_effect=OSError("disk unavailable"))):
            result = await self.command("db_create", "work")
        self.assertFalse(result["ok"])
        self.assertIn("disk unavailable", result["error"])
        self.assertEqual(self.archive_changes, [])
        self.assertEqual(self.bridge._get_global_history()[0], [])

    async def test_clean_transaction_failure_rolls_back_text_and_fts(self):
        await self.seed()
        before = await self.contents()
        original = self.service.db.execute

        async def fail_middle(sql, params=()):
            if sql == "DELETE FROM cursors":
                raise sqlite3.OperationalError("injected write failure")
            return await original(sql, params)

        with patch.object(self.service.db, "execute", fail_middle):
            result = await self.manager.clean()
        self.assertFalse(result["ok"])
        self.assertEqual(await self.contents(), before)
        await self.service.db.validate()
        if self.service.db.fts_enabled:
            self.assertEqual(len((await self.service.query.search_person(NICK, "Полный"))["items"]), 1)

    async def test_backup_io_failure_cannot_fall_through_to_clean(self):
        await self.seed()
        before = await self.contents()
        with patch.object(self.service.db, "backup_to", AsyncMock(side_effect=OSError("disk full"))):
            result = await self.manager.clean()
        self.assertFalse(result["ok"])
        self.assertEqual(await self.contents(), before)
        self.assertEqual(list(Path(self.manager.trash_dir()).glob("*.db")), [])

    async def test_partial_trash_move_rolls_back_every_already_moved_sibling(self):
        source, target = os.path.join(self.root, "parts.db"), os.path.join(self.root, "moved.db")
        for suffix in ("", "-wal", "-shm"):
            Path(source + suffix).write_bytes(("original" + suffix).encode())
        rename = os.rename

        def fail_wal(old, new):
            if old == source + "-wal":
                raise PermissionError("in use")
            return rename(old, new)

        with patch("backend.db_manager.os.rename", fail_wal):
            with self.assertRaises(PermissionError):
                self.manager._move_group(source, target)
        for suffix in ("", "-wal", "-shm"):
            self.assertEqual(Path(source + suffix).read_bytes(), ("original" + suffix).encode())
            self.assertFalse(os.path.exists(target + suffix))

    async def test_failed_recent_config_publish_does_not_truncate_global_undo(self):
        timeline = [{"kind": "labels", "value": {"before": {}, "after": {"name": "Важно"}}}]
        self.cfg.set_state(undo_history=timeline, undo_history_index=0)
        before = Path(self.cfg._path).read_bytes()
        with patch("backend.config_manager.os.replace", side_effect=OSError("disk unavailable")):
            self.cfg.set_state(db_recent=["attempted new path"])
        self.assertEqual(Path(self.cfg._path).read_bytes(), before)
        self.assertEqual(json.loads(Path(self.cfg._path).read_text())["state"]["undo_history"], timeline)
        self.assertEqual(list(Path(self.root).glob(".config.json.*.tmp")), [])



class TestStartupRecovery(SafetyCase):
    async def test_previous_builds_bad_selection_falls_back_without_touching_queue(self):
        await self.seed("preserved startup history")
        await self.service.close()
        before = Path(self.memory._db_path).read_bytes()
        self.cfg.set("history", {**self.cfg.get("history"), "db_path": self.memory._db_path})
        service = HistoryService(self.page, self.cfg, memory=self.memory)
        try:
            await service.init()
            self.assertEqual(service.db.path, self.path)
            self.assertEqual(await service.db.scalar("SELECT text FROM messages"), "preserved startup history")
            self.assertEqual(Path(self.memory._db_path).read_bytes(), before)
        finally:
            await service.close()

    async def test_no_valid_archive_creates_a_separate_recovery_file_not_over_bad_data(self):
        await self.service.close()
        Path(self.path).write_bytes(b"keep these original bytes")
        service = HistoryService(self.page, self.cfg, memory=self.memory)
        try:
            await service.init()
            self.assertTrue(service.db.is_open)
            self.assertNotEqual(service.db.path, self.path)
            self.assertEqual(Path(self.path).read_bytes(), b"keep these original bytes")
            await service.db.validate()
        finally:
            await service.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
