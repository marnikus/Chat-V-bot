"""Backfill media recovery — Bug #2, end-to-end regression cover.

Drives the REAL pipeline (Collector → ChatParser → HistoryRepo → MediaStore)
with a CDP-shaped fake that mirrors the live report of 2026-09-07:

  * a private chat with `глубокаясосуха` (My nick `Хорошо Все`);
  * a small sent webp (saves fine) and two large received GIFs;
  * downloads that fail at first and succeed later (host/CORS recovered);
  * a media line that renders AFTER its first parse (empty slot);
  * a virtualised pane whose newest window only returns after the
    scroll-to-top backfill restored the viewport.

Run with:  python3 tests/test_media_recovery_e2e.py
"""

import asyncio
import base64
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.chat_agent_js import AGENT_VERSION
from backend.chat_parser import ChatParser  # noqa: E402
from backend.collector import Collector  # noqa: E402
from backend.history_db import HistoryDB  # noqa: E402
from backend.history_models import MessageRecord, fingerprint  # noqa: E402
from backend.history_repo import HistoryRepo  # noqa: E402
from backend.media_store import MediaStore  # noqa: E402

NOW = datetime(2026, 9, 7, 16, 30, 0)
ME = "Хорошо Все"
PARTNER = "глубокаясосуха"
SENT_WEBP = "https://images.virt-chat.com/images/m_HoroshoVse_c3a3_.webp"
GIF1 = "https://images.virt-chat.com/images/m_Glotkoder_e911_.gif"
GIF2 = "https://images.virt-chat.com/images/m_Piterk7_7a86_.gif"


def raw(text="", direction="in", from_nick=PARTNER, time="16:22",
        kind="text", media=None, occ=0, idx=0):
    payload = media["url"] if media else text
    return {"fp": fingerprint(direction, from_nick, time, kind, payload, occ),
            "dir": direction, "from": from_nick, "kind": kind, "text": text,
            "media": media, "time": time, "occ": occ, "idx": idx}


def user_conversation():
    """The 27-line conversation from the live report (media + text)."""
    return [
        raw("приветик", "out", ME, "16:22", idx=0),
        raw("", "out", ME, "16:22", "image",
            {"url": SENT_WEBP, "kind": "image"}, idx=1),
        raw("привет", "in", PARTNER, "16:22", idx=2),
        raw("кайф поглубже мм", "in", PARTNER, "16:22", idx=3),
        raw("", "in", PARTNER, "16:24", "gif",
            {"url": GIF1, "kind": "gif"}, idx=4),
        raw("да сладенько", "in", PARTNER, "16:24", idx=5),
        raw("горлотрах)", "in", PARTNER, "16:28", idx=6),
        raw("", "in", PARTNER, "16:28", "gif",
            {"url": GIF2, "kind": "gif"}, idx=7),
        raw("ага это я и видел от тебя)", "out", ME, "16:29", idx=8),
    ]


class FakeChatPage:
    """CDP-shaped fake: a private chat that can fail and then recover.

    ``ok_urls``   URLs the in-page fetch can download (others "fail");
    ``rendered``  when False, media records are reported WITHOUT their URL
                  (the `<img>` has not rendered yet) — the parse artefact
                  that used to leave an empty, unrecoverable row;
    ``top_window`` when True (a scroll-to-top pass is in flight) slices
                  only return the OLDER half of the conversation, the way a
                  virtualised pane drops the newest nodes.
    """

    def __init__(self, messages, ok_urls=()):
        self.messages = list(messages)
        self.tab, self.partner, self.me = "private", PARTNER, ME
        self.title = PARTNER
        self.participants = 2
        self.is_connected = True
        self.ok_urls = set(ok_urls)
        self.rendered = True
        self.top_window = False
        self.top_view = None           # what the DOM holds at the top
        self.scroll_restores = 0
        self.scroll_top = 400          # a realistic mid-conversation viewport
        self._stack = []

    # ── test helpers ──
    def visible(self):
        out = []
        for m in self.messages:
            if (not self.rendered and m.get("media")
                    and m["media"].get("url")):
                media = dict(m["media"])
                media["url"] = ""            # <img> not in the DOM yet
                out.append(dict(m, media=media, kind="text", text="",
                                fp=fingerprint(m["dir"], m["from"], m["time"],
                                               "text", "", m.get("occ") or 0)))
            else:
                out.append(m)
        if self.top_window and self.top_view is not None:
            return list(self.top_view)   # virtualiser dropped the tail
        return out

    async def evaluate(self, expression):
        if "/*CVB_STATE*/" in expression:
            msgs = self.visible()
            ins, outs = [], []
            for m in msgs:
                nick = m["from"]
                if m["dir"] == "out":
                    if nick not in outs:
                        outs.append(nick)
                elif nick not in ins:
                    ins.append(nick)
            fps = [m["fp"] for m in msgs]
            return json.dumps({
                "ok": True, "agent": AGENT_VERSION, "tab": self.tab,
                "partner": self.partner, "me": self.me, "title": self.title,
                "participants": self.participants,
                "in_authors": ins, "out_authors": outs, "authors": ins + outs,
                "count": len(msgs), "head": fps[:5], "tail": fps[-25:],
                "pending": 0,
                "scroll": {"top": self.scroll_top, "height": 1000,
                           "client": 600,
                           "atTop": self.scroll_top <= 4,
                           "atBottom": self.scroll_top + 600 >= 1000 - 4},
            })
        if "/*CVB_SLICE*/" in expression:
            payload = json.loads(expression.split("/*ARGS:")[1].split("*/")[0])
            msgs = self.visible()
            a = max(0, min(len(msgs), payload["from"]))
            b = max(a, min(len(msgs), payload["to"]))
            return json.dumps({"ok": True, "from": a, "to": b,
                               "items": msgs[a:b]})
        if "/*CVB_SCROLL_TOP*/" in expression:
            self.top_window = True
            self.scroll_top = 0
            return json.dumps({"ok": True, "top": 0, "atTop": True,
                               "count": len(self.visible())})
        if "/*CVB_RESTORE_SCROLL*/" in expression:
            self.top_window = False
            self.scroll_top = 400
            self.scroll_restores += 1
            return json.dumps({"ok": True, "top": 400})
        if "/*CVB_FETCH_MEDIA*/" in expression:
            url = json.loads(expression.split("/*ARGS:")[1]
                             .split("*/")[0])["url"]
            if url in self.ok_urls:
                data = (b"GIF89a" + b"\x00" * 3 * 1024 * 1024
                        if url.endswith(".gif")
                        else b"\x89PNG\r\n\x1a\n" + b"\x00" * 400)
                return json.dumps({
                    "ok": True, "mime": "image/gif" if url.endswith(".gif")
                    else "image/png",
                    "b64": base64.b64encode(data).decode(),
                    "bytes": len(data)})
            return json.dumps({"ok": False, "error": "Failed to fetch"})
        return None


class E2ECase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.dir = tempfile.mkdtemp()
        self.db = HistoryDB(os.path.join(self.dir, "history.db"))
        await self.db.init()

    async def asyncTearDown(self):
        await self.db.close()

    def _collector(self, page, cap_mb=25, **settings):
        self.store = MediaStore(self.db, cdp=page,
                                cache_dir=os.path.join(self.dir, "saved_media"),
                                max_file_mb=cap_mb, max_cache_mb=200)
        self.repo = HistoryRepo(self.db, media=self.store, session_id="e2e")
        parser = ChatParser(page, chunk_size=80, chunk_pause_ms=0)
        col = Collector(cdp=page, repo=self.repo, parser=parser,
                        media=self.store,
                        settings={"my_nick": ME, "auto_backfill": False,
                                  **settings})
        col.now = lambda: NOW
        self.logs = []
        col.collector_log.connect(
            lambda p: self.logs.append(json.loads(p)))
        return col

    async def media_rows(self):
        return await self.db.fetchdicts(
            "SELECT m.ord, m.kind, md.state AS state, md.bytes AS bytes, "
            "md.cache_path AS path FROM messages m "
            "LEFT JOIN media md ON md.id=m.media_id "
            "WHERE m.kind IN ('image','gif') ORDER BY m.ord")


class TestBackfillRecoversFailedMedia(E2ECase):
    """The live report: sent webp cached, received GIFs failed forever."""

    async def test_backfill_requeues_and_finishes_the_gif_downloads(self):
        page = FakeChatPage(user_conversation(), ok_urls={SENT_WEBP})
        col = self._collector(page)
        await col.tick()
        rows = await self.media_rows()
        self.assertEqual([r["state"] for r in rows],
                         ["cached", "failed", "failed"])

        page.ok_urls.add(GIF1)          # the host serves the GIFs now
        page.ok_urls.add(GIF2)
        await col.backfill_older()

        rows = await self.media_rows()
        self.assertEqual([r["state"] for r in rows],
                         ["cached", "cached", "cached"],
                         "backfill must re-queue and finish failed media")
        self.assertTrue(all(r["path"] for r in rows))
        for r in rows:
            self.assertTrue(os.path.exists(r["path"]), r["path"])
        self.assertIn("gifs", rows[1]["path"].replace("\\", "/"))
        person_dir = os.path.dirname(os.path.dirname(rows[1]["path"]))
        marker = os.path.join(person_dir, "_nick.txt")
        self.assertTrue(os.path.exists(marker), person_dir)
        with open(marker, encoding="utf-8") as handle:
            self.assertEqual(handle.read().strip(), PARTNER)
        total = await self.db.scalar("SELECT COUNT(*) FROM messages", (), 0)
        self.assertEqual(total, 9, "no duplicate rows may appear")
        self.assertTrue(any("Media recovery" in x["message"]
                            for x in self.logs), self.logs)

    async def test_oversize_gif_is_saved_with_the_new_cap(self):
        """The old 2 MB cap skipped every ordinary GIF — root cause RC1."""
        page = FakeChatPage(user_conversation(),
                            ok_urls={SENT_WEBP, GIF1, GIF2})
        col = self._collector(page, cap_mb=25)
        await col.tick()
        rows = await self.media_rows()
        self.assertEqual([r["state"] for r in rows],
                         ["cached", "cached", "cached"])
        self.assertGreater(rows[1]["bytes"], 2 * 1024 * 1024,
                           "a 3 MB GIF must actually be stored")

        # …and the same download under the old 2 MB cap is 'skipped', which
        # is why the cap had to move. The host serves the bytes — the cap,
        # not the network, is what rejects the file.
        page2 = FakeChatPage(user_conversation(),
                             ok_urls={SENT_WEBP, GIF1, GIF2})
        db2 = HistoryDB(os.path.join(self.dir, "h2.db"))
        await db2.init()
        self.addAsyncCleanup(db2.close)
        store2 = MediaStore(db2, cdp=page2,
                            cache_dir=os.path.join(self.dir, "m2"),
                            max_file_mb=2)
        await store2.register(GIF2, "gif", nick=PARTNER, day="2026-09-07")
        await store2.process_pending()
        row = await store2.get_by_url(GIF2)
        self.assertEqual(row["state"], "skipped")
        self.assertIn("too large", row["fail_reason"])


class TestLateRenderedMedia(E2ECase):
    """RC2: a line parsed before `app-chat-image` renders left an empty row."""

    async def test_late_render_upgrades_the_empty_slot_without_duplicates(self):
        page = FakeChatPage(user_conversation(),
                            ok_urls={SENT_WEBP, GIF1, GIF2})
        page.rendered = False            # the GIFs parse as empty text rows
        col = self._collector(page)
        await col.tick()
        rows = await self.db.fetchdicts(
            "SELECT kind, text, media_id FROM messages ORDER BY ord")
        empties = [r for r in rows
                   if r["kind"] == "text" and not r["text"]
                   and r["media_id"] is None]
        self.assertEqual(len(empties), 0, "new collection must defer incomplete bodies")
        self.assertEqual(len(rows), 6)

        page.rendered = True             # the images are in the DOM now
        await col.tick()                 # an ordinary heartbeat, no backfill

        rows = await self.db.fetchdicts(
            "SELECT kind, text, media_id FROM messages ORDER BY ord")
        empties = [r for r in rows
                   if r["kind"] == "text" and not r["text"]
                   and r["media_id"] is None]
        self.assertEqual(empties, [],
                         "the empty slots must be repaired in place")
        media_rows = await self.media_rows()
        self.assertEqual(len(media_rows), 3)
        self.assertEqual([r["state"] for r in media_rows],
                         ["cached", "cached", "cached"])
        total = await self.db.scalar("SELECT COUNT(*) FROM messages", (), 0)
        self.assertEqual(total, 9,
                         "the repaired line must not be archived twice")

    async def test_a_pushed_empty_slot_is_upgraded_by_the_next_push(self):
        page = FakeChatPage(user_conversation(), ok_urls={SENT_WEBP, GIF1})
        col = self._collector(page)
        await col.tick()                 # all media known and cached

        # the partner sends a new GIF; the observer push fires before the
        # <img> renders — an empty slot — and the second push carries the URL
        await col.handle_push(json.dumps(
            [raw("", "in", PARTNER, "16:31", "text", None, idx=9)]))
        await col.handle_push(json.dumps(
            [raw("", "in", PARTNER, "16:31", "gif",
                 {"url": GIF2, "kind": "gif"}, idx=9)]))
        rows = await self.db.fetchdicts(
            "SELECT ord, kind, text, media_id FROM messages "
            "WHERE ts_display='16:31' ORDER BY ord")
        self.assertEqual(len(rows), 1,
                         "the URL-bearing push upgrades the empty slot")
        self.assertEqual(rows[0]["kind"], "gif")
        self.assertIsNotNone(rows[0]["media_id"])

    async def test_a_new_gif_cannot_fill_yesterdays_slot(self):
        """The HH:MM clock repeats every day — a slot from an older day must
        never absorb a NEW message with the same on-screen time."""
        page = FakeChatPage(user_conversation(), ok_urls={SENT_WEBP, GIF1})
        col = self._collector(page)
        await col.tick()
        # an empty slot from 2026-09-06 (yesterday) at 16:24 — stored above
        # today's conversation, hence ord 0
        await self.db.execute(
            "INSERT INTO messages(person_id, ord, fp, direction, from_nick, "
            "my_nick, kind, text, text_lc, media_id, ts_display, "
            "ts_resolved, day, ts_exact, occ, dom_idx, session_id, "
            "created_at, dup_key) VALUES(?,0,'x','in',?,'','text','','',"
            "NULL,'16:24','','2026-09-06',0,0,0,'e2e','','yesterday-slot')",
            (await self.repo.ensure_person(PARTNER), PARTNER))
        await self.db.commit()
        # a NEW gif arrives today, same author, same HH:MM as yesterday
        await col.handle_push(json.dumps(
            [raw("", "in", PARTNER, "16:24", "gif",
                 {"url": GIF2, "kind": "gif"}, idx=9)]))
        rows = await self.db.fetchdicts(
            "SELECT day, kind, media_id, dup_key FROM messages "
            "WHERE ts_display='16:24' AND (kind='gif' OR "
            "day='2026-09-06') ORDER BY ord")
        # yesterday's slot + today's original GIF1 + today's new GIF2
        self.assertEqual(len(rows), 3,
                         "yesterday's empty slot and today's new gif must "
                         "both exist — no cross-day absorption")
        self.assertEqual(rows[0]["day"], "2026-09-06")
        self.assertIsNone(rows[0]["media_id"], "yesterday's slot stays empty")
        self.assertTrue(all(r["day"] == "2026-09-07" for r in rows[1:]))
        self.assertTrue(all(r["media_id"] for r in rows[1:]))


class TestRecoveryScoping(E2ECase):
    """RC3/RC4: register-on-failed requeues; heartbeats stay cheap."""

    async def test_recovery_requeues_a_media_row_that_was_already_failed(self):
        page = FakeChatPage([])
        col = self._collector(page)
        # the GIF was seen before and its download failed
        mid = await self.store.register(GIF1, "gif", nick=PARTNER,
                                        day="2026-09-07")
        await self.store.process_pending()
        self.assertEqual((await self.store.get(mid))["state"], "failed")

        await self.repo.append(PARTNER, [MessageRecord(
            direction="in", from_nick=PARTNER, kind="gif",
            ts_display="16:24")], my_nick=ME, now=NOW)
        pid = await self.repo.ensure_person(PARTNER)
        stats = await self.repo.recover_media(
            pid, [MessageRecord(direction="in", from_nick=PARTNER,
                                ts_display="16:24", kind="gif",
                                media_url=GIF1, media_kind="gif")],
            media=self.store, nick=PARTNER, now=NOW)
        self.assertEqual(stats["repaired"], 1)
        self.assertEqual(stats["requeued"], 1,
                         "linking a message to a failed row must re-queue it")
        row = await self.store.get(mid)
        self.assertEqual(row["state"], "pending")
        self.assertEqual(row["recovery_attempts"], 1)

    async def test_heartbeat_pass_does_not_requeue_failed_downloads(self):
        page = FakeChatPage(user_conversation(), ok_urls={SENT_WEBP})
        col = self._collector(page)
        await col.tick()
        failed = await self.db.fetchall(
            "SELECT id FROM media WHERE state='failed'")
        self.assertEqual(len(failed), 2)

        stats = await self.repo.recover_media(
            await self.repo.ensure_person(PARTNER), [], media=self.store,
            nick=PARTNER, now=NOW, requeue_failed=False)
        self.assertEqual(stats["requeued"], 0,
                         "ordinary ticks repair, they do not hammer a dead "
                         "URL every heartbeat")
        still = await self.db.fetchall(
            "SELECT id FROM media WHERE state='failed'")
        self.assertEqual(len(still), 2)

    async def test_backfill_repairs_the_newest_window_after_the_scroll(self):
        """RC4: the newest media is not in the DOM during the top pass."""
        page = FakeChatPage(user_conversation(), ok_urls={SENT_WEBP, GIF1})
        # phase 1: nothing is rendered yet — every media line is an empty slot
        page.rendered = False
        col = self._collector(page)
        await col.tick()
        empties = await self.db.fetchall(
            "SELECT id FROM messages WHERE kind='text' AND text='' "
            "AND media_id IS NULL")
        self.assertEqual(len(empties), 0, "incomplete bodies are deferred, not archived")

        # phase 2: the images render; scrolling to the top drops the newest
        # two lines from the DOM (the virtualiser keeps a window) while older
        # history loads in — GIF2 is only in the DOM again AFTER the restore
        page.rendered = True
        page.ok_urls.add(GIF2)
        older = [raw(f"старое сообщение {i}", "in", PARTNER, "15:0{i}"
                     if i < 10 else "15:10", idx=-i) for i in range(6)]
        page.top_view = older + user_conversation()[:7]
        await col.backfill_older()
        self.assertGreaterEqual(page.scroll_restores, 1,
                                "the viewport must be restored before the "
                                "newest window can be repaired")
        media_rows = await self.media_rows()
        self.assertEqual([r["state"] for r in media_rows],
                         ["cached", "cached", "cached"],
                         "the newest media must meet its DOM record after "
                         "restoreScroll, not only during the top pass")
        empties = await self.db.fetchall(
            "SELECT id FROM messages WHERE kind='text' AND text='' "
            "AND media_id IS NULL")
        self.assertEqual(empties, [])
        total = await self.db.scalar("SELECT COUNT(*) FROM messages", (), 0)
        self.assertEqual(total, 9 + len(older))

    async def test_unrepairable_rows_do_not_trigger_a_tail_read_forever(self):
        page = FakeChatPage(user_conversation(), ok_urls={SENT_WEBP})
        col = self._collector(page)
        await col.tick()
        # a message the DOM can no longer supply (deleted on the site)
        await self.repo.append(PARTNER, [MessageRecord(
            direction="in", from_nick=PARTNER, kind="text",
            ts_display="10:00")], my_nick=ME, now=NOW)
        pid = await self.repo.ensure_person(PARTNER)
        self.assertTrue(await self.repo.has_repairable_media(
            pid, include_failed=False))
        stats = await self.repo.recover_media(
            pid, [], media=self.store, nick=PARTNER, now=NOW,
            requeue_failed=False)
        self.assertEqual(stats["scanned"], 1)
        self.assertFalse(await self.repo.has_repairable_media(
            pid, include_failed=False),
            "a scanned-but-unfound row must not re-trigger every heartbeat")

    async def test_idle_ticks_still_drain_the_download_queue(self):
        """A re-queued backlog must not stall while the chat is idle."""
        page = FakeChatPage(user_conversation(), ok_urls={SENT_WEBP, GIF1,
                                                          GIF2})
        col = self._collector(page)
        await col.tick()
        # a backlog of fresh pending rows beyond the 25-per-pass limit
        for i in range(30):
            await self.store.register(
                f"https://images.virt-chat.com/images/extra_{i}.gif", "gif",
                nick=PARTNER, day="2026-09-07")
            page.ok_urls.add(f"https://images.virt-chat.com/images/extra_{i}.gif")
        pending = await self.db.scalar(
            "SELECT COUNT(*) FROM media WHERE state='pending'", (), 0)
        self.assertGreater(pending, 25)
        state = await col.tick()       # unchanged conversation, idle chat
        self.assertEqual(state, "no_new")
        first = await self.db.scalar(
            "SELECT COUNT(*) FROM media WHERE state='pending'", (), 0)
        self.assertLess(first, pending,
                        "the idle tick must keep draining the download queue")
        await col.tick()               # and the next idle tick drains the rest
        self.assertEqual(await self.db.scalar(
            "SELECT COUNT(*) FROM media WHERE state='pending'", (), 0),
            0, "the idle tick must keep draining the download queue")

    async def test_pre_fix_duplicate_pair_is_cleaned_up(self):
        """Databases from before the fix hold BOTH the empty slot and the
        payload row for one message — recovery removes the artefact."""
        page = FakeChatPage(user_conversation(), ok_urls={SENT_WEBP, GIF1,
                                                          GIF2})
        col = self._collector(page)
        await col.tick()
        # re-create the pre-fix artefact: an extra empty slot next to the
        # real GIF1 row, same author and minute
        await self.db.execute(
            "INSERT INTO messages(person_id, ord, fp, direction, from_nick, "
            "my_nick, kind, text, text_lc, media_id, ts_display, "
            "ts_resolved, day, ts_exact, occ, dom_idx, session_id, "
            "created_at, dup_key) VALUES(?,1,'x','in',?,'','text','','',"
            "NULL,'16:24','','2026-09-07',0,0,0,'e2e','','legacy-empty-key')",
            (await self.repo.ensure_person(PARTNER), PARTNER))
        await self.db.commit()
        pid = await self.repo.ensure_person(PARTNER)
        self.assertTrue(await self.repo.has_repairable_media(
            pid, include_failed=True))
        dom = [MessageRecord(direction="in", from_nick=PARTNER,
                             ts_display="16:24", kind="gif",
                             media_url=GIF1, media_kind="gif")]
        stats = await self.repo.recover_media(
            pid, dom, media=self.store, nick=PARTNER, now=NOW,
            requeue_failed=True)
        self.assertEqual(stats["repaired"], 0,
                         "the payload row already exists — nothing to repair")
        leftovers = await self.db.fetchall(
            "SELECT id FROM messages WHERE kind='text' AND text='' "
            "AND media_id IS NULL")
        self.assertEqual(leftovers, [],
                         "the legacy empty slot must be removed, not kept "
                         "as a second copy of the message")


class TestServiceCapMigration(unittest.TestCase):
    """RC1: the stored 2 MB default must be migrated up."""

    def test_old_default_cap_is_raised(self):
        from backend.history_service import (HISTORY_DEFAULTS,
                                             MAX_FILE_MB_DEFAULT,
                                             HistoryService, _merge)
        self.assertEqual(HISTORY_DEFAULTS["media"]["max_file_mb"],
                         MAX_FILE_MB_DEFAULT)
        self.assertEqual(MAX_FILE_MB_DEFAULT, 25)

        class FakeConfig:
            def __init__(self, data):
                self.data = data

            def get(self, section, key=None, default=None):
                return self.data.get(section, default)

        service = HistoryService.__new__(HistoryService)
        service.config = None
        service._settings = _merge(HISTORY_DEFAULTS,
                                   {"media": {"max_file_mb": 2}})
        service._migrate_media_cap()
        self.assertEqual(service._settings["media"]["max_file_mb"], 25)

        service._settings = _merge(HISTORY_DEFAULTS,
                                   {"media": {"max_file_mb": 50}})
        service._migrate_media_cap()
        self.assertEqual(service._settings["media"]["max_file_mb"], 50,
                         "a deliberately larger cap is kept")


if __name__ == "__main__":
    unittest.main(verbosity=2)
