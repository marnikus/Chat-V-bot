"""Bug #2 — saved media must be browsable, not a flat sha256 pile.

What the user has to be able to do: open the folder in Explorer, see one
folder per person with `images/` and `gifs/` inside, recognise the file by
its name, and copy-paste it. So:

    saved_media/
      Horosho_Vse/
        images/2026-09-07_001.png
        gifs/2026-09-07_001.gif
      Lizalo4ka/
        images/2026-09-07_001.jpg

Folder names are ASCII (Latin) transliterations of the nick — Cyrillic nicks
would otherwise be unreadable/unusable depending on the console codepage.
Paths are absolute so the UI can render `file://…` instead of the
percent-encoded remote URL that showed up as a broken image.

Run with:  python3 tests/test_media_layout.py
"""

import base64
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from stores.history_db import HistoryDB  # noqa: E402
from stores.history_models import MessageRecord  # noqa: E402
from stores.history_repo import HistoryRepo  # noqa: E402
from stores.media_store import MediaStore, slugify_nick  # noqa: E402

GIF = b"GIF89a" + b"\x00" * 200
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 500
JPG = b"\xff\xd8\xff" + b"\x00" * 300

DAY = datetime(2026, 9, 7, 12, 0, 0)
ME = "Хорошо Все"
PARTNER = "Ански"


class FakeCDP:
    def __init__(self, payloads):
        self.payloads = payloads

    async def evaluate(self, expression):
        if "/*CVB_FETCH_MEDIA*/" not in expression:
            return None
        url = json.loads(expression.split("/*ARGS:")[1]
                         .split("*/")[0])["url"]
        data = self.payloads.get(url, GIF)
        mime = ("image/gif" if url.endswith(".gif")
                else "image/png" if url.endswith(".png") else "image/jpeg")
        return json.dumps({"ok": True,
                           "b64": base64.b64encode(data).decode(),
                           "mime": mime, "bytes": len(data)})


# ── the Latin folder name ────────────────────────────────────────

class TestSlug(unittest.TestCase):
    def test_cyrillic_nicks_become_latin(self):
        self.assertEqual(slugify_nick("Хорошо Все"), "Horosho_Vse")
        self.assertEqual(slugify_nick("Ански"), "Anski")
        self.assertEqual(slugify_nick("Макс__Б"), "Maks__B")

    def test_latin_nicks_are_kept_as_they_are(self):
        self.assertEqual(slugify_nick("Lizalo4ka"), "Lizalo4ka")
        self.assertEqual(slugify_nick("Hi.Honey-2"), "Hi.Honey-2")

    def test_the_result_is_always_ascii_and_filesystem_safe(self):
        for nick in ["Хорошо Все", "日本語", "a/b\\c:d*e?f\"g<h>i|j",
                     "  spaced  out  ", "…", "CON", "ünïcødé"]:
            slug = slugify_nick(nick)
            self.assertTrue(slug, f"{nick!r} produced an empty folder name")
            slug.encode("ascii")               # raises if not Latin
            for bad in '/\\:*?"<>| ':
                self.assertNotIn(bad, slug)
            self.assertNotIn("..", slug)

    def test_unnamed_or_symbol_only_nicks_still_get_a_stable_folder(self):
        first = slugify_nick("★★★")
        self.assertEqual(first, slugify_nick("★★★"))
        self.assertNotEqual(first, slugify_nick("☆☆☆"))
        self.assertTrue(slugify_nick(""))

    def test_windows_reserved_names_are_escaped(self):
        self.assertNotEqual(slugify_nick("CON").upper(), "CON")


class LayoutCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.dir = tempfile.mkdtemp()
        self.root = os.path.join(self.dir, "saved_media")
        self.db = HistoryDB(os.path.join(self.dir, "history.db"))
        await self.db.init()
        self.cdp = FakeCDP({"https://images.virt-chat.com/images/m_1.gif": GIF,
                            "https://images.virt-chat.com/images/m_2.png": PNG,
                            "https://images.virt-chat.com/images/m_3.jpg": JPG})
        self.store = MediaStore(self.db, cdp=self.cdp, cache_dir=self.root,
                                max_file_mb=1, max_cache_mb=10)
        self.store.now = lambda: DAY

    async def asyncTearDown(self):
        await self.db.close()

    def rel(self, path):
        return os.path.relpath(path, self.root).replace(os.sep, "/")

    async def cache(self, url, kind, nick):
        mid = await self.store.register(url, kind, nick=nick)
        await self.store.process_pending()
        return await self.store.get(mid)


# ── the tree on disk ─────────────────────────────────────────────

class TestFolders(LayoutCase):
    async def test_images_and_gifs_live_in_their_own_person_folders(self):
        gif = await self.cache("https://images.virt-chat.com/images/m_1.gif",
                               "gif", PARTNER)
        png = await self.cache("https://images.virt-chat.com/images/m_2.png",
                               "image", PARTNER)
        self.assertEqual(self.rel(gif["cache_path"]),
                         "Anski/gifs/2026-09-07_001.gif")
        self.assertEqual(self.rel(png["cache_path"]),
                         "Anski/images/2026-09-07_001.png")
        self.assertTrue(os.path.exists(gif["cache_path"]))
        self.assertTrue(os.path.exists(png["cache_path"]))

    async def test_each_person_gets_their_own_latin_folder(self):
        mine = await self.cache("https://images.virt-chat.com/images/m_2.png",
                                "image", ME)
        self.assertEqual(self.rel(mine["cache_path"]),
                         "Horosho_Vse/images/2026-09-07_001.png")
        self.assertIn("Horosho_Vse", os.listdir(self.root))

    async def test_files_are_numbered_within_the_day(self):
        first = await self.cache("https://images.virt-chat.com/images/m_1.gif",
                                 "gif", PARTNER)
        second = await self.cache("https://images.virt-chat.com/images/m_3.jpg",
                                  "gif", PARTNER)
        self.assertEqual(self.rel(first["cache_path"]),
                         "Anski/gifs/2026-09-07_001.gif")
        self.assertEqual(self.rel(second["cache_path"]),
                         "Anski/gifs/2026-09-07_002.jpg")

    async def test_numbering_restarts_on_the_next_day(self):
        await self.cache("https://images.virt-chat.com/images/m_1.gif",
                         "gif", PARTNER)
        self.store.now = lambda: datetime(2026, 9, 8, 9, 0, 0)
        later = await self.cache("https://images.virt-chat.com/images/m_3.jpg",
                                 "gif", PARTNER)
        self.assertEqual(self.rel(later["cache_path"]),
                         "Anski/gifs/2026-09-08_001.jpg")

    async def test_the_day_of_the_message_wins_over_today(self):
        mid = await self.store.register(
            "https://images.virt-chat.com/images/m_1.gif", "gif",
            nick=PARTNER, day="2026-08-31")
        await self.store.process_pending()
        row = await self.store.get(mid)
        self.assertEqual(self.rel(row["cache_path"]),
                         "Anski/gifs/2026-08-31_001.gif")

    async def test_paths_are_absolute_so_the_ui_can_show_them(self):
        row = await self.cache("https://images.virt-chat.com/images/m_1.gif",
                               "gif", PARTNER)
        self.assertTrue(os.path.isabs(row["cache_path"]))
        info = await self.store.path_for(row["id"])
        self.assertTrue(os.path.isabs(info["path"]))
        self.assertEqual(info["state"], "cached")

    async def test_the_owner_is_remembered_on_the_row(self):
        row = await self.cache("https://images.virt-chat.com/images/m_1.gif",
                               "gif", PARTNER)
        self.assertEqual(row["owner"], PARTNER)

    async def test_an_unknown_owner_still_gets_a_folder(self):
        row = await self.cache("https://images.virt-chat.com/images/m_1.gif",
                               "gif", "")
        self.assertTrue(self.rel(row["cache_path"]).endswith(
            "/gifs/2026-09-07_001.gif"))
        self.assertTrue(os.path.exists(row["cache_path"]))

    async def test_two_nicks_that_transliterate_alike_do_not_collide(self):
        a = await self.cache("https://images.virt-chat.com/images/m_1.gif",
                             "gif", "Anski")
        b = await self.cache("https://images.virt-chat.com/images/m_2.png",
                             "image", "Ански")
        self.assertNotEqual(os.path.dirname(os.path.dirname(a["cache_path"])),
                            os.path.dirname(os.path.dirname(b["cache_path"])))
        self.assertEqual(self.store.folder_for("Anski"),
                         self.store.folder_for("Anski"))

    async def test_the_same_url_is_stored_once(self):
        url = "https://images.virt-chat.com/images/m_1.gif"
        first = await self.cache(url, "gif", PARTNER)
        await self.store.register(url, "gif", nick=PARTNER)
        await self.store.process_pending()
        second = await self.store.get(first["id"])
        self.assertEqual(first["cache_path"], second["cache_path"])
        self.assertEqual(
            len(os.listdir(os.path.dirname(first["cache_path"]))), 1)

    async def test_folder_for_is_public_so_the_ui_can_open_it(self):
        folder = self.store.folder_for(PARTNER)
        self.assertTrue(os.path.isabs(folder))
        self.assertTrue(folder.endswith(os.path.join("saved_media", "Anski")))


# ── the CORS-free Python fallback ────────────────────────────────

class BlockingCDP(FakeCDP):
    """A page whose in-page fetch is blocked (no CORS on the image host)."""
    def __init__(self):
        super().__init__({})

    async def evaluate(self, expression):
        if "/*CVB_FETCH_MEDIA*/" in expression:
            return json.dumps({"ok": False, "error": "CORS blocked"})
        return None


class TestCorsFallback(LayoutCase):
    async def test_python_fallback_caches_a_gif_when_the_page_fetch_is_blocked(self):
        self.cdp = BlockingCDP()
        self.store = MediaStore(self.db, cdp=self.cdp, cache_dir=self.root,
                                max_file_mb=1, max_cache_mb=10)
        self.store.now = lambda: DAY

        async def fetch(url):
            mime = "image/gif" if url.endswith(".gif") else "image/png"
            data = GIF if url.endswith(".gif") else PNG
            return {"ok": True, "b64": base64.b64encode(data).decode(),
                    "mime": mime, "bytes": len(data)}
        self.store._http_fetcher = fetch

        row = await self.cache("https://images.virt-chat.com/images/m_1.gif",
                               "gif", PARTNER)
        self.assertEqual(row["state"], "cached")
        self.assertEqual(self.rel(row["cache_path"]),
                         "Anski/gifs/2026-09-07_001.gif")
        self.assertTrue(os.path.exists(row["cache_path"]))
        self.assertEqual(row["fail_reason"], "")

    async def test_failed_uncached_rows_are_re_queued_once(self):
        self.cdp = BlockingCDP()
        self.store = MediaStore(self.db, cdp=self.cdp, cache_dir=self.root)
        self.store.now = lambda: DAY
        mid = await self.store.register(
            "https://images.virt-chat.com/images/m_1.gif", "gif",
            nick=PARTNER)
        await self.store.process_pending()
        row = await self.store.get(mid)
        self.assertEqual(row["state"], "failed")
        self.assertEqual(await self.store.retry_failed_uncached(), 1)
        row = await self.store.get(mid)
        self.assertEqual(row["state"], "pending")
        self.assertEqual(await self.store.retry_failed_uncached(), 0)


# ── moving an old flat cache into the new tree ───────────────────

class TestMigration(LayoutCase):
    async def test_flat_sha256_files_are_moved_into_the_person_tree(self):
        old_dir = self.root
        os.makedirs(old_dir, exist_ok=True)
        flat = os.path.join(old_dir, "a" * 64 + ".gif")
        with open(flat, "wb") as handle:
            handle.write(GIF)
        await self.db.execute(
            "INSERT INTO media(url, kind, state, sha256, bytes, cache_path, "
            "ref_count, created_at, last_used) "
            "VALUES(?,?,'cached',?,?,?,1,?,?)",
            ("https://images.virt-chat.com/images/m_old.gif", "gif",
             "a" * 64, len(GIF), flat, "2026-09-01T10:00:00",
             "2026-09-01T10:00:00"))
        await self.db.commit()
        row = await self.store.get_by_url(
            "https://images.virt-chat.com/images/m_old.gif")
        await self.db.execute("UPDATE media SET owner=? WHERE id=?",
                              (PARTNER, row["id"]))
        await self.db.commit()

        moved = await self.store.migrate_layout()
        self.assertEqual(moved, 1)
        row = await self.store.get(row["id"])
        self.assertEqual(self.rel(row["cache_path"]),
                         "Anski/gifs/2026-09-01_001.gif")
        self.assertTrue(os.path.exists(row["cache_path"]))
        self.assertFalse(os.path.exists(flat))

    async def test_migration_is_idempotent(self):
        await self.cache("https://images.virt-chat.com/images/m_1.gif",
                         "gif", PARTNER)
        self.assertEqual(await self.store.migrate_layout(), 0)

    async def test_a_missing_file_does_not_break_the_migration(self):
        await self.db.execute(
            "INSERT INTO media(url, kind, state, sha256, bytes, cache_path, "
            "owner, ref_count, created_at, last_used) "
            "VALUES(?,?,'cached',?,?,?,?,1,?,?)",
            ("https://x/gone.gif", "gif", "b" * 64, 10,
             os.path.join(self.root, "b" * 64 + ".gif"), PARTNER,
             "2026-09-01T10:00:00", "2026-09-01T10:00:00"))
        await self.db.commit()
        self.assertEqual(await self.store.migrate_layout(), 0)


# ── the archive passes the owner down ────────────────────────────

class TestRepoWiring(LayoutCase):
    async def test_the_repo_tells_the_store_whose_media_it_is(self):
        repo = HistoryRepo(self.db, media=self.store, session_id="t")
        await repo.append(PARTNER, [MessageRecord(
            direction="in", from_nick=PARTNER, kind="gif", ts_display="11:55",
            media_url="https://images.virt-chat.com/images/m_1.gif",
            media_kind="gif")], my_nick=ME, now=DAY)
        await self.store.process_pending()
        row = await self.store.get_by_url(
            "https://images.virt-chat.com/images/m_1.gif")
        self.assertEqual(row["owner"], PARTNER)
        self.assertEqual(self.rel(row["cache_path"]),
                         "Anski/gifs/2026-09-07_001.gif")

    async def test_my_own_media_is_filed_under_the_partner_folder(self):
        # a conversation folder holds BOTH directions — that is what makes
        # the tree readable ("everything I exchanged with Ански")
        repo = HistoryRepo(self.db, media=self.store, session_id="t")
        await repo.append(PARTNER, [MessageRecord(
            direction="out", from_nick=ME, kind="image", ts_display="11:58",
            media_url="https://images.virt-chat.com/images/m_2.png",
            media_kind="image")], my_nick=ME, now=DAY)
        await self.store.process_pending()
        row = await self.store.get_by_url(
            "https://images.virt-chat.com/images/m_2.png")
        self.assertEqual(row["owner"], PARTNER)
        self.assertEqual(self.rel(row["cache_path"]),
                         "Anski/images/2026-09-07_001.png")


if __name__ == "__main__":
    unittest.main(verbosity=2)
