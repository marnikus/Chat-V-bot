"""CDP transport + lease: the socket lifecycle the suite never exercised.

Round H step H-B6 (docs/archive/2026-09-14-round-h/AREA_B_BACKEND_BRIDGE_DESIGN_2026-09-14.md
§3): every CDP call in the application goes through `backend/cdp_client.py`,
and before this file a third of its statements were never executed — the
connect/disconnect/send path, the tab discovery, the command helpers and the
lease hand-over edges. These tests lock that behaviour down BEFORE the
transport-vs-events split moves it (RULE 16 §16.5: "Touch a hotspot only with
tests that lock current behaviour first").

Two conventions keep the pins honest across the split:

  * acquisition is scripted through `cdp.wire` (Area A); HTTP/WebSocket
    adapter behavior is tested separately in test_cdp_wire_adapters.py;
  * the instance seam the existing `tests/test_cdp_events.py` uses — shadowing
    `cdp.send` with a fake, assigning `cdp._ws` / `cdp._connected` — is reused
    verbatim, because that seam is the contract the split must keep.

Run with:  python3 tests/unit/backend/test_cdp_client_transport.py
"""

import asyncio
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))))

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend.cdp_transport import CdpWire  # noqa: E402
from fake_cdp_wire import FakeTabDiscovery  # noqa: E402

from backend.cdp_client import CDPClient, CdpLease, LOW, HIGH  # noqa: E402


class _Connector:
    def __init__(self, socket=None, error=None):
        self._socket, self._error = socket, error

    async def open(self, ws_url):
        if self._error is not None:
            raise self._error
        return self._socket


def wired(cdp, socket=None, error=None, tabs=()):
    cdp.wire = CdpWire(_Connector(socket, error), FakeTabDiscovery(tabs))
    return cdp


def run(coro):
    return asyncio.run(coro)


class FakeSocket:
    """Async-iterable stand-in for the websocket connection (same shape as
    the one in tests/test_cdp_events.py, with a `closed` marker)."""

    def __init__(self, frames):
        self._frames = list(frames)
        self.sent = []
        self.closed = False

    def __aiter__(self):
        async def gen():
            for f in self._frames:
                # a real socket only yields what has arrived by now — handing
                # every frame out in one task turn would let the receive loop
                # run past the requests that are still being registered
                await asyncio.sleep(0)
                yield f
        return gen()

    async def send(self, payload):
        self.sent.append(payload)

    async def close(self):
        self.closed = True


class HangingSocket:
    """Parks inside `async for` until it is closed — a live connection."""

    def __init__(self):
        self.sent = []
        self.closed = False
        self.parked = asyncio.get_event_loop().create_future()

    def __aiter__(self):
        async def gen():
            self.parked.set_result(True)
            yield await asyncio.get_event_loop().create_future()
        return gen()

    async def send(self, payload):
        self.sent.append(payload)

    async def close(self):
        self.closed = True


class ReplySocket:
    """A socket that models what a real network enforces: a reply only
    exists AFTER its request was sent, and every delivery costs a loop turn.

    The naive "preloaded frames" fake cannot model `connect()`: with four
    replies sitting in the buffer, the receive task drains them all in one
    burst, three of them before their requests are even registered. A real
    CDP server only ever has a reply for a request it already received, and
    the client only sends request n+1 after reply n arrived — so this socket
    waits for each request before answering it.
    """

    def __init__(self, result_of=None):
        self._result_of = result_of or (lambda _req: {"result": {}})
        self.sent = []
        self.closed = False

    def __aiter__(self):
        async def gen():
            n = 1
            while True:
                while len(self.sent) < n:       # the request is not on the wire
                    await asyncio.sleep(0)
                req = json.loads(self.sent[n - 1])
                await asyncio.sleep(0)          # the reply travels the wire
                yield json.dumps({"id": req["id"],
                                  **self._result_of(req)})
                n += 1
        return gen()

    async def send(self, payload):
        self.sent.append(payload)

    async def close(self):
        self.closed = True


def reply(cmd_id, value=None):
    return json.dumps({"id": cmd_id, "result": {"result": {"value": value}}})


class FakeSession:
    """`aiohttp.ClientSession` stand-in: one GET to /json/list."""

    class _Resp:
        def __init__(self, payload, status=200):
            self._payload, self.status = payload, status

        async def json(self):
            return self._payload

    def __init__(self, payload, status=200, exc=None):
        self._payload, self._status, self._exc = payload, status, exc

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    def get(self, url, timeout=None):
        if self._exc is not None:
            raise self._exc
        return FakeSession._Ctx(self._Resp(self._payload, self._status))

    class _Ctx:
        def __init__(self, resp):
            self._resp = resp

        async def __aenter__(self):
            return self._resp

        async def __aexit__(self, *exc_info):
            return False


class TestSend(unittest.TestCase):
    def test_send_without_a_socket_is_a_connection_error(self):
        async def scenario():
            cdp = CDPClient()
            try:
                await cdp.send("Page.enable")
                return None
            except ConnectionError as exc:
                return str(exc)
        self.assertIn("not connected", run(scenario()).lower())

    def test_send_stamps_an_id_and_resolves_on_the_matching_frame(self):
        async def scenario():
            cdp = CDPClient()
            cdp._connected = True
            cdp._ws = FakeSocket([])
            task = asyncio.get_event_loop().create_task(
                cdp.send("Runtime.evaluate", {"expression": "1"}))
            await asyncio.sleep(0)               # let the frame go out
            frame = json.loads(cdp._ws.sent[-1])
            cdp._pending[frame["id"]].set_result(
                {"id": frame["id"], "result": {}})
            await task
            return frame
        frame = run(scenario())
        self.assertEqual(frame["method"], "Runtime.evaluate")
        self.assertEqual(frame["params"], {"expression": "1"})
        self.assertIsInstance(frame["id"], int)

    def test_pending_table_holds_one_entry_per_inflight_command(self):
        async def scenario():
            cdp = CDPClient()
            cdp._connected = True
            cdp._ws = FakeSocket([reply(1, {}), reply(2, {}), reply(3, {})])
            tasks = [asyncio.get_event_loop().create_task(cdp.send("X"))
                     for _ in range(3)]
            await asyncio.sleep(0)
            inflight = len(cdp._pending)
            await cdp._receive_loop()           # the loop pops as it resolves
            await asyncio.gather(*tasks)
            return inflight, len(cdp._pending)
        inflight, after = run(scenario())
        self.assertEqual(inflight, 3)
        self.assertEqual(after, 0)


class TestConnectDisconnect(unittest.TestCase):
    def test_connect_enables_the_domains_and_emits_connected(self):
        async def scenario():
            cdp = CDPClient("127.0.0.1", 9333)
            states = []
            cdp.connected.connect(lambda: states.append("connected"))
            cdp.error.connect(lambda _e: states.append("error"))

            socket = ReplySocket()
            wired(cdp, socket)
            ok = await cdp.connect("ws://tab/1")
            sent = [json.loads(f)["method"] for f in socket.sent]
            await cdp.disconnect()
            return ok, states, sent
        ok, states, methods = run(scenario())
        self.assertTrue(ok)
        self.assertEqual(states, ["connected"])
        self.assertEqual(methods, ["Page.enable", "DOM.enable",
                                   "Runtime.enable", "Network.enable"])

    def test_connect_failure_reports_error_and_stays_disconnected(self):
        async def scenario():
            cdp = CDPClient()
            states = []
            cdp.error.connect(lambda _e: states.append("error"))
            cdp.disconnected.connect(lambda: states.append("disconnected"))

            wired(cdp, error=OSError("refused"))
            ok = await cdp.connect("ws://tab/1")
            return ok, states, cdp.is_connected
        ok, states, connected = run(scenario())
        self.assertFalse(ok)
        self.assertIn("error", states)
        self.assertFalse(connected)

    def test_is_connected_needs_both_the_flag_and_the_socket(self):
        async def scenario():
            cdp = CDPClient()
            cdp._connected = True
            no_socket = cdp.is_connected
            cdp._ws = FakeSocket([])
            return no_socket, cdp.is_connected, cdp.base_url
        no_socket, connected, base = run(scenario())
        self.assertFalse(no_socket)     # the flag alone is not a connection
        self.assertTrue(connected)
        self.assertEqual(base, "http://127.0.0.1:9222")

    def test_disconnect_cancels_the_loop_closes_the_socket_and_emits(self):
        async def scenario():
            cdp = CDPClient()
            states = []
            cdp.disconnected.connect(lambda: states.append("disconnected"))
            fut = asyncio.get_event_loop().create_future()
            cdp._pending[9] = fut
            socket = HangingSocket()
            cdp._ws = socket               # before the loop starts on it
            cdp._connected = True
            task = asyncio.get_event_loop().create_task(
                cdp._receive_loop())
            cdp._receive_task = task
            await socket.parked            # the loop is live on the socket
            await cdp.disconnect()
            try:
                await task
            except asyncio.CancelledError:
                pass
            # the loop swallows the CancelledError and returns cleanly
            # (that except branch is what keeps a cancelled receive from
            # surfacing as an unhandled error)
            return (states, cdp._ws is None, len(cdp._pending),
                    socket.closed, task.done(), task.cancelled(),
                    cdp._connected)
        (states, ws_gone, pending, closed, task_done, task_cancelled,
         connected) = run(scenario())
        self.assertIn("disconnected", states)
        self.assertTrue(ws_gone)
        self.assertEqual(pending, 0)
        self.assertTrue(closed)
        self.assertTrue(task_done)
        self.assertFalse(task_cancelled)   # exited through the except branch
        self.assertFalse(connected)


class TestFetchTabs(unittest.TestCase):
    def _tabs(self, session_factory):
        # Discovery consumer tests, not HTTP status-policy tests. The real
        # HttpTabDiscovery is independently exercised by adapter contracts.
        session = session_factory()
        items = session._payload if session._status == 200 else []

        async def scenario():
            cdp = CDPClient("h", 9223)
            cdp.wire = CdpWire(_Connector(),
                               FakeTabDiscovery(items or [], session._exc))
            return await cdp.fetch_tabs()
        return run(scenario())

    def test_only_page_entries_survive_as_tab_info(self):
        payload = [
            {"type": "page", "id": "a", "title": "Chat", "url": "https://x",
             "webSocketDebuggerUrl": "ws://x/a"},
            {"type": "service_worker", "id": "b", "title": "sw",
             "url": "https://x/sw", "webSocketDebuggerUrl": "ws://x/b"},
            {"type": "page", "id": "c"},
        ]
        tabs = self._tabs(lambda: FakeSession(payload))
        self.assertEqual([t.id for t in tabs], ["a", "c"])
        self.assertEqual(tabs[0].title, "Chat")
        self.assertEqual(tabs[0].ws_url, "ws://x/a")
        self.assertEqual(tabs[1].url, "")      # absent fields default to ""

    def test_endpoint_error_is_an_empty_list_not_an_exception(self):
        tabs = self._tabs(lambda: FakeSession(None, exc=OSError("down")))
        self.assertEqual(tabs, [])

    def test_non_200_is_an_empty_list(self):
        tabs = self._tabs(lambda: FakeSession(None, status=404))
        self.assertEqual(tabs, [])


class TestCommands(unittest.TestCase):
    """The command helpers, through the `cdp.send` instance seam the existing
    suite established: a fake `send` records what the command would put on the
    wire and answers the way the DevTools protocol does."""

    def _client(self, answer=None):
        cdp = CDPClient()
        calls = []

        async def fake_send(method, params=None):
            calls.append((method, params or {}))
            if answer is not None:
                if isinstance(answer, Exception):
                    raise answer
                return answer
            return {"result": {}}

        cdp.send = fake_send
        return cdp, calls

    def test_evaluate_reads_the_nested_value(self):
        cdp, _calls = self._client({"result": {"result":
                                               {"value": [1, 2]}}})
        self.assertEqual(run(cdp.evaluate("1+1")), [1, 2])

    def test_click_at_sends_press_then_release_at_the_same_point(self):
        cdp, calls = self._client()
        run(cdp.click_at(10.5, 20))
        self.assertEqual([m for m, _p in calls],
                         ["Input.dispatchMouseEvent"] * 2)
        self.assertEqual(calls[0][1]["type"], "mousePressed")
        self.assertEqual(calls[1][1]["type"], "mouseReleased")
        for _m, p in calls:
            self.assertEqual((p["x"], p["y"], p["button"]),
                             (10.5, 20, "left"))

    def test_mouse_wheel_sends_one_frame_with_the_deltas(self):
        cdp, calls = self._client()
        run(cdp.mouse_wheel(1, -30, 5, 6))
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][1], {"type": "mouseWheel", "x": 5, "y": 6,
                                       "deltaX": 1, "deltaY": -30})

    def test_get_element_rect_evaluates_the_probe_and_returns_the_value(self):
        cdp, calls = self._client({"result": {"result":
                                              {"value": {"x": 1, "y": 2}}}})
        rect = run(cdp.get_element_rect("div.x"))
        self.assertEqual(rect, {"x": 1, "y": 2})
        method, params = calls[0]
        self.assertEqual(method, "Runtime.evaluate")
        self.assertIn("div.x", params["expression"])

    def _scripted(self, *answers):
        cdp = CDPClient()
        calls = []
        queue = list(answers)

        async def scripted_send(method, params=None):
            calls.append((method, params or {}))
            return queue.pop(0) if queue else {"result": {}}

        cdp.send = scripted_send
        return cdp, calls

    def test_set_file_input_files_walks_doc_query_set(self):
        cdp, calls = self._scripted(
            {"result": {"root": {"nodeId": 7}}},
            {"result": {"nodeId": 42}},
            {"result": {}})
        run(cdp.set_file_input_files("input#file", ["/tmp/a.jpg"]))
        self.assertEqual([m for m, _p in calls],
                         ["DOM.getDocument", "DOM.querySelector",
                          "DOM.setFileInputFiles"])
        self.assertEqual(calls[1][1], {"nodeId": 7,
                                       "selector": "input#file"})
        self.assertEqual(calls[2][1], {"files": ["/tmp/a.jpg"],
                                       "nodeId": 42})

    def test_set_file_input_files_skips_the_set_when_the_node_is_zero(self):
        cdp, calls = self._scripted(
            {"result": {"root": {"nodeId": 7}}},
            {"result": {"nodeId": 0}})
        run(cdp.set_file_input_files("input#file", ["/tmp/a.jpg"]))
        self.assertEqual([m for m, _p in calls],
                         ["DOM.getDocument", "DOM.querySelector"])

    def test_add_script_failure_is_an_empty_identifier_not_an_exception(self):
        cdp, calls = self._client(RuntimeError("no such domain"))
        ident = run(cdp.add_script_on_new_document("window.x=1"))
        self.assertEqual(ident, "")
        self.assertEqual(calls[0][0],
                         "Page.addScriptToEvaluateOnNewDocument")

    def test_remove_script_on_an_empty_identifier_is_a_noop(self):
        cdp, calls = self._client()
        self.assertFalse(run(cdp.remove_script_on_new_document("")))
        self.assertEqual(calls, [])

    def test_remove_script_sends_the_identifier(self):
        cdp, calls = self._client()
        self.assertTrue(run(cdp.remove_script_on_new_document("s1")))
        self.assertEqual(calls[0], ("Page.removeScriptToEvaluateOnNewDocument",
                                    {"identifier": "s1"}))

    def test_remove_script_failure_is_false_not_an_exception(self):
        cdp, _calls = self._client(RuntimeError("gone"))
        self.assertFalse(run(cdp.remove_script_on_new_document("s1")))


class TestCookies(unittest.TestCase):
    """The cookie-domain matching that the Python download path relies on."""

    def _header(self, cookies, url="https://images.virt-chat.com/a.gif"):
        async def scenario():
            cdp = CDPClient()
            calls = []

            async def fake_send(method, params=None):
                calls.append(method)
                return {"result": {"cookies": cookies}}

            cdp.send = fake_send
            return await cdp.get_cookies(url), calls
        return run(scenario())

    def test_parent_domain_covers_subdomains_but_siblings_do_not(self):
        header, calls = self._header([
            {"name": "sid", "value": "abc", "domain": "virt-chat.com"},
            {"name": "nope", "value": "1", "domain": "other.ru"},
        ])
        self.assertIn("sid=abc", header)
        self.assertNotIn("nope", header)
        self.assertEqual(calls, ["Network.getAllCookies"])

    def test_empty_value_renders_as_name_equals_empty(self):
        header, _calls = self._header(
            [{"name": "t", "value": None, "domain": "virt-chat.com"}])
        self.assertIn("t=", header)

    def test_cookie_without_a_domain_is_kept(self):
        header, _calls = self._header([{"name": "anon", "value": "1"}])
        self.assertIn("anon=1", header)


class TestCdpLeaseHandOver(unittest.TestCase):
    def test_busy_waiting_and_high_waiting_reflect_the_queue(self):
        async def scenario():
            lease = CdpLease()
            async with lease.high():
                return (lease.busy, lease.waiting, lease.high_waiting)
        busy, waiting, high = run(scenario())
        self.assertTrue(busy)
        self.assertEqual(waiting, 0)
        self.assertFalse(high)

    def test_cancellation_that_lost_the_race_hands_the_lease_back(self):
        """The `release()` right before a cancel: the waiter's future already
        carries the hand-over (done, not cancelled), so the except branch must
        release instead of dead-locking the socket."""
        async def scenario():
            lease = CdpLease()
            lease._locked = True                  # someone else holds it
            task = asyncio.get_event_loop().create_task(
                lease.acquire(LOW))
            await asyncio.sleep(0)                # now waiting in the heap
            lease.release()                       # hand-over: future done
            task.cancel()                         # and the cancel still lands
            try:
                await task
            except asyncio.CancelledError:
                pass
            return lease.busy
        self.assertFalse(run(scenario()))

    def test_plain_cancellation_keeps_the_previous_holder(self):
        """Cancelled while genuinely waiting (no hand-over yet): the lock
        stays with the previous holder — no lock is invented out of nothing."""
        async def scenario():
            lease = CdpLease()
            lease._locked = True
            task = asyncio.get_event_loop().create_task(lease.acquire(LOW))
            await asyncio.sleep(0)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            return lease.busy
        self.assertTrue(run(scenario()))

    def test_releases_skip_waiters_that_already_got_the_lease(self):
        async def scenario():
            lease = CdpLease()
            holder = asyncio.get_event_loop().create_task(
                lease.acquire(HIGH))
            await asyncio.sleep(0)               # holder owns the lock
            taker = asyncio.get_event_loop().create_task(
                lease.acquire(LOW))
            third = asyncio.get_event_loop().create_task(
                lease.acquire(LOW))
            await asyncio.sleep(0)               # both queued in the heap
            lease.release()                      # hand-over: taker gets it
            await holder
            lease.release()                      # skips taker's done future
            await asyncio.gather(taker, third)   # … and hands the lock to third
            lease.release()                      # the last holder gives it back
            return lease.busy, lease.high_waiting
        busy, high = run(scenario())
        self.assertFalse(busy)
        self.assertFalse(high)


class TestReceiveLoopRobustness(unittest.TestCase):
    def test_an_unknown_reply_id_is_ignored_not_crashed_on(self):
        async def scenario():
            cdp = CDPClient()
            seen = []
            cdp.on_event("Runtime.bindingCalled", seen.append)
            cdp._ws = FakeSocket([
                json.dumps({"id": 999, "result": {}}),          # nobody asked
                json.dumps({"method": "Runtime.bindingCalled",
                            "params": {"payload": "x"}}),
            ])
            await cdp._receive_loop()
            return seen, cdp._connected
        seen, connected = run(scenario())
        self.assertEqual(len(seen), 1)
        self.assertFalse(connected)    # the socket ran dry → loop ended

    def test_a_malformed_frame_is_logged_and_the_loop_stops_cleanly(self):
        async def scenario():
            cdp = CDPClient()
            states = []
            cdp.disconnected.connect(lambda: states.append("disconnected"))
            cdp._ws = FakeSocket(["{not json"])
            await cdp._receive_loop()
            return states, cdp._connected
        states, connected = run(scenario())
        self.assertEqual(states, ["disconnected"])
        self.assertFalse(connected)


if __name__ == "__main__":
    unittest.main(verbosity=2)
