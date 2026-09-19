import itertools

import pytest

from bridge import wire_db as db
from core.announcer import Announcer, INTENT_ONLY, confirmed
from core.events import EventBus, LogMessage

pytestmark = pytest.mark.pure


@pytest.mark.parametrize('ok,unchanged,offline', list(itertools.product([False, True], repeat=3)))
def test_switched(ok, unchanged, offline):
    assert db.world_switched(dict(ok=ok, unchanged=unchanged, offline=offline)) is (ok and not unchanged and not offline)


@pytest.mark.parametrize('op,rebuild', [('create', True), ('load', True), ('delete', True), ('clean', False), ('other', False)])
def test_db_policy(op, rebuild):
    assert db.rebuild_needed(op) is rebuild
    result = dict(op='actual', path='/world/Ž.db', before_path='before', backup='backup')
    entry = db.undo_entry(op, result)
    assert entry == (None if op == 'delete' else result)
    assert db.undo_entry(op, {}) == (None if op == 'delete' else dict(op=op, path='', before_path='', backup=''))
    assert db.success_text('{name}: {path}', result) == 'Ž.db: /world/Ž.db'
    assert db.success_text('{name}: {path}', {}) == ': '


@pytest.mark.parametrize('result,expected', [(None, False), (True, False), ([], False), ({}, False), ({'ok': False}, False), ({'ok': True}, True), ({'ok': 1}, True)])
def test_confirmation(result, expected):
    assert confirmed(result) is expected


@pytest.mark.parametrize('kind', ['stack', 'grid', 'people', 'archive', 'dbconn', 'future', 'labels'])
@pytest.mark.parametrize('result', [None, {'ok': False}, {'ok': True}])
def test_announcer(kind, result):
    bus, seen = EventBus(), []
    bus.subscribe(LogMessage, seen.append)
    announcer = Announcer(bus)
    expected = kind == 'labels' or confirmed(result)
    assert announcer.report(kind, result, 'landed') is expected
    assert [(e.message, e.level) for e in seen] == ([('landed', 'success')] if expected else [])


@pytest.mark.parametrize('forward,prefix', [(False, '↩ Undo'), (True, '↪ Redo')])
def test_intent(forward, prefix):
    assert INTENT_ONLY == ('labels',)
    bus, seen = EventBus(), []
    bus.subscribe(LogMessage, seen.append)
    a = Announcer(bus)
    for kind in ['archive', 'dbconn', 'people', 'future']:
        assert a.report_intent(kind, forward, 'restored') is False
    assert seen == []
    assert a.report_intent('labels', forward, 'labels restored') is True
    assert [(e.message, e.level) for e in seen] == [(prefix + ' — labels restored', 'info')]
