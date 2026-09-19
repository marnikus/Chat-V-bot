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


class TestIdentityEdges(unittest.TestCase):
    """Safety corners the first mutation run found under-specified."""

    def test_unknown_me_and_multiple_outbound_authors_refuses_all(self):
        state = {'tab': 'private', 'partner': PARTNER, 'in_authors': [PARTNER],
                 'out_authors': ['First', 'Second']}
        got = judge(state, my_nick='')
        self.assertEqual((got.ok, got.reason, got.me, got.partner, got.strangers),
                         (False, 'strangers', '', PARTNER, ['First', 'Second']))
        self.assertEqual(got.detail, 'other people write here: First, Second')

    def test_unknown_me_and_empty_pane_keeps_legacy_acceptance(self):
        got = judge({'tab': 'private', 'partner': PARTNER, 'authors': []}, my_nick='')
        self.assertEqual((got.ok, got.me, got.partner, got.strangers), (True, '', PARTNER, []))

    def test_flat_authors_without_me_use_target_fallback(self):
        state = {'tab': 'private', 'partner': PARTNER, 'authors': [PARTNER, STRANGER]}
        got = judge(state, my_nick='')
        self.assertEqual((got.reason, got.me, got.strangers), ('strangers', '', [STRANGER]))

    def test_flat_authors_report_only_configured_me_as_outbound(self):
        state = {'tab': 'private', 'partner': PARTNER, 'authors': [PARTNER, ME, STRANGER]}
        got = judge(state)
        self.assertEqual((got.reason, got.me, got.strangers), ('strangers', ME, [STRANGER]))

    def test_renamed_me_preserves_configured_reporting_and_accepts_current(self):
        state = {'tab': 'private', 'partner': PARTNER, 'me': 'Current',
                 'in_authors': [PARTNER], 'out_authors': ['Old', 'Current', PARTNER, STRANGER]}
        got = judge(state, my_nick='Old')
        self.assertEqual((got.reason, got.me, got.partner, got.strangers),
                         ('strangers', 'Old', PARTNER, [STRANGER]))

    def test_state_me_is_reported_when_configuration_missing(self):
        state = {'tab': 'private', 'partner': PARTNER, 'me': ME,
                 'in_authors': [PARTNER], 'out_authors': [ME, STRANGER]}
        got = judge(state, my_nick='')
        self.assertEqual((got.reason, got.me, got.strangers), ('strangers', ME, [STRANGER]))

    def test_stale_config_matching_partner_is_not_self_chat_after_rename(self):
        state = {'tab': 'private', 'partner': PARTNER, 'me': ME,
                 'in_authors': [PARTNER], 'out_authors': [ME]}
        got = judge(state, my_nick=PARTNER)
        self.assertEqual((got.reason, got.me), ('ok', PARTNER))

    def test_three_strangers_not_elided_and_display_identity_preserved(self):
        state = {'tab': 'private', 'partner': '  ански ', 'me': ME,
                 'in_authors': ['АНСКИ', 'A', 'B', 'C'], 'out_authors': [ME, 'A']}
        got = judge(state)
        self.assertEqual((got.reason, got.detail, got.partner, got.strangers),
                         ('strangers', 'other people write here: A, B, C', 'ански', ['A', 'B', 'C']))

    def test_default_typed_query_is_strict_and_has_no_item_override(self):
        state = decode_tab_state(cell('private', 'named', 'exact', 'stranger_in'))
        self.assertEqual(judge_private(state, PARTNER, ME).reason, 'strangers')
        self.assertEqual(judge_private(state.with_tab('room', PARTNER), PARTNER, ME).reason, 'not_private')

    def test_empty_nick_never_authorizes_despite_valid_state(self):
        self.assertEqual(judge(cell('private', 'named', 'exact', 'two_nicks'), nick='').reason, 'no_partner')
