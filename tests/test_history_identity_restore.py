"""Regression: former self nick is not a stranger; a full reset recollects fresh.

No hardcoded application allowlist. These tests declare names through the real
My Nick API/archive metadata and exercise generated JS, the live gate, Clear,
reset, and isolated global undo with actual temporary SQLite files.
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
class TestIdentityAndResetDOM(unittest.IsolatedAsyncioTestCase):
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


    async def test_declared_nick_history_allows_reimport_into_a_fresh_empty_archive(self):
        await self.rename()
        self.assertEqual(await self.col.tick(), CollectorState.COLLECTED)
        rows = await self.rows()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1]['from_nick'], OLD)
        self.assertEqual(rows[1]['direction'], 'out')


    async def test_scoped_browser_self_overrides_stale_config_only_for_capture(self):
        await self.cdp.evaluate('document.querySelector(".primary-text.bold").textContent=' + json.dumps(CURRENT, ensure_ascii=False))
        await self.col.tick()
        self.assertEqual(len(await self.rows()), 2)
        self.assertEqual(self.col.my_nick, CURRENT)
        self.assertEqual(self.col.configured_my_nick, OLD)
        self.assertEqual(self.cfg.get('collector', 'my_nick'), OLD, 'no silent settings rewrite')
        self.assertEqual(self.col.state_payload()['identity_source'], 'pane_roster')


    async def test_manual_collect_history_uses_the_same_known_identity_gate(self):
        await self.rename()
        block = CollectHistory(pre_delay_ms=0, chunk_pause_ms=0, download_media=False)
        block.now = lambda: NOW
        engine = types.SimpleNamespace(history=self.service, report=lambda *_: None, is_stopping=lambda: False)
        self.assertEqual(await block.execute('', self.cdp, engine), 'ok')
        self.assertEqual(len(await self.rows()), 2)
        self.assertEqual((await self.rows())[1]['from_nick'], OLD)


    async def test_unknown_push_author_and_payload_alias_forgery_stay_refused(self):
        await self.seed()
        await self.rename()
        await self.col.tick()
        result = await self.col.handle_push({'partner': PEER, 'title': PEER, 'tab': 'private', 'capture_epoch': self.col._capture_epoch,
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
        result = await self.col.handle_push({'partner': PEER, 'title': PEER, 'tab': 'private', 'capture_epoch': self.col._capture_epoch,
            'items': [raw('new old-self text', from_nick=OLD, direction='in', time='21:02', idx=2)]})
        self.assertEqual(result, 1)
        row = (await self.rows())[-1]
        self.assertEqual(row['from_nick'], OLD)
        self.assertEqual(row['direction'], 'out')


    async def test_old_self_identity_survives_clear_outside_the_message_tracking_store(self):
        await self.seed()
        await self.action('history_clear_person', PEER)
        await self.rename()
        self.cfg.set_state(my_nick_recent=[])
        self.assertEqual((await self.service.repo.get_person(PEER))['my_nicks'], [])
        self.assertIn(OLD, self.cfg.get_state('declared_self_nicks'))
        self.assertEqual(await self.col.tick(), CollectorState.COLLECTED)
        self.assertEqual(len(await self.rows()), 2)
        self.assertEqual((await self.rows())[1]['from_nick'], OLD)

    async def test_historical_general_background_recollects_as_self_after_full_reset(self):
        before = await self.seed()
        await self.action('history_clear_person', PEER)
        await self.rename(general_background=True)
        self.assertEqual(await self.col.tick(), CollectorState.COLLECTED)
        fresh = await self.rows()
        self.assertEqual(len(fresh), 2)
        self.assertEqual(fresh[1]['direction'], 'out')
        self.assertEqual(fresh[1]['from_nick'], OLD)
        self.assertTrue({r['id'] for r in before}.isdisjoint(r['id'] for r in fresh))
        await self.col.tick()
        self.assertEqual(len(await self.rows(True)), 2)

    async def test_legacy_clear_conversion_keeps_explicit_undo_but_no_active_tombstones(self):
        before = await self.seed()
        token = '2026-09-08T22:00:00#legacy-clear'
        await self.service.repo.legacy_hide_history(PEER, token=token)
        self.bridge._push_global('archive', {'op': 'clear_history', 'nick': PEER, 'token': token})
        await self.service._migrate_bulk_tombstones(self.service.db)
        self.service.reset_runtime(PEER)
        self.assertEqual(await self.rows(True), [])
        self.assertEqual(self.bridge._get_global_history()[0][-1]['value']['op'], 'reset_history')
        await self.action('undo')
        self.assertEqual([r['text'] for r in await self.rows()], [r['text'] for r in before])
        await self.action('redo')
        self.assertEqual(await self.rows(True), [])
        await self.col.tick()
        self.assertEqual(len(await self.rows()), 2)

    async def test_legacy_deleted_person_is_converted_and_can_be_seen_as_new(self):
        await self.seed()
        token = self.service.repo.new_op_token()
        await self.service.repo.legacy_hide_person(PEER, token=token)
        self.bridge._push_global('archive', {'op': 'delete_person', 'nick': PEER, 'token': token})
        await self.service._migrate_bulk_tombstones(self.service.db)
        self.service.reset_runtime(PEER)
        self.assertIsNone(await self.service.repo.get_person(PEER))
        await self.col.tick()
        self.assertEqual(len(await self.rows()), 2)
        await self.action('undo')
        self.assertEqual(len(await self.rows(True)), 2, 'legacy undo merges with fresh collection')

    async def test_legacy_restore_undo_does_not_reintroduce_a_bulk_denylist(self):
        await self.seed()
        token = await self.service.repo.legacy_hide_history(PEER)
        groups = await self.service.repo.cleared_groups(PEER)
        await self.service.repo.apply_clear_restore(PEER, groups)
        self.bridge._push_global('archive', {'op': 'restore_cleared', 'nick': PEER,
                                             'db_path': self.service.db.path, 'groups': groups})
        await self.action('undo')
        self.assertEqual(await self.rows(True), [])
        await self.action('redo')
        self.assertEqual(len(await self.rows()), 2)
        self.assertEqual(await self.service.repo.deleted_count(PEER), 0)

    async def test_clear_page_has_no_old_hidden_count_or_restore_registry(self):
        await self.seed()
        await self.action('history_clear_person', PEER)
        replies = []
        self.bridge.history_page_ready.connect(lambda _req, data: replies.append(json.loads(data)))
        await self.bridge._history_page('inspect', PEER, {})
        self.assertEqual(replies[-1]['items'], [])
        self.assertEqual(replies[-1]['total'], 0)
        self.assertEqual(replies[-1]['stats']['hidden'], 0)
        self.assertNotIn('cleared_messages', replies[-1])


if __name__ == '__main__':
    unittest.main(verbosity=2)
