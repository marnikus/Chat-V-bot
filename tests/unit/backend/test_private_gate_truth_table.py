"""Area A supplied 768-cell oracle and named refusal approvals (RULE 15)."""
import itertools
import pickle
import unittest

from backend.parser_requests import PrivateQuery
from backend.private_gate import judge_private, title_matches
from backend.probe_results import decode_tab_state

PARTNER, ME, STRANGER = 'Ански', 'Хорошо Все', 'Макс__Б'
TABS = {'private': {'tab': 'private'}, 'room': {'tab': 'room'},
        'none': {'tab': 'none'}, 'missing': {}}
PARTNERS = {'named': {'partner': PARTNER}, 'blank': {'partner': ''}}
TITLES = {'exact': {'title': PARTNER}, 'contains': {'title': f'{PARTNER} (2)'},
          'other': {'title': 'Гостиная'}, 'empty': {'title': ''}}
AUTHORS = {
    'two_nicks': {'in_authors': [PARTNER], 'out_authors': [ME]},
    'stranger_in': {'in_authors': [PARTNER, STRANGER], 'out_authors': [ME]},
    'stranger_out': {'in_authors': [PARTNER], 'out_authors': [ME, STRANGER]},
    'flat_only': {'authors': [PARTNER, ME]}, 'no_data': {},
    'garbage': {'in_authors': 'not-a-list', 'out_authors': 7},
}
MY_NICK = {'configured': ME, 'unset': ''}
STRICT = {'strict': True, 'lenient': False}


def cell(tab, partner, title, authors):
    return {'me': ME, **TABS[tab], **PARTNERS[partner], **TITLES[title], **AUTHORS[authors]}


def every_cell():
    return itertools.product(TABS, PARTNERS, TITLES, AUTHORS, MY_NICK, STRICT)


def oracle(tab, partner, title, authors, strict):
    if strict and tab != 'private':
        return 'not_private'
    if partner == 'blank':
        return 'no_partner'
    if title == 'other':
        return 'title_mismatch'
    if authors in ('no_data', 'garbage'):
        return 'no_author_data'
    return 'ok' if authors in ('two_nicks', 'flat_only') else 'strangers'


def judge(state, my_nick=ME, strict=True, nick=PARTNER):
    return judge_private(decode_tab_state(state), nick, my_nick,
                         PrivateQuery(require_private=strict))


class TestExhaustiveTable(unittest.TestCase):
    def test_every_cell_matches_the_contract(self):
        oks = 0
        for tab, partner, title, authors, my, strict in every_cell():
            want = oracle(tab, partner, title, authors, STRICT[strict])
            got = judge(cell(tab, partner, title, authors), MY_NICK[my], STRICT[strict])
            with self.subTest(tab=tab, partner=partner, title=title, authors=authors, my=my, strict=strict):
                self.assertEqual((got.reason, got.ok, bool(got)), (want, want == 'ok', want == 'ok'))
            oks += got.ok
        self.assertEqual(oks, 60)
        self.assertEqual(len(list(every_cell())), 768)

    def test_legacy_door_equals_typed_core(self):
        from backend.chat_parser import verify_private
        for tab, partner, title, authors, my, strict in every_cell():
            state = cell(tab, partner, title, authors)
            query = PrivateQuery(require_private=STRICT[strict])
            with self.subTest(cell=(tab, partner, title, authors, my, strict)):
                self.assertEqual(verify_private(state, PARTNER, MY_NICK[my], query),
                                 judge_private(decode_tab_state(state), PARTNER, MY_NICK[my], query))

    def test_non_dict_legacy_state_is_not_decoded_as_json(self):
        from backend.chat_parser import verify_private
        for raw in (None, '', 'not json', 42, [], '[1,2]', {'tab': None},
                    '{"tab":"private","partner":"Ански","authors":[]}'):
            with self.subTest(raw=raw):
                self.assertEqual(verify_private(raw, PARTNER, ME).reason, 'not_private')


class TestPinnedCells(unittest.TestCase):
    def check(self, state, reason, detail, my_nick=ME, nick=PARTNER, strict=True):
        got = judge(state, my_nick, strict, nick)
        self.assertEqual((got.reason, got.detail), (reason, detail))
        return got

    def test_happy_path(self):
        got = self.check(cell('private', 'named', 'exact', 'two_nicks'), 'ok', '')
        self.assertEqual((got.me, got.partner, got.strangers), (ME, PARTNER, []))

    def test_room(self):
        self.check(cell('room', 'named', 'exact', 'two_nicks'), 'not_private',
                   'the active tab is not a private chat')

    def test_lenient_room_still_needs_title(self):
        self.check(cell('room', 'named', 'other', 'two_nicks'), 'title_mismatch',
                   'the active tab is “Гостиная”, not “Ански”', strict=False)

    def test_no_partner(self):
        self.check(cell('private', 'blank', 'exact', 'two_nicks'), 'no_partner',
                   'the active tab does not name a person')

    def test_self_chat(self):
        state = cell('private', 'named', 'exact', 'two_nicks')
        state.update(partner=ME, title=ME, me=ME)
        self.check(state, 'self_chat', 'the partner is my own nick', nick=ME)

    def test_missing_authors(self):
        self.check(cell('private', 'named', 'exact', 'no_data'), 'no_author_data',
                   'this page cannot tell me who wrote what')

    def test_strangers(self):
        got = self.check(cell('private', 'named', 'exact', 'stranger_in'), 'strangers',
                         'other people write here: Макс__Б')
        self.assertEqual(got.strangers, [STRANGER])

    def test_stranger_elision(self):
        state = cell('private', 'named', 'exact', 'two_nicks')
        state['in_authors'] = [PARTNER, 'A', 'B', 'C', 'D']
        self.check(state, 'strangers', 'other people write here: A, B, C…')

    def test_inferred_outbound_me(self):
        state = cell('private', 'named', 'exact', 'two_nicks')
        state['me'] = ''
        self.assertEqual(self.check(state, 'ok', '', my_nick='').me, ME)

    def test_push_items_override_state_authors(self):
        state = decode_tab_state(cell('private', 'named', 'exact', 'two_nicks'))
        got = judge_private(state, PARTNER, ME, PrivateQuery(items=[{'dir': 'in', 'from': STRANGER}]))
        self.assertEqual((got.reason, got.strangers), ('strangers', [STRANGER]))

    def test_title_normalization_and_empty(self):
        self.assertTrue(title_matches('  ански ', PARTNER))
        self.assertTrue(title_matches('Ански (печатает)', PARTNER))
        self.assertFalse(title_matches('', PARTNER))
        self.assertFalse(title_matches(PARTNER, ''))

    def test_malformed_unused_author_key_still_refuses(self):
        state = cell('private', 'named', 'exact', 'two_nicks')
        state['authors'] = 'not a list'
        self.assertEqual(judge(state).reason, 'no_author_data')

    def test_malformed_numeric_metadata_does_not_crash_gate(self):
        state = cell('private', 'named', 'exact', 'two_nicks')
        state.update(count=float('inf'), pending=float('nan'), agent='bad')
        self.assertTrue(judge(state).ok)

    def test_public_result_identity_and_pickle_home(self):
        from backend.chat_parser import PrivateCheck
        from backend.private_gate import PrivateCheck as CoreCheck
        self.assertIs(PrivateCheck, CoreCheck)
        result = judge(cell('private', 'named', 'exact', 'two_nicks'))
        self.assertEqual(result.__class__.__module__, 'backend.chat_parser')
        self.assertEqual(pickle.loads(pickle.dumps(result)), result)
