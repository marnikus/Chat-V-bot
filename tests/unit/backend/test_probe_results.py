"""Field-by-field contracts for supplied Area A typed values and bad inputs."""
from dataclasses import FrozenInstanceError
import json
import unittest

from backend.probe_results import (PaneAuthors, ScrollPos, TabState,
                                  decode_pane_authors, decode_scroll_pos, decode_tab_state)

AGENT_ANSWER = {
    'ok': True, 'agent': 11, 'tab': 'private', 'partner': 'На работе 25',
    'title': 'На работе 25', 'me': 'HiHoney', 'participants': 2, 'count': 6,
    'authors': ['На работе 25', 'HiHoney'], 'in_authors': ['На работе 25'],
    'out_authors': ['HiHoney'], 'panes': 1, 'pane_source': 'first', 'pane_same': False,
    'head': ['05b1422fb6979400', '1d0fbc53d5b02e51'], 'tail': ['1d0fbc53d5b02e51'],
    'head_any': [], 'tail_any': [], 'pending': 0, 'dropped': 0,
    'scroll': {'top': 0, 'height': 0, 'client': 0, 'atTop': True, 'atBottom': True},
}


class TestDecodeTabState(unittest.TestCase):
    def test_agent_shaped_answer_field_by_field(self):
        self.assertEqual(decode_tab_state(AGENT_ANSWER), TabState(
            ok=True, agent=11, tab='private', partner='На работе 25',
            title='На работе 25', me='HiHoney', participants=2, count=6,
            head=('05b1422fb6979400', '1d0fbc53d5b02e51'), tail=('1d0fbc53d5b02e51',),
            authors=PaneAuthors(('На работе 25',), ('HiHoney',),
                                ('На работе 25', 'HiHoney'), True),
            scroll=ScrollPos(True, 0)))

    def test_json_and_dict_identical(self):
        self.assertEqual(decode_tab_state(json.dumps(AGENT_ANSWER)), decode_tab_state(AGENT_ANSWER))

    def test_garbage_is_absent(self):
        for raw in (None, '', 'not json', '[1]', 3, [], {}, object()):
            with self.subTest(raw=raw):
                self.assertEqual(decode_tab_state(raw), TabState.absent())
        self.assertEqual(TabState.absent('missing').reason, 'missing')
        self.assertFalse(TabState.absent().ok)
        self.assertFalse(TabState.absent().authors.reported)

    def test_missing_fields(self):
        state = decode_tab_state({'ok': True})
        self.assertEqual((state.tab, state.partner, state.title, state.me), ('none', '', '', ''))
        self.assertEqual((state.count, state.head, state.tail), (0, (), ()))
        self.assertFalse(state.authors.reported)
        self.assertTrue(decode_tab_state({'tab': 'private'}).ok)

    def test_reason_and_false_ok(self):
        state = decode_tab_state({'ok': False, 'reason': 'agent missing'})
        self.assertEqual((state.ok, state.agent, state.reason), (False, 0, 'agent missing'))

    def test_numbers(self):
        state = decode_tab_state({'count': '12', 'agent': -3, 'participants': 'many', 'pending': None})
        self.assertEqual((state.count, state.agent, state.participants, state.pending), (12, 0, 0, 0))
        for bad in (float('inf'), float('-inf'), float('nan'), [], {}):
            with self.subTest(bad=bad):
                self.assertEqual(decode_tab_state({'count': bad}).count, 0)

    def test_preserve_raw_strings(self):
        state = decode_tab_state({'partner': '  Ански  ', 'title': None, 'me': 7, 'tab': ' private '})
        self.assertEqual((state.partner, state.title, state.me, state.tab), ('  Ански  ', '', '7', ' private '))

    def test_fingerprint_order_and_invalid_shapes(self):
        state = decode_tab_state({'head': [1, 'x', 'x'], 'tail': 'not-a-list'})
        self.assertEqual((state.head, state.tail), (('1', 'x', 'x'), ()))

    def test_with_tab_does_not_mutate(self):
        original = decode_tab_state(AGENT_ANSWER)
        sibling = original.with_tab('room', 'Гостиная')
        self.assertEqual((sibling.tab, sibling.partner, sibling.title), ('room', 'Гостиная', 'Гостиная'))
        self.assertEqual(sibling.authors, original.authors)
        self.assertEqual(original.tab, 'private')
        self.assertEqual(original.with_tab('none').partner, '')
        with self.assertRaises(FrozenInstanceError):
            original.tab = 'room'


class TestAuthors(unittest.TestCase):
    def test_absent(self):
        self.assertEqual(decode_pane_authors({'tab': 'private'}), PaneAuthors())

    def test_split_and_deduplication(self):
        authors = decode_pane_authors({'in_authors': ['A', ' A ', 'B'], 'out_authors': ['Me']})
        self.assertEqual((authors.inbound, authors.outbound, authors.split, authors.reported),
                         (('A', 'B'), ('Me',), True, True))

    def test_flat_only(self):
        authors = decode_pane_authors({'authors': ['A', 'Me']})
        self.assertEqual((authors.everyone, authors.split, authors.reported), (('A', 'Me'), False, True))

    def test_null_lists(self):
        authors = decode_pane_authors({'in_authors': None, 'out_authors': None})
        self.assertEqual((authors.reported, authors.split), (True, False))

    def test_unreadable_present_lists(self):
        for bad in ({'in_authors': 'A,B'}, {'out_authors': 7}, {'authors': {'A': 1}},
                    {'in_authors': ['A'], 'out_authors': 'Me'}):
            with self.subTest(bad=bad):
                self.assertFalse(decode_pane_authors(bad).reported)

    def test_blank_and_numeric_names(self):
        self.assertEqual(decode_pane_authors({'in_authors': ['', None, 0, 'A', 5]}).inbound, ('A', '5'))


class TestScroll(unittest.TestCase):
    def test_geometry(self):
        self.assertEqual(decode_scroll_pos({'atTop': 1, 'top': '40'}), ScrollPos(True, 40))
        self.assertEqual(decode_scroll_pos({'atTop': False, 'top': -1}), ScrollPos())

    def test_non_objects(self):
        for raw in (None, 'top', [], 0):
            with self.subTest(raw=raw):
                self.assertEqual(decode_scroll_pos(raw), ScrollPos())


class TestNonDefaultState(unittest.TestCase):
    def test_pending_and_scroll_survive_the_outer_decoder(self):
        state = decode_tab_state({'ok': True, 'pending': '7',
                                  'scroll': {'top': '42', 'atTop': True}})
        self.assertEqual((state.pending, state.scroll), (7, ScrollPos(True, 42)))

    def test_falsey_tab_defaults_to_none_but_unknown_tab_is_not_rewritten(self):
        for tab in (None, '', 0, False):
            with self.subTest(tab=tab):
                self.assertEqual(decode_tab_state({'tab': tab}).tab, 'none')
        self.assertEqual(decode_tab_state({'tab': 'unknown'}).tab, 'unknown')
