"""Capture regression: real generated JS → DOM/protocol → parser → SQLite.

The host replaces Chrome/transport, NOT message records or probe expressions.
It uses an actual DOM implementation, preserves JS exceptions, and emits real
MutationObserver binding payloads. It is not a live Chrome/layout test.

Setup: npm ci --prefix tests
Run: python -m unittest discover -s tests -p 'test_capture_after_clear.py' -v
Set REQUIRE_DOM_TESTS=1 in CI to fail, rather than skip, if jsdom is absent.
"""

import asyncio
from datetime import datetime
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import AsyncMock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))

from PySide6.QtCore import QObject
from backend.bridge import Bridge
from backend.cdp_client import CDPClient, CDPEvaluationError
from backend.chat_agent_js import AGENT_VERSION
from backend.chat_parser import CaptureReadError, ChatParser
from backend.collector import CollectorState
from backend.config_manager import ConfigManager
from backend.history_service import HistoryService
from test_chat_parser_delta import FakePage

NICK, ME = 'Svetik25❤️', 'Хорошо Все'
NOW = datetime(2026, 9, 8, 23, 0)
FIXTURE = (ROOT / 'tests/fixtures/private_capture.html').read_text()
NODE = shutil.which('node')
HAVE_DOM = NODE and subprocess.run(
    [NODE, '-e', "require('jsdom')"], cwd=ROOT / 'tests',
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
if os.environ.get('REQUIRE_DOM_TESTS') and not HAVE_DOM:
    raise RuntimeError('DOM regression tests required: run npm ci --prefix tests')


class DomCDP(CDPClient):
    """Use the production evaluate decoder/event dispatcher with a DOM host."""

    @property
    def is_connected(self):
        return self._connected and getattr(self, 'host', None) is not None and self.host.returncode is None

    async def open(self, html=FIXTURE):
        self.host = await asyncio.create_subprocess_exec(
            NODE, str(ROOT / 'tests/capture_dom_host.js'), cwd=ROOT,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE)
        self.forward_events = False
        self._connected = True
        self._receive_task = asyncio.create_task(self._read_host())
        await self.send('Test.load', {'html': html})
        return self

    async def _read_host(self):
        try:
            while line := await self.host.stdout.readline():
                frame = json.loads(line)
                mid = frame.get('id')
                if mid in self._pending:
                    self._pending.pop(mid).set_result(frame)
                elif frame.get('method') and self.forward_events:
                    self._dispatch_event(frame)
        finally:
            for future in self._pending.values():
                if not future.done():
                    future.set_exception(ConnectionError('DOM host stopped'))
            self._pending.clear()

    async def send(self, method, params=None):
        self._cmd_id += 1
        mid = self._cmd_id
        future = asyncio.get_running_loop().create_future()
        self._pending[mid] = future
        self.host.stdin.write((json.dumps({'id': mid, 'method': method, 'params': params or {}},
                                         ensure_ascii=False) + '\n').encode())
        await self.host.stdin.drain()
        return await asyncio.wait_for(future, 5)

    async def close(self):
        task = self._receive_task
        self.host.stdin.close()
        await asyncio.wait_for(self.host.wait(), 5)
        if task:
            await task
        self._receive_task = None
        self._connected = False
        stderr = (await self.host.stderr.read()).decode()
        if self.host.returncode:
            raise AssertionError(f'DOM host failed: {stderr}')


@unittest.skipUnless(HAVE_DOM, 'Install development DOM dependency: npm ci --prefix tests')
class TestCaptureDOM(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.cdp = await DomCDP().open()
        self.addAsyncCleanup(self.cdp.close)
        self.cfg = ConfigManager(os.path.join(self.temp.name, 'config.json'))
        history = self.cfg.get('history')
        history['media']['cache_dir'] = os.path.join(self.temp.name, 'media')
        self.cfg.set('history', history)
        self.service = HistoryService(self.cdp, self.cfg,
                                      db_path=os.path.join(self.temp.name, 'history.db'))
        await self.service.init()
        self.addAsyncCleanup(self.service.close)
        self.col = self.service.collector
        self.col.configure(my_nick=ME, download_media=False, auto_backfill=False,
                           chunk_pause_ms=0, heartbeat_ms=1500)
        self.col.now = lambda: NOW
        self.logs = []
        self.col.collector_log.connect(lambda p: self.logs.append(json.loads(p)))
        self.bridge = Bridge.__new__(Bridge)
        QObject.__init__(self.bridge)
        self.bridge._config = self.cfg
        self.bridge._memory = None
        self.bridge._engine = types.SimpleNamespace(load_stack=lambda _: None)
        self.bridge.attach_history(self.service)

    async def rows(self, include_hidden=False):
        where = '' if include_hidden else " WHERE deleted_at=''"
        return await self.service.db.fetchdicts('SELECT * FROM messages' + where + ' ORDER BY ord')

    async def append_dom(self, text, *, source='classless', direction='in', time='21:02'):
        # Mutate a real DOM. Do not supply parsed records to the Python code.
        name = NICK if direction == 'in' else ME
        await self.cdp.evaluate('''(() => {
          const p = %s;
          const root = document.querySelector('.messages-root');
          const node = root.children[p.direction === 'in' ? 0 : 1].cloneNode(true);
          node.className = 'message-container ' + (p.direction === 'out' ? 'my-message-background' : 'general-background');
          node.querySelector('.from').textContent = p.name;
          node.querySelector('.sent-time').textContent = p.time;
          let payload = node.querySelector('span.message');
          if (!payload) {
            payload = document.createElement('span');
            payload.className = 'message';
            node.querySelector('p.message').appendChild(payload);
          }
          payload.textContent = p.text;
          if (p.source === 'classless') payload.removeAttribute('class');
          if (p.source === 'direct') payload.replaceWith(document.createTextNode(p.text));
          root.appendChild(node);
          return true;
        })()''' % json.dumps(dict(text=text, source=source, direction=direction, name=name, time=time),
                            ensure_ascii=False))

    async def clear_through_bridge(self):
        done = asyncio.get_running_loop().create_future()
        def changed(payload):
            if json.loads(payload).get('action') == 'cleared' and not done.done():
                done.set_result(True)
        self.bridge.userdb_changed.connect(changed)
        try:
            self.assertTrue(self.bridge.history_clear_person(NICK))
            await asyncio.wait_for(done, 3)
        finally:
            self.bridge.userdb_changed.disconnect(changed)

    async def test_two_text_messages_clear_then_new_text_is_saved_old_stays_hidden(self):
        self.assertEqual(await self.col.tick(), CollectorState.COLLECTED)
        before = await self.rows()
        self.assertEqual([r['text'] for r in before], ['Старое сообщение', 'Старый ответ'])
        await self.clear_through_bridge()
        self.assertEqual(await self.rows(), [])
        self.assertEqual(await self.col.tick(), CollectorState.NO_NEW)
        await self.col.backfill_older()
        self.assertEqual(await self.rows(), [], 'Backfill is not permission to undo Clear')
        self.assertEqual(len(await self.rows(True)), 2)

        text = 'Новое сообщение\nНе терять строку 😊'
        await self.append_dom(text)
        self.assertEqual(await self.col.tick(), CollectorState.COLLECTED)
        saved = await self.rows()
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]['text'], text)
        self.assertEqual(saved[0]['from_nick'], NICK)
        self.assertEqual(saved[0]['my_nick'], ME)
        self.assertEqual(saved[0]['ts_display'], '21:02')
        self.assertEqual(saved[0]['direction'], 'in')
        all_rows = await self.rows(True)
        self.assertTrue(all_rows[0]['deleted_at'] and all_rows[1]['deleted_at'])
        self.assertEqual(self.col.state_payload()['capture_missing'], 0)
        self.assertEqual(self.col.state_payload()['last_probe']['pane_source'], 'single-pane')

    async def test_outgoing_direct_text_is_saved_after_clear(self):
        await self.col.tick()
        await self.clear_through_bridge()
        await self.append_dom('Новый исходящий ответ', direction='out', source='direct')
        await self.col.tick()
        rows = await self.rows()
        self.assertEqual([r['text'] for r in rows], ['Новый исходящий ответ'])
        self.assertEqual(rows[0]['from_nick'], ME)
        self.assertEqual(rows[0]['direction'], 'out')

    async def test_clear_undo_remains_a_single_command_and_keeps_new_messages(self):
        await self.col.tick()
        await self.clear_through_bridge()
        await self.append_dom('Новое после очистки')
        await self.col.tick()
        done = asyncio.get_running_loop().create_future()
        def changed(payload):
            if json.loads(payload).get('action') == 'undo' and not done.done():
                done.set_result(True)
        self.bridge.userdb_changed.connect(changed)
        try:
            self.assertEqual(json.loads(self.bridge.undo())['kind'], 'archive')
            await asyncio.wait_for(done, 3)
        finally:
            self.bridge.userdb_changed.disconnect(changed)
        self.assertEqual([r['text'] for r in await self.rows()],
                         ['Старое сообщение', 'Старый ответ', 'Новое после очистки'])

    async def test_real_observer_push_saves_new_classless_text_after_clear(self):
        await self.col.tick()
        await self.clear_through_bridge()
        self.cdp.forward_events = True
        appended = asyncio.get_running_loop().create_future()
        def notified(payload):
            if json.loads(payload).get('added') and not appended.done():
                appended.set_result(True)
        self.col.history_appended.connect(notified)
        try:
            await self.append_dom('Из MutationObserver')
            await asyncio.wait_for(appended, 3)
        finally:
            self.col.history_appended.disconnect(notified)
        self.assertEqual([r['text'] for r in await self.rows()], ['Из MutationObserver'])

    async def test_scoped_fallback_preserves_links_breaks_and_emoji_not_icons_or_controls(self):
        await self.cdp.evaluate('''(() => {
          document.querySelector('span.message').outerHTML =
            '<span>Первый ряд<br>ссылка <a href="https://example.test">текст</a> 😊</span>';
          return true;
        })()''')
        await self.col.tick()
        row = (await self.rows())[0]
        self.assertEqual(row['text'], 'Первый ряд\nссылка текст 😊')
        for metadata in ('gender-female', 'Delete', '21:00', NICK, 'read'):
            self.assertNotIn(metadata, row['text'])

    async def test_empty_primary_span_does_not_hide_a_ready_body_sibling(self):
        await self.cdp.evaluate('''(() => {
          const span = document.querySelector('span.message');
          span.textContent = '';
          span.after(document.createTextNode('Доступный текст рядом'));
        })()''')
        await self.col.tick()
        self.assertEqual((await self.rows())[0]['text'], 'Доступный текст рядом')

    async def test_metadata_only_messages_are_pending_not_saved_or_reported_as_no_new(self):
        await self.cdp.evaluate("document.querySelectorAll('span.message').forEach(s => s.remove())")
        state = await self.col.tick()
        self.assertEqual(state, CollectorState.CAPTURE_PENDING)
        self.assertEqual(await self.rows(), [])
        self.assertEqual(self.col.state_payload()['capture_missing'], 2)
        self.assertEqual(self.col.next_interval_ms(), 1500, 'deliberate waits must not make the interval 20 seconds')
        self.assertFalse(any('No new messages' in row['message'] for row in self.logs))
        self.assertNotIn(NICK, json.dumps(self.col.state_payload()['capture_diagnostics'], ensure_ascii=False))

    async def test_unreadable_first_range_does_not_starve_new_text_later(self):
        self.service.parser.chunk_size = 1
        await self.cdp.evaluate("document.querySelector('span.message').remove()")
        await self.append_dom('Видимое новое сообщение', source='payload')
        await self.col.tick()
        self.assertEqual([r['text'] for r in await self.rows()], ['Старый ответ', 'Видимое новое сообщение'])
        self.assertEqual(self.col.state, CollectorState.CAPTURE_PENDING)
        self.assertEqual(self.col.state_payload()['capture_missing'], 1)
        pid = await self.service.repo.ensure_person(NICK)
        self.assertFalse((await self.service.repo.get_cursor(pid))['tail_sig'])

    async def test_sender_avatar_is_not_a_missing_message_attachment(self):
        await self.cdp.evaluate('''(() => {
          for (const from of document.querySelectorAll('span.from')) {
            const img = document.createElement('img');
            img.setAttribute('src', '');
            img.alt = 'avatar';
            from.appendChild(img);
          }
        })()''')
        await self.col.tick()
        rows = await self.rows()
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(r['media_id'] is None for r in rows))
        self.assertTrue(all(r['kind'] == 'text' for r in rows))

    async def test_image_sibling_outside_paragraph_is_found_without_becoming_text(self):
        await self.cdp.evaluate('''(() => {
          const node = document.querySelector('.message-content');
          node.querySelector('span.message').remove();
          const wrapper = document.createElement('div');
          wrapper.className = 'image-wrapper';
          wrapper.innerHTML = '<img alt="chat image" src="https://example.test/image.gif">';
          node.appendChild(wrapper);
        })()''')
        await self.col.tick()
        row = (await self.rows())[0]
        self.assertEqual(row['text'], '')
        self.assertEqual(row['kind'], 'gif')
        self.assertIsNotNone(row['media_id'])

    async def test_broken_slice_is_force_reinstalled_and_real_text_is_saved(self):
        await self.service.parser.install()
        await self.cdp.evaluate("window.__cvbAgent.slice = function(){ throw new Error('stale slice'); }")
        await self.col.tick()
        self.assertEqual(len(await self.rows()), 2)
        diagnostic = self.col.state_payload()['capture_diagnostics'][-1]
        self.assertEqual(diagnostic['attempts'], 2)
        self.assertTrue(diagnostic['agent_refreshed'])
        self.assertEqual(self.col.state, CollectorState.COLLECTED)

    async def test_permanent_malformed_probe_response_is_an_error_not_an_empty_capture(self):
        # Alter the page's serialization at the failure boundary. The normal
        # response still comes from executing the actual shipped expression.
        await self.cdp.evaluate('''(() => {
          const original = JSON.stringify;
          JSON.stringify = function(value) {
            if (value && value.items) return original({ok:true, items:42});
            return original.apply(this, arguments);
          };
        })()''')
        await self.col.tick()
        state = self.col.state_payload()
        self.assertEqual(state['state'], CollectorState.ERROR)
        self.assertEqual(state['capture_errors'], 1)
        self.assertIn('record list', state['error'])
        self.assertEqual(state['capture_diagnostics'][-1]['attempts'], 4)
        self.assertEqual(await self.rows(), [])
        self.assertFalse(any('No new messages' in row['message'] for row in self.logs))

    async def test_failed_first_probe_does_not_block_later_new_messages_after_clear(self):
        await self.col.tick()
        await self.clear_through_bridge()
        self.service.parser.chunk_size = 1
        await self.append_dom('Сохранить несмотря на ошибку раньше')
        await self.cdp.evaluate("""(() => {
          const original = JSON.stringify;
          JSON.stringify = function(value) {
            if (value && value.items && value.from === 0) return original({ok:true, items:42});
            return original.apply(this, arguments);
          };
        })()""")
        await self.col.tick()
        self.assertEqual([r['text'] for r in await self.rows()], ['Сохранить несмотря на ошибку раньше'])
        self.assertEqual(self.col.state_payload()['capture_errors'], 1)
        self.assertEqual(self.col.state, CollectorState.ERROR)
        self.assertTrue((await self.rows(True))[0]['deleted_at'])

    async def test_javascript_exception_is_preserved_by_the_production_cdp_decoder(self):
        with self.assertRaisesRegex(CDPEvaluationError, 'runtime failure'):
            await self.cdp.evaluate("(() => { throw new Error('runtime failure'); })()")
        self.assertIsNone(await self.cdp.evaluate('undefined'))
        self.assertIsNone(await self.cdp.evaluate('null'))

    async def test_visible_text_is_saved_before_scroll_can_unload_it(self):
        self.col.configure(auto_backfill=True)
        await self.service.parser.install()
        await self.cdp.evaluate('''(() => {
          window.scrollVisits = 0;
          const scroll = window.__cvbAgent.scrollToTop;
          window.__cvbAgent.scrollToTop = function() {
            window.scrollVisits++;
            document.querySelectorAll('span.message').forEach(s => s.textContent = '');
            return scroll();
          };
        })()''')
        await self.col.tick()
        self.assertEqual(len(await self.rows()), 2, 'visible bodies must reach SQLite before scroll-to-top')
        self.assertEqual(await self.cdp.evaluate('window.scrollVisits'), 1)
        await self.col.tick()
        self.assertEqual(await self.cdp.evaluate('window.scrollVisits'), 1,
                         'an incomplete visible pass retries in place, without another destructive scroll')

    async def test_wrong_private_tab_cannot_supply_fallback_text(self):
        await self.cdp.evaluate("document.querySelector('.chat-title').textContent = 'Other person'")
        await self.col.tick()
        self.assertNotEqual(self.col.state, CollectorState.COLLECTED)
        self.assertEqual(await self.rows(), [])

    async def test_original_saved_private_markup_works_through_generated_probes(self):
        await self.cdp.send('Test.load', {'html': (ROOT / 'Вирт чат privat.html').read_text()})
        parser = self.service.parser
        await parser.install()
        state = await parser.state()
        records = await parser.slice(0, state['count'])
        self.assertEqual(len(records), 4)
        self.assertTrue(all(not r.incomplete for r in records))
        self.assertEqual(records[0].text, 'повезло ученикам))')
        self.assertEqual(state['agent'], AGENT_VERSION)


class TestCaptureReadContract(unittest.IsolatedAsyncioTestCase):
    async def test_protocol_error_is_not_an_undefined_value(self):
        client = CDPClient()
        client.send = AsyncMock(return_value={'error': {'code': -32000, 'message': 'Execution context gone'}})
        with self.assertRaisesRegex(CDPEvaluationError, 'Execution context gone'):
            await client.evaluate('1')

    async def test_failed_range_and_malformed_records_raise_explicit_errors(self):
        for response in (None, 'not JSON', {'ok': False, 'error': 'slice exploded'},
                         {'ok': True, 'items': 2}, {'ok': True, 'items': [{'unexpected': True}]}):
            parser = ChatParser(types.SimpleNamespace(evaluate=AsyncMock(return_value=response)))
            with self.subTest(response=response), self.assertRaises(CaptureReadError):
                await parser.slice(0, 2)
            self.assertTrue(parser.last_capture_diagnostic.get('error'))

    async def test_valid_empty_range_is_still_distinct_from_a_probe_error(self):
        parser = ChatParser(types.SimpleNamespace(evaluate=AsyncMock(return_value={'ok': True, 'items': []})))
        self.assertEqual(await parser.slice(0, 2), [])
        self.assertEqual(parser.last_capture_diagnostic['reason'], 'range_empty')

    async def test_probe_metrics_do_not_include_intentional_waits(self):
        parser = ChatParser(FakePage())
        parser.reset_probe_metrics()
        await parser.state()
        measured = parser.probe_seconds
        await asyncio.sleep(0.15)
        self.assertEqual(parser.probe_seconds, measured)
        self.assertLess(measured, 0.05)

    async def test_real_slow_evaluate_still_increases_probe_latency(self):
        async def slow(_):
            await asyncio.sleep(0.15)
            return {'ok': True, 'agent': AGENT_VERSION}
        parser = ChatParser(types.SimpleNamespace(evaluate=slow))
        await parser.state()
        self.assertGreaterEqual(parser.probe_seconds, 0.14)


if __name__ == '__main__':
    unittest.main(verbosity=2)
