"""Regression: former self nick is not a stranger; Clear has explicit restore.

No hardcoded application allowlist. These tests declare names through the real
My Nick API/archive metadata and exercise generated JS, the live gate, Clear,
Restore, and global undo with actual temporary SQLite files.
"""

import asyncio
from datetime import datetime
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))

from PySide6.QtCore import QObject
from actions.collect_history import CollectHistory
from backend.bridge import Bridge
from backend.chat_agent_js import AGENT_VERSION
from backend.chat_parser import identify_records, verify_private
from backend.collector import CollectorState
from backend.config_manager import ConfigManager
from backend.db_manager import DbManager
from backend.history_models import MessageRecord
from backend.history_service import HistoryService
from test_capture_after_clear import DomCDP, FIXTURE, HAVE_DOM
from test_chat_parser_delta import raw

PEER, OLD, CURRENT, OTHER = 'Катя462', 'Пошлый01', 'Хорошо Все', 'SomeoneElse'
NOW = datetime(2026, 9, 8, 23, 0)


def state(**changes):
    result = dict(ok=True, agent=AGENT_VERSION, tab='private', partner=PEER, title=PEER,
                  me=CURRENT, me_source='pane_roster', participants=2,
                  participant_nicks=[CURRENT, PEER], count=2,
                  in_authors=[PEER], out_authors=[OLD], authors=[PEER, OLD])
    result.update(changes)
    return result


class TestHistoricalIdentity(unittest.TestCase):
    def test_declared_former_self_is_not_a_third_participant(self):
        check = verify_private(state(), PEER, CURRENT, known_self_nicks=[OLD])
        self.assertTrue(check.ok, check.detail)
        self.assertEqual(check.me, CURRENT)
        self.assertEqual(set(check.self_nicks), {CURRENT, OLD})
        self.assertEqual(check.strangers, [])

    def test_unknown_outbound_name_is_not_automatically_learned(self):
        check = verify_private(state(), PEER, CURRENT)
        self.assertFalse(check.ok)
        self.assertEqual(check.strangers, [OLD])

    def test_actual_third_author_is_still_rejected(self):
        check = verify_private(state(in_authors=[PEER, OTHER], count=3), PEER, CURRENT,
                               known_self_nicks=[OLD])
        self.assertFalse(check.ok)
        self.assertEqual(check.strangers, [OTHER])

    def test_known_historical_self_can_have_general_background_after_rename(self):
        check = verify_private(state(in_authors=[PEER, OLD], out_authors=[]), PEER, CURRENT,
                               known_self_nicks=[OLD])
        self.assertTrue(check.ok)
        original = MessageRecord.from_dict(raw('historical text', from_nick=OLD, direction='in', time='21:00'))
        fixed = identify_records([original], check)[0]
        self.assertEqual(fixed.direction, 'out')
        self.assertEqual(fixed.from_nick, OLD)
        self.assertEqual(fixed.text, original.text)
        self.assertEqual(fixed.ts_display, original.ts_display)
        self.assertNotEqual(fixed.fp, original.fp)
        self.assertEqual(original.direction, 'in', 'the raw record is not mutated')

    def test_scoped_roster_can_correct_a_stale_configured_name_without_overwriting_it(self):
        check = verify_private(state(out_authors=[CURRENT]), PEER, OLD)
        self.assertTrue(check.ok)
        self.assertEqual(check.me, CURRENT)
        self.assertEqual(check.identity_source, 'pane_roster')
        self.assertIn(OLD, check.warning)
        self.assertIn(CURRENT, check.warning)

    def test_global_me_fallback_cannot_override_an_explicit_name(self):
        check = verify_private(state(me=OTHER, me_source='global_fallback', participant_nicks=[],
                                     out_authors=[OTHER]), PEER, CURRENT)
        self.assertFalse(check.ok)
        self.assertEqual(check.strangers, [OTHER])

    def test_another_panes_roster_cannot_be_used(self):
        check = verify_private(state(participant_nicks=[CURRENT, OTHER]), PEER, CURRENT,
                               known_self_nicks=[OLD])
        self.assertFalse(check.ok)
        self.assertEqual(check.reason, 'roster_mismatch')

    def test_three_participants_are_refused_even_before_a_third_person_writes(self):
        check = verify_private(state(participants=3, participant_nicks=[CURRENT, PEER, OTHER]),
                               PEER, CURRENT, known_self_nicks=[OLD])
        self.assertFalse(check.ok)
        self.assertEqual(check.reason, 'participants_mismatch')

    def test_room_and_different_peer_stay_refused_with_self_aliases(self):
        for changes in (dict(tab='room'), dict(partner=PEER + ' other', title=PEER + ' other')):
            with self.subTest(changes=changes):
                self.assertFalse(verify_private(state(**changes), PEER, CURRENT,
                                                known_self_nicks=[OLD]).ok)

    def test_push_payload_cannot_declare_its_own_trusted_aliases(self):
        forged = state(known_self_nicks=[OTHER], self_nicks=[OTHER], out_authors=[OTHER])
        self.assertFalse(verify_private(forged, PEER, CURRENT).ok)

    def test_disabling_numeric_counter_guard_does_not_allow_a_third_identity(self):
        check = verify_private(state(participants=3, participant_nicks=[CURRENT, PEER, OTHER]),
                               PEER, CURRENT, known_self_nicks=[OLD], require_two_participants=False)
        self.assertFalse(check.ok)
        check = verify_private(state(participants=3, participant_nicks=[], me_source='global_fallback',
                                     in_authors=[PEER, OTHER]), PEER, CURRENT,
                               known_self_nicks=[OLD], require_two_participants=False)
        self.assertFalse(check.ok)
        self.assertEqual(check.strangers, [OTHER])

    def test_missing_sender_is_incomplete_even_if_text_is_ready(self):
        self.assertTrue(MessageRecord(text='ready body', from_nick='').incomplete)


@unittest.skipUnless(HAVE_DOM, 'Install development DOM dependency: npm ci --prefix tests')
class TestIdentityAndRestoreDOM(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.cdp = await DomCDP().open(FIXTURE.replace('Svetik25❤️', PEER).replace('Хорошо Все', OLD))
        self.addAsyncCleanup(self.cdp.close)
        self.cfg = ConfigManager(os.path.join(self.temp.name, 'config.json'))
        history = self.cfg.get('history')
        history['media']['cache_dir'] = os.path.join(self.temp.name, 'media')
        self.cfg.set('history', history)
        self.service = HistoryService(self.cdp, self.cfg, db_path=os.path.join(self.temp.name, 'history.db'))
        await self.service.init()
        self.addAsyncCleanup(self.service.close)
        self.col = self.service.collector
        self.col.configure(auto_backfill=False, download_media=False, chunk_pause_ms=0)
        self.col.now = lambda: NOW
        self.bridge = Bridge.__new__(Bridge)
        QObject.__init__(self.bridge)
        self.bridge._config, self.bridge._memory, self.bridge._presets = self.cfg, None, None
        self.bridge._engine = types.SimpleNamespace(load_stack=lambda _: None)
        self.bridge.attach_history(self.service)
        self.bridge.set_my_nick(OLD)
        self.events = []
        self.bridge.userdb_changed.connect(lambda payload: self.events.append(json.loads(payload)))

    async def rows(self, hidden=False, nick=PEER):
        person = await self.service.repo.get_person(nick)
        if not person:
            return []
        return await self.service.db.fetchdicts(
            'SELECT * FROM messages WHERE person_id=?' + ('' if hidden else " AND deleted_at=''") + ' ORDER BY ord',
            (person['id'],))

    async def action(self, name, *args):
        self.events.clear()
        done = asyncio.get_running_loop().create_future()
        def handler(payload):
            if not done.done():
                done.set_result(json.loads(payload))
        self.bridge.userdb_changed.connect(handler)
        try:
            result = getattr(self.bridge, name)(*args)
            self.assertTrue(result)
            return await asyncio.wait_for(done, 3)
        finally:
            self.bridge.userdb_changed.disconnect(handler)

    async def seed(self):
        self.assertEqual(await self.col.tick(), CollectorState.COLLECTED)
        self.assertEqual(len(await self.rows()), 2)
        return await self.rows()

    async def rename(self, general_background=False):
        await self.cdp.evaluate('document.querySelector(".primary-text.bold").textContent=' + json.dumps(CURRENT, ensure_ascii=False))
        if general_background:
            await self.cdp.evaluate("document.querySelector('.my-message-background').className='message-container general-background'")
        self.bridge.set_my_nick(CURRENT)

    async def append_new(self, author=CURRENT):
        await self.cdp.evaluate('''(() => {
          const node = document.querySelectorAll('.message-container')[1].cloneNode(true);
          node.className = 'message-container my-message-background';
          node.querySelector('.from').textContent = %s;
          node.querySelector('span.message').textContent = 'Новое после восстановления';
          node.querySelector('.sent-time').textContent = '21:02';
          document.querySelector('.messages-root').appendChild(node);
        })()''' % json.dumps(author, ensure_ascii=False))

    async def test_reported_case_clear_rename_explicit_restore_same_original_ids_and_text(self):
        before = await self.seed()
        await self.action('history_clear_person', PEER)
        await self.rename()
        self.assertEqual(await self.col.tick(), CollectorState.NO_NEW)
        self.assertEqual(await self.rows(), [], 'a tick must not undo Clear')
        self.assertIn(OLD, self.col.state_payload()['known_self_nicks'])
        self.assertEqual(self.col.state_payload()['my_nick'], CURRENT)
        self.assertEqual(await self.service.repo.cleared_count(PEER), 2)
        result = await self.action('history_restore_cleared', PEER)
        self.assertEqual(result['restored'], 2)
        self.assertEqual(await self.rows(), before, 'only the deletion flag is changed; original rows/metadata return')
        self.assertEqual(self.col.state_payload()['total'], 2)
        await self.col.tick()
        self.assertEqual(len(await self.rows(True)), 2, 're-reading must not insert duplicates')

    async def test_archive_self_metadata_is_sufficient_even_without_recent_config_entries(self):
        await self.seed()
        await self.action('history_clear_person', PEER)
        await self.rename()
        self.cfg.set_state(my_nick_recent=[])
        self.assertEqual(await self.col.tick(), CollectorState.NO_NEW)
        self.assertIn(OLD, self.col.state_payload()['known_self_nicks'])

    async def test_declared_nick_history_allows_reimport_into_a_fresh_empty_archive(self):
        await self.rename()
        self.assertEqual(await self.col.tick(), CollectorState.COLLECTED)
        rows = await self.rows()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1]['from_nick'], OLD)
        self.assertEqual(rows[1]['direction'], 'out')

    async def test_historical_general_background_is_normalized_before_dedupe(self):
        before = await self.seed()
        await self.action('history_clear_person', PEER)
        await self.rename(general_background=True)
        await self.col.tick()
        self.assertEqual(await self.rows(), [])
        self.assertEqual(len(await self.rows(True)), 2, 'the same old body must not get a new inbound identity')
        await self.action('history_restore_cleared', PEER)
        self.assertEqual(await self.rows(), before)

    async def test_scoped_browser_self_overrides_stale_config_only_for_capture(self):
        await self.cdp.evaluate('document.querySelector(".primary-text.bold").textContent=' + json.dumps(CURRENT, ensure_ascii=False))
        await self.col.tick()
        self.assertEqual(len(await self.rows()), 2)
        self.assertEqual(self.col.my_nick, CURRENT)
        self.assertEqual(self.col.configured_my_nick, OLD)
        self.assertEqual(self.cfg.get('collector', 'my_nick'), OLD, 'no silent settings rewrite')
        self.assertEqual(self.col.state_payload()['identity_source'], 'pane_roster')

    async def test_explicit_restore_undo_redo_does_not_touch_messages_collected_later(self):
        await self.seed()
        await self.action('history_clear_person', PEER)
        await self.rename()
        await self.col.tick()
        await self.action('history_restore_cleared', PEER)
        await self.append_new()
        await self.col.tick()
        self.assertEqual(len(await self.rows()), 3)
        self.assertEqual(self.bridge._get_global_history()[0][-1]['value']['op'], 'restore_cleared')
        await self.action('undo')
        self.assertEqual([r['text'] for r in await self.rows()], ['Новое после восстановления'])
        await self.action('redo')
        self.assertEqual(len(await self.rows()), 3)
        self.assertEqual(len(await self.rows(True)), 3)
        await self.action('undo')
        self.assertEqual(len(await self.rows()), 1)

    async def test_individual_deletion_is_not_restored_by_restore_cleared(self):
        before = await self.seed()
        await self.action('history_delete_message', PEER, str(before[0]['id']))
        await self.action('history_clear_person', PEER)
        self.assertEqual(await self.service.repo.cleared_count(PEER), 1)
        result = await self.action('history_restore_cleared', PEER)
        self.assertEqual(result['restored'], 1)
        self.assertEqual([r['id'] for r in await self.rows()], [before[1]['id']])
        self.assertTrue((await self.rows(True))[0]['deleted_at'])

    async def test_v11_clear_tokens_are_recognized_from_the_existing_global_history(self):
        before = await self.seed()
        token = '2026-09-08T22:00:00#legacy-clear'
        await self.service.repo.soft_delete_history(PEER, token=token)
        self.bridge._push_global('archive', {'op': 'clear_history', 'nick': PEER, 'token': token})
        self.assertEqual(await self.service.repo.cleared_count(PEER), 0, 'an unknown token is not assumed to be Clear')
        result = await self.action('history_restore_cleared', PEER)
        self.assertEqual(result['restored'], 2)
        self.assertEqual(await self.rows(), before)

    async def test_unknown_legacy_deletion_is_not_guessed_to_be_a_clear(self):
        before = await self.seed()
        await self.service.repo.soft_delete_message(PEER, before[0]['id'], token='unknown-legacy-delete')
        result = await self.action('history_restore_cleared', PEER)
        self.assertEqual(result['restored'], 0)
        self.assertEqual(len(await self.rows()), 1)
        self.assertEqual(self.bridge._get_global_history()[0], [])

    async def test_restoring_twice_adds_no_duplicate_rows_or_noop_history_entry(self):
        await self.seed()
        await self.action('history_clear_person', PEER)
        await self.action('history_restore_cleared', PEER)
        size = len(self.bridge._get_global_history()[0])
        again = await self.action('history_restore_cleared', PEER)
        self.assertEqual(again['restored'], 0)
        self.assertEqual(len(self.bridge._get_global_history()[0]), size)
        self.assertEqual(len(await self.rows(True)), 2)

    async def test_other_person_and_deleted_person_are_not_restored(self):
        await self.seed()
        await self.service.repo.append(OTHER, [raw('other body', from_nick=OTHER)], now=NOW)
        await self.service.repo.soft_delete_history(OTHER)
        await self.action('history_clear_person', PEER)
        await self.action('history_restore_cleared', PEER)
        self.assertEqual(await self.rows(nick=OTHER), [])
        await self.service.repo.soft_delete_history(PEER)
        await self.service.repo.delete_person(PEER)
        self.assertEqual((await self.action('history_restore_cleared', PEER))['restored'], 0)
        self.assertTrue((await self.service.repo.get_person(PEER))['deleted'])

    async def test_restore_is_available_without_a_live_chat_and_does_not_resume_collection(self):
        await self.seed()
        await self.action('history_clear_person', PEER)
        self.col.stop()
        self.assertEqual((await self.action('history_restore_cleared', PEER))['restored'], 2)
        self.assertFalse(self.col.running)
        self.assertEqual(len(await self.rows()), 2)

    async def test_unknown_push_author_and_payload_alias_forgery_stay_refused(self):
        await self.seed()
        await self.rename()
        await self.col.tick()
        result = await self.col.handle_push({'partner': PEER, 'title': PEER, 'tab': 'private',
            'known_self_nicks': [OTHER], 'me': OTHER, 'me_source': 'pane_roster',
            'participant_nicks': [PEER, OTHER],
            'items': [raw('foreign', from_nick=OTHER, direction='out')]})
        self.assertEqual(result, 0)
        self.assertFalse(self.col._verified)
        self.assertEqual(len(await self.rows()), 2)

    async def test_verified_old_self_push_keeps_its_author_without_duplicate_old_rows(self):
        await self.seed()
        await self.rename()
        await self.col.tick()
        result = await self.col.handle_push({'partner': PEER, 'title': PEER, 'tab': 'private',
            'items': [raw('new old-self text', from_nick=OLD, direction='in', time='21:02', idx=2)]})
        self.assertEqual(result, 1)
        row = (await self.rows())[-1]
        self.assertEqual(row['from_nick'], OLD)
        self.assertEqual(row['direction'], 'out')

    async def test_manual_collect_history_uses_the_same_known_identity_gate(self):
        await self.rename()
        block = CollectHistory(pre_delay_ms=0, chunk_pause_ms=0, download_media=False)
        block.now = lambda: NOW
        engine = types.SimpleNamespace(history=self.service, report=lambda *_: None, is_stopping=lambda: False)
        self.assertEqual(await block.execute('', self.cdp, engine), 'ok')
        self.assertEqual(len(await self.rows()), 2)
        self.assertEqual((await self.rows())[1]['from_nick'], OLD)

    async def test_restore_undo_is_refused_on_a_different_database(self):
        await self.seed()
        await self.action('history_clear_person', PEER)
        await self.action('history_restore_cleared', PEER)
        before_index = self.bridge._get_global_history()[1]
        manager = DbManager(self.cfg, self.service, self.temp.name)
        other = await manager.create('other')
        await manager.load(other['path'])
        await self.service.repo.append(PEER, [raw('keep other db', from_nick=PEER)], now=NOW)
        self.assertEqual(self.bridge.undo(), 'null')
        self.assertEqual(self.bridge._get_global_history()[1], before_index)
        self.assertEqual([r['text'] for r in await self.rows()], ['keep other db'])

    async def test_media_links_and_reference_counts_are_preserved_by_restore(self):
        await self.cdp.evaluate("""(() => {
          const wrapper = document.createElement('div');
          wrapper.className = 'image-wrapper';
          wrapper.innerHTML = '<img src="https://example.test/photo.gif" alt="chat image">';
          document.querySelectorAll('.message-content')[1].appendChild(wrapper);
        })()""")
        before = await self.seed()
        media_id = before[1]['media_id']
        self.assertIsNotNone(media_id)
        media_before = await self.service.media.get(media_id)
        await self.action('history_clear_person', PEER)
        await self.action('history_restore_cleared', PEER)
        self.assertEqual(await self.rows(), before)
        self.assertEqual(await self.service.media.get(media_id), media_before)

    async def test_failed_counter_update_rolls_back_the_entire_restore(self):
        await self.seed()
        await self.action('history_clear_person', PEER)
        before = await self.rows(True)
        with patch.object(self.service.repo, '_recount', AsyncMock(side_effect=RuntimeError('counter update failed'))):
            with self.assertRaisesRegex(RuntimeError, 'counter update failed'):
                await self.service.repo.restore_cleared(PEER)
        self.assertEqual(await self.rows(True), before)
        self.assertEqual(await self.rows(), [])
        self.assertEqual((await self.service.repo.get_person(PEER))['message_count'], 0)

    async def test_global_undo_waits_for_the_restore_command_to_finish(self):
        await self.seed()
        await self.action('history_clear_person', PEER)
        entered, release = asyncio.Event(), asyncio.Event()
        original = self.service.repo.restore_cleared
        async def delayed(*args, **kwargs):
            entered.set()
            await release.wait()
            return await original(*args, **kwargs)
        with patch.object(self.service.repo, 'restore_cleared', delayed):
            operation = asyncio.create_task(self.action('history_restore_cleared', PEER))
            try:
                await asyncio.wait_for(entered.wait(), 3)
                self.assertEqual(self.bridge.undo(), 'null')
                self.assertEqual(self.bridge.redo(), 'null')
                self.assertEqual(self.bridge._get_global_history()[1], 0)
            finally:
                release.set()
                await operation
        self.assertEqual(self.bridge._get_global_history()[1], 1)
        self.assertEqual(getattr(self.bridge, '_archive_actions_pending'), 0)

    async def test_failed_restore_undo_keeps_the_global_index_and_rows(self):
        await self.seed()
        await self.action('history_clear_person', PEER)
        await self.action('history_restore_cleared', PEER)
        previous = self.bridge._get_global_history()[1]
        error = asyncio.get_running_loop().create_future()
        def failed(_scope, message):
            if not error.done():
                error.set_result(message)
        self.bridge.history_error.connect(failed)
        try:
            with patch.object(self.service.repo, 'apply_clear_restore', AsyncMock(side_effect=RuntimeError('write failed'))):
                self.assertEqual(json.loads(self.bridge.undo())['kind'], 'archive')
                self.assertIn('write failed', await asyncio.wait_for(error, 3))
        finally:
            self.bridge.history_error.disconnect(failed)
        self.assertEqual(self.bridge._get_global_history()[1], previous)
        self.assertEqual(len(await self.rows()), 2)

    async def test_history_page_reports_recoverable_count_for_the_empty_view(self):
        await self.seed()
        await self.action('history_clear_person', PEER)
        replies = []
        self.bridge.history_page_ready.connect(lambda _req, payload: replies.append(json.loads(payload)))
        await self.bridge._history_page('inspect', PEER, {})
        self.assertEqual(replies[-1]['items'], [])
        self.assertEqual(replies[-1]['cleared_messages'], 2)
        self.assertEqual(replies[-1]['stats']['cleared_messages'], 2)


if __name__ == '__main__':
    unittest.main(verbosity=2)
