"""Backfill media recovery — Bug #2.

When an image/GIF was saved without its URL, or its download failed, a
manual "Backfill older" pass re-reads the DOM.  The recovery step has to:

  * find the saved message that should have media but has none,
  * match it to the freshly parsed DOM record,
  * register the real URL into the right person folder,
  * re-queue a failed row so the normal downloader retries it, and
  * mark what was scanned so it is not retried endlessly.

Run with:  python3 tests/test_media_recovery.py
"""

import base64
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.history_db import HistoryDB  # noqa: E402
from backend.history_models import MessageRecord  # noqa: E402
from backend.history_repo import HistoryRepo  # noqa: E402
from backend.media_store import MediaStore  # noqa: E402

GIF = b"GIF89a" + b"\x00" * 200
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 500

DAY = datetime(2026, 9, 7, 12, 0, 0)
ME = "Хорошо Все"
PARTNER = "Ански"
GIF_URL = "https://images.virt-chat.com/images/m_1.gif"
PNG_URL = "https://images.virt-chat.com/images/m_2.png"


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


class RecoveryCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.dir = tempfile.mkdtemp()
        self.root = os.path.join(self.dir, "saved_media")
        self.db = HistoryDB(os.path.join(self.dir, "history.db"))
        await self.db.init()
        self.cdp = FakeCDP({GIF_URL: GIF, PNG_URL: PNG})
        self.store = MediaStore(self.db, cdp=self.cdp, cache_dir=self.root,
                                max_file_mb=1, max_cache_mb=10)
        self.store.now = lambda: DAY
        self.repo = HistoryRepo(self.db, media=self.store, session_id="t")

    async def asyncTearDown(self):
        await self.db.close()

    async def _save_missing(self, url="", kind="image", ts="11:55",
                            nick=PARTNER):
        await self.repo.append(nick, [MessageRecord(
            direction="in", from_nick=nick, kind=kind, ts_display=ts,
            media_url=url, media_kind=kind if url else "")],
            my_nick=ME, now=DAY)
        return await self.repo.ensure_person(nick)


class TestMissingUrlRecovery(RecoveryCase):
    async def test_backfill_recovers_a_message_whose_url_was_empty(self):
        pid = await self._save_missing()
        before = await self.db.fetchone(
            "SELECT media_id FROM messages WHERE person_id=?", (pid,))
        self.assertIn(None, [before["media_id"]])

        dom = [MessageRecord(
            direction="in", from_nick=PARTNER, ts_display="11:55",
            kind="image", media_url=PNG_URL, media_kind="image")]
        changed = await self.repo.recover_media(
            pid, dom, media=self.store, nick=PARTNER, now=DAY)
        self.assertEqual(changed, 1)

        row = await self.db.fetchone(
            "SELECT media_id, media_scan_at, media_recovered_at "
            "FROM messages WHERE person_id=?", (pid,))
        self.assertIsNotNone(row["media_id"])
        self.assertTrue(row["media_recovered_at"])

        await self.store.process_pending()
        media = await self.store.get(row["media_id"])
        self.assertEqual(media["state"], "cached")
        self.assertTrue(media["cache_path"].endswith(
            os.path.join("Anski", "images", "2026-09-07_001.png")))
        self.assertTrue(os.path.exists(media["cache_path"]))

        # the row is no longer a candidate, so the next backfill does nothing
        again = await self.repo.recover_media(
            pid, dom, media=self.store, nick=PARTNER, now=DAY)
        self.assertEqual(again, 0)

    async def test_a_missing_url_that_is_not_in_the_dom_is_scanned_once(self):
        pid = await self._save_missing(ts="12:00")
        changed = await self.repo.recover_media(
            pid, [], media=self.store, nick=PARTNER, now=DAY)
        self.assertEqual(changed, 0)

        row = await self.db.fetchone(
            "SELECT media_id, media_scan_at FROM messages WHERE person_id=?",
            (pid,))
        self.assertIsNone(row["media_id"])
        self.assertTrue(row["media_scan_at"])

        second = await self.repo.recover_media(
            pid, [], media=self.store, nick=PARTNER, now=DAY)
        self.assertEqual(second, 0)


class TestFailedRowRecovery(RecoveryCase):
    async def test_backfill_requeues_a_failed_row_without_re_reading_the_dom(self):
        mid = await self.store.register(GIF_URL, "gif", nick=PARTNER,
                                        day="2026-09-07")
        await self.store.process_pending()
        row = await self.store.get(mid)
        self.assertEqual(row["state"], "cached")

        # simulate the CORS regression: the bytes were never saved
        await self.db.execute(
            "UPDATE media SET state='failed', sha256='', bytes=0, "
            "cache_path='', fail_reason='CORS blocked' WHERE id=?", (mid,))
        await self.db.commit()
        await self.repo.append(PARTNER, [MessageRecord(
            direction="in", from_nick=PARTNER, ts_display="11:56",
            kind="gif", media_url=GIF_URL, media_kind="gif")],
            my_nick=ME, now=DAY)
        pid = await self.repo.ensure_person(PARTNER)

        changed = await self.repo.recover_media(
            pid, [], media=self.store, nick=PARTNER, now=DAY)
        self.assertEqual(changed, 1)

        row = await self.store.get(mid)
        self.assertEqual(row["state"], "pending")
        self.assertEqual(row["recovery_attempts"], 1)
        self.assertTrue(row["recovered_at"])

        # and the normal downloader can now finish the job
        await self.store.process_pending()
        row = await self.store.get(mid)
        self.assertEqual(row["state"], "cached")
        self.assertTrue(os.path.exists(row["cache_path"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
