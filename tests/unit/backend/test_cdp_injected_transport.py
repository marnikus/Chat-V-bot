"""Round I/A: real lifecycle and framing, synthetic scripted browser I/O.

No patched network modules, live Chrome, or real-time waits. These fixtures
are synthetic protocol examples, NOT captured user conversations.
"""
import asyncio
import json
import unittest

from backend.cdp_client import CDPClient, client_with_transport
from backend.cdp_transport import WebSocketConnector, HttpTabDiscovery


class ScriptedConnection:
    def __init__(self):
        self.frames = asyncio.Queue()
        self.commands = []
        self.closed = False

    def __aiter__(self):
        return self

    async def __anext__(self):
        frame = await self.frames.get()
        if frame is None:
            raise StopAsyncIteration
        return frame

    async def send(self, payload):
        command = json.loads(payload)
        self.commands.append(command)
        result = {"result": {"value": "answer"}} if command["method"] == "Runtime.evaluate" else {}
        await self.frames.put(json.dumps({"id": command["id"], "result": result}))

    async def close(self):
        self.closed = True
        await self.frames.put(None)


class FakeTransport:
    def __init__(self):
        self.connections = []
        self.urls = []
        self.targets = []
        self.failure = None

    async def connect(self, url):
        self.urls.append(url)
        if self.failure:
            raise self.failure
        connection = ScriptedConnection()
        self.connections.append(connection)
        return connection

    async def discover(self, base_url):
        self.urls.append(base_url)
        if self.failure:
            raise self.failure
        return self.targets


class TestInjectedTransport(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.browser = FakeTransport()
        self.client = client_with_transport(self.browser, "browser.test", 9333)

    async def asyncTearDown(self):
        await self.client.disconnect()
        await asyncio.sleep(0)  # flush cancellation, never a wall-clock delay

    async def test_default_adapter_is_retained(self):
        wire = CDPClient().wire
        self.assertIsInstance(wire.connector, WebSocketConnector)
        self.assertIsInstance(wire.discovery, HttpTabDiscovery)

    async def test_connect_domain_order_evaluate_and_disconnect(self):
        signals = []
        self.client.connected.connect(lambda: signals.append("connected"))
        self.client.disconnected.connect(lambda: signals.append("disconnected"))
        self.assertTrue(await self.client.connect("ws://browser.test/page"))
        socket = self.browser.connections[0]
        self.assertEqual([c["method"] for c in socket.commands],
                         [f"{d}.enable" for d in ("Page", "DOM", "Runtime", "Network")])
        self.assertTrue(self.client.is_connected)
        self.assertEqual(await self.client.evaluate("'answer'"), "answer")
        self.assertEqual(socket.commands[-1], {
            "id": 5, "method": "Runtime.evaluate", "params": {
                "expression": "'answer'", "returnByValue": True, "awaitPromise": True}})
        self.assertEqual(self.client._pending, {})
        await self.client.disconnect()
        self.assertTrue(socket.closed)
        self.assertFalse(self.client.is_connected)
        self.assertEqual(signals[:2], ["disconnected", "connected"])

    async def test_reconnect_closes_previous_connection(self):
        await self.client.connect("ws://first")
        first = self.browser.connections[0]
        await self.client.connect("ws://second")
        self.assertTrue(first.closed)
        self.assertEqual(self.browser.urls, ["ws://first", "ws://second"])
        self.assertEqual(self.browser.connections[1].commands[0]["id"], 5)

    async def test_discovery_filters_non_pages_and_preserves_tab_fields(self):
        self.browser.targets = [
            {"type": "worker", "id": "ignored"},
            {"type": "page", "id": "page", "title": "Chat", "url": "https://chat",
             "webSocketDebuggerUrl": "ws://page"}]
        tabs = await self.client.fetch_tabs()
        self.assertEqual(len(tabs), 1)
        self.assertEqual(tabs[0].title, "Chat")
        self.assertEqual(self.browser.urls, ["http://browser.test:9333"])

    async def test_connection_failure_reports_error(self):
        errors = []
        self.client.error.connect(errors.append)
        self.browser.failure = OSError("offline")
        self.assertFalse(await self.client.connect("ws://offline"))
        self.assertEqual(errors, ["offline"])
        self.assertFalse(self.client.is_connected)
        self.assertEqual(await self.client.fetch_tabs(), [])

    async def test_events_flow_through_real_receive_loop(self):
        await self.client.connect("ws://page")
        observed = asyncio.get_running_loop().create_future()
        self.client.on_event("Runtime.bindingCalled", observed.set_result)
        await self.browser.connections[0].frames.put(json.dumps({
            "method": "Runtime.bindingCalled", "params": {"name": "__cvbPush"}}))
        self.assertEqual(await asyncio.wait_for(observed, 1), {"name": "__cvbPush"})

    async def test_malformed_frame_disconnects_without_success(self):
        await self.client.connect("ws://page")
        task = self.client._receive_task
        await self.browser.connections[0].frames.put("not json")
        await asyncio.wait_for(task, 1)
        self.assertFalse(self.client.is_connected)

    async def test_remote_eof_disconnects(self):
        await self.client.connect("ws://page")
        task = self.client._receive_task
        await self.browser.connections[0].frames.put(None)
        await asyncio.wait_for(task, 1)
        self.assertFalse(self.client.is_connected)

    async def test_send_without_socket_is_broken_not_empty(self):
        with self.assertRaisesRegex(ConnectionError, "CDP not connected"):
            await self.client.send("Runtime.evaluate")
