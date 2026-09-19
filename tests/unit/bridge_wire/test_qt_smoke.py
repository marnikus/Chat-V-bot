"""Real Qt adapters and complete Router artifact, kept outside pure tests."""
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

pytestmark = [pytest.mark.needs_qt, pytest.mark.qt]


def test_schema_exact():
    from tools.wire_schema import render, schema
    path = Path(__file__).resolve().parents[3] / 'ui/js/wire-schema.json'
    assert path.read_text() == render()
    methods = schema()['methods']
    for name in ('copy_text', 'copy_media', 'open_media_folder', 'get_history_settings', 'save_history_settings', 'detect_my_nick'):
        assert name in methods
    assert methods['history_open']['params'] == ['QString', 'QString', 'QString']


def test_people_real_signals_and_manual_clock():
    from bridge.people_bridge import PeopleBridge
    from core.scheduler import ManualScheduler
    from core.events import EventBus, LogMessage
    from core.result import Ok
    clock, bus, events = ManualScheduler(), EventBus(), []
    bus.subscribe(LogMessage, events.append)
    class People:
        async def payload(self):
            return Ok({'users': ['Ž'], 'stats': {'count': 1}})
    ctx = SimpleNamespace(bus=bus, engine=None, memory=SimpleNamespace(is_open=False), people=People())
    bridge = PeopleBridge(ctx, scheduler=clock)
    seen = []
    bridge.users_updated.connect(lambda raw: seen.append(('users', json.loads(raw))))
    bridge.stats_updated.connect(lambda raw: seen.append(('stats', json.loads(raw))))
    asyncio.run(bridge._refresh_users_async())
    assert seen == [('users', ['Ž']), ('stats', {'count': 1})]
    assert clock.now() == pytest.approx(15)
    bridge.delete_users('{}')
    assert events[-1].message == '❌ Delete aborted: selection is not a list'


def test_stack_save_keeps_normalization_before_cap():
    from bridge.undo_bridge import UndoBridge
    from core.events import EventBus
    from services.undo_service import UndoService
    undo = SimpleNamespace(_clean_history=UndoService._clean_history, set_stack_projection=Mock())
    bridge = UndoBridge(SimpleNamespace(bus=EventBus(), undo=undo))
    raw = [None, [], 'invalid']
    bridge.save_stack_history(json.dumps(raw), 0)
    undo.set_stack_projection.assert_called_once_with([[]], 0)
