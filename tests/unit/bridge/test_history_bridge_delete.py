"""HistoryBridge delete/media/settings paths: behaviour locked BEFORE the
Round H split (step H-B1).

The root suite (tests/test_history_bridge.py) reaches the archive through
the full router and only samples a few of the delete outcomes; this file
drives `HistoryBridge` directly with a stubbed `BridgeContext` so the
orchestration is pinned exactly:

* the undo tickets pushed to the undo timeline (shape + when they are
  skipped),
* the `people` before/after snapshots carried by a person-deletion ticket,
* the bus announcements (LogMessage / PeopleChanged) and the
  `userdb_changed` payloads the UI reacts to,
* every refusal: empty nick, bad message id, missing archive,
* the media + clipboard slots (folder, open, copy) and the settings slots,
* the `_people_snapshot` memory path.

It also contains the first test that FAILS on the pre-fix code: the hard
delete of an existing person. `HistoryBridge.history_delete_person` calls
`self.ctx.label_store.forget(...)` — without the call parentheses that
every other bridge uses — so the bound method has no `forget`, and the
AttributeError kills the rest of the work coroutine: the person is erased
in the database, but the UI never receives the `userdb_changed`
announcement and instead gets a stray `history_error`.

Run with:  python3 tests/unit/bridge/test_history_bridge_delete.py
"""

import asyncio
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))))

from core.events import LogMessage, PeopleChanged  # noqa: E402
from bridge.context import BridgeContext  # noqa: E402
from bridge import history_bridge_delete as delete_part  # noqa: E402
from bridge.history_bridge import HistoryBridge  # noqa: E402
from backend.config_manager import ConfigManager  # noqa: E402

PERSON_ROW = {
    "nick": "Nick", "gender": "m", "registered": "2024-01-01",
    "anonymous": False, "guest": False, "first_seen": "2024-01-01",
    "last_seen": "2024-06-01", "messaged": True, "message_count": 3,
    "last_messaged": "2024-06-01", "notes": "",
}


class StubRepo:
    """Records every call; each method answers from `answers` (an Exception
    instance raises, a callable is applied, anything else is returned)."""

    def __init__(self, answers=None):
        self.calls = []
        self.answers = dict(answers or {})
        self._token_seq = 0

    def new_op_token(self):
        self.calls.append(("new_op_token", (), {}))
        self._token_seq += 1
        return f"tok-{self._token_seq}"

    def _record(self, name, args, kw):
        self.calls.append((name, args, kw))
        ans = self.answers.get(name)
        if isinstance(ans, Exception):
            raise ans
        if callable(ans):
            return ans(*args, **kw)
        return ans

    async def delete_person(self, nick, hard=False, token=None):
        return self._record("delete_person", (nick,),
                            {"hard": hard, "token": token})

    async def soft_delete_history(self, nick, token=""):
        return self._record("soft_delete_history", (nick,), {"token": token})

    async def get_person(self, nick):
        return self._record("get_person", (nick,), {})

    async def reset_cursor(self, nick):
        return self._record("reset_cursor", (nick,), {})

    async def soft_delete_message(self, nick, message_id, token=""):
        return self._record("soft_delete_message", (nick, message_id),
                            {"token": token})

    async def purge_deleted(self, nick=""):
        return self._record("purge_deleted", (nick,), {})

    async def restore_person(self, nick, token=""):
        return self._record("restore_person", (nick,), {"token": token})

    async def merge_persons(self, from_nick, into_nick):
        return self._record("merge_persons", (from_nick, into_nick), {})


class StubMedia:
    def __init__(self):
        self.folders = {}
        self.folder_exc = None
        self.clipboard_payloads = {}

    def folder_for(self, nick):
        if self.folder_exc is not None:
            raise self.folder_exc
        return self.folders.get(nick, "")

    async def clipboard_payload(self, ref):
        return self.clipboard_payloads.get(str(ref), {"ok": False})


class _ParserStub:
    def __init__(self, owner):
        self._owner = owner

    async def state(self):
        return self._owner.parser_state


class StubArchive:
    def __init__(self, repo):
        self.repo = repo
        self.db = None                # no world to wait for
        self.media = StubMedia()
        self.applied = []
        self.parser_state = {"me": "Me", "partner": "Nick"}
        self.parser = _ParserStub(self)

    def apply_settings(self, patch):
        self.applied.append(patch)

    def settings(self):
        return {"preview": {"page_size": 50}}

    def preview_settings(self):
        return {"page_size": 50}


class StubMemory:
    def __init__(self, rows=None, exc=None):
        self.rows = [dict(r) for r in (rows or [])]
        self.deleted = []
        self.exc = exc

    async def get_all(self):
        if self.exc is not None:
            raise self.exc
        return [dict(r) for r in self.rows]

    async def delete_user(self, nick):
        self.deleted.append(nick)
        self.rows = [r for r in self.rows if r.get("nick") != nick]


class StubPeople:
    def __init__(self, memory, labels_map=None, exc=None):
        self.memory = memory
        self.labels_map = dict(labels_map or {})
        self.exc = exc
        self.label_calls = []

    def attach(self, deps=None):
        pass    # BridgeContext._crosswire wires the real services this way

    async def rows(self):
        if self.exc is not None:
            raise self.exc
        return await self.memory.get_all()

    def labels_for_nicks(self, nicks):
        nicks = list(nicks)
        self.label_calls.append(nicks)
        return {n: self.labels_map.get(n, []) for n in nicks}


class StubUndo:
    def __init__(self):
        self.pushed = []

    def attach(self, deps=None):
        pass

    def push(self, section, entry):
        self.pushed.append((section, json.loads(json.dumps(entry))))


class StubLabels:
    def __init__(self):
        self.forgotten = []

    def forget(self, nick):
        self.forgotten.append(nick)


class BridgeCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.cfg = ConfigManager(os.path.join(self.dir, "config.json"))
        self.repo = StubRepo()
        self.archive = StubArchive(self.repo)
        self.memory = StubMemory([PERSON_ROW])
        self.people = StubPeople(self.memory, labels_map={"Nick": ["vip"]})
        self.undo = StubUndo()
        self.labels = StubLabels()
        self.ctx = BridgeContext(config=self.cfg)
        self.ctx.archive = self.archive
        self.ctx.memory = self.memory
        self.ctx._people_svc = self.people
        self.ctx._undo_svc = self.undo
        self.ctx.labels = self.labels
        self.bridge = HistoryBridge(self.ctx)
        self.log_messages, self.people_changed, self.userdb_changed = [], [], []
        self.ctx.bus.subscribe(LogMessage,
                               lambda e: self.log_messages.append(e))
        self.ctx.bus.subscribe(PeopleChanged,
                               lambda e: self.people_changed.append(e))
        self.bridge.userdb_changed.connect(self.userdb_changed.append)
        self.errors = []
        self.bridge.history_error.connect(
            lambda scope, msg: self.errors.append((scope, msg)))

    async def wait_for(self, box, turns=200):
        """Yield until `box` fills. The bridge schedules its work on the
        running loop, so this waits a bounded number of *yield points* rather
        than guessing how long the machine needs (I-1.3: `asyncio.sleep(0)` is
        a synchronisation primitive, `asyncio.sleep(0.0N)` is not)."""
        for _ in range(turns):
            if box:
                break
            await asyncio.sleep(0)
        self.assertTrue(box, "the bridge never answered")
        return box

    async def settle(self, turns=50) -> None:
        """Let anything already scheduled run — for the tests that assert a
        slot did NOT schedule work. Same yield point, no guesswork."""
        for _ in range(turns):
            await asyncio.sleep(0)

    def changed(self):
        return [json.loads(p) for p in self.userdb_changed]


class TestDeletePerson(BridgeCase):
    async def test_soft_delete_pushes_an_undo_ticket_with_the_snapshots(self):
        self.repo.answers["delete_person"] = True
        self.assertTrue(self.bridge.history_delete_person("Nick", False))
        await self.wait_for(self.undo.pushed)
        section, entry = self.undo.pushed[-1]
        self.assertEqual(section, "archive")
        self.assertEqual(entry["op"], "delete_person")
        self.assertEqual(entry["nick"], "Nick")
        self.assertTrue(entry["token"].startswith("tok-"))
        # the ticket carries the people table before and after, so an undo
        # can restore the person row as it was
        self.assertEqual([r["nick"] for r in entry["people"]["before"]],
                         ["Nick"])
        self.assertEqual(entry["people"]["after"], [])
        # and the memory row is removed with the archive row
        await self.wait_for(self.memory.deleted)
        self.assertEqual(self.memory.deleted, ["Nick"])
        self.assertEqual(self.changed()[-1],
                         {"action": "deleted", "nick": "Nick",
                          "hard": False, "ok": True})
        self.assertTrue(any("🗑" in e.message for e in self.log_messages))
        self.assertEqual(self.people_changed[0].reason, "archive")
        self.assertEqual(self.errors, [])

    async def test_soft_delete_of_a_missing_person_reports_failure(self):
        self.repo.answers["delete_person"] = False
        self.assertTrue(self.bridge.history_delete_person("Ghost", False))
        await self.wait_for(self.userdb_changed)
        self.assertEqual(self.changed()[-1]["ok"], False)
        self.assertEqual(self.undo.pushed, [])
        # the memory row is dropped when the people table was readable —
        # even when the archive says the person was never there
        self.assertEqual(self.memory.deleted, ["Ghost"])

    async def test_hard_delete_erases_forgets_labels_and_announces(self):
        self.repo.answers["delete_person"] = True
        self.assertTrue(self.bridge.history_delete_person("Nick", True))
        await self.wait_for(self.userdb_changed)
        call = self.repo.calls[-1]
        self.assertEqual(call, ("delete_person", ("Nick",),
                                {"hard": True, "token": "tok-1"}))
        # the label store must forget the person — this is the call that
        # crashed on the pre-fix code (missing parentheses)
        await self.wait_for(self.labels.forgotten)
        self.assertEqual(self.labels.forgotten, ["Nick"])
        self.assertEqual(self.changed()[-1],
                         {"action": "deleted", "nick": "Nick",
                          "hard": True, "ok": True})
        self.assertTrue(any("🔥" in e.message for e in self.log_messages))
        self.assertEqual(self.undo.pushed, [])      # hard is not undoable
        self.assertEqual(self.errors, [])

    async def test_empty_nick_is_refused_without_talking_to_the_archive(self):
        self.assertFalse(self.bridge.history_delete_person("   ", False))
        await self.settle()
        self.assertEqual(self.repo.calls, [])
        self.assertEqual(self.errors, [])

    async def test_missing_archive_is_an_error_not_a_crash(self):
        self.ctx.archive = None
        self.assertFalse(self.bridge.history_delete_person("Nick", False))
        self.assertEqual(self.errors,
                         [("history_delete_person",
                           "the message archive is not running")])


class TestClearPerson(BridgeCase):
    async def test_clearing_messages_pushes_an_undo_ticket(self):
        self.repo.answers["soft_delete_history"] = "tok-9"
        self.assertTrue(self.bridge.history_clear_person("Nick"))
        await self.wait_for(self.undo.pushed)
        self.assertEqual(self.undo.pushed[-1][1],
                         {"op": "clear_history", "nick": "Nick",
                          "token": "tok-9"})
        self.assertEqual(self.changed()[-1],
                         {"action": "cleared", "nick": "Nick", "ok": True})
        self.assertTrue(any("🧹" in e.message for e in self.log_messages))
        self.assertEqual(self.errors, [])

    async def test_clearing_a_person_with_no_messages_resets_the_cursor(self):
        self.repo.answers["soft_delete_history"] = ""     # nothing hidden
        self.repo.answers["get_person"] = PERSON_ROW
        self.assertTrue(self.bridge.history_clear_person("Nick"))
        await self.wait_for(self.userdb_changed)
        self.assertIn("reset_cursor", [c[0] for c in self.repo.calls])
        self.assertEqual(self.undo.pushed, [])
        self.assertEqual(self.changed()[-1]["ok"], False)
        self.assertTrue(any("ℹ" in e.message for e in self.log_messages))

    async def test_clearing_an_unknown_person_does_not_reset(self):
        self.repo.answers["soft_delete_history"] = ""
        self.repo.answers["get_person"] = None
        self.assertTrue(self.bridge.history_clear_person("Ghost"))
        await self.wait_for(self.userdb_changed)
        self.assertNotIn("reset_cursor", [c[0] for c in self.repo.calls])

    async def test_clear_refusals(self):
        self.assertFalse(self.bridge.history_clear_person("  "))
        self.ctx.archive = None
        self.assertFalse(self.bridge.history_clear_person("Nick"))
        self.assertEqual(self.errors,
                         [("history_clear_person",
                           "the message archive is not running")])


class TestDeleteMessage(BridgeCase):
    async def test_deleting_one_message_pushes_an_undo_ticket(self):
        self.repo.answers["soft_delete_message"] = "tok-5"
        self.assertTrue(self.bridge.history_delete_message("Nick", 42))
        await self.wait_for(self.undo.pushed)
        self.assertEqual(self.undo.pushed[-1][1],
                         {"op": "delete_message", "nick": "Nick",
                          "token": "tok-5", "message_id": 42})
        self.assertEqual(self.repo.calls[-1],
                         ("soft_delete_message", ("Nick", 42), {"token": ""}))
        self.assertEqual(self.changed()[-1],
                         {"action": "message_deleted", "nick": "Nick",
                          "id": 42})
        self.assertEqual(self.errors, [])

    async def test_a_message_that_is_already_gone_says_so(self):
        self.repo.answers["soft_delete_message"] = ""
        self.assertTrue(self.bridge.history_delete_message("Nick", "42"))
        await self.wait_for(self.log_messages)
        self.assertTrue(any("⚠" in e.message for e in self.log_messages))
        self.assertEqual(self.undo.pushed, [])
        self.assertEqual(self.changed(), [])

    async def test_invalid_ids_are_refused_before_the_archive(self):
        self.assertFalse(self.bridge.history_delete_message("Nick", ""))
        self.assertFalse(self.bridge.history_delete_message("Nick", "junk"))
        self.assertFalse(self.bridge.history_delete_message("Nick", "0"))
        self.ctx.archive = None
        self.assertFalse(self.bridge.history_delete_message("Nick", 42))
        self.assertEqual(self.errors,
                         [("history_delete_message",
                           "the message archive is not running")])


class TestPurgeRestoreMerge(BridgeCase):
    async def test_purge_reports_the_erased_count(self):
        self.repo.answers["purge_deleted"] = 7
        self.assertTrue(self.bridge.history_purge_deleted("Nick"))
        await self.wait_for(self.userdb_changed)
        self.assertEqual(self.repo.calls[-1],
                         ("purge_deleted", ("Nick",), {}))
        self.assertEqual(self.changed()[-1],
                         {"action": "purged", "nick": "Nick", "count": 7})
        self.assertTrue(any("🔥" in e.message for e in self.log_messages))

    async def test_restore_announces_the_outcome_and_refreshes_people(self):
        self.repo.answers["restore_person"] = True
        self.assertTrue(self.bridge.history_restore_person("Nick"))
        await self.wait_for(self.userdb_changed)
        self.assertEqual(self.changed()[-1],
                         {"action": "restored", "nick": "Nick", "ok": True})
        self.assertEqual(self.people_changed[0].reason, "archive")

    async def test_merge_reports_the_rows_moved(self):
        self.repo.answers["merge_persons"] = 12
        self.assertTrue(self.bridge.history_merge("Old", "Nick"))
        await self.wait_for(self.userdb_changed)
        self.assertEqual(self.changed()[-1],
                         {"action": "merged", "nick": "Nick",
                          "from": "Old", "moved": 12})

    async def test_missing_archive_refuses_all_three(self):
        self.ctx.archive = None
        self.assertFalse(self.bridge.history_purge_deleted("Nick"))
        self.assertFalse(self.bridge.history_restore_person("Nick"))
        self.assertFalse(self.bridge.history_merge("Old", "Nick"))
        self.assertEqual(self.errors, [])   # refusals, not errors


class TestMediaAndClipboard(BridgeCase):
    async def test_media_folder_reads_the_archive(self):
        self.archive.media.folders["Nick"] = "/tmp/nick"
        self.assertEqual(self.bridge.media_folder("Nick"), "/tmp/nick")
        self.assertEqual(self.bridge.media_folder("Ghost"), "")
        self.archive.media.folder_exc = OSError("denied")
        self.assertEqual(self.bridge.media_folder("Nick"), "")
        self.ctx.archive = None
        self.assertEqual(self.bridge.media_folder("Nick"), "")

    async def test_open_media_folder_creates_and_reports(self):
        folder = os.path.join(self.dir, "media", "Nick")
        self.archive.media.folders["Nick"] = folder
        ok = self.bridge.open_media_folder("Nick")
        await self.wait_for(self.log_messages)
        self.assertIsInstance(ok, bool)
        self.assertTrue(os.path.isdir(folder))      # makedirs ran
        self.assertTrue(any(folder in e.message for e in self.log_messages))

    async def test_open_media_folder_without_a_folder_is_false(self):
        self.assertFalse(self.bridge.open_media_folder("Ghost"))
        await self.settle()
        self.assertEqual(self.log_messages, [])

    async def test_copy_media_reports_the_result_on_the_signal(self):
        self.archive.media.clipboard_payloads["12"] = {"ok": True,
                                                       "text": "hello"}
        box = []
        self.bridge.media_ready.connect(lambda *a: box.append(a))
        self.bridge.copy_media("12")
        await self.wait_for(box)
        data = json.loads(box[-1][1])
        self.assertEqual(box[-1][0], "12")
        self.assertEqual(data["ok"], True)
        self.assertIn("copied", data)      # False when no Qt app is running

    async def test_copy_text_returns_a_bool_and_never_raises(self):
        self.assertIsInstance(self.bridge.copy_text("hello"), bool)
        self.assertIsInstance(self.bridge.copy_text(None), bool)

    async def test_copy_media_without_archive_is_silently_skipped(self):
        self.ctx.archive = None
        self.bridge.copy_media("12")
        await self.settle()
        self.assertEqual(self.errors, [])


class FakeClipboard:
    def __init__(self):
        self.text = ""
        self.mime = None

    def setText(self, t):
        self.text = t

    def setMimeData(self, m):
        self.mime = m

    def text(self):
        return self.text


def tiny_png(path):
    """A real 1x1 PNG, built in-test, so QImage decodes it (not isNull)."""
    import struct
    import zlib

    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data +
                struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) +
           chunk(b"IDAT", zlib.compress(b"\x00\xff\x00\x00")) +
           chunk(b"IEND", b""))
    with open(path, "wb") as f:
        f.write(png)


class TestClipboardMechanics(BridgeCase):
    """The clipboard helpers with the app boundary faked: the part's
    `qt_clipboard` is patched (the repo's other tests never create a real
    QGuiApplication — a process-wide one would leak into the whole suite)."""

    def setUp(self):
        super().setUp()
        import bridge.history_bridge_media as media_part
        self.media_part = media_part
        self.clip = FakeClipboard()
        self._real = media_part.qt_clipboard
        media_part.qt_clipboard = lambda: self.clip

    def tearDown(self):
        self.media_part.qt_clipboard = self._real
        super().tearDown()

    async def test_copy_media_with_text_announces_and_marks_copied(self):
        self.archive.media.clipboard_payloads["3"] = {"ok": True,
                                                      "text": "hi"}
        box = []
        self.bridge.media_ready.connect(lambda *a: box.append(a))
        self.bridge.copy_media("3")
        await self.wait_for(box)
        data = json.loads(box[-1][1])
        self.assertTrue(data["copied"])
        self.assertEqual(self.clip.text, "hi")
        self.assertTrue(any("📋 Copied" in e.message
                            for e in self.log_messages))

    async def test_copy_media_payload_failure_still_answers(self):
        self.archive.media.clipboard_payloads["4"] = {"ok": False}
        box = []
        self.bridge.media_ready.connect(lambda *a: box.append(a))
        self.bridge.copy_media("4")
        await self.wait_for(box)
        data = json.loads(box[-1][1])
        self.assertFalse(data["ok"])
        self.assertNotIn("copied", data)
        self.assertEqual(self.clip.text, "")

    async def test_copy_media_with_a_real_image_carries_the_file(self):
        path = os.path.join(self.dir, "pic.png")
        tiny_png(path)
        self.archive.media.clipboard_payloads["5"] = {
            "ok": True, "path": path, "mode": "image"}
        self.assertTrue(self.media_part.to_clipboard(
            self.bridge, {"path": path, "mode": "image"}))
        self.assertIsNotNone(self.clip.mime)      # URL + pixels + text

    async def test_copy_media_with_a_missing_path_copies_the_path_text(self):
        payload = {"path": os.path.join(self.dir, "gone.png")}
        self.assertTrue(self.media_part.to_clipboard(self.bridge, payload))
        self.assertEqual(self.clip.text, payload["path"])

    async def test_a_broken_clipboard_is_a_false_not_an_exception(self):
        def boom():
            raise OSError("no display")
        self.media_part.qt_clipboard = boom
        self.assertFalse(self.media_part.to_clipboard(
            self.bridge, {"text": "x"}))

    def test_open_folder_reports_a_qt_failure(self):
        from PySide6.QtGui import QDesktopServices
        folder = os.path.join(self.dir, "m")
        self.archive.media.folders["Nick"] = folder
        real = QDesktopServices.openUrl

        def no_handler(*_a):
            raise OSError("no file manager")

        QDesktopServices.openUrl = staticmethod(no_handler)
        try:
            ok = self.bridge.open_media_folder("Nick")
        finally:
            QDesktopServices.openUrl = real
        self.assertFalse(ok)
        self.assertTrue(any("⚠ Cannot open" in e.message
                            for e in self.log_messages))


class TestSettingsAndDetection(BridgeCase):
    def test_get_settings_prefers_the_live_archive(self):
        got = json.loads(self.bridge.get_history_settings())
        self.assertEqual(got["preview"]["page_size"], 50)

    def test_get_settings_without_archive_falls_back_to_config(self):
        self.ctx.archive = None
        got = json.loads(self.bridge.get_history_settings())
        self.assertIsInstance(got, dict)

    def test_save_settings_without_archive_writes_the_config(self):
        self.ctx.archive = None
        self.bridge.save_history_settings(
            json.dumps({"preview": {"preload_rows": 25}}))
        reopened = ConfigManager(self.cfg._path)
        self.assertEqual(reopened.get("history", "preview", "preload_rows"),
                         25)

    def test_save_settings_with_archive_applies_and_announces(self):
        patch = json.dumps({"preview": {"show_images": False}})
        self.bridge.save_history_settings(patch)
        self.assertEqual(self.archive.applied,
                         [{"preview": {"show_images": False}}])
        self.assertTrue(any("💾" in e.message for e in self.log_messages))

    async def test_detect_my_nick_reports_both_identities(self):
        box = []
        self.bridge.history_stats_ready.connect(lambda *a: box.append(a))
        self.bridge.detect_my_nick("d1")
        await self.wait_for(box)
        self.assertEqual(box[-1][0], "d1")
        data = json.loads(box[-1][1])
        self.assertEqual(data["detected"], "Me")
        self.assertEqual(data["partner"], "Nick")


class TestPeopleSnapshot(BridgeCase):
    """The people snapshot the deletion ticket carries lives in the delete
    part (it is the part's, not the wire's, concern)."""

    async def test_snapshot_comes_from_the_memory_rows(self):
        snap = await delete_part.people_snapshot(self.bridge)
        self.assertEqual([r["nick"] for r in snap], ["Nick"])

    async def test_snapshot_without_memory_is_none(self):
        self.ctx.memory = None
        self.assertIsNone(await delete_part.people_snapshot(self.bridge))

    async def test_snapshot_survives_a_broken_people_service(self):
        self.people.exc = OSError("locked")
        self.assertIsNone(await delete_part.people_snapshot(self.bridge))


if __name__ == "__main__":
    unittest.main(verbosity=2)
