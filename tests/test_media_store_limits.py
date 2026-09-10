"""stores/media_store — path, duplicate, limit, recovery edges.

Design refs: docs/archive/2026-09-09-test-suite/STORES_TEST_DESIGN_2026-09-09.md §11 (MED-01–21).

test_media_store.py (21) + test_media_store_paths.py (12) +
test_media_recovery_e2e.py (12) pin register/cache/duplicate/oversize/
fallbacks/LRU/recovery. This file pins the hostile and boundary edges
around them: traversal-proof slugs, nick-collision folders, free-name
sequences, zero/negative caps, LRU order with recency bumps, requeue and
download_one state machines, layout migration, and the stale-path fallback.

Run with:  python3 tests/test_media_store_limits.py
"""

import base64
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from stores.history_db import HistoryDB  # noqa: E402
from stores.media_store import MediaStore, slugify_nick  # noqa: E402

GIF = b"GIF89a" + b"\x00" * 200
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 500


class FakeCDP:
    """Answers the in-page media fetch probe with canned bytes."""

    def __init__(self, payloads=None, fail=()):
        self.payloads = payloads or {}
        self.fail = set(fail)
        self.fetched = []

    async def evaluate(self, expression):
        if "/*CVB_FETCH_MEDIA*/" not in expression:
            return None
        url = json.loads(expression.split("/*ARGS:")[1]
                         .split("*/")[0])["url"]
        self.fetched.append(url)
        if url in self.fail:
            return json.dumps({"ok": False, "error": "network error"})
        data = self.payloads.get(url, GIF)
        return json.dumps({"ok": True,
                           "b64": base64.b64encode(data).decode(),
                           "mime": "image/gif" if url.endswith(".gif")
                                   else "image/png",
                           "bytes": len(data)})

    async def get_cookies(self, url):
        return ""

    async def send(self, method, params=None):
        return {"result": {}}

    def on_event(self, method, callback):
        return callback

    def off_event(self, method, callback):
        pass


class MediaCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.dir = tempfile.mkdtemp()
        self.db = HistoryDB(os.path.join(self.dir, "history.db"))
        await self.db.init()
        self.cdp = FakeCDP()
        self.store = MediaStore(self.db, cdp=self.cdp,
                                cache_dir=os.path.join(self.dir, "media"),
                                max_file_mb=1, max_cache_mb=10)

    async def asyncTearDown(self):
        await self.db.close()

    async def cached_row(self, url, nick="Ann", kind="gif", data=GIF):
        self.cdp.payloads[url] = data
        mid = await self.store.register(url, kind, nick=nick)
        await self.store.process_pending()
        return await self.store.get(mid)


class TestSlugs(unittest.TestCase):
    def test_traversal_collapses_to_a_flat_name(self):  # MED-01
        slug = slugify_nick("../../etc")
        self.assertNotIn("/", slug)
        self.assertNotIn("..", slug)
        self.assertTrue(slug)

    def test_empty_and_unspeakable_nicks_still_name_a_folder(self):  # MED-02
        self.assertEqual(slugify_nick(""), "unknown")
        self.assertEqual(slugify_nick("   "), "unknown")
        for nick in ("😀🎉", "日本語", "___"):
            slug = slugify_nick(nick)
            self.assertTrue(slug and slug.strip("_"), nick)
            self.assertNotIn("/", slug)

    def test_cyrillic_contract(self):  # MED-03
        self.assertEqual(slugify_nick("Хорошо Все"), "Horosho_Vse")
        self.assertEqual(slugify_nick("Lizalo4ka"), "Lizalo4ka")

    def test_reserved_windows_names_are_defused(self):  # MED-01b
        for nick in ("con", "PRN", "com1", "lpt9", "aux"):
            self.assertNotEqual(slugify_nick(nick).lower(), nick.lower())


class TestFolders(MediaCase):
    async def test_collision_nicks_get_different_folders(self):  # MED-04
        first = self.store.folder_for("Ански")
        second = self.store.folder_for("Anski")
        self.assertNotEqual(first, second)
        # … and the mapping is stable across a restart with cached bytes
        await self.cached_row("https://x/a.gif", nick="Ански")
        twin = MediaStore(self.db, cdp=self.cdp,
                          cache_dir=os.path.join(self.dir, "media"))
        self.assertEqual(twin.folder_for("Ански"), first)
        self.assertEqual(twin.folder_for("Anski"), second)

    async def test_hostile_nicks_stay_inside_cache_dir(self):  # MED-05
        root = os.path.abspath(os.path.join(self.dir, "media"))
        for nick in ("a/b", "..", "..\\..\\x", "C:\\win", "/abs"):
            folder = self.store.folder_for(nick, kind="gif")
            self.assertTrue(os.path.abspath(folder).startswith(root + os.sep),
                            (nick, folder))

    async def test_free_name_sequences_within_a_day(self):  # MED-06
        folder = os.path.join(self.dir, "day")
        os.makedirs(folder)
        first = self.store._free_name(folder, "2026-09-09", ".gif")
        self.assertTrue(first.endswith("2026-09-09_001.gif"))
        open(first, "wb").write(b"x")
        second = self.store._free_name(folder, "2026-09-09", ".gif")
        self.assertTrue(second.endswith("2026-09-09_002.gif"))
        open(second, "wb").write(b"x")
        # other days and junk files do not disturb the sequence
        open(os.path.join(folder, "2026-09-08_009.gif"), "wb").write(b"x")
        open(os.path.join(folder, "notes.txt"), "w").write("x")
        third = self.store._free_name(folder, "2026-09-09", ".gif")
        self.assertTrue(third.endswith("2026-09-09_003.gif"))


class TestRegistration(MediaCase):
    async def test_empty_url_creates_no_row(self):  # MED-07
        self.assertIsNone(await self.store.register("  "))
        self.assertEqual(await self.db.scalar("SELECT COUNT(*) FROM media"),
                         0)

    async def test_reregister_keeps_first_nonempty_owner(self):  # MED-08
        first = await self.store.register("https://x/a.gif", "gif",
                                          nick="Ann")
        second = await self.store.register("https://x/a.gif", "gif",
                                           nick="Bob")
        self.assertEqual(first, second)
        row = await self.store.get(first)
        self.assertEqual((row["owner"], row["ref_count"]), ("Ann", 2))

    async def test_reregister_fills_an_empty_owner(self):  # MED-08b
        mid = await self.store.register("https://x/a.gif", "gif")
        await self.store.register("https://x/a.gif", "gif", nick="Bob")
        self.assertEqual((await self.store.get(mid))["owner"], "Bob")

    async def test_unknown_lookups_are_none(self):  # MED-09
        self.assertIsNone(await self.store.get(424242))
        self.assertIsNone(await self.store.get("garbage"))
        self.assertIsNone(await self.store.get_by_url("https://x/ghost.gif"))


class TestLimits(MediaCase):
    async def test_zero_limit_caches_nothing(self):  # MED-10
        await self.store.register("https://x/a.gif", "gif")
        self.assertEqual(await self.store.process_pending(limit=0), 0)
        self.assertEqual(await self.store.process_pending(limit=-3), 0)
        row = await self.store.get_by_url("https://x/a.gif")
        self.assertEqual(row["state"], "pending")
        self.assertEqual(self.cdp.fetched, [])

    async def test_zero_file_cap_skips_with_reason(self):  # MED-11
        tiny = MediaStore(self.db, cdp=self.cdp,
                          cache_dir=os.path.join(self.dir, "m0"),
                          max_file_mb=0)
        mid = await tiny.register("https://x/a.gif", "gif")
        self.assertEqual(await tiny.process_pending(), 0)
        row = await tiny.get(mid)
        self.assertEqual(row["state"], "skipped")
        self.assertIn("too large", row["fail_reason"])

    async def test_empty_payload_is_never_cached(self):  # MED-11b
        self.cdp.payloads["https://x/empty.gif"] = b""
        mid = await self.store.register("https://x/empty.gif", "gif")
        self.assertEqual(await self.store.process_pending(), 0)
        row = await self.store.get(mid)
        self.assertEqual(row["state"], "failed")
        self.assertFalse(row["cache_path"])

    async def test_zero_cache_cap_empties_to_url_fallback(self):  # MED-12
        row = await self.cached_row("https://x/a.gif")
        self.assertEqual(row["state"], "cached")
        self.store.max_cache_bytes = 0
        removed = await self.store.evict_if_needed()
        self.assertEqual(removed, 1)
        usage = await self.store.cache_usage()
        self.assertEqual((usage["files"], usage["bytes"]), (0, 0))
        info = await self.store.path_for(row["id"])
        self.assertEqual(info["path"], "")
        self.assertEqual(info["url"], "https://x/a.gif")

    async def test_lru_order_with_recency_bump(self):  # MED-13
        ids = []
        for i, url in enumerate(("https://x/a.gif", "https://x/b.gif",
                                 "https://x/c.gif")):
            row = await self.cached_row(url, data=GIF + bytes([i]))
            ids.append(row["id"])
        # stagger recency: a oldest … c newest
        for pos, mid in enumerate(ids):
            await self.db.execute(
                "UPDATE media SET last_used=?, bytes=100 WHERE id=?",
                (f"2026-09-09T10:0{pos}:00", mid))
        await self.db.commit()
        # touching `a` makes it newest; `b` is now the victim
        await self.store.path_for(ids[0])
        self.store.max_cache_bytes = 150  # room for one file only
        self.assertEqual(await self.store.evict_if_needed(), 2)
        states = {mid: (await self.store.get(mid))["state"] for mid in ids}
        self.assertEqual(states[ids[0]], "cached")  # bumped `a` survives
        self.assertEqual(states[ids[1]], "evicted")
        self.assertEqual(states[ids[2]], "evicted")

    async def test_clear_cache_degrades_rows_without_deleting(self):  # MED-14
        row = await self.cached_row("https://x/a.gif")
        path = row["cache_path"]
        self.assertTrue(os.path.exists(path))
        self.assertEqual(await self.store.clear_cache(), 1)
        self.assertFalse(os.path.exists(path))
        kept = await self.store.get(row["id"])
        self.assertIsNotNone(kept)  # the row survives, degraded …
        self.assertEqual(kept["state"], "evicted")
        info = await self.store.path_for(row["id"])
        self.assertEqual((info["path"], info["url"]),
                         ("", "https://x/a.gif"))


class TestRecoveryStates(MediaCase):
    async def test_requeue_unknown_is_quiet(self):  # MED-15
        self.assertFalse(await self.store.requeue(424242))
        self.assertFalse(await self.store.requeue("garbage"))

    async def test_download_one_cached_skips_the_fetch(self):  # MED-16
        row = await self.cached_row("https://x/a.gif")
        self.cdp.fetched.clear()
        info = await self.store.download_one(row["id"])
        self.assertEqual(info["path"], row["cache_path"])
        self.assertEqual(self.cdp.fetched, [])  # no re-download

    async def test_download_one_repairs_a_lost_file(self):  # MED-17
        row = await self.cached_row("https://x/a.gif")
        os.remove(row["cache_path"])
        info = await self.store.download_one(row["id"])
        self.assertTrue(info["path"] and os.path.exists(info["path"]))
        self.assertEqual((await self.store.get(row["id"]))["state"], "cached")

    async def test_retry_uncached_only_touches_failed_without_file(self):  # MED-18
        no_file = await self.store.register("https://x/nf.gif", "gif")
        await self.db.execute(
            "UPDATE media SET state='failed', fail_reason='x' WHERE id=?",
            (no_file,))
        with_file = await self.store.register("https://x/wf.gif", "gif")
        keep = os.path.join(self.dir, "keep.gif")
        open(keep, "wb").write(b"x")
        await self.db.execute(
            "UPDATE media SET state='failed', fail_reason='x', "
            "cache_path=? WHERE id=?", (keep, with_file))
        skipped = await self.store.register("https://x/sk.gif", "gif")
        await self.db.execute("UPDATE media SET state='skipped' WHERE id=?",
                              (skipped,))
        await self.db.commit()
        self.assertEqual(await self.store.retry_failed_uncached(), 1)
        self.assertEqual((await self.store.get(no_file))["state"], "pending")
        self.assertEqual((await self.store.get(with_file))["state"], "failed")
        self.assertEqual((await self.store.get(skipped))["state"], "skipped")
        self.assertEqual(await self.store.retry_failed_uncached(), 0)

    async def test_migrate_layout_moves_flat_files_once(self):  # MED-19
        mid = await self.store.register("https://x/flat.gif", "gif",
                                        nick="Ann")
        root = os.path.abspath(os.path.join(self.dir, "media"))
        os.makedirs(root, exist_ok=True)
        flat = os.path.join(root, "abc123.gif")
        open(flat, "wb").write(GIF)
        await self.db.execute(
            "UPDATE media SET state='cached', cache_path=?, bytes=? "
            "WHERE id=?", (flat, len(GIF), mid))
        await self.db.commit()
        self.assertEqual(await self.store.migrate_layout(), 1)
        row = await self.store.get(mid)
        self.assertFalse(os.path.exists(flat))
        self.assertTrue(os.path.exists(row["cache_path"]))
        self.assertIn("gifs", row["cache_path"])
        self.assertEqual(await self.store.migrate_layout(), 0)

    async def test_clipboard_unknown_is_a_clean_failure(self):  # MED-20
        payload = await self.store.clipboard_payload(424242)
        self.assertFalse(payload["ok"])
        self.assertIn("424242", payload["error"])

    async def test_path_for_falls_back_when_bytes_vanish(self):  # MED-21
        row = await self.cached_row("https://x/a.gif")
        os.remove(row["cache_path"])  # user deleted the file by hand
        info = await self.store.path_for(row["id"])
        self.assertEqual(info["path"], "")  # never a stale path …
        self.assertEqual(info["url"], "https://x/a.gif")  # … always the link


if __name__ == "__main__":
    unittest.main()
