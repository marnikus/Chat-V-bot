"""Clean-slate contract: active state is erased; undo is never a seen registry.

Run: REQUIRE_DOM_TESTS=1 python -m unittest discover -s tests -p 'test_clean_slate_reset.py' -v
The DOM cases execute the shipped reset/state/slice/push code through the real
protocol adapter. All storage cases use actual SQLite files and command paths.
"""

import asyncio
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import types
import unittest
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))

from PySide6.QtCore import QObject
from backend.bridge import Bridge
from backend.chat_parser import ChatParser
from backend.collector import CollectorState
from backend.config_manager import ConfigManager
from backend.db_manager import DbManager
from backend.history_db import inspect_archive
from backend.history_service import HistoryService
from backend.user_memory import UserMemory, UserRecord
from test_chat_parser_delta import FakePage, raw
from test_capture_after_clear import DomCDP, FIXTURE, HAVE_DOM

NICK, ME = 'Svetik25❤️', 'Хорошо Все'
NOW = datetime(2026, 9, 9, 23, 0)


class ResetCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.cfg = ConfigManager(os.path.join(self.temp.name, 'config.json'))
        history = self.cfg.get('history')
        history['media']['cache_dir'] = os.path.join(self.temp.name, 'media')
        self.cfg.set('history', history)
        self.page = FakePage([raw('message ' + str(i), from_nick=NICK, time='21:00', idx=i)
                              for i in range(25)], partner=NICK, me=ME)
        self.page.is_connected = True
        self.service = HistoryService(self.page, self.cfg, db_path=os.path.join(self.temp.name, 'history.db'))
        await self.service.init()
        self.addAsyncCleanup(self.service.close)
        self.col, self.repo, self.db = self.service.collector, self.service.repo, self.service.db
        self.col.configure(my_nick=ME, download_media=False, auto_backfill=False, chunk_pause_ms=0)
        self.col.now = lambda: NOW
        self.bridge = Bridge.__new__(Bridge)
        QObject.__init__(self.bridge)
        self.bridge._config, self.bridge._memory, self.bridge._presets = self.cfg, None, None
        self.bridge._engine = types.SimpleNamespace(load_stack=lambda _: None)
        self.bridge.attach_history(self.service)

    async def action(self, method, *args):
        future = asyncio.get_running_loop().create_future()
        def changed(payload):
            if not future.done():
                future.set_result(json.loads(payload))
        self.bridge.userdb_changed.connect(changed)
        try:
            self.assertTrue(getattr(self.bridge, method)(*args))
            return await asyncio.wait_for(future, 5)
        finally:
            self.bridge.userdb_changed.disconnect(changed)

    async def seed(self):
        self.assertEqual(await self.col.tick(), CollectorState.COLLECTED)
        self.assertEqual(await self.count(), 25)
        self.assertEqual(self.col.state_payload()['session_added'], 25)

    async def count(self):
        return int(await self.service.db.scalar('SELECT COUNT(*) FROM messages', (), 0))

    async def rows(self):
        return await self.service.db.fetchdicts('SELECT * FROM messages ORDER BY ord')

    async def assert_forgotten(self, *, deleted=False):
        for table in ('messages', 'cursors', 'gaps', 'media'):
            self.assertEqual(await self.db.scalar(f'SELECT COUNT(*) FROM {table}'), 0, table)
        person = await self.repo.get_person(NICK)
        if deleted:
            self.assertIsNone(person)
        else:
            self.assertIsNotNone(person)
            for key in ('message_count', 'in_count', 'out_count', 'media_count', 'last_ord'):
                self.assertEqual(person[key], 0, key)
            self.assertIsNone(person['first_seen'])
            self.assertIsNone(person['last_seen'])
            self.assertEqual(person['my_nicks'], [])
            self.assertFalse(person['deleted'])
        self.assertEqual(self.col.state_payload()['added'], 0)
        self.assertEqual(self.col.state_payload()['session_added'], 0)
        self.assertEqual(self.col.state_payload()['total'], 0)
        self.assertEqual(self.col.state_payload()['last_probe'], {})
        self.assertEqual(self.col.state_payload()['capture_diagnostics'], [])
        self.assertFalse(self.col._verified)
        self.assertEqual(self.service.parser.last_capture_diagnostic, {})
        if self.db.fts_enabled:
            self.assertEqual(await self.db.scalar('SELECT COUNT(*) FROM messages_fts'), 0)


class TestCleanSlateStorage(ResetCase):
    async def test_clear_erases_all_tracking_and_same_25_messages_are_new_on_next_scan(self):
        await self.seed()
        old = await self.rows()
        person = await self.repo.get_person(NICK)
        await self.repo.record_gap(person['id'], 25, 'test', 'old pointer')
        await self.db.execute("UPDATE messages SET text_scan_at='2099-01-01', media_scan_at='2099-01-01'")
        await self.repo.mark_backfilled(person['id'])
        await self.db.execute("UPDATE persons SET note='keep this contact note' WHERE id=?", (person['id'],))
        await self.db.commit()
        await self.action('history_clear_person', NICK)
        await self.assert_forgotten()
        self.assertEqual((await self.repo.get_person(NICK))['note'], 'keep this contact note')
        self.assertEqual((await self.repo.get_person(NICK))['id'], person['id'])
        self.assertEqual(await self.col.tick(), CollectorState.COLLECTED)
        self.assertEqual(await self.count(), 25)
        fresh = await self.rows()
        self.assertEqual([r['text'] for r in fresh], [r['text'] for r in old])
        self.assertTrue({r['id'] for r in old}.isdisjoint(r['id'] for r in fresh))
        self.assertEqual([r['ord'] for r in fresh], list(range(1, 26)))
        self.assertEqual(self.col.state_payload()['session_added'], 25)

    async def test_delete_removes_person_and_reopening_creates_a_fresh_person_and_messages(self):
        await self.seed()
        old_pid = (await self.repo.get_person(NICK))['id']
        await self.action('history_delete_person', NICK, False)
        await self.assert_forgotten(deleted=True)
        self.assertEqual(await self.col.tick(), CollectorState.COLLECTED)
        self.assertEqual(await self.count(), 25)
        self.assertNotEqual((await self.repo.get_person(NICK))['id'], old_pid)
        self.assertEqual(self.col.state_payload()['session_added'], 25)

    async def test_repeated_clear_cycles_are_25_zero_25_not_50(self):
        await self.seed()
        for _ in range(3):
            await self.action('history_clear_person', NICK)
            await self.assert_forgotten()
            await self.col.tick()
            self.assertEqual(await self.count(), 25)
            self.assertEqual(self.col.state_payload()['session_added'], 25)
            await self.col.tick()
            self.assertEqual(await self.count(), 25)
            self.assertEqual(self.col.state_payload()['session_added'], 25)

    async def test_clear_removes_individual_and_legacy_bulk_tombstones_too(self):
        await self.seed()
        first = (await self.rows())[0]
        await self.repo.soft_delete_message(NICK, first['id'])
        await self.repo.legacy_hide_history(NICK)
        self.assertEqual(await self.repo.deleted_count(NICK), 25)
        await self.action('history_clear_person', NICK)
        await self.assert_forgotten()
        await self.col.tick()
        self.assertEqual(await self.count(), 25)
        self.assertEqual(await self.repo.deleted_count(NICK), 0)

    async def test_low_level_bulk_apis_also_remove_real_rows_not_just_visibility(self):
        await self.seed()
        await self.repo.soft_delete_history(NICK)
        self.assertEqual(await self.count(), 0)
        self.assertEqual(await self.db.scalar('SELECT COUNT(*) FROM cursors'), 0)
        await self.col.tick()
        self.assertEqual(await self.count(), 25)
        await self.repo.delete_person(NICK)
        self.assertIsNone(await self.repo.get_person(NICK))
        self.assertEqual(await self.count(), 0)

    async def test_snapshot_is_not_an_archive_and_collection_never_reads_it(self):
        await self.seed()
        await self.action('history_clear_person', NICK)
        entry = self.bridge._get_global_history()[0][-1]['value']
        snapshot = entry['snapshot']
        self.assertTrue(os.path.isfile(snapshot))
        self.assertFalse(inspect_archive(snapshot))
        with sqlite3.connect(snapshot) as undo:
            self.assertEqual(undo.execute('SELECT COUNT(*) FROM messages').fetchone()[0], 25)
        before = hashlib.sha256(Path(snapshot).read_bytes()).hexdigest()
        with patch.object(self.service.undo_store, 'read', AsyncMock(side_effect=AssertionError('collector consulted undo'))):
            await self.col.tick()
            await self.col.tick()
        self.assertEqual(await self.count(), 25)
        self.assertEqual(hashlib.sha256(Path(snapshot).read_bytes()).hexdigest(), before)
        databases = await self.db.fetchall('PRAGMA database_list')
        self.assertFalse(any(str(row[2]) == snapshot for row in databases))
        self.assertEqual([p['name'] for p in DbManager(self.cfg, self.service).list_dbs()], ['history.db'])

    async def test_undo_before_rescan_restores_snapshot_and_redo_is_another_fresh_reset(self):
        await self.seed()
        old = await self.rows()
        await self.action('history_clear_person', NICK)
        await self.action('undo')
        self.assertEqual(await self.rows(), old)
        self.assertEqual(await self.db.scalar('SELECT COUNT(*) FROM cursors'), 0)
        await self.action('redo')
        await self.assert_forgotten()
        await self.col.tick()
        self.assertEqual(await self.count(), 25)

    async def test_undo_after_recollection_merges_without_duplicates_or_losing_new_messages(self):
        await self.seed()
        await self.action('history_delete_person', NICK, False)
        await self.col.tick()
        self.page.append(raw('a new message', from_nick=NICK, time='21:01', idx=25))
        await self.col.tick()
        self.assertEqual(await self.count(), 26)
        await self.action('undo')
        self.assertEqual(await self.count(), 26)
        self.assertEqual(len({r['dup_key'] for r in await self.rows()}), 26)
        await self.action('redo')
        self.assertEqual(await self.count(), 0)
        self.assertIsNone(await self.repo.get_person(NICK))
        await self.action('undo')
        self.assertEqual(await self.count(), 26, 'redo must update the command-side snapshot')

    async def test_backup_failure_keeps_live_rows_and_cursor_intact(self):
        await self.seed()
        rows = await self.rows()
        pid = (await self.repo.get_person(NICK))['id']
        cursor = await self.repo.get_cursor(pid)
        with patch.object(self.service.undo_store, 'capture', AsyncMock(side_effect=OSError('snapshot failed'))):
            with self.assertRaisesRegex(OSError, 'snapshot failed'):
                await self.service.reset_conversation(NICK)
        self.assertEqual(await self.rows(), rows)
        self.assertEqual(await self.repo.get_cursor(pid), cursor)
        self.assertTrue(self.col._verified)

    async def test_transaction_failure_rolls_back_all_active_state(self):
        await self.seed()
        before = await self.rows()
        original = self.db.execute
        async def fail(sql, params=()):
            if sql.startswith('DELETE FROM cursors'):
                raise sqlite3.OperationalError('injected deletion failure')
            return await original(sql, params)
        with patch.object(self.db, 'execute', fail):
            with self.assertRaisesRegex(sqlite3.OperationalError, 'injected'):
                await self.service.reset_conversation(NICK)
        self.assertEqual(await self.rows(), before)
        self.assertEqual((await self.repo.get_person(NICK))['message_count'], 25)

    async def test_other_person_and_their_cursor_session_counts_are_untouched(self):
        await self.seed()
        await self.repo.append('Other', [raw('other body', from_nick='Other')], now=NOW,
                               dom_count=1, head_sig='other', tail_sig='other')
        other = await self.repo.get_person('Other')
        cursor = await self.repo.get_cursor(other['id'])
        self.col._session_added['Other'] = 7
        await self.action('history_clear_person', NICK)
        self.assertEqual(await self.repo.get_person('Other'), other)
        self.assertEqual(await self.repo.get_cursor(other['id']), cursor)
        self.assertEqual(self.col._session_added['Other'], 7)
        self.assertEqual(await self.db.scalar('SELECT COUNT(*) FROM messages'), 1)

    async def test_clear_while_paused_does_not_resume_or_restore_old_session_count(self):
        await self.seed()
        self.col.pause()
        await self.action('history_clear_person', NICK)
        self.assertTrue(self.col.paused)
        self.assertEqual(self.col.state_payload()['session_added'], 0)
        self.assertEqual(await self.col.tick(), CollectorState.PAUSED)
        self.col.resume()
        await self.col.tick()
        self.assertEqual(await self.count(), 25)

    async def test_restart_after_clear_starts_fresh_without_reading_undo(self):
        await self.seed()
        await self.action('history_clear_person', NICK)
        await self.service.close()
        service = HistoryService(self.page, self.cfg, db_path=self.db.path)
        get_state = self.cfg.get_state
        def without_undo(key, *args, **kwargs):
            if key == 'undo_history':
                raise AssertionError('clean archive consulted undo history')
            return get_state(key, *args, **kwargs)
        try:
            with patch.object(self.cfg, 'get_state', without_undo):
                await service.init()
                service.collector.configure(my_nick=ME, auto_backfill=False, download_media=False)
                with patch.object(service.undo_store, 'read', AsyncMock(side_effect=AssertionError('undo consulted'))):
                    await service.collector.tick()
            self.assertEqual(await service.db.scalar('SELECT COUNT(*) FROM messages'), 25)
        finally:
            await service.close()

    async def test_old_bulk_marks_are_isolated_at_startup_so_old_empty_views_do_not_stay_stuck(self):
        await self.seed()
        token = await self.repo.legacy_hide_history(NICK)
        self.bridge._push_global('archive', {'op': 'clear_history', 'nick': NICK, 'token': token})
        await self.service.close()
        service = HistoryService(self.page, self.cfg, db_path=self.db.path)
        try:
            await service.init()
            self.assertEqual(await service.db.scalar('SELECT COUNT(*) FROM messages'), 0)
            self.assertEqual(await service.db.scalar('SELECT COUNT(*) FROM cursors'), 0)
            entry = self.cfg.get_state('undo_history')[-1]['value']
            self.assertEqual(entry['op'], 'reset_history')
            self.assertTrue(os.path.isfile(entry['snapshot']))
            service.collector.configure(my_nick=ME, auto_backfill=False, download_media=False)
            await service.collector.tick()
            self.assertEqual(await service.db.scalar('SELECT COUNT(*) FROM messages'), 25)
        finally:
            await service.close()

    async def test_media_rows_and_exclusive_files_leave_the_active_store_but_undo_has_bytes(self):
        self.page.messages = [raw('', from_nick=NICK, time='21:00', kind='gif',
                                  media={'url': 'https://example.test/a.gif', 'kind': 'gif'})]
        await self.col.tick()
        row = (await self.rows())[0]
        path = self.service.media._target_path(NICK, 'gif', '2026-09-09', '.gif')
        Path(path).write_bytes(b'GIF89a-test-payload')
        await self.db.execute("UPDATE media SET state='cached',cache_path=?,bytes=18 WHERE id=?", (path, row['media_id']))
        await self.db.commit()
        await self.action('history_clear_person', NICK)
        await self.assert_forgotten()
        self.assertFalse(os.path.exists(path))
        await self.action('undo')
        restored = (await self.rows())[0]
        media = await self.service.media.get(restored['media_id'])
        self.assertEqual(Path(media['cache_path']).read_bytes(), b'GIF89a-test-payload')
        self.assertEqual(media['url'], 'https://example.test/a.gif')
        self.assertEqual(media['ref_count'], 1)

    async def test_legacy_conversion_does_not_overwrite_concurrent_global_history_edits(self):
        await self.seed()
        token = await self.repo.legacy_hide_history(NICK)
        self.bridge._push_global('archive', {'op': 'clear_history', 'nick': NICK, 'token': token})
        capture = self.service.undo_store.capture
        async def concurrent_edit(*args, **kwargs):
            snapshot = await capture(*args, **kwargs)
            self.bridge._push_global('labels', {'before': {}, 'after': {'keep': True}})
            return snapshot
        with patch.object(self.service.undo_store, 'capture', concurrent_edit):
            await self.service._migrate_bulk_tombstones(self.db)
        history, index = self.bridge._get_global_history()
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0]['value']['op'], 'reset_history')
        self.assertEqual(history[1]['kind'], 'labels')
        self.assertEqual(index, 1)

    async def test_shared_media_is_not_deleted_with_the_reset_person(self):
        media = {'url': 'https://example.test/shared.gif', 'kind': 'gif'}
        await self.repo.append(NICK, [raw('', from_nick=NICK, kind='gif', media=media)], now=NOW)
        await self.repo.append('Other', [raw('', from_nick='Other', kind='gif', media=media)], now=NOW)
        mid = await self.db.scalar('SELECT id FROM media')
        await self.action('history_delete_person', NICK, False)
        self.assertEqual(await self.db.scalar('SELECT COUNT(*) FROM messages'), 1)
        self.assertEqual(await self.db.scalar('SELECT ref_count FROM media WHERE id=?', (mid,)), 1)
        self.assertEqual(await self.db.scalar('SELECT owner FROM media WHERE id=?', (mid,)), 'Other')
    async def test_legacy_conversion_preserves_post_clear_live_rows_and_their_order(self):
        await self.seed()
        token = await self.repo.legacy_hide_history(NICK)
        self.bridge._push_global('archive', {'op': 'clear_history', 'nick': NICK, 'token': token})
        self.page.append(raw('new since old clear', from_nick=NICK, time='21:01', idx=25))
        await self.col.tick()
        self.assertEqual(await self.db.scalar("SELECT COUNT(*) FROM messages WHERE deleted_at=''"), 1)
        await self.service._migrate_bulk_tombstones(self.db)
        self.service.reset_runtime(NICK)
        self.assertEqual(await self.count(), 1)
        self.assertEqual((await self.rows())[0]['ord'], 1)
        await self.col.tick()
        self.assertEqual(await self.count(), 26)
        self.assertEqual((await self.rows())[-1]['text'], 'new since old clear')
        self.assertEqual([r['ord'] for r in await self.rows()], list(range(1, 27)))

    async def test_undo_is_bound_to_the_original_archive(self):
        await self.seed()
        await self.action('history_clear_person', NICK)
        index = self.bridge._get_global_history()[1]
        manager = DbManager(self.cfg, self.service, self.temp.name)
        other = await manager.create('other')
        await manager.load(other['path'])
        await self.service.repo.append(NICK, [raw('keep other archive', from_nick=NICK)], now=NOW)
        self.assertEqual(self.bridge.undo(), 'null')
        self.assertEqual(self.bridge._get_global_history()[1], index)
        self.assertEqual((await self.rows())[0]['text'], 'keep other archive')

    async def test_cancelled_reset_cannot_commit_a_partial_delete(self):
        await self.seed()
        before = await self.rows()
        entered, release = asyncio.Event(), asyncio.Event()
        original = self.repo.forget_messages
        async def paused(*args, **kwargs):
            result = await original(*args, **kwargs)
            entered.set()
            await release.wait()
            return result
        with patch.object(self.repo, 'forget_messages', paused):
            task = asyncio.create_task(self.service.reset_conversation(NICK))
            await asyncio.wait_for(entered.wait(), 3)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertEqual(await self.rows(), before)
        self.assertEqual((await self.repo.get_person(NICK))['message_count'], 25)
        self.assertFalse(self.db.conn.in_transaction)

    async def test_delete_queue_undo_is_scoped_and_keeps_people_discovered_later(self):
        memory = UserMemory(os.path.join(self.temp.name, 'queue.db'))
        await memory.init()
        self.addAsyncCleanup(memory.close)
        self.bridge._memory = memory
        await memory.upsert_user(UserRecord(NICK))
        await memory.upsert_user(UserRecord('Other'))
        await memory.mark_messaged(NICK)
        await self.seed()
        await self.action('history_delete_person', NICK, False)
        self.assertIsNone(await memory.get_user(NICK))
        await memory.upsert_user(UserRecord('New after delete'))
        await self.action('undo')
        self.assertTrue((await memory.get_user(NICK)).messaged)
        self.assertIsNotNone(await memory.get_user('Other'))
        self.assertIsNotNone(await memory.get_user('New after delete'))

    async def test_explicit_undo_can_restore_cached_bytes_after_message_recollection(self):
        self.page.messages = [raw('', from_nick=NICK, kind='gif', time='21:00',
                                 media={'url': 'https://example.test/reused.gif', 'kind': 'gif'})]
        await self.col.tick()
        row = (await self.rows())[0]
        target = self.service.media._target_path(NICK, 'gif', '2026-09-09', '.gif')
        Path(target).write_bytes(b'GIF89a-original')
        await self.db.execute("UPDATE media SET state='cached',cache_path=? WHERE id=?", (target, row['media_id']))
        await self.db.commit()
        await self.action('history_clear_person', NICK)
        await self.col.tick()
        self.assertEqual(await self.count(), 1)
        await self.action('undo')
        self.assertEqual(await self.count(), 1)
        restored = (await self.rows())[0]
        media = await self.service.media.get(restored['media_id'])
        self.assertEqual(Path(media['cache_path']).read_bytes(), b'GIF89a-original')
        self.assertEqual(media['ref_count'], 1)



@unittest.skipUnless(HAVE_DOM, 'Install DOM test dependency: npm ci --prefix tests')
class TestCleanSlateDOM(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.cdp = await DomCDP().open(FIXTURE)
        self.addAsyncCleanup(self.cdp.close)
        self.cfg = ConfigManager(os.path.join(self.temp.name, 'config.json'))
        self.service = HistoryService(self.cdp, self.cfg, db_path=os.path.join(self.temp.name, 'history.db'))
        await self.service.init()
        self.addAsyncCleanup(self.service.close)
        self.col = self.service.collector
        self.col.configure(my_nick=ME, auto_backfill=False, download_media=False, chunk_pause_ms=0)
        self.col.now = lambda: NOW

    async def count(self):
        return int(await self.service.db.scalar('SELECT COUNT(*) FROM messages'))

    async def test_same_dom_recollects_after_clear_and_after_delete_with_a_new_epoch(self):
        await self.col.tick()
        first = await self.service.parser.state()
        self.assertEqual(await self.count(), 2)
        await self.service.reset_conversation(NICK)
        self.assertEqual(await self.count(), 0)
        await self.col.tick()
        self.assertEqual(await self.count(), 2)
        second = await self.service.parser.state()
        self.assertNotEqual(first['capture_epoch'], second['capture_epoch'])
        await self.service.reset_conversation(NICK, delete_person=True)
        self.assertIsNone(await self.service.repo.get_person(NICK))
        await self.col.tick()
        self.assertEqual(await self.count(), 2)

    async def test_queued_old_push_is_rejected_even_after_a_fresh_gate_is_verified(self):
        await self.col.tick()
        state = await self.service.parser.state()
        old = json.loads(await self.cdp.evaluate('JSON.stringify(window.__cvbAgent.slice(0,2))'))
        payload = {'tab': 'private', 'partner': NICK, 'title': NICK,
                   'capture_epoch': state['capture_epoch'], 'items': old['items']}
        await self.service.reset_conversation(NICK)
        await self.col.tick()
        # Clear only SQL rows to expose a mistaken late insertion, without
        # resetting the now freshly verified epoch a second time.
        await self.service.repo.forget_messages(NICK)
        self.assertEqual(await self.col.handle_push(payload), 0)
        self.assertEqual(await self.count(), 0)

    async def test_pre_reset_cache_is_not_used_when_text_changed_without_an_observer(self):
        await self.col.tick()
        await self.cdp.evaluate("window.__cvbAgent.uninstall(); document.querySelector('span.message').textContent='fresh after reset'")
        await self.service.reset_conversation(NICK)
        await self.col.tick()
        texts = [r[0] for r in await self.service.db.fetchall('SELECT text FROM messages ORDER BY ord')]
        self.assertEqual(texts[0], 'fresh after reset')
        self.assertNotIn('Старое сообщение', texts)

    async def test_failed_browser_reset_is_deferred_and_cannot_verify_old_payloads(self):
        await self.col.tick()
        await self.service.reset_conversation(NICK)
        original = self.cdp.evaluate
        async def fail_reset(expression):
            if '/*CVB_RESET_AGENT*/' in expression:
                raise ConnectionError('temporary disconnect')
            return await original(expression)
        with patch.object(self.cdp, 'evaluate', fail_reset):
            self.assertNotEqual(await self.col.tick(), CollectorState.COLLECTED)
            self.assertFalse(self.col._verified)
            self.assertEqual(await self.count(), 0)
        await self.col.tick()
        self.assertEqual(await self.count(), 2)


if __name__ == '__main__':
    unittest.main(verbosity=2)
