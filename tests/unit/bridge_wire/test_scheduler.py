import asyncio
import inspect
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from core.scheduler import ManualScheduler, POLL_STEP_S, WAIT_S
from services.world_events import AsyncioScheduler, WorldGate, run_when_world_open, wait_for_world_open

pytestmark = pytest.mark.pure


def test_clock():
    async def scenario():
        clock = ManualScheduler(4)
        await clock.sleep(-1)
        assert clock.now() == 4 and clock.sleeps == [0]
        assert await clock.until(lambda: clock.now() >= 5, 2, .25)
        assert clock.now() == 5 and clock.sleeps == [0, .25, .25, .25, .25]
        assert not await clock.until(lambda: False, 0)
        assert not await clock.until(lambda: False, -1)
        assert await clock.until(lambda: True, 0)
        assert clock.now() == 5
    asyncio.run(asyncio.wait_for(scenario(), timeout=.5))


@pytest.mark.parametrize('step', [0, -1, float('nan')])
def test_invalid_poll_step(step):
    with pytest.raises(ValueError, match='positive'):
        asyncio.run(asyncio.wait_for(ManualScheduler().until(lambda: False, 1, step), .5))


def test_gate_wait():
    async def scenario():
        clock = ManualScheduler()
        gate = WorldGate(clock)
        assert not await gate.wait(None)
        assert not await gate.wait(object())
        assert await gate.wait(SimpleNamespace(is_open=True))
        assert clock.sleeps == []
        assert not await gate.wait(SimpleNamespace(is_open=False))
        assert clock.now() == pytest.approx(WAIT_S)
        assert all(s == POLL_STEP_S for s in clock.sleeps)
        assert not await gate.wait(SimpleNamespace(is_open=False), .5, .25)
        assert clock.now() == pytest.approx(WAIT_S + .5)
        assert clock.sleeps[-2:] == [.25, .25]
        class Opening:
            @property
            def is_open(self):
                return clock.now() >= WAIT_S + 1
        assert await gate.wait(Opening(), 1, .25)
        assert clock.now() == pytest.approx(WAIT_S + 1)
    asyncio.run(asyncio.wait_for(scenario(), timeout=.5))


def test_run_timeout_errors_and_cancellation(caplog):
    async def scenario():
        clock = ManualScheduler()
        gate = WorldGate(clock)
        seen = []
        async def work():
            seen.append('ran')
            raise RuntimeError('closed')
        await gate.run('page', work(), SimpleNamespace(is_open=False), lambda scope, msg: seen.append((scope, msg)))
        assert seen == ['ran', ('page', 'closed')]
        assert clock.now() == pytest.approx(WAIT_S)
        await gate.run('page', work(), None)
        async def cancel():
            raise asyncio.CancelledError()
        with pytest.raises(asyncio.CancelledError):
            await gate.run('cancel', cancel(), None)
        pending = work()
        task = asyncio.create_task(gate.run('waiting', pending, SimpleNamespace(is_open=False)))
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert inspect.getcoroutinestate(pending) == inspect.CORO_CLOSED
    asyncio.run(asyncio.wait_for(scenario(), timeout=.5))
    assert 'archive page failed: closed' in caplog.text


def test_success_and_wait_failure():
    async def scenario():
        seen = []
        async def work():
            seen.append('ran')
        await WorldGate(ManualScheduler()).run('ok', work(), None)
        assert seen == ['ran']
        class Broken:
            @property
            def is_open(self):
                raise RuntimeError('broken flag')
        pending = work()
        await WorldGate().run('bad', pending, Broken(), lambda scope, msg: seen.append((scope, msg)))
        assert seen == ['ran', ('bad', 'broken flag')]
        assert inspect.getcoroutinestate(pending) == inspect.CORO_CLOSED
    asyncio.run(asyncio.wait_for(scenario(), timeout=.5))


def test_production_and_facades():
    async def scenario():
        scheduler = AsyncioScheduler()
        with patch('services.world_events.time.monotonic', return_value=8):
            assert scheduler.now() == 8
        await scheduler.sleep(0)
        assert await scheduler.until(lambda: True, 0)
        with patch('services.world_events.WAIT_S', 0):
            assert not await wait_for_world_open(SimpleNamespace(is_open=False))
            seen = []
            async def work():
                seen.append(1)
            await run_when_world_open('ok', work(), None)
            assert seen == [1]
    asyncio.run(asyncio.wait_for(scenario(), timeout=.5))


def test_world_broadcast_preserved(caplog):
    import json
    from core.events import EventBus, LabelsChanged, PeopleChanged, UserDbChanged
    from services.world_events import announce_world_live
    bus, seen = EventBus(), []
    for event in (LabelsChanged, PeopleChanged, UserDbChanged):
        bus.subscribe(event, seen.append)
    announce_world_live(bus)
    assert [(type(e).__name__) for e in seen] == ['PeopleChanged', 'UserDbChanged']
    assert seen[0].reason == 'db_switch'
    assert json.loads(seen[1].payload) == {'action': 'db_switch', 'ok': True}
    seen.clear()
    labels = SimpleNamespace(state=lambda: {'labels': ['Ž']})
    announce_world_live(bus, labels, 'startup')
    assert seen[0].reason == 'startup'
    assert json.loads(seen[1].payload) == {'action': 'startup', 'ok': True}
    assert json.loads(seen[2].payload) == {'labels': ['Ž']}
    assert 'Ž' in seen[2].payload
    seen.clear()
    announce_world_live(bus, object())
    assert len(seen) == 2
    assert 'label state not announced' in caplog.text


def test_legacy_facades_forward_every_argument():
    from unittest.mock import AsyncMock
    async def scenario():
        store, coro, error = object(), object(), object()
        with patch('services.world_events.WorldGate') as factory:
            gate = factory.return_value
            gate.wait = AsyncMock(return_value=False)
            gate.run = AsyncMock()
            assert not await wait_for_world_open(store, 2.5, .3)
            gate.wait.assert_awaited_once_with(store, 2.5, .3)
            await run_when_world_open('request', coro, store, error)
            gate.run.assert_awaited_once_with('request', coro, store, error)
    asyncio.run(scenario())


def test_falsey_scheduler_is_not_replaced():
    class Clock(ManualScheduler):
        def __bool__(self):
            return False
    clock = Clock()
    assert WorldGate(clock).scheduler is clock
