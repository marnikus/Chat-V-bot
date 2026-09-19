"""Supplied Area A wire replay contracts, including the current hangup quirk."""
import asyncio
from pathlib import Path
import re
import sys
import unittest

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT), str(Path(__file__).parent)]
from backend import cdp_client_transport as transport
from backend.cdp_transport import (CdpConnection, CdpConnector, TabDiscovery,
                                  WebSocketConnector, HttpTabDiscovery, default_wire)
from fake_cdp_wire import FakeConnection, FakeConnector, FakeTabDiscovery, fake_wire


class _Signal:
    def __init__(self):
        self.fired = []

    def emit(self, *args):
        self.fired.append(args)


class StubClient:
    def __init__(self, wire):
        self.wire = wire
        self._ws = None
        self._cmd_id = 0
        self._pending = {}
        self._receive_task = None
        self._connected = False
        self.connected, self.disconnected, self.error = _Signal(), _Signal(), _Signal()
        self.events = []

    @property
    def base_url(self):
        return "http://127.0.0.1:9222"

    async def send(self, method, params=None):
        return await transport.raw_send(self, method, params)

    def _dispatch_event(self, frame):
        self.events.append(frame)


ENABLES = ["Page.enable", "DOM.enable", "Runtime.enable", "Network.enable"]


def value_reply(value):
    return lambda _req: {"result": {"result": {"value": value}}}


class TestWireReplay(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.conn = FakeConnection(value_reply(42))
        self.client = StubClient(fake_wire(self.conn))

    async def asyncTearDown(self):
        await transport.close_client(self.client)
        await asyncio.sleep(0)

    async def test_connect_sequence(self):
        self.assertTrue(await transport.open_client(self.client, "ws://one"))
        self.assertEqual(self.conn.methods, ENABLES)
        self.assertEqual(self.client.wire.connector.opened, ["ws://one"])
        self.assertEqual(self.client.connected.fired, [()])
        self.assertEqual(self.client.error.fired, [])

    async def test_evaluate_value_and_frame(self):
        await transport.open_client(self.client, "ws://one")
        self.assertEqual(await transport.evaluate(self.client, "40 + 2"), 42)
        self.assertEqual(self.conn.sent[-1], {
            "id": 5, "method": "Runtime.evaluate", "params": {
                "expression": "40 + 2", "returnByValue": True, "awaitPromise": True}})
        self.assertEqual(self.client._pending, {})

    async def test_refused_connect(self):
        self.client.wire = fake_wire(refuse=1)
        self.assertFalse(await transport.open_client(self.client, "ws://one"))
        self.assertEqual(self.client.error.fired, [("refused",)])
        self.assertEqual(self.client.connected.fired, [])
        self.assertFalse(self.client._connected)
        self.assertIsNone(self.client._ws)

    async def test_reconnect_closes_old_before_opening_new(self):
        await transport.open_client(self.client, "ws://one")
        first = self.conn
        second = FakeConnection()
        checks = []

        class Connector:
            async def open(inner, url):
                checks.append((first.closed, url))
                return second
        from backend.cdp_transport import CdpWire
        self.client.wire = CdpWire(Connector(), FakeTabDiscovery())
        await transport.open_client(self.client, "ws://two")
        self.assertEqual(checks, [(True, "ws://two")])
        self.assertEqual(second.methods, ENABLES)

    async def test_peer_hangup_leaves_pending_until_close(self):
        self.client.wire = fake_wire(FakeConnection(
            lambda req: None if req["id"] > 4 else {"result": {}}))
        await transport.open_client(self.client, "ws://one")
        request = asyncio.create_task(self.client.send("Runtime.evaluate"))
        # EOF completion is deterministic; no 30-second timeout sleep.
        await asyncio.wait_for(self.client._receive_task, 1)
        self.assertFalse(self.client._connected)
        self.assertFalse(request.done())
        self.assertEqual(len(self.client._pending), 1)
        request.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await request
        await transport.close_client(self.client)
        self.assertEqual(self.client._pending, {})

    async def test_malformed_frame_stops_with_disconnected(self):
        conn = FakeConnection(lambda _: "{not json")
        self.client._ws = conn
        self.client._connected = True
        await conn.send('{"id": 1, "method": "Page.enable"}')
        await transport.receive_loop(self.client)
        self.assertFalse(self.client._connected)
        self.assertEqual(self.client.disconnected.fired, [()])

    async def test_event_frames_reach_dispatch(self):
        event = {"method": "Runtime.bindingCalled", "params": {"name": "__cvbPush"}}
        self.client.wire = fake_wire(FakeConnection(events=[event]))
        await transport.open_client(self.client, "ws://one")
        self.assertEqual(self.client.events, [event])

    async def test_send_disconnected_is_broken_not_empty(self):
        with self.assertRaises(ConnectionError):
            await self.client.send("X")

    async def test_tab_discovery_filters_pages(self):
        self.client.wire = fake_wire(tabs=[{"type": "page", "id": "a"},
                                          {"type": "worker"}, {"type": "page", "id": "c"}])
        self.assertEqual([p['id'] for p in await transport.fetch_tabs(self.client)], ['a', 'c'])
        self.assertEqual(self.client.wire.discovery.asked, [self.client.base_url])

    async def test_tab_discovery_failure_is_empty(self):
        self.client.wire = fake_wire(tab_error=OSError("closed"))
        self.assertEqual(await transport.fetch_tabs(self.client), [])

    async def test_real_qt_client_with_wire(self):
        from backend.cdp_client import CDPClient
        client = CDPClient.with_wire(fake_wire(FakeConnection(value_reply("ok"))), "h", 9333)
        try:
            self.assertTrue(await client.connect("ws://one"))
            self.assertEqual(await client.evaluate("1"), "ok")
            self.assertTrue(client.is_connected)
            self.assertEqual(client.base_url, "http://h:9333")
        finally:
            await client.disconnect()


class TestWireContract(unittest.TestCase):
    def test_fakes_are_structural_ports(self):
        self.assertIsInstance(FakeConnection(), CdpConnection)
        self.assertIsInstance(FakeConnector(), CdpConnector)
        self.assertIsInstance(FakeTabDiscovery(), TabDiscovery)

    def test_production_bindings(self):
        wire = default_wire()
        self.assertIsInstance(wire.connector, WebSocketConnector)
        self.assertIsInstance(wire.discovery, HttpTabDiscovery)
        self.assertIsInstance(wire.connector, CdpConnector)
        self.assertIsInstance(wire.discovery, TabDiscovery)

    def test_backend_network_imports_are_confined(self):
        pattern = re.compile(r'^\s*(import|from)\s+(websockets|aiohttp)\b', re.M)
        offenders = sorted(p.relative_to(ROOT).as_posix() for p in (ROOT/'backend').rglob('*.py')
                           if pattern.search(p.read_text()))
        self.assertEqual(offenders, ['backend/cdp_transport.py'])
