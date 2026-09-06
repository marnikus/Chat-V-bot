"""Media cache — hybrid storage (milestone M5).

Decision D-1: the DB keeps the URL + a hash, the BYTES live on disk under a
size cap. That gives previews that survive the site expiring an image,
without a database that grows by gigabytes.

Bytes are fetched by an in-page `fetch()` (the page owns the cookies), so
the download path is exercised here through a fake CDP that answers the
media probe with base64.

Run with:  python3 tests/test_media_store.py
"""

import asyncio
import base64
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.history_db import HistoryDB  # noqa: E402
from backend.media_store import MediaStore  # noqa: E402

GIF = b"GIF89a" + b"\x00" * 200
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 500


class FakeCDP:
    """Answers the in-page media fetch probe."""

    def __init__(self, payloads=None, fail=()):
        self.payloads = payloads or {}
        self.fail = set(fail)
        self.fetched = []

    async def evaluate(self, expression):
        if "/*CVB_FETCH_MEDIA*/" not in expression:
            return None
        url = json.loads(expression.split("/*ARGS*/")[1]
                         .split("/*END*/")[0])["url"]
        self.fetched.append(url)
        if url in self.fail:
            return json.dumps({"ok": False, "error": "network error"})
        data = self.payloads.get(url, GIF)
        return json.dumps({"ok": True,
                           "b64": base64.b64encode(data).decode(),
                           "mime": "image/gif" if url.endswith(".gif")
                                   else "image/png",
                           "bytes": len(data)})


class MediaCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.dir = tempfile.mkdtemp()
        self.db = HistoryDB(os.path.join(self.dir, "history.db"))
        await self.db.init()
        self.cdp = FakeCDP({"https://x/a.gif": GIF, "https://x/b.png": PNG,
                            "https://x/copy.gif": GIF})
        self.store = MediaStore(self.db, cdp=self.cdp,
                                cache_dir=os.path.join(self.dir, "media"),
                                max_file_mb=1, max_cache_mb=10)

    async def asyncTearDown(self):
        await self.db.close()


class TestRegistration(MediaCase):
    async def test_registering_a_url_creates_one_pending_row(self):
        mid = await self.store.register("https://x/a.gif", "gif")
        row = await self.store.get(mid)
        self.assertEqual(row["state"], "pending")
        self.assertEqual(row["url"], "https://x/a.gif")
        self.assertEqual(row["kind"], "gif")

    async def test_the_same_url_is_registered_once_and_counted(self):
        a = await self.store.register("https://x/a.gif", "gif")
        b = await self.store.register("https://x/a.gif", "gif")
        self.assertEqual(a, b)
        row = await self.store.get(a)
        self.assertEqual(row["ref_count"], 2)

    async def test_kind_is_inferred_from_the_extension(self):
        mid = await self.store.register("https://x/photo.PNG")
        self.assertEqual((await self.store.get(mid))["kind"], "image")
        mid = await self.store.register("https://x/anim.gif")
        self.assertEqual((await self.store.get(mid))["kind"], "gif")

    async def test_empty_url_is_refused(self):
        self.assertIsNone(await self.store.register(""))


class TestDownloading(MediaCase):
    async def test_pending_media_is_cached_on_disk(self):
        mid = await self.store.register("https://x/a.gif", "gif")
        done = await self.store.process_pending()
        self.assertEqual(done, 1)
        row = await self.store.get(mid)
        self.assertEqual(row["state"], "cached")
        self.assertTrue(os.path.exists(row["cache_path"]))
        self.assertEqual(row["bytes"], len(GIF))
        self.assertTrue(row["sha256"])

    async def test_identical_bytes_are_stored_once(self):
        await self.store.register("https://x/a.gif", "gif")
        await self.store.register("https://x/copy.gif", "gif")
        await self.store.process_pending()
        rows = await self.db.fetchall(
            "SELECT cache_path FROM media WHERE state='cached'")
        paths = {r[0] for r in rows}
        self.assertEqual(len(rows), 2)
        self.assertEqual(len(paths), 1, "same bytes ⇒ one file on disk")

    async def test_oversize_files_are_skipped_with_a_reason(self):
        self.store.max_file_bytes = 100
        mid = await self.store.register("https://x/b.png")
        await self.store.process_pending()
        row = await self.store.get(mid)
        self.assertEqual(row["state"], "skipped")
        self.assertIn("too large", row["fail_reason"])

    async def test_network_failure_is_recorded_not_retried_forever(self):
        self.cdp.fail.add("https://x/a.gif")
        mid = await self.store.register("https://x/a.gif", "gif")
        await self.store.process_pending()
        row = await self.store.get(mid)
        self.assertEqual(row["state"], "failed")
        self.assertIn("network", row["fail_reason"])
        await self.store.process_pending()
        self.assertEqual(len(self.cdp.fetched), 1, "a failed row is not retried")

    async def test_caching_disabled_leaves_rows_pending(self):
        self.store.enabled = False
        mid = await self.store.register("https://x/a.gif", "gif")
        self.assertEqual(await self.store.process_pending(), 0)
        self.assertEqual((await self.store.get(mid))["state"], "pending")
        self.assertEqual(self.cdp.fetched, [])

    async def test_paused_downloads_do_nothing_but_stay_pending(self):
        mid = await self.store.register("https://x/a.gif", "gif")
        self.store.paused = True
        self.assertEqual(await self.store.process_pending(), 0)
        self.store.paused = False
        self.assertEqual(await self.store.process_pending(), 1)
        self.assertEqual((await self.store.get(mid))["state"], "cached")

    async def test_no_cdp_means_no_crash(self):
        store = MediaStore(self.db, cdp=None,
                           cache_dir=os.path.join(self.dir, "m2"))
        await store.register("https://x/a.gif", "gif")
        self.assertEqual(await store.process_pending(), 0)


class TestServingAndEviction(MediaCase):
    async def test_path_for_prefers_the_local_file(self):
        mid = await self.store.register("https://x/a.gif", "gif")
        await self.store.process_pending()
        info = await self.store.path_for(mid)
        self.assertEqual(info["state"], "cached")
        self.assertTrue(info["path"].endswith(".gif"))
        self.assertEqual(info["url"], "https://x/a.gif")

    async def test_path_for_falls_back_to_the_remote_url(self):
        mid = await self.store.register("https://x/a.gif", "gif")
        info = await self.store.path_for(mid)
        self.assertEqual(info["path"], "")
        self.assertEqual(info["url"], "https://x/a.gif")

    async def test_lru_eviction_frees_space_and_degrades_to_the_url(self):
        self.store.max_cache_bytes = 300     # room for exactly one payload
        a = await self.store.register("https://x/a.gif", "gif")
        await self.store.process_pending()
        b = await self.store.register("https://x/b.png")
        await self.store.process_pending()
        evicted = await self.store.evict_if_needed()
        self.assertGreaterEqual(evicted, 1)
        rows = {r["id"]: r for r in [await self.store.get(a),
                                     await self.store.get(b)]}
        states = {rows[a]["state"], rows[b]["state"]}
        self.assertIn("evicted", states)
        gone = [r for r in rows.values() if r["state"] == "evicted"][0]
        self.assertFalse(os.path.exists(gone["cache_path"] or "x"))
        info = await self.store.path_for(gone["id"])
        self.assertEqual(info["path"], "")
        self.assertTrue(info["url"])

    async def test_cache_usage_and_clear(self):
        await self.store.register("https://x/a.gif", "gif")
        await self.store.register("https://x/b.png")
        await self.store.process_pending()
        usage = await self.store.cache_usage()
        self.assertEqual(usage["files"], 2)
        self.assertGreater(usage["bytes"], 0)
        removed = await self.store.clear_cache()
        self.assertEqual(removed, 2)
        self.assertEqual((await self.store.cache_usage())["files"], 0)
        rows = await self.db.fetchall(
            "SELECT COUNT(*) FROM media WHERE state='cached'")
        self.assertEqual(rows[0][0], 0)


class TestClipboard(MediaCase):
    async def test_cached_image_is_offered_as_a_file(self):
        mid = await self.store.register("https://x/b.png")
        await self.store.process_pending()
        payload = await self.store.clipboard_payload(mid)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["mode"], "image")
        self.assertTrue(os.path.exists(payload["path"]))

    async def test_cached_gif_is_offered_as_file_plus_link(self):
        mid = await self.store.register("https://x/a.gif", "gif")
        await self.store.process_pending()
        payload = await self.store.clipboard_payload(mid)
        self.assertEqual(payload["mode"], "file_link")
        self.assertTrue(payload["path"])
        self.assertEqual(payload["text"], "https://x/a.gif")

    async def test_uncached_media_falls_back_to_the_link(self):
        mid = await self.store.register("https://x/a.gif", "gif")
        payload = await self.store.clipboard_payload(mid)
        self.assertEqual(payload["mode"], "link")
        self.assertEqual(payload["text"], "https://x/a.gif")

    async def test_unknown_reference_is_a_clean_failure(self):
        payload = await self.store.clipboard_payload(9999)
        self.assertFalse(payload["ok"])
        self.assertIn("not found", payload["error"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
