"""AREA B2 — the network-capture helper the media fetcher was cut into.

Design ref: docs/REFACTOR_2026-09-09_AREA_B_DESIGN.md §2.3 (as delivered).

`_fetch_via_network` was the CC-32 body of `media_store.py`: 88 lines with six
nested closures. It is now the fetcher plus `_NetworkWatch`, which owns the CDP
event handlers, the request id it remembers and the once-only future. Those are
pure functions of the event payloads, so they can be pinned without a browser —
which is the point: the part that used to be untestable is now the part under
test, and the byte plumbing around it (`_download`) is checked for the one thing
production depends on, an error string that names the real reason.

Run with:  python3 tests/unit/stores/test_media_network_watch.py
"""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)

from stores.media_fetch import _NetworkWatch                       # noqa: E402
from stores.media_store import MediaStore                          # noqa: E402


class EmittingCdp:
    """A CDP host that lets the test push events by hand."""

    def __init__(self, fail_send=False):
        self.hooks: dict = {}
        self.sent = []
        self.fail_send = fail_send
        self.off = []

    def on_event(self, name, handler):
        self.hooks.setdefault(name, []).append(handler)
        return handler

    def off_event(self, name, handle):
        self.off.append(name)
        handlers = self.hooks.get(name, [])
        if handle in handlers:
            handlers.remove(handle)

    async def send(self, method, params=None):
        self.sent.append((method, params or {}))
        if self.fail_send:
            raise RuntimeError("devtools off")
        return {}

    async def evaluate(self, expression, *args, **kwargs):
        return None

    def emit(self, name, params):
        for handler in list(self.hooks.get(name, [])):
            handler(params)


def _fetcher(cdp):
    store = MediaStore(None, cdp=cdp)                # no db: nothing is written
    return store, store.fetcher


class TestNetworkWatch(unittest.IsolatedAsyncioTestCase):
    URL = "https://cdn.example.com/img/a.png?tok=1#frag"

    async def watch(self, cdp=None):
        cdp = cdp or EmittingCdp()
        store, fetcher = _fetcher(cdp)
        watch = _NetworkWatch(fetcher, self.URL)
        watch.handles = watch.attach()
        self.addCleanup(watch.detach, watch.handles)
        return cdp, fetcher, watch

    async def test_the_id_is_taken_from_the_request_whose_url_matches(self):
        cdp, fetcher, watch = await self.watch()
        cdp.emit("Network.requestWillBeSent",
                 {"requestId": "1", "request": {"url": self.URL}})
        cdp.emit("Network.requestWillBeSent",
                 {"requestId": "2", "request": {"url": "https://x/b.png"}})
        self.assertEqual(watch.info["request_id"], "1",
                         "query and fragment are stripped, not the match")

    async def test_a_redirect_keeps_the_id_and_adopts_the_mime(self):
        cdp, fetcher, watch = await self.watch()
        cdp.emit("Network.requestWillBeSent",
                 {"requestId": "7", "request": {"url": self.URL}})
        cdp.emit("Network.responseReceived", {
            "requestId": "7",
            "response": {"url": "https://cdn.example.com/img/cached.png",
                         "mimeType": "image/webp"}})
        self.assertEqual(watch.info["request_id"], "7",
                         "the id of the request we started must survive the "
                         "redirect — those are the bytes `getResponseBody` "
                         "can still read")
        self.assertEqual(watch.info["mime"], "image/webp")

    async def test_the_mime_can_come_from_the_headers(self):
        cdp, fetcher, watch = await self.watch()
        cdp.emit("Network.requestWillBeSent",
                 {"requestId": "3", "request": {"url": self.URL}})
        cdp.emit("Network.responseReceived", {
            "requestId": "3",
            "response": {"url": self.URL,
                         "headers": {"Content-Type": "image/gif; charset=x"}}})
        self.assertEqual(watch.info["mime"], "image/gif; charset=x")

    async def test_finished_resolves_once_and_body_wins(self):
        cdp, fetcher, watch = await self.watch()
        calls = []

        def finish(fut, info):
            calls.append(dict(info))
            fut.set_result({"ok": True, "b64": "AA=="})

        fetcher._finish_network_body = finish
        cdp.emit("Network.requestWillBeSent",
                 {"requestId": "5", "request": {"url": self.URL}})
        cdp.emit("Network.loadingFinished", {"requestId": "5"})
        cdp.emit("Network.loadingFinished", {"requestId": "5"})
        self.assertEqual(calls, [{"request_id": "5", "mime": ""}],
                         "the `fut.done()` guard is what keeps a second event "
                         "from reading the same body twice")
        self.assertTrue(watch.fut.done())

    async def test_a_failed_load_reports_the_error_text(self):
        cdp, fetcher, watch = await self.watch()
        cdp.emit("Network.requestWillBeSent",
                 {"requestId": "9", "request": {"url": self.URL}})
        cdp.emit("Network.loadingFailed",
                 {"requestId": "9", "errorText": "net::ERR_BLOCKED"})
        self.assertEqual(await watch.fut,
                         {"ok": False, "error": "net::ERR_BLOCKED"})

    async def test_a_failure_for_another_request_is_ignored(self):
        cdp, fetcher, watch = await self.watch()
        cdp.emit("Network.requestWillBeSent",
                 {"requestId": "9", "request": {"url": self.URL}})
        cdp.emit("Network.loadingFailed", {"requestId": "10",
                                           "errorText": "unrelated"})
        self.assertFalse(watch.fut.done())

    async def test_detach_leaves_no_handler_behind(self):
        cdp, fetcher, watch = await self.watch()
        watch.detach(watch.handles)
        for name in cdp.hooks:
            self.assertEqual(cdp.hooks[name], [],
                              f"{name} would keep firing for a finished scan")
        self.assertEqual(len(cdp.off), 4)


class TestFetcherGuards(unittest.IsolatedAsyncioTestCase):
    async def test_capture_needs_three_hooks(self):
        class Bare:
            async def send(self, *a, **kw):
                return {}

        store, fetcher = _fetcher(Bare())
        store.cdp = Bare()
        self.assertEqual(
            await fetcher._fetch_via_network("https://x/a.png"),
            {"ok": False, "error": "CDP network capture unavailable"})

    async def test_the_cache_toggle_swallows_its_own_failure(self):
        cdp = EmittingCdp(fail_send=True)
        store, fetcher = _fetcher(cdp)
        # a DevTools method that refuses must not turn the capture into an
        # error: the toggle is a hint, both ways
        await fetcher._cache_disabled(cdp, True)
        await fetcher._cache_disabled(cdp, False)
        self.assertEqual([p["cacheDisabled"] for _, p in cdp.sent],
                         [True, False])


class TestDownloadChain(unittest.IsolatedAsyncioTestCase):
    """`_download` may only report reasons that mean something."""

    async def test_the_later_tiers_are_skipped_once_one_works(self):
        store, fetcher = _fetcher(EmittingCdp())
        seen = []

        async def page(url):
            seen.append("page")
            return {"ok": True, "b64": "AA==", "mime": "image/png"}

        async def python(url):
            seen.append("python")
            return {"ok": False, "error": "no"}

        async def network(url):
            seen.append("network")
            return {"ok": False, "error": "no"}

        fetcher._fetch_in_page, fetcher._fetch_via_python = page, python
        fetcher._fetch_via_network = network
        payload, errors = await fetcher._download("https://x/a.png")
        self.assertTrue(payload["ok"])
        self.assertEqual(seen, ["page"], "a working page fetch is the cheapest "
                                        "answer — never download twice")
        self.assertEqual(errors, [])

    async def test_the_noise_is_dropped_when_a_real_reason_exists(self):
        store, fetcher = _fetcher(EmittingCdp())

        async def page(url):
            return {"ok": False, "error": "no downloadable media"}

        async def python(url):
            return {"ok": False, "error": "HTTP 403"}

        async def network(url):
            return {"ok": False, "error": "network capture timed out"}

        fetcher._fetch_in_page, fetcher._fetch_via_python = page, python
        fetcher._fetch_via_network = network
        payload, errors = await fetcher._download("https://x/a.png")
        self.assertFalse(payload["ok"])
        self.assertEqual(errors, ["HTTP 403", "network capture timed out"],
                         "`no downloadable media` is what the page says when "
                         "it simply had none; it must not hide the 403")

    async def test_only_noise_still_reports_something(self):
        store, fetcher = _fetcher(EmittingCdp())

        async def nope(url):
            return {"ok": False, "error": "no downloadable media"}

        fetcher._fetch_in_page = fetcher._fetch_via_python = nope
        fetcher._fetch_via_network = nope
        _payload, errors = await fetcher._download("https://x/a.png")
        self.assertEqual(errors, ["no downloadable media"],
                         "the report may never be an empty string")


if __name__ == "__main__":
    unittest.main()
