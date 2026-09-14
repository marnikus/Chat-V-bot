"""bridge/history_media — the media-cache and clipboard slots.

Round H (H1) split these seven slots out of `history_bridge`, and Round I
measured the result at **37.6%** line coverage — the second-worst file in the
tree. The wire contract test proves the slots are still REGISTERED with Qt;
nothing proved they still WORK.

The gap mattered most for the clipboard path, which is the one place in the
app that silently degrades: with no QGuiApplication (a headless run, a
crashed UI) every copy must return False rather than raise, and the code says
so in three separate `except` arms that no test had ever entered.

`_to_clipboard` is a staticmethod and the two module helpers are free
functions, so they are exercised directly — no QObject, no archive, no
QWebChannel. The slots that need a bridge use a minimal stub context, because
what is being tested is the slot's DECISION (is there an archive? was the
folder empty?), not the async plumbing `history_bridge` already owns.
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
import unittest

import bridge.history_media as hm
from bridge.history_media import HistoryMediaMixin


class FakeClipboard:
    def __init__(self):
        self.text = None
        self.mime = None

    def setText(self, value):
        self.text = value

    def setMimeData(self, mime):
        self.mime = mime


class ClipboardCase(unittest.TestCase):
    """Swaps the module's clipboard accessor; always restored."""

    def setUp(self):
        self.clip = FakeClipboard()
        self._orig = hm._qt_clipboard
        hm._qt_clipboard = lambda: self.clip

    def tearDown(self):
        hm._qt_clipboard = self._orig


class TestCopyingText(ClipboardCase):
    def test_plain_text_lands_on_the_clipboard(self):
        self.assertTrue(HistoryMediaMixin._to_clipboard(
            {"mode": "text", "text": "hello"}))
        self.assertEqual(self.clip.text, "hello")

    def test_missing_text_copies_an_empty_string_rather_than_none(self):
        self.assertTrue(HistoryMediaMixin._to_clipboard({"mode": "text"}))
        self.assertEqual(self.clip.text, "",
                         "None would be pasted as the literal text 'None'")

    def test_a_path_that_does_not_exist_is_copied_as_text(self):
        """A stale cache entry still gives the user something to paste."""
        self.assertTrue(HistoryMediaMixin._to_clipboard(
            {"mode": "image", "path": "/no/such/file.png"}))
        self.assertEqual(self.clip.text, "/no/such/file.png")
        self.assertIsNone(self.clip.mime, "a missing file must not be carried")


class TestCopyingARealFile(ClipboardCase):
    def setUp(self):
        super().setUp()
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.path = os.path.join(self.dir.name, "shot.png")
        with open(self.path, "wb") as fh:
            fh.write(b"not really a png")

    def test_an_existing_file_is_carried_as_mime_data(self):
        self.assertTrue(HistoryMediaMixin._to_clipboard(
            {"mode": "file", "path": self.path}))
        self.assertIsNotNone(self.clip.mime)
        self.assertEqual(self.clip.mime.text(), self.path)
        self.assertTrue(self.clip.mime.hasUrls())

    def test_an_undecodable_image_still_copies_the_file_and_path(self):
        """QImage returns null for junk; that must not lose the copy."""
        self.assertTrue(HistoryMediaMixin._to_clipboard(
            {"mode": "image", "path": self.path}))
        self.assertTrue(self.clip.mime.hasUrls())
        self.assertFalse(self.clip.mime.hasImage(),
                         "junk bytes should not have produced pixels")


class TestTheClipboardCanBeAbsent(unittest.TestCase):
    def test_no_qt_application_means_false_not_an_exception(self):
        orig = hm._qt_clipboard
        hm._qt_clipboard = lambda: None
        try:
            self.assertFalse(HistoryMediaMixin._to_clipboard({"text": "x"}))
        finally:
            hm._qt_clipboard = orig

    def test_a_raising_clipboard_is_swallowed_and_reported_false(self):
        orig = hm._qt_clipboard

        def boom():
            raise RuntimeError("no display")

        hm._qt_clipboard = boom
        try:
            self.assertFalse(HistoryMediaMixin._to_clipboard({"text": "x"}))
        finally:
            hm._qt_clipboard = orig


# ── the slots that only decide ────────────────────────────────────────


class _Ctx:
    def __init__(self, archive=None):
        self.archive = archive
        self.emitted = []
        self.bus = self

    def emit(self, event):
        self.emitted.append(event)


class _Media:
    def __init__(self, folder="", raises=None):
        self._folder = folder
        self._raises = raises

    def folder_for(self, nick):
        if self._raises:
            raise self._raises
        return os.path.join(self._folder, nick) if nick else self._folder


class _Archive:
    def __init__(self, media):
        self.media = media


class _Bridge(HistoryMediaMixin):
    """The mixin on a plain object: these slots need nothing from QObject."""

    def __init__(self, ctx):
        self.ctx = ctx


class TestMediaFolder(unittest.TestCase):
    def test_no_archive_yields_an_empty_string(self):
        self.assertEqual(_Bridge(_Ctx(None)).media_folder("ann"), "")

    def test_the_folder_is_per_person(self):
        bridge = _Bridge(_Ctx(_Archive(_Media("/cache"))))
        self.assertEqual(bridge.media_folder("ann"),
                         os.path.join("/cache", "ann"))

    def test_a_raising_store_degrades_to_empty_not_an_error(self):
        bridge = _Bridge(_Ctx(_Archive(_Media(raises=OSError("gone")))))
        self.assertEqual(bridge.media_folder("ann"), "")


class TestOpenMediaFolder(unittest.TestCase):
    def test_an_empty_folder_is_refused_before_touching_the_desktop(self):
        bridge = _Bridge(_Ctx(None))
        self.assertFalse(bridge.open_media_folder("ann"))
        self.assertEqual(bridge.ctx.emitted, [],
                         "nothing to open is not worth a log line")

    def test_a_failure_to_open_is_reported_to_the_user(self):
        """The user asked for a window; silence would be the wrong answer."""
        ctx = _Ctx(_Archive(_Media(raises=None, folder="\0bad")))
        bridge = _Bridge(ctx)
        self.assertFalse(bridge.open_media_folder("ann"))
        self.assertTrue(ctx.emitted, "a failed open must say why")
        self.assertEqual(ctx.emitted[-1].level, "warn")


class TestCopyText(ClipboardCase):
    def test_copy_text_is_the_clipboard_path_and_returns_a_bool(self):
        bridge = _Bridge(_Ctx(None))
        self.assertTrue(bridge.copy_text("selected words"))
        self.assertEqual(self.clip.text, "selected words")

    def test_copy_text_coerces_none(self):
        bridge = _Bridge(_Ctx(None))
        self.assertTrue(bridge.copy_text(None))
        self.assertEqual(self.clip.text, "")


class TestCopyMediaNeedsAnArchive(unittest.TestCase):
    def test_copy_media_without_an_archive_does_nothing_and_does_not_raise(self):
        bridge = _Bridge(_Ctx(None))
        self.assertIsNone(bridge.copy_media("ref-1"))


# ── the async slot bodies ─────────────────────────────────────────────
#
# The three request slots defer their work into an `async def work()` closure
# that `_run_async` schedules. That closure holds the actual behaviour — the
# reply shape, the clipboard hand-off, the success log — so a test that only
# calls the slot proves nothing. `_run_async` is captured here and the
# coroutine run directly, which is what the real event loop ends up doing.


class _AsyncMedia:
    def __init__(self, payload):
        self.payload = payload
        self.seen = []

    async def path_for(self, ref):
        self.seen.append(("path_for", ref))
        return dict(self.payload)

    async def download_one(self, ref):
        self.seen.append(("download_one", ref))
        return dict(self.payload)

    async def clipboard_payload(self, ref):
        self.seen.append(("clipboard_payload", ref))
        return dict(self.payload)


class _Signal:
    def __init__(self):
        self.emissions = []

    def emit(self, *args):
        self.emissions.append(args)


class _AsyncBridge(HistoryMediaMixin):
    """Captures the scheduled coroutine instead of needing a Qt event loop."""

    def __init__(self, ctx):
        self.ctx = ctx
        self.media_ready = _Signal()
        self.history_error = _Signal()
        self.scheduled = []

    def _run_async(self, scope, coro):
        self.scheduled.append((scope, coro))

    def _need_archive(self, scope, req_id=""):
        if self.ctx.archive is None:
            self.history_error.emit(scope, "the message archive is not running")
            return False
        return True

    def _reply(self, signal, req_id, payload, **extra):
        payload["req_id"] = req_id
        payload.update(extra)
        signal.emit(req_id, json.dumps(payload, ensure_ascii=False))

    def drain(self):
        """Run the one scheduled coroutine to completion."""
        self.assertion_scope, coro = self.scheduled.pop()
        asyncio.run(coro)


class AsyncSlotCase(unittest.TestCase):
    def make(self, payload):
        self.media = _AsyncMedia(payload)
        bridge = _AsyncBridge(_Ctx(_Archive(self.media)))
        return bridge

    def last_reply(self, bridge):
        req_id, body = bridge.media_ready.emissions[-1]
        return req_id, json.loads(body)


class TestMediaPathAndRestore(AsyncSlotCase):
    def test_media_path_answers_on_the_media_ready_signal(self):
        bridge = self.make({"ok": True, "path": "/cache/a.png"})
        bridge.media_path("req-7", "ref-1")
        bridge.drain()
        req_id, body = self.last_reply(bridge)
        self.assertEqual(req_id, "req-7")
        self.assertEqual(body["req_id"], "req-7",
                         "the id must be INSIDE the body: the UI correlates "
                         "replies by reading it")
        self.assertEqual(body["id"], "ref-1")
        self.assertEqual(body["path"], "/cache/a.png")

    def test_media_restore_downloads_rather_than_reading_the_cache(self):
        bridge = self.make({"ok": True})
        bridge.media_restore("req-8", "ref-2")
        bridge.drain()
        self.assertEqual(self.media.seen, [("download_one", "ref-2")])
        self.assertEqual(self.last_reply(bridge)[0], "req-8")

    def test_both_slots_refuse_without_an_archive(self):
        for name in ("media_path", "media_restore"):
            bridge = _AsyncBridge(_Ctx(None))
            getattr(bridge, name)("req-9", "ref")
            self.assertEqual(bridge.scheduled, [],
                             f"{name} scheduled work with no archive")
            self.assertEqual(bridge.history_error.emissions[-1][0], name)


class TestCopyMediaBody(AsyncSlotCase, ClipboardCase):
    def setUp(self):
        ClipboardCase.setUp(self)

    def test_a_successful_payload_reaches_the_clipboard_and_is_logged(self):
        bridge = self.make({"ok": True, "path": "/cache/a.png",
                            "mode": "text"})
        bridge.copy_media("ref-3")
        bridge.drain()
        _req, body = self.last_reply(bridge)
        self.assertTrue(body["copied"])
        self.assertEqual(bridge.ctx.emitted[-1].level, "success")
        self.assertIn("/cache/a.png", bridge.ctx.emitted[-1].message)

    def test_a_failed_payload_is_still_answered_but_not_copied(self):
        """The UI is waiting on media_ready; a failure must not hang it."""
        bridge = self.make({"ok": False, "error": "no such media"})
        bridge.copy_media("ref-4")
        bridge.drain()
        _req, body = self.last_reply(bridge)
        self.assertNotIn("copied", body)
        self.assertEqual(bridge.ctx.emitted, [],
                         "a failed copy must not claim success")

    def test_a_clipboard_refusal_is_reported_as_copied_false(self):
        hm._qt_clipboard = lambda: None
        bridge = self.make({"ok": True, "text": "hi"})
        bridge.copy_media("ref-5")
        bridge.drain()
        _req, body = self.last_reply(bridge)
        self.assertFalse(body["copied"])
        self.assertEqual(bridge.ctx.emitted, [])


if __name__ == "__main__":
    unittest.main()
