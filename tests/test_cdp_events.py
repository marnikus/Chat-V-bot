"""CDP foundation for the passive collector (milestone M0).

The collector cannot exist until the CDP client can do two new things:

  * deliver EVENTS. `_receive_loop()` used to drop every frame without an
    `id`, which is exactly where `Runtime.bindingCalled` lives — the push
    channel the in-page agent uses to hand us new messages;
  * share the socket fairly. The action engine and the collector both talk
    to one WebSocket, so the collector must be preemptible: a HIGH waiter
    (a run) always overtakes a LOW waiter (collection).

Run with:  python3 tests/test_cdp_events.py
"""

import asyncio
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.cdp_client import CDPClient, CdpLease  # noqa: E402


def run(coro):
    return asyncio.run(coro)


class FakeSocket:
    """Async-iterable stand-in for the websocket connection."""

    def __init__(self, frames):
        self._frames = list(frames)
        self.sent = []

    def __aiter__(self):
        async def gen():
            for f in self._frames:
                yield f
        return gen()

    async def send(self, payload):
        self.sent.append(payload)

    async def close(self):
        pass


class TestEventFanOut(unittest.TestCase):
    def test_listener_receives_event_params(self):
        cdp = CDPClient()
        seen = []
        cdp.on_event("Runtime.bindingCalled", lambda p: seen.append(p))
        cdp._dispatch_event({"method": "Runtime.bindingCalled",
                             "params": {"name": "__cvbPush", "payload": "[]"}})
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0]["name"], "__cvbPush")

    def test_other_methods_are_not_delivered(self):
        cdp = CDPClient()
        seen = []
        cdp.on_event("Runtime.bindingCalled", seen.append)
        cdp._dispatch_event({"method": "Page.loadEventFired", "params": {}})
        self.assertEqual(seen, [])

    def test_off_event_removes_one_listener_and_all(self):
        cdp = CDPClient()
        a, b = [], []
        cb_a, cb_b = a.append, b.append
        cdp.on_event("X", cb_a)
        cdp.on_event("X", cb_b)
        cdp.off_event("X", cb_a)
        cdp._dispatch_event({"method": "X", "params": {"n": 1}})
        self.assertEqual(len(a), 0)
        self.assertEqual(len(b), 1)
        cdp.off_event("X")
        cdp._dispatch_event({"method": "X", "params": {"n": 2}})
        self.assertEqual(len(b), 1)

    def test_a_throwing_listener_cannot_kill_the_fan_out(self):
        cdp = CDPClient()
        seen = []

        def boom(_):
            raise RuntimeError("listener exploded")

        cdp.on_event("X", boom)
        cdp.on_event("X", seen.append)
        cdp._dispatch_event({"method": "X", "params": {}})
        self.assertEqual(len(seen), 1)   # second listener still ran

    def test_async_listeners_are_scheduled(self):
        async def scenario():
            cdp = CDPClient()
            got = asyncio.get_event_loop().create_future()

            async def cb(params):
                got.set_result(params)

            cdp.on_event("X", cb)
            cdp._dispatch_event({"method": "X", "params": {"v": 7}})
            return await asyncio.wait_for(got, timeout=1)

        self.assertEqual(run(scenario())["v"], 7)

    def test_receive_loop_routes_replies_and_events(self):
        async def scenario():
            cdp = CDPClient()
            events = []
            cdp.on_event("Runtime.bindingCalled", events.append)
            fut = asyncio.get_event_loop().create_future()
            cdp._pending[1] = fut
            cdp._ws = FakeSocket([
                '{"method":"Runtime.bindingCalled","params":{"payload":"x"}}',
                '{"id":1,"result":{"result":{"value":42}}}',
            ])
            await cdp._receive_loop()
            return events, fut.result()

        events, reply = run(scenario())
        self.assertEqual(len(events), 1)
        self.assertEqual(reply["result"]["result"]["value"], 42)


class TestBindings(unittest.TestCase):
    def test_add_binding_and_script_send_the_right_commands(self):
        async def scenario():
            cdp = CDPClient()
            calls = []

            async def fake_send(method, params=None):
                calls.append((method, params or {}))
                return {"result": {"identifier": "s1"}}

            cdp.send = fake_send
            cdp._connected = True
            cdp._ws = FakeSocket([])
            ok = await cdp.add_binding("__cvbPush")
            ident = await cdp.add_script_on_new_document("window.x=1")
            return ok, ident, calls

        ok, ident, calls = run(scenario())
        self.assertTrue(ok)
        self.assertEqual(ident, "s1")
        methods = [c[0] for c in calls]
        self.assertIn("Runtime.addBinding", methods)
        self.assertIn("Page.addScriptToEvaluateOnNewDocument", methods)
        self.assertEqual(calls[0][1].get("name"), "__cvbPush")
        self.assertIn("window.x=1", calls[1][1].get("source", ""))

    def test_binding_failure_is_reported_not_raised(self):
        async def scenario():
            cdp = CDPClient()

            async def fake_send(method, params=None):
                raise RuntimeError("no such domain")

            cdp.send = fake_send
            return await cdp.add_binding("__cvbPush")

        self.assertFalse(run(scenario()))


class TestCdpLease(unittest.TestCase):
    def test_high_waiter_overtakes_a_queued_low_waiter(self):
        async def scenario():
            lease = CdpLease()
            order = []

            async def work(name, prio, hold=0.02):
                cm = lease.high() if prio == "high" else lease.low()
                async with cm:
                    order.append(name)
                    await asyncio.sleep(hold)

            # holder occupies the lease; low queues first, high queues second
            holder = asyncio.create_task(work("holder", "high", 0.05))
            await asyncio.sleep(0.005)
            low = asyncio.create_task(work("low", "low"))
            await asyncio.sleep(0.005)
            high = asyncio.create_task(work("high", "high"))
            await asyncio.gather(holder, low, high)
            return order

        self.assertEqual(run(scenario()), ["holder", "high", "low"])

    def test_lease_is_released_even_when_the_body_raises(self):
        async def scenario():
            lease = CdpLease()
            try:
                async with lease.low():
                    raise ValueError("boom")
            except ValueError:
                pass
            # a second acquisition must not hang
            await asyncio.wait_for(_acquire_once(lease), timeout=1)
            return True

        async def _acquire_once(lease):
            async with lease.high():
                return True

        self.assertTrue(run(scenario()))

    def test_low_priority_work_serialises(self):
        async def scenario():
            lease = CdpLease()
            live, peak = 0, 0

            async def work():
                nonlocal live, peak
                async with lease.low():
                    live += 1
                    peak = max(peak, live)
                    await asyncio.sleep(0.01)
                    live -= 1

            await asyncio.gather(*(work() for _ in range(4)))
            return peak

        self.assertEqual(run(scenario()), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
