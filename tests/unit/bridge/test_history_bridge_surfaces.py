"""bridge/history_bridge — the surfaces the archive window's other tests miss.

`tests/test_history_bridge.py` pins the request/response reads, the Full User
Database and the media restore; `tests/test_archive_delete_undo.py` pins the
three reversible deletions. What was left unpinned is exactly what a split of
`HistoryBridge` could silently drop (god-class round, step 6 —
`docs/archive/2026-09-13-god-classes/STEP6_BRIDGE_FACADES_DESIGN_2026-09-13.md`):

  * the **no-archive guard** — every slot must refuse loudly (`history_error`,
    the message the UI shows) and answer nothing, never raise (RULE 4: empty
    is not broken);
  * the **refusals before the archive** — a blank nick or a non-positive
    message id returns False without an undo step and without a log line;
  * `history_purge_deleted`, `history_merge`, `open_media_folder`,
    `copy_media`, `detect_my_nick` — five slots no test called at all;
  * the **settings fallback** — with no archive the two settings slots read
    and write the config file instead of the service;
  * `_json_arg` — bad JSON and non-dict JSON fall back to the defaults, a
    dict argument is used as it is.

Per RULE 8 everything here drives the REAL `HistoryService`, the REAL repo and
the REAL `Bridge` (router + domain bridge) over a real SQLite file; the only
fakes are the page (`tests/test_chat_parser_delta.FakePage`, the shared
harness) and Qt's desktop-open call, which is the operating system's seam.

Run:  python -m pytest tests/unit/bridge/test_history_bridge_surfaces.py
"""

import asyncio
import json
import os
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
for _path in (ROOT, os.path.join(ROOT, "tests")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from core.events import LogMessage                   # noqa: E402
from test_history_bridge import BridgeCase, wait_for  # noqa: E402

NO_ARCHIVE = "the message archive is not running"


async def settle(times=20, step=0.02):
    """Let the scheduled tasks behind one slot finish."""
    for _ in range(times):
        await asyncio.sleep(step)


class SurfaceCase(BridgeCase):
    """The shared harness plus the two things these surfaces are read by:
    the `userdb_changed` payloads and the log lines the bridge emits."""

    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.changed = []
        self.bridge.userdb_changed.connect(
            lambda p: self.changed.append(json.loads(p)))
        self.logs = []
        self.bridge._ctx.bus.subscribe(
            LogMessage, lambda e: self.logs.append((e.level, e.message)))
        self.answers = []
        for signal in (self.bridge.history_page_ready,
                       self.bridge.history_search_ready,
                       self.bridge.history_stats_ready,
                       self.bridge.userdb_page_ready,
                       self.bridge.media_ready):
            signal.connect(lambda *a: self.answers.append(a))

    def log_lines(self, needle):
        return [m for _lvl, m in self.logs if needle in m]

    async def changed_with(self, action):
        await wait_for([c for c in self.changed if c["action"] == action])
        return [c for c in self.changed if c["action"] == action][-1]


class NoArchiveCase(SurfaceCase):
    """The same bridge with the world detached — `ctx.archive is None`."""

    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.bridge._history = None       # write-through → ctx.archive
        self.answers.clear()
        self.errors.clear()


class TestNoArchiveGuard(NoArchiveCase):
    """A detached world is refused loudly; nothing is answered, nothing raises."""

    READ_SLOTS = (
        ("history_open", ("r1", "Nick", "{}")),
        ("history_page", ("r2", "Nick", "{}")),
        ("history_search", ("r3", "{}")),
        ("history_stats", ("r4", "Nick")),
        ("userdb_page", ("r5", "{}")),
        ("userdb_stats", ("r6",)),
        ("media_path", ("r7", "1")),
        ("media_restore", ("r8", "1")),
        ("detect_my_nick", ("r9",)),
    )

    async def test_every_read_slot_refuses_on_its_own_scope(self):
        for name, args in self.READ_SLOTS:
            getattr(self.bridge, name)(*args)
        await settle(5)
        self.assertEqual(sorted(scope for scope, _m in self.errors),
                         sorted(name for name, _a in self.READ_SLOTS))
        self.assertEqual({m for _s, m in self.errors}, {NO_ARCHIVE})
        self.assertEqual(self.answers, [], "a refused read must not answer")

    async def test_every_write_slot_returns_false(self):
        refusals = [
            self.bridge.history_delete_person("Nick", False),
            self.bridge.history_clear_person("Nick"),
            self.bridge.history_delete_message("Nick", "3"),
            self.bridge.history_purge_deleted("Nick"),
            self.bridge.history_restore_person("Nick"),
            self.bridge.history_merge("A", "B"),
            self.bridge.open_media_folder("Nick"),
        ]
        self.assertEqual(refusals, [False] * len(refusals))
        await settle(5)
        # the three reversible deletions say why; purge/restore/merge and the
        # folder open simply refuse (they have no req_id to answer on)
        self.assertEqual(sorted(scope for scope, _m in self.errors),
                         ["history_clear_person", "history_delete_message",
                          "history_delete_person"])
        self.assertEqual(self.answers, [])

    def test_media_folder_is_empty_and_copy_media_is_silent(self):
        self.assertEqual(self.bridge.media_folder("Nick"), "")

    async def test_copy_media_never_answers_without_a_world(self):
        self.assertIsNone(self.bridge.copy_media("1"))
        await settle(5)
        self.assertEqual(self.answers, [])

    def test_settings_fall_back_to_the_config_file(self):
        # no archive → the config's own history section, defaults included
        self.assertEqual(json.loads(self.bridge.get_history_settings())
                         ["preview"]["page_size"], 50)
        self.bridge.save_history_settings(json.dumps(
            {"preview": {"preload_rows": 7}}))
        reopened = type(self.cfg)(self.cfg._path)
        self.assertEqual(reopened.get("history", "preview", "preload_rows"), 7)
        # the fallback merges SHALLOW: the patched section replaces the stored
        # one key for key, so the untouched defaults of that section are gone
        self.assertEqual(reopened.get("history", "preview"),
                         {"preload_rows": 7})
        self.assertEqual(self.logs, [], "no archive → no 'saved' announcement")


class TestRefusalsBeforeTheArchive(SurfaceCase):
    """Bad arguments are refused before the archive is even looked at."""

    def test_a_blank_nick_is_refused_without_an_error_signal(self):
        self.assertFalse(self.bridge.history_delete_person("   ", False))
        self.assertFalse(self.bridge.history_clear_person("  "))
        self.assertEqual(self.errors, [])

    def test_a_message_id_must_be_a_positive_number(self):
        for bad in ("0", "-3", "abc", "", None):
            self.assertFalse(self.bridge.history_delete_message("Nick", bad),
                             f"id {bad!r} was accepted")
        self.assertFalse(self.bridge.history_delete_message("", "3"))
        self.assertEqual(self.errors, [])
        self.assertEqual(self.logs, [])


class TestMessageDeletionEdges(SurfaceCase):
    async def test_an_already_gone_message_warns_and_records_nothing(self):
        await self.seed("Nick", 3)
        before = self.bridge._get_global_history()[0]
        self.assertTrue(self.bridge.history_delete_message("Nick", "999999"))
        await settle()
        self.assertTrue(self.log_lines("already gone"), self.logs)
        self.assertEqual(self.changed, [], "nothing happened → no wire event")
        self.assertEqual(self.bridge._get_global_history()[0], before,
                         "a refusal must not grow the timeline")


class TestPersonOperations(SurfaceCase):
    async def test_purge_erases_the_hidden_rows_for_good(self):
        await self.seed("Nick", 3)
        page = json.loads((await self.ask(
            self.bridge.history_open, "r", "Nick", "{}",
            signal=self.bridge.history_page_ready))[1])
        victim = page["items"][0]["id"]
        self.bridge.history_delete_message("Nick", str(victim))
        await self.changed_with("message_deleted")
        self.assertEqual(await self.service.repo.deleted_count(), 1)

        self.assertTrue(self.bridge.history_purge_deleted("Nick"))
        event = await self.changed_with("purged")
        self.assertEqual(event["count"], 1)
        self.assertTrue(self.log_lines("erased permanently"), self.logs)
        self.assertEqual(await self.service.repo.deleted_count(), 0,
                         "the tombstone is gone with the row it hid")

    async def test_merge_moves_every_row_into_the_other_person(self):
        await self.seed("Nick", 3)
        await self.seed("Other", 2)
        self.assertTrue(self.bridge.history_merge("Other", "Nick"))
        event = await self.changed_with("merged")
        self.assertEqual((event["from"], event["nick"], event["moved"]),
                         ("Other", "Nick", 2))
        page = json.loads((await self.ask(
            self.bridge.history_open, "r", "Nick", "{}",
            signal=self.bridge.history_page_ready))[1])
        self.assertEqual(len(page["items"]), 5)

    async def test_clearing_an_empty_conversation_keeps_the_person(self):
        await self.seed("Nick", 2)
        self.assertTrue(self.bridge.history_clear_person("Nick"))
        await self.changed_with("cleared")
        self.assertTrue(self.log_lines("cleared"), self.logs)

        self.assertTrue(self.bridge.history_clear_person("Nick"))
        await settle()
        self.assertTrue(self.log_lines("no messages to clear"), self.logs)
        self.assertIsNotNone(await self.service.repo.get_person("Nick"),
                             "clearing never removes the person (RULE 14)")


class TestMediaFolderAndClipboard(SurfaceCase):
    async def seed_media(self):
        from test_chat_parser_delta import raw
        self.page.messages = [raw("", kind="gif", idx=0,
                                  media={"url": "https://x/y.gif",
                                         "kind": "gif"})]
        await self.service.collector.tick()
        page = json.loads((await self.ask(
            self.bridge.history_open, "r", "Nick", "{}",
            signal=self.bridge.history_page_ready))[1])
        return page["items"][0]["media"]["id"]

    def test_media_folder_is_the_persons_cache_folder(self):
        folder = self.bridge.media_folder("Nick")
        self.assertTrue(os.path.isabs(folder), folder)
        self.assertIn("Nick", folder)
        self.assertEqual(self.service.media.folder_for("Nick"), folder)

    async def test_open_media_folder_creates_it_and_announces(self):
        from PySide6.QtGui import QDesktopServices
        with mock.patch.object(QDesktopServices, "openUrl",
                               return_value=True) as opened:
            self.assertTrue(self.bridge.open_media_folder("Nick"))
        self.assertEqual(opened.call_count, 1)
        self.assertTrue(self.log_lines("📂"), self.logs)
        self.assertTrue(os.path.isdir(self.service.media.folder_for("Nick")))

    async def test_open_media_folder_reports_a_refusal_as_a_warning(self):
        from PySide6.QtGui import QDesktopServices
        with mock.patch.object(QDesktopServices, "openUrl",
                               side_effect=OSError("no desktop")):
            self.assertFalse(self.bridge.open_media_folder("Nick"))
        self.assertTrue(self.log_lines("Cannot open"), self.logs)

    async def test_copy_media_answers_with_the_archive_payload(self):
        ref = await self.seed_media()
        self.answers.clear()
        self.bridge.copy_media(str(ref))
        await wait_for(self.answers)
        answered, payload = self.answers[-1]
        data = json.loads(payload)
        self.assertEqual(answered, str(ref))
        self.assertTrue(data["ok"], data)
        self.assertEqual(data["mode"], "link")     # the file is not cached
        self.assertEqual(data["url"], "https://x/y.gif")
        # headless: either the clipboard took it or the payload says it did not
        self.assertIn(data.get("copied"), (True, False))


class TestMyNickDetection(SurfaceCase):
    async def test_detect_my_nick_reads_the_live_page(self):
        await self.seed("Nick", 2)
        _req, payload = await self.ask(self.bridge.detect_my_nick, "d1",
                                       signal=self.bridge.history_stats_ready)
        data = json.loads(payload)
        self.assertEqual(data["req_id"], "d1")
        self.assertEqual(data["partner"], "Nick")
        self.assertEqual(data["detected"], "Me")


class TestJsonArgumentParsing(SurfaceCase):
    async def test_broken_json_falls_back_to_the_defaults(self):
        await self.seed("Nick", 3)
        for bad in ("not json", "", None, json.dumps([1, 2]),
                    json.dumps("nick")):
            self.answers.clear()
            self.bridge.history_open("r", "Nick", bad)
            await wait_for(self.answers)
            data = json.loads(self.answers[-1][1])
            self.assertEqual(len(data["items"]), 3, f"{bad!r} lost the page")

    async def test_a_dict_argument_is_used_as_it_is(self):
        await self.seed("Nick", 3)
        self.answers.clear()
        self.bridge.history_search("s", {"q": "m1", "scope": "global"})
        await wait_for(self.answers)
        data = json.loads(self.answers[-1][1])
        self.assertEqual(data["scope"], "global")
        self.assertEqual(data["groups"][0]["nick"], "Nick")


if __name__ == "__main__":
    unittest.main(verbosity=2)
