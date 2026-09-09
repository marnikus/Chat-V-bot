"""services/cdp_service — tab discovery, connection, URL matching (Result seam).

The contract (docs/SERVICES_TEST_DESIGN_2026-09-09.md §2.3): every method
returns ``Result`` — no bare exception crosses the seam. Outcomes are
announced on the EventBus (TabsReceived / ConnectionChanged / TabMatchResult
/ LogMessage) for the CdpBridge to forward.

Run with:  python3 tests/integration/services/test_services_cdp.py
"""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))

from core.events import (EventBus, ConnectionChanged, LogMessage,  # noqa: E402
                         TabMatchResult, TabsReceived)
from services.cdp_service import CdpService  # noqa: E402


class Tab:
    def __init__(self, tid, title, url, ws_url):
        self.id = tid
        self.title = title
        self.url = url
        self.ws_url = ws_url
        self.__dict__  # tab_matcher uses t.__dict__


class FakeCdp:
    def __init__(self, tabs=None, fetch_error=None, connect_result=True,
                 connect_error=None):
        self._tabs = tabs or []
        self.fetch_error = fetch_error
        self._connect_result = connect_result
        self.connect_error = connect_error
        self.fetches = 0
        self.connect_calls = []

    async def fetch_tabs(self):
        self.fetches += 1
        if self.fetch_error:
            raise self.fetch_error
        return list(self._tabs)

    async def connect(self, ws_url):
        self.connect_calls.append(ws_url)
        if self.connect_error:
            raise self.connect_error
        return self._connect_result


class SignalStub:
    """Stands in for a PySide6 Signal: connect() records the callback."""

    def __init__(self):
        self._fns = []

    def connect(self, fn):
        self._fns.append(fn)

    def emit(self, *args):
        for fn in list(self._fns):
            fn(*args)


class SignalCdp:
    """Fake cdp whose Qt signals are plain stubs."""

    def __init__(self):
        self.connected = SignalStub()
        self.disconnected = SignalStub()
        self.error = SignalStub()


class CdpCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.bus = EventBus()
        self.tabs_events = []
        self.conn_events = []
        self.match_events = []
        self.logs = []
        self.bus.subscribe(TabsReceived, lambda e: self.tabs_events.append(e))
        self.bus.subscribe(ConnectionChanged, lambda e: self.conn_events.append(e))
        self.bus.subscribe(TabMatchResult, lambda e: self.match_events.append(e))
        self.bus.subscribe(LogMessage,
                           lambda e: self.logs.append((e.message, e.level)))

    def use(self, cdp):
        self.cdp = cdp
        return CdpService(cdp, bus=self.bus)


def tab(tid, title, url, ws="ws://x"):
    return Tab(tid, title, url, ws)


class TestFetchTabs(CdpCase):
    async def test_ok_payload_has_id_title_url_ws(self):
        service = self.use(FakeCdp(tabs=[
            tab("t1", "Chat", "https://ru.virt-chat.com/chat", "ws://t1"),
            tab("t2", "Room", "https://ru.virt-chat.com/room")]))
        result = await service.fetch_tabs()
        payload = json.loads(self.tabs_events[-1].payload)
        self.assertEqual(len(payload), 2)
        self.assertEqual(payload[0]["id"], "t1")
        self.assertEqual(payload[0]["title"], "Chat")
        self.assertEqual(payload[0]["url"], "https://ru.virt-chat.com/chat")
        self.assertEqual(payload[0]["ws_url"], "ws://t1")
        self.assertEqual(payload[1]["ws_url"], "ws://x")

    async def test_failure_becomes_err_not_an_escape(self):
        service = self.use(FakeCdp(fetch_error=RuntimeError("no chrome")))
        result = await service.fetch_tabs()
        self.assertTrue(result.is_err)
        self.assertEqual(result.code, "tab_fetch_failed")
        self.assertIn("no chrome", result.detail)
        self.assertTrue(any(lvl == "error" and "Tab discovery failed" in msg
                            for msg, lvl in self.logs))

    async def test_malformed_tab_cannot_escape_the_seam(self):
        # A tab object missing attributes must not raise AttributeError
        # outside the Result — the service contract is Result-only.
        service = self.use(FakeCdp(tabs=[object()]))
        result = await service.fetch_tabs()
        self.assertTrue(result.is_err, "malformed tab must become Err, not raise")
        self.assertEqual(result.code, "tab_fetch_failed")


class TestConnect(CdpCase):
    async def test_success(self):
        service = self.use(FakeCdp(connect_result=True))
        result = await service.connect("ws://t1")
        self.assertEqual(result.value, True)
        self.assertEqual(self.cdp.connect_calls, ["ws://t1"])
        self.assertTrue(any("Connected" in msg and lvl == "info"
                            for msg, lvl in self.logs))

    async def test_false_is_ok_not_an_error(self):
        service = self.use(FakeCdp(connect_result=False))
        result = await service.connect("ws://t1")
        self.assertTrue(result.is_ok)
        self.assertFalse(result.value)
        self.assertFalse(any("Connected" in msg for msg, _ in self.logs))

    async def test_exception_becomes_err(self):
        service = self.use(FakeCdp(connect_error=RuntimeError("refused")))
        result = await service.connect("ws://t1")
        self.assertTrue(result.is_err)
        self.assertEqual(result.code, "connect_failed")


class TestFindTabByUrl(CdpCase):
    async def test_empty_query_is_err_with_empty_match_event(self):
        for query in ("", "   "):
            service = self.use(FakeCdp())
            result = await service.find_tab_by_url(query)
            self.assertTrue(result.is_err)
            self.assertEqual(result.code, "empty_query")
            # the event carries the NORMALISED query (empty after strip)
            self.assertEqual(self.match_events[-1].query, "")
            self.assertEqual(json.loads(self.match_events[-1].matches_json), [])

    async def test_fetch_failure_propagates_as_err(self):
        service = self.use(FakeCdp(fetch_error=RuntimeError("boom")))
        result = await service.find_tab_by_url("https://ru.virt-chat.com/chat")
        self.assertTrue(result.is_err)
        self.assertEqual(result.code, "tab_fetch_failed")
        self.assertEqual(json.loads(self.match_events[-1].matches_json), [])

    async def test_no_tabs_warns_and_returns_empty(self):
        service = self.use(FakeCdp(tabs=[]))
        result = await service.find_tab_by_url("https://ru.virt-chat.com/chat")
        self.assertTrue(result.is_ok)
        self.assertEqual(result.value, [])
        self.assertTrue(any("remote-debugging-port" in msg
                            for msg, _ in self.logs))

    async def test_match_found(self):
        service = self.use(FakeCdp(tabs=[
            tab("t1", "Chat", "https://ru.virt-chat.com/chat"),
            tab("t2", "Other", "https://example.com")]))
        result = await service.find_tab_by_url("https://ru.virt-chat.com/chat")
        self.assertTrue(result.is_ok)
        self.assertTrue(result.value)
        payload = json.loads(self.match_events[-1].matches_json)
        self.assertEqual(payload[0]["kind"], "url_exact")
        self.assertEqual(payload[0]["id"], "t1")
        self.assertTrue(any("match" in msg.lower() for msg, _ in self.logs))

    async def test_no_match_lists_available_tabs(self):
        service = self.use(FakeCdp(tabs=[
            tab("t1", "Chat", "https://ru.virt-chat.com/chat")]))
        result = await service.find_tab_by_url("https://other.example")
        self.assertTrue(result.is_ok)
        self.assertEqual(result.value, [])
        self.assertEqual(json.loads(self.match_events[-1].matches_json), [])
        error = [msg for msg, lvl in self.logs if lvl == "error"]
        self.assertTrue(error and "No open tab matches" in error[0])


class TestStatusForwarding(CdpCase):
    async def test_connected_disconnected_error_re_emitted(self):
        cdp = SignalCdp()
        service = self.use(cdp)
        service.install_status_forwarding()
        cdp.connected.emit()
        cdp.disconnected.emit()
        cdp.error.emit("boom")
        statuses = [e.status for e in self.conn_events]
        self.assertEqual(statuses, ["connected", "disconnected", "error"])

    async def test_no_cdp_is_a_noop(self):
        service = CdpService(cdp=None, bus=self.bus)
        self.assertIsNone(service.install_status_forwarding())

    async def test_broken_signal_target_cannot_kill_install(self):
        class Broken:
            def __init__(self):
                self.connected = None     # no .connect

        # object() has no attributes at all
        service = self.use(SignalCdp())
        service.attach(cdp=Broken())
        self.assertIsNone(service.install_status_forwarding())
        self.assertEqual(self.conn_events, [])


class TestAttach(CdpCase):
    async def test_attach_swaps_the_cdp_and_bus(self):
        service = self.use(FakeCdp(tabs=[tab("a", "A", "https://a")]))
        bus2 = EventBus()
        got = []
        bus2.subscribe(TabsReceived, lambda e: got.append(e))
        cdp2 = FakeCdp(tabs=[tab("b", "B", "https://b")])
        service.attach(cdp=cdp2, bus=bus2)
        result = await service.fetch_tabs()
        self.assertTrue(result.is_ok)
        self.assertEqual(len(got), 1)
        self.assertEqual(json.loads(got[0].payload)[0]["id"], "b")
        self.assertEqual(self.tabs_events, [], "old bus must not see new work")


if __name__ == "__main__":
    unittest.main(verbosity=2)
