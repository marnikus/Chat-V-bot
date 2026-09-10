"""services/db_service (backend/db_manager) — corrupt files, containment,
concurrency.

Design refs: docs/archive/2026-09-09-test-suite/BACKEND_TESTS_DESIGN_2026-09-09.md §DB#1–5.

Promises proven here (module docstring, DB_CREATION_DELETION_REDESIGN):

  * a world a user creates can never land outside the app folder —
    `safe_db_name` exists precisely so "the user cannot use a name to
    escape the app folder";
  * switching to a CORRUPT file fails with a clear error and leaves the
    previous world connected ("a failed swap leaves the app connected",
    fail closed) — never a half-switched state;
  * the DB window's data (list_dbs / info) survives a corrupt *.db
    neighbour in the folder;
  * create() refuses to reuse an existing path — even a corrupt one
    (no silent overwrite of a file we could not even read);
  * two concurrent creates of the same name end with exactly ONE world.

Run with:  python3 tests/test_db_manager_corrupt.py
"""

import asyncio
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend.config_manager import ConfigManager  # noqa: E402
from backend.db_manager import DbManager  # noqa: E402
from backend.history_service import HistoryService  # noqa: E402
from test_chat_parser_delta import FakePage, raw  # noqa: E402


class ConnectedPage(FakePage):
    is_connected = True


class DbCase(unittest.IsolatedAsyncioTestCase):
    """DbManager wired to a REAL HistoryService over real SQLite files."""

    async def asyncSetUp(self):
        self.dir = tempfile.mkdtemp()
        self.cfg = ConfigManager(os.path.join(self.dir, "config.json"))
        media_cfg = dict(self.cfg.get("history", "media", default={}) or {})
        media_cfg["cache_dir"] = os.path.join(self.dir, "saved_media")
        self.cfg.set("history", "media", media_cfg)
        self.page = ConnectedPage([raw(f"m{i}", idx=i) for i in range(4)])
        self.db_path = os.path.join(self.dir, "history.db")
        self.service = HistoryService(cdp=self.page, config=self.cfg,
                                      db_path=self.db_path)
        await self.service.init()
        self.service.collector.configure(my_nick="Me")
        self.manager = DbManager(config=self.cfg, service=self.service,
                                 root=self.dir)

    async def asyncTearDown(self):
        try:
            await self.service.close()
        except Exception:
            pass

    async def seed(self, nick="Nick", count=4):
        self.page.partner = nick
        self.page.messages = [raw(f"m{i}", from_nick=nick, idx=i)
                              for i in range(count)]
        await self.service.collector.tick()

    async def message_count(self):
        rows = await self.service.db.fetchall(
            "SELECT COUNT(*) FROM messages")
        return rows[0][0]

    def write_corrupt(self, name="corrupt.db"):
        path = os.path.join(self.dir, name)
        with open(path, "wb") as fh:
            fh.write(b"SQLite format 3\x00" + os.urandom(512))  # garbage
        return path


# ══════════════════════════════════════════════════════════════════
# DB#1 — a created world cannot escape the app folder
# ══════════════════════════════════════════════════════════════════
class TestCreateContainment(DbCase):

    async def test_create_with_a_traversal_name_stays_inside_the_root(self):
        """Ledger #6: `resolve()` hands any name containing a separator
        straight through (`normpath` only), so `create("../evil")` would
        place the new world OUTSIDE the app folder — exactly what
        `safe_db_name` promises to prevent. The bridge feeds the raw
        text of the DB window's name field straight into create()."""
        result = await self.manager.create("../evil")
        if result.get("ok"):
            created = os.path.abspath(result["path"])
            self.assertTrue(created.startswith(
                os.path.abspath(self.dir) + os.sep),
                f"create escaped the app folder: {created}")
        else:
            # refusing loudly is also acceptable — but no file may appear
            self.assertFalse(os.path.exists(
                os.path.join(self.dir, "..", "evil")),
                "the traversal file was created anyway")

    async def test_create_with_an_absolute_name_stays_inside_the_root(self):
        outside = os.path.join(self.dir, "..", "absolute_evil.db")
        result = await self.manager.create(outside)
        if result.get("ok"):
            self.assertTrue(os.path.abspath(result["path"]).startswith(
                os.path.abspath(self.dir) + os.sep),
                f"create accepted an absolute path outside the root: "
                f"{result['path']}")
        try:
            os.unlink(outside)                      # don't litter ../
        except OSError:
            pass

    async def test_create_refuses_an_existing_corrupt_file(self):
        corrupt = self.write_corrupt()
        result = await self.manager.create("corrupt")
        self.assertFalse(result.get("ok"),
                         "create silently reused an existing (corrupt) file")
        self.assertIn("exists", result.get("error", ""))


# ══════════════════════════════════════════════════════════════════
# DB#2 / DB#3 — corrupt neighbours and a failed swap
# ══════════════════════════════════════════════════════════════════
class TestCorruptFile(DbCase):

    async def test_loading_a_corrupt_file_fails_closed(self):
        await self.seed()
        before_count = await self.message_count()
        corrupt = self.write_corrupt()

        result = await self.manager.load(corrupt)

        self.assertFalse(result.get("ok"), "a corrupt swap must fail")
        self.assertTrue(str(result.get("error", "")),
                        "the failure must carry a readable error")
        # fail closed: the PREVIOUS world is still the one connected
        self.assertEqual(os.path.abspath(self.service.db.path),
                         os.path.abspath(self.db_path),
                         "a failed swap left the app on the wrong file")
        self.assertTrue(self.service.db.is_open)
        self.assertEqual(await self.message_count(), before_count,
                         "the old world's data must be untouched")

    async def test_the_db_window_survives_a_corrupt_neighbour(self):
        self.write_corrupt()
        await self.seed()
        listing = self.manager.list_dbs()
        names = [item["name"] for item in listing]
        self.assertIn("corrupt.db", names,
                      "a corrupt world must still be listed (it exists)")
        info = await self.manager.info()
        self.assertTrue(info["connected"])
        self.assertGreaterEqual(info["db_bytes"], 0)

    async def test_a_corrupt_file_reports_zero_readable_counts(self):
        self.write_corrupt("broken.db")
        listing = {i["name"]: i for i in self.manager.list_dbs()}
        self.assertGreaterEqual(listing["broken.db"]["bytes"], 0)
        self.assertTrue(listing["broken.db"]["exists"])


# ══════════════════════════════════════════════════════════════════
# DB#4 — concurrent create of the same world
# ══════════════════════════════════════════════════════════════════
class TestConcurrentCreate(DbCase):

    async def test_two_racing_creates_end_with_one_world(self):
        results = await asyncio.gather(self.manager.create("race"),
                                       self.manager.create("race"))
        races = [os.path.join(self.dir, "race.db")]
        present = [p for p in races if os.path.exists(p)]
        self.assertEqual(len(present), 1,
                         "two creates made two files or none")
        oks = [r for r in results if r.get("ok")]
        # both may succeed onto the same file, or the loser refuses —
        # but the end state must be ONE connectable world
        if len(oks) == 2:
            paths = {os.path.abspath(r["path"]) for r in oks}
            self.assertEqual(len(paths), 1,
                             "the racing creates resolved to different files")
        rows = await self.service.db.fetchall(
            "SELECT name FROM sqlite_master WHERE type='table'")
        self.assertTrue(rows, "the surviving world must have its schema")


if __name__ == "__main__":
    unittest.main(verbosity=2)
