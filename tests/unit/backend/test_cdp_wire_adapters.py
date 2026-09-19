"""Exercise real adapter policy at the external library boundary (no network).

Unlike consumer tests, these must test timeouts/non-200/error behavior in the
production adapter, not precompute what a discovery fake should answer.
"""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
import unittest

from backend.cdp_transport import (HttpTabDiscovery, WebSocketConnector,
                                   WebSocketConnection)
from backend.cdp_client_transport import BrowserTransport


class Closed(Exception):
    pass


class Socket:
    def __init__(self, frames=(), error=None):
        self.frames = frames
        self.error = error
        self.send = AsyncMock()
        self.close = AsyncMock()

    def __aiter__(self):
        return self.iterate()

    async def iterate(self):
        for frame in self.frames:
            yield frame
        if self.error:
            raise self.error


class Response:
    def __init__(self, status=200, payload=None, error=None):
        self.status = status
        self.json = AsyncMock(return_value=payload, side_effect=error)
        self.exited = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        self.exited = True


class Session(Response):
    def __init__(self, response, error=None):
        super().__init__()
        self.get = Mock(return_value=response, side_effect=error)


class TestAdapters(unittest.IsolatedAsyncioTestCase):
    async def test_socket_options_stream_send_close(self):
        socket = Socket(['{"id":1}', b'bytes'])
        library = SimpleNamespace(connect=AsyncMock(return_value=socket), ConnectionClosed=Closed)
        with patch.dict('sys.modules', {'websockets': library}):
            conn = await WebSocketConnector().open('ws://tab')
        library.connect.assert_awaited_once_with('ws://tab', max_size=52428800,
                                                open_timeout=10, close_timeout=5)
        self.assertEqual([frame async for frame in conn], ['{"id":1}', b'bytes'])
        await conn.send('payload')
        await conn.close()
        socket.send.assert_awaited_once_with('payload')
        socket.close.assert_awaited_once_with()

    async def test_connection_closed_normalizes_to_eof(self):
        conn = WebSocketConnection(Socket(['first'], Closed()), Closed)
        self.assertEqual([frame async for frame in conn], ['first'])

    async def test_other_errors_and_cancellation_propagate(self):
        for error in (ValueError('bad'), asyncio.CancelledError()):
            conn = WebSocketConnection(Socket(error=error), Closed)
            with self.subTest(error=type(error)), self.assertRaises(type(error)):
                [frame async for frame in conn]

    async def test_send_and_close_errors_propagate(self):
        socket = Socket()
        conn = WebSocketConnection(socket, Closed)
        socket.send.side_effect = OSError('send')
        socket.close.side_effect = OSError('close')
        with self.assertRaisesRegex(OSError, 'send'):
            await conn.send('payload')
        with self.assertRaisesRegex(OSError, 'close'):
            await conn.close()

    async def test_socket_open_failure_propagates(self):
        library = SimpleNamespace(connect=AsyncMock(side_effect=OSError('offline')), ConnectionClosed=Closed)
        with patch.dict('sys.modules', {'websockets': library}), self.assertRaises(OSError):
            await WebSocketConnector().open('ws://tab')

    async def test_http_status_timeout_and_resource_cleanup(self):
        for status in (200, 404, 500):
            response = Response(status, [{'type': 'page'}])
            session = Session(response)
            timeout = object()
            library = SimpleNamespace(ClientSession=Mock(return_value=session),
                                      ClientTimeout=Mock(return_value=timeout))
            with self.subTest(status=status), patch.dict('sys.modules', {'aiohttp': library}):
                result = await HttpTabDiscovery().list_tabs('http://browser:9333')
            self.assertEqual(result, [{'type': 'page'}] if status == 200 else [])
            session.get.assert_called_once_with('http://browser:9333/json/list', timeout=timeout)
            library.ClientTimeout.assert_called_once_with(total=5)
            self.assertEqual(response.json.await_count, int(status == 200))
            self.assertTrue(session.exited and response.exited)

    async def test_http_json_errors_and_cancellation_cleanup(self):
        for error in (ValueError('json'), asyncio.CancelledError()):
            response = Response(error=error)
            session = Session(response)
            library = SimpleNamespace(ClientSession=lambda: session, ClientTimeout=lambda **kw: kw)
            with patch.dict('sys.modules', {'aiohttp': library}), self.assertRaises(type(error)):
                await HttpTabDiscovery().list_tabs('http://browser')
            self.assertTrue(session.exited and response.exited)

    async def test_http_get_failure_closes_session(self):
        session = Session(Response(), error=OSError('offline'))
        library = SimpleNamespace(ClientSession=lambda: session, ClientTimeout=lambda **kw: kw)
        with patch.dict('sys.modules', {'aiohttp': library}), self.assertRaises(OSError):
            await HttpTabDiscovery().list_tabs('http://browser')
        self.assertTrue(session.exited)

    async def test_round_i_browser_adapter_remains_usable(self):
        socket = Socket()
        response = Response(payload=[{'id': 'a'}])
        session = Session(response)
        ws = SimpleNamespace(connect=AsyncMock(return_value=socket), ConnectionClosed=Closed)
        http = SimpleNamespace(ClientSession=lambda: session, ClientTimeout=lambda **kw: kw)
        with patch.dict('sys.modules', {'websockets': ws, 'aiohttp': http}):
            adapter = BrowserTransport()
            conn = await adapter.connect('ws://tab')
            self.assertIsInstance(conn, WebSocketConnection)
            self.assertEqual(await adapter.discover('http://browser'), [{'id': 'a'}])
