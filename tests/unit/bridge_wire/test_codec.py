"""Execute the pure wire seams without QObject fakes."""
import json

import pytest

from bridge import wire_codec as wire
from bridge import wire_undo as undo
from core.result import Err, Ok
from services.layout_service import LayoutService

pytestmark = pytest.mark.pure


@pytest.mark.parametrize('raw,expected', [(None, {}), ('', {}), ('null', {'x': 1}),
    ('[]', {'x': 1}), ('bad', {'x': 1}), (42, {'x': 1}), ('{"q":"ž"}', {'q': 'ž'})])
def test_object(raw, expected):
    assert wire.object_arg(raw, {'x': 1}) == expected


def test_identity_and_default_copy():
    value = {'x': 1}
    assert wire.object_arg(value) is value
    assert wire.object_arg('bad', value) is not value
    assert wire.object_arg('bad') == {}


@pytest.mark.parametrize('raw,expected', [(None, ''), (' \tŽan\n K  ', 'Žan K'), (42, '42')])
def test_nick(raw, expected):
    assert wire.clean_nick(raw) == expected


@pytest.mark.parametrize('raw,expected', [(None, 0), ('', 0), ('  ', 0), (' 42 ', 42),
    ('bad', 0), ('1.5', 0), (-2, -2)])
def test_id(raw, expected):
    assert wire.message_id(raw) == expected


@pytest.mark.parametrize('raw,expected,error', [('', [], None),
    ('["Ž",2,null]', ['Ž', '2', 'None'], None),
    ('bad', None, '❌ Delete aborted: bad selection payload'),
    ('{}', None, '❌ Delete aborted: selection is not a list')])
def test_selection(raw, expected, error):
    assert wire.selection(raw) == (expected, error)


def test_request_and_people():
    req = wire.person_request({})
    assert (req.q, req.limit, req.offset, req.sort, req.dir, req.include_deleted) == ('', 50, 0, 'recent', '', False)
    req = wire.person_request(dict(q='Ž', limit='3', offset='2', sort='nick', dir='asc', include_deleted=1))
    assert (req.q, req.limit, req.offset, req.sort, req.dir, req.include_deleted) == ('Ž', 3, 2, 'nick', 'asc', True)
    assert wire.people_payload(Err('offline')) is None
    assert wire.people_payload(Ok({'users': ['Ž'], 'stats': {'a': 2}})) == ('["Ž"]', '{"a": 2}')


@pytest.mark.parametrize('kind,raw,expected', [('stack', '', (True, [])),
    ('stack', '[1]', (True, [1])), ('stack', '{}', (False, {})),
    ('stack', 'bad', (False, None)), ('people', '[]', (False, None))])
def test_global(kind, raw, expected):
    assert undo.global_payload(kind, raw) == expected


def test_grid():
    raw = json.dumps({'v': LayoutService.GRID_VERSION, 'tree': LayoutService.default_grid_tree()})
    accepted, value = undo.global_payload('grid', raw)
    assert accepted and value
    assert undo.global_payload('grid', '')[0] is False
    entry = json.dumps({'kind': 'grid', 'value': value})
    assert undo.kind_value(entry, 'grid') == LayoutService.legacy_grid_payload(value)
    assert undo.kind_value('{"kind":"grid"}', 'grid') == 'null'


@pytest.mark.parametrize('raw,expected', [('null', 'null'), ('[]', 'null'), ('bad', 'null'),
    (None, 'null'), ('{"kind":"grid","value":[]}', 'null'),
    ('{"kind":"stack"}', 'null'), ('{"kind":"stack","value":["Ž"]}', '["Ž"]')])
def test_projection(raw, expected):
    assert undo.kind_value(raw, 'stack') == expected


@pytest.mark.parametrize('raw,expected', [('', []), ('[1]', [1]), ('bad', None), ('{}', None)])
def test_list(raw, expected):
    assert undo.list_arg(raw) == expected


@pytest.mark.parametrize('history,index,cap,expected', [([], 'bad', 3, ([], -1)),
    ([1, 2], 1, 2, ([1, 2], 1)), ([1, 2], -1, 2, ([1, 2], -1)), ([1, 2, 3], 2, 2, ([2, 3], 1)),
    ([1, 2, 3], -1, 2, ([2, 3], 0)), ([1, 2, 3], 'bad', 2, ([2, 3], 0))])
def test_trim(history, index, cap, expected):
    original = list(history)
    assert undo.trim_history(history, index, cap) == expected
    assert history == original
