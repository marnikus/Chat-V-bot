"""Registry, standalone mirror, explicit doc table and legacy-site ratchet."""
import json
from pathlib import Path
import re
import unittest

from backend import selectors

ROOT = Path(__file__).resolve().parents[3]
AGENT = ROOT / 'backend/js/chat_agent.js'
DOC = ROOT / 'docs/current/DOM_SELECTORS.md'
GRANDFATHERED = {
    'backend/criteria_engine.py', 'backend/media_handler.py',
    'backend/message_injector_field.py', 'backend/message_injector_send.py',
    'backend/scroll_parser_model.py',
}
_TOKENS = ('user-item', 'tab-item', 'chat-title', 'chat-type-icon', 'messages-root',
           'message-container', 'sent-time', 'users-counter', 'app-messages',
           'avatar-wrapper', 'primary-text', 'app-chat-image', 'textarea[',
           'button[type', 'input[type=', 'search-field', 'mat-icon')
_TOKEN_RE = '|'.join(re.escape(t) for t in _TOKENS)
_LITERAL = re.compile(r'"([^"\n]*(?:%s)[^"\n]*)"|\'([^\'\n]*(?:%s)[^\'\n]*)\'' % (_TOKEN_RE, _TOKEN_RE))


def python_selector_sites():
    return {p.relative_to(ROOT).as_posix() for p in (ROOT/'backend').rglob('*.py')
            if p.name != 'selectors.py' and _LITERAL.search(p.read_text())}


class TestRegistry(unittest.TestCase):
    def test_read_only_and_lookup(self):
        with self.assertRaises(TypeError):
            selectors.SELECTORS['active_tab'] = '.hacked'
        self.assertEqual(selectors.selector('active_tab'), '.tab-item.active')
        with self.assertRaises(KeyError):
            selectors.selector('unknown')

    def test_json_literals(self):
        self.assertEqual(selectors.js_literal('tab_title'), '"p.chat-title"')
        self.assertEqual(json.loads(selectors.js_literal('message_image')), 'app-chat-image img')
        self.assertEqual({k: json.loads(v) for k,v in selectors.js_literals().items()}, dict(selectors.SELECTORS))

    def test_mirror_parsing(self):
        block = selectors.mirror_block()
        self.assertTrue(block.startswith(selectors.JS_BEGIN))
        self.assertTrue(block.endswith(selectors.JS_END))
        self.assertEqual(selectors.parse_mirror('x\n' + block + '\ny'), dict(selectors.SELECTORS))
        self.assertIsNone(selectors.parse_mirror('no markers'))
        self.assertIsNone(selectors.parse_mirror(
            f'{selectors.JS_BEGIN} var SEL = {{oops}}; {selectors.JS_END}'))

    def test_agent_mirror_parity_including_format(self):
        source = AGENT.read_text()
        self.assertEqual(selectors.parse_mirror(source), dict(selectors.SELECTORS))
        self.assertIn(selectors.mirror_block(), source)
        self.assertEqual(source.count(selectors.JS_BEGIN), 1)
        self.assertEqual(source.count(selectors.JS_END), 1)

    def test_agent_query_literals_and_unknown_names(self):
        source = AGENT.read_text()
        self.assertEqual(re.findall(r'qsa?\([A-Za-z0-9_.\[\]]+,\s*([\'"])(.+?)\1', source), [])
        used = set(re.findall(r'\bSEL\.([a-z_]+)', source))
        self.assertTrue(used)
        self.assertLessEqual(used, set(selectors.SELECTORS))

    def test_all_entries_used(self):
        used = set(re.findall(r'\bSEL\.([a-z_]+)', AGENT.read_text()))
        used |= set(re.findall(r'%\(([a-z_]+)\)s', (ROOT/'backend/scroll_parser_dom.py').read_text()))
        self.assertEqual(set(selectors.SELECTORS)-used, set())

    def test_exact_documented_table(self):
        documented = dict(re.findall(r'^\| `([a-z_]+)` \| `([^`]+)` \|$', DOC.read_text(), re.M))
        self.assertEqual(documented, dict(selectors.SELECTORS))
        self.assertIn('backend/selectors.py', DOC.read_text())

    def test_scroll_probe_consumes_registry(self):
        source = (ROOT/'backend/scroll_parser_dom.py').read_text()
        self.assertIn('js_literals()', source)
        for key in ('user_item', 'avatar_wrapper', 'user_badge', 'user_nick'):
            self.assertIn(f'%({key})s', source)
        self.assertNotIn("'user-item'", source)

    def test_no_new_python_selector_sites(self):
        self.assertEqual(python_selector_sites()-GRANDFATHERED, set())

    def test_remove_migrated_sites_from_ratchet(self):
        self.assertEqual(GRANDFATHERED-python_selector_sites(), set())
