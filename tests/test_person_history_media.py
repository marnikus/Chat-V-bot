"""Supplied nested attachment -> generated JS/CDP -> SQLite/file -> live UI.

Only resource bytes/transport are controlled. Message records, fetch probes,
private validation, storage and bridge signals are the production code. The
example's external image is never needed: all download attempts are intercepted.
"""

import asyncio
import base64
from datetime import datetime
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import AsyncMock

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]

from PySide6.QtCore import QObject
from backend.bridge import Bridge
from backend.chat_agent_js import AGENT_VERSION, slice_expression
from backend.collector import CollectorState
from backend.config_manager import ConfigManager
from backend.history_service import HistoryService
from test_capture_after_clear import DomCDP, FIXTURE, HAVE_DOM, ME, NICK
from test_media_store import NetworkCDP

SAMPLE = (ROOT / "tests/fixtures/person_media.html").read_text()
URL = ("https://images.virt-chat.com/images/"
       "m_%D0%9F%D1%80%D0%B8%D0%B2%D0%B5%D1%82%D0%91_"
       "7eca7b743e76442f1056921bd49489afe18471a4c91c9f8a4d29615ed0919ad8_.gif")
OLD_SELF = "Пошлый01"
NOW = datetime(2026, 9, 9, 23, 30)
# A complete 1x1 GIF, not a fake header followed by random padding.
GIF = base64.b64decode("R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7")


@unittest.skipUnless(HAVE_DOM, "Install development DOM dependency: npm ci --prefix tests")
class MediaDOMCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.cdp = await DomCDP().open(FIXTURE)
        self.addAsyncCleanup(self.cdp.close)
        await self.markup(SAMPLE)
        await self.resource()
        self.cfg = ConfigManager(str(Path(self.temp.name) / "config.json"))
        settings = self.cfg.get("history")
        settings["media"]["cache_dir"] = str(Path(self.temp.name) / "saved media")
        self.cfg.set("history", settings)
        self.cfg.set_state(my_nick_recent=[OLD_SELF, ME])
        self.service = HistoryService(self.cdp, self.cfg,
                                      db_path=str(Path(self.temp.name) / "history.db"))
        await self.service.init()
        self.addAsyncCleanup(self.service.close)
        await self.service.parser.install()
        self.store, self.col = self.service.media, self.service.collector
        # Even failure tests must never contact the sample CDN.
        self.store._http_fetcher = AsyncMock(return_value={"ok": False, "error": "controlled HTTP failure"})
        self.store._fetch_via_network = AsyncMock(return_value={"ok": False, "error": "controlled network failure"})
        self.col.configure(my_nick=ME, auto_backfill=False, download_media=True, chunk_pause_ms=0)
        self.col.now = lambda: NOW
        self.bridge = Bridge.__new__(Bridge)
        QObject.__init__(self.bridge)
        self.bridge._config = self.cfg
        self.bridge._memory = None
        self.bridge._engine = types.SimpleNamespace(load_stack=lambda _: None)
        self.bridge.attach_history(self.service)
        self.events, self.appends = [], []
        self.bridge.media_ready.connect(lambda req, data: self.events.append((req, json.loads(data))))
        self.bridge.history_appended.connect(lambda data: self.appends.append(json.loads(data)))

    async def markup(self, html):
        await self.cdp.evaluate("(() => { document.querySelector('.messages-root').innerHTML = " + json.dumps(html) + "; return true; })()")

    async def resource(self, *, status=200, data=GIF, mime="image/gif"):
        # Execute the real fetch_media_expression, including blob/base64 transfer.
        # This substitutes only fetch's resource response, not its CVB probe.
        await self.cdp.evaluate("""(() => {
          const resource = %s;
          window.mediaFetches = [];
          window.fetch = async (url, options) => {
            window.mediaFetches.push({ url, options });
            const data = Uint8Array.from(atob(resource.b64), ch => ch.charCodeAt(0));
            return { ok: resource.status === 200, status: resource.status,
              blob: async () => ({ type: resource.mime, size: data.length,
                arrayBuffer: async () => data.buffer }) };
          };
        })()""" % json.dumps({"b64": base64.b64encode(data).decode(), "mime": mime, "status": status}))

    async def record(self):
        return json.loads(await self.cdp.evaluate(slice_expression(0, 1)))["items"][0]

    async def page(self):
        return await self.service.query.page(NICK)

    async def ask_media(self, slot, req, media_id):
        done = asyncio.get_running_loop().create_future()
        def answer(request, payload):
            if request == req and not done.done():
                done.set_result(json.loads(payload))
        self.bridge.media_ready.connect(answer)
        try:
            slot(req, str(media_id))
            return await asyncio.wait_for(done, 5)
        finally:
            self.bridge.media_ready.disconnect(answer)


class TestSuppliedAttachmentDOM(MediaDOMCase):
    async def test_exact_supplied_markup_is_a_gif_not_an_empty_text_record(self):
        rec = await self.record()
        self.assertGreaterEqual(AGENT_VERSION, 14)
        self.assertEqual((rec["dir"], rec["from"], rec["time"]), ("out", OLD_SELF, "23:29"))
        self.assertEqual(rec["kind"], "gif")
        self.assertEqual(rec["media"], {"url": URL, "kind": "gif"})
        self.assertEqual(rec["text"], "")
        self.assertFalse(rec["capture_pending"])

    async def test_nested_attachment_also_works_in_other_text_containers(self):
        for tag in ("span", "div"):
            with self.subTest(tag=tag):
                await self.markup(SAMPLE)
                await self.cdp.evaluate("""(() => {
                  const old = document.querySelector('.message-text');
                  const wrapper = document.createElement(%s);
                  %s
                  wrapper.replaceChildren(...old.childNodes);
                  old.replaceWith(wrapper);
                })()""" % (json.dumps(tag), "wrapper.setAttribute('class', 'message');" if tag == "span" else "wrapper.setAttribute('data-message-text', '');"))
                self.assertEqual((await self.record())["media"]["url"], URL)

    async def test_incoming_image_preserves_its_caption_without_icons_or_attachment_alt(self):
        await self.cdp.evaluate("""(() => {
          const row = document.querySelector('.message-container');
          row.className = 'message-container general-background';
          row.querySelector('.from').textContent = %s;
          const body = row.querySelector('.message-text');
          body.insertAdjacentHTML('afterbegin', 'Подпись<br><a href="https://example.test/">ссылка</a> <img class="emoji" alt="😊" src="emoji.png">');
          row.querySelector('app-chat-image img').src = 'https://example.test/photo.PNG?original=1';
          row.querySelector('avatar-item').insertAdjacentHTML('afterbegin', '<img src="avatar.png" alt="profile">');
          row.querySelector('mat-menu').textContent = 'Copy Delete';
        })()""" % json.dumps(NICK))
        rec = await self.record()
        self.assertEqual((rec["dir"], rec["from"], rec["kind"]), ("in", NICK, "image"))
        self.assertEqual(rec["text"], "Подпись\nссылка 😊")
        self.assertEqual(rec["media"]["url"], "https://example.test/photo.PNG?original=1")
        self.assertFalse(rec["capture_pending"])

    async def test_avatar_and_inline_emoji_are_not_archived_as_media(self):
        await self.cdp.evaluate("""(() => {
          document.querySelector('app-chat-image').remove();
          document.querySelector('avatar-item').insertAdjacentHTML('afterbegin', '<img src="avatar.gif">');
          document.querySelector('.message-text').innerHTML = 'Hello <img alt="😊" class="emoji" src="emoji.gif">';
        })()""")
        rec = await self.record()
        self.assertIsNone(rec["media"])
        self.assertEqual(rec["text"], "Hello 😊")
        self.assertEqual(rec["kind"], "text")
        await self.col.tick()
        self.assertEqual(await self.service.db.scalar("SELECT COUNT(*) FROM media"), 0)
        self.assertEqual(await self.cdp.evaluate("window.mediaFetches.length"), 0)

    async def test_component_waiting_for_its_image_is_pending_even_with_a_caption(self):
        await self.cdp.evaluate("""(() => {
          document.querySelector('app-chat-image img').remove();
          document.querySelector('.message-text').prepend(document.createTextNode('Caption'));
        })()""")
        rec = await self.record()
        self.assertEqual(rec["capture_reason"], "media_url_pending")
        self.assertEqual(rec["text"], "Caption")
        self.assertEqual(await self.col.tick(), CollectorState.CAPTURE_PENDING)
        self.assertEqual((await self.page())["total"], 0)
        await self.cdp.evaluate("""(() => {
          const img = document.createElement('img'); img.src = %s;
          document.querySelector('.image-wrapper').appendChild(img);
        })()""" % json.dumps(URL))
        self.assertEqual(await self.col.tick(), CollectorState.COLLECTED)
        page = await self.page()
        self.assertEqual(page["total"], 1)
        self.assertEqual(page["items"][0]["text"], "Caption")
        self.assertEqual(page["items"][0]["media"]["state"], "cached")

    async def test_lazy_empty_url_is_retried_and_data_src_is_not_lost(self):
        await self.cdp.evaluate("document.querySelector('app-chat-image img').removeAttribute('src')")
        self.assertEqual((await self.record())["capture_reason"], "media_url_pending")
        await self.cdp.evaluate("window.__cvbAgent.uninstall()")
        await self.cdp.evaluate("document.querySelector('app-chat-image img').setAttribute('data-src', " + json.dumps(URL) + ")")
        rec = await self.record()
        self.assertEqual(rec["media"]["url"], URL)
        self.assertFalse(rec["capture_pending"])

    async def test_unknown_author_still_cannot_save_media(self):
        await self.cdp.evaluate("document.querySelector('.from').textContent = 'Unknown third participant'")
        self.assertEqual(await self.col.tick(), CollectorState.GROUP_TAB)
        self.assertEqual(await self.service.db.scalar("SELECT COUNT(*) FROM messages"), 0)
        self.assertEqual(await self.service.db.scalar("SELECT COUNT(*) FROM media"), 0)
        self.assertEqual(await self.cdp.evaluate("window.mediaFetches.length"), 0)


class TestMediaFileDelivery(MediaDOMCase):
    async def test_sample_is_saved_and_delivered_to_live_history_with_its_local_path(self):
        self.assertEqual(await self.col.tick(), CollectorState.COLLECTED)
        page = await self.page()
        self.assertEqual(page["total"], 1)
        item = page["items"][0]
        info = item["media"]
        self.assertEqual((item["from"], item["dir"], item["time"], item["day"]),
                         (OLD_SELF, "out", "23:29", "2026-09-09"))
        self.assertEqual(info["state"], "cached")
        self.assertEqual(Path(info["path"]).read_bytes(), GIF)
        self.assertEqual(Path(info["path"]).parent, Path(self.store.folder_for(NICK, "gif")))
        self.assertEqual(info["url"], URL)
        self.assertEqual(self.appends[-1]["items"][0]["media"], info,
                         "append must not deliver its pre-download pending snapshot")
        self.assertEqual(self.events[-1][1]["path"], info["path"])
        self.assertEqual(self.events[-1][1]["generation"], self.service.generation)
        self.assertEqual(await self.cdp.evaluate("window.mediaFetches[0].url"), URL)
        # Actual renderer code receives the DTO from the actual database.
        for source in ("history-model.js", "history-view.js"):
            await self.cdp.evaluate((ROOT / "ui/js" / source).read_text())
        preview = await self.cdp.evaluate("""(() => {
          const host = document.createElement('div');
          HistoryView.renderRows(host, HistoryModel.toRows(%s), {});
          const img = host.querySelector('.msg-media');
          return { src: img.getAttribute('src'), gif: img.classList.contains('is-gif') };
        })()""" % json.dumps(page["items"]))
        self.assertEqual(preview["src"], Path(info["path"]).as_uri())
        self.assertTrue(preview["gif"])
        self.assertEqual(await self.col.tick(), CollectorState.NO_NEW)
        self.assertEqual((await self.page())["total"], 1)
        self.assertEqual(await self.cdp.evaluate("window.mediaFetches.length"), 1)

    async def test_push_pending_row_gets_cache_completion_without_a_new_message(self):
        await self.markup("")
        await self.col.tick()
        await self.markup(SAMPLE)
        payload = await self.cdp.evaluate("JSON.stringify(window.__cvbAgent.drain())")
        self.assertEqual(await self.col.handle_push(payload), 1)
        self.assertEqual(self.appends[-1]["items"][0]["media"]["state"], "pending")
        appends = len(self.appends)
        await self.col.tick()
        self.assertEqual(len(self.appends), appends)
        self.assertTrue(any(data["state"] == "cached" for _, data in self.events))
        self.assertEqual((await self.page())["total"], 1)
        self.assertEqual(self.col.state_payload()["session_added"], 1)

    async def test_unchanged_heartbeat_finishes_later_download_batches_and_emits_updates(self):
        await self.markup("\n".join(SAMPLE.replace(URL, URL + "?part=" + str(i)) for i in range(28)))
        await self.col.tick()
        self.assertEqual(len(self.appends[-1]["items"]), 28)
        self.assertEqual(sum(row["media"]["state"] == "pending" for row in self.appends[-1]["items"]), 3)
        before = len(self.events)
        appends = len(self.appends)
        await self.col.tick()
        self.assertEqual(self.col.state_payload()["sync_reason"], "unchanged_cursor")
        self.assertEqual(len(self.events) - before, 3)
        self.assertEqual(len(self.appends), appends)
        self.assertTrue(all(row["media"]["state"] == "cached" for row in (await self.page())["items"]))

    async def test_turning_downloads_back_on_finishes_an_already_archived_attachment(self):
        self.col.configure(download_media=False)
        await self.col.tick()
        self.assertEqual((await self.page())["items"][0]["media"]["state"], "pending")
        self.assertEqual(self.events, [])
        self.col.configure(download_media=True)
        await self.col.tick()
        self.assertEqual(self.events[-1][1]["state"], "cached")
        self.assertEqual((await self.page())["total"], 1)

    async def test_failed_download_has_a_reason_and_explicit_restore_returns_a_ready_file(self):
        await self.resource(status=403)
        await self.col.tick()
        item = (await self.page())["items"][0]
        info = item["media"]
        self.assertEqual(info["state"], "failed")
        self.assertEqual(info["path"], "")
        self.assertIn("HTTP 403", info["error"])
        self.assertIn("HTTP 403", self.events[-1][1]["error"])
        await self.resource()
        restored = await self.ask_media(self.bridge.media_restore, "restore", info["id"])
        self.assertEqual(restored["state"], "cached")
        self.assertEqual(restored["error"], "")
        self.assertEqual(restored["generation"], self.service.generation)
        self.assertEqual(Path(restored["path"]).read_bytes(), GIF)
        self.assertEqual((await self.page())["total"], 1)

    async def test_missing_file_is_honest_in_pages_and_media_path_and_can_be_restored(self):
        await self.col.tick()
        info = (await self.page())["items"][0]["media"]
        Path(info["path"]).unlink()
        gone = await self.ask_media(self.bridge.media_path, "missing", info["id"])
        self.assertEqual(gone["state"], "missing")
        self.assertEqual(gone["path"], "")
        self.assertIn("missing", gone["error"])
        self.assertEqual((await self.page())["items"][0]["media"]["state"], "missing")
        fixed = await self.store.download_one(info["id"])
        self.assertEqual(Path(fixed["path"]).read_bytes(), GIF)

    async def test_disabled_paused_and_disconnected_restore_explain_why_without_changing_settings(self):
        self.col.configure(download_media=False)
        await self.col.tick()
        mid = (await self.page())["items"][0]["media"]["id"]
        for setting, value, phrase in [("enabled", False, "disabled"), ("paused", True, "paused"), ("cdp", None, "not connected")]:
            with self.subTest(setting=setting):
                old = getattr(self.store, setting)
                setattr(self.store, setting, value)
                try:
                    result = await self.store.download_one(mid)
                    self.assertIn(phrase, result["error"])
                    self.assertEqual(result["path"], "")
                    self.assertEqual(getattr(self.store, setting), value)
                finally:
                    setattr(self.store, setting, old)
        self.assertEqual(await self.cdp.evaluate("window.mediaFetches.length"), 0)

    async def test_eviction_event_removes_the_old_preview_path(self):
        await self.col.tick()
        before = (await self.page())["items"][0]["media"]
        await self.store.clear_cache()
        self.assertEqual(self.events[-1][1]["state"], "evicted")
        self.assertEqual(self.events[-1][1]["path"], "")
        self.assertFalse(Path(before["path"]).exists())

    async def test_oversize_file_is_not_saved_and_the_limit_is_visible(self):
        self.store.max_file_bytes = len(GIF) - 1
        await self.col.tick()
        info = (await self.page())["items"][0]["media"]
        self.assertEqual(info["state"], "skipped")
        self.assertIn("too large", info["error"])
        self.assertEqual(info["path"], "")
        self.assertEqual(self.events[-1][1]["state"], "skipped")

    async def test_callback_failures_do_not_turn_a_successful_download_into_failure(self):
        for asynchronous in (False, True):
            with self.subTest(asynchronous=asynchronous):
                def fail(_):
                    raise RuntimeError("controlled UI listener failure")
                async def async_fail(info):
                    fail(info)
                self.store.on_change = async_fail if asynchronous else fail
                mid = await self.store.register(URL + "?listener=" + str(asynchronous), "gif", nick=NICK)
                self.assertEqual(await self.store.process_pending(), 1)
                self.assertEqual((await self.store.path_for(mid))["state"], "cached")

    async def test_encoded_url_still_uses_browser_network_fallback_when_page_fetch_is_blocked(self):
        # Event-shaped CDP stand-in: no external URL is requested.
        self.store.cdp = NetworkCDP(URL, GIF, "image/gif")
        del self.store._fetch_via_network  # exercise the real network fallback method
        mid = await self.store.register(URL, "gif", nick=NICK)
        self.assertEqual(await self.store.process_pending(), 1)
        info = await self.store.path_for(mid)
        self.assertEqual(Path(info["path"]).read_bytes(), GIF)
        self.assertEqual(self.events[-1][1]["state"], "cached")

    async def test_clear_and_delete_recollect_the_same_media_fresh_without_undo_reads(self):
        await self.col.tick()
        first_id = (await self.page())["items"][0]["id"]
        self.service.undo_store.read = AsyncMock(side_effect=AssertionError("Collection must not read Undo"))
        for delete in (False, True):
            await self.service.reset_conversation(NICK, delete_person=delete)
            self.assertEqual(await self.service.db.scalar("SELECT COUNT(*) FROM messages"), 0)
            self.assertEqual(await self.service.db.scalar("SELECT COUNT(*) FROM media"), 0)
            self.assertEqual(self.col.state_payload()["session_added"], 0)
            await self.col.tick()
            item = (await self.page())["items"][0]
            self.assertNotEqual(item["id"], first_id)
            self.assertEqual(item["media"]["state"], "cached")
            self.assertEqual(Path(item["media"]["path"]).read_bytes(), GIF)
            self.assertEqual(self.col.state_payload()["session_added"], 1)
            self.assertEqual(self.events[-1][1]["generation"], self.service.generation)
            first_id = item["id"]
        self.service.undo_store.read.assert_not_awaited()

    async def test_saved_preview_survives_restart_without_a_browser(self):
        await self.col.tick()
        before = (await self.page())["items"][0]
        await self.service.close()
        reopened = HistoryService(None, self.cfg, db_path=self.service.db.path)
        await reopened.init()
        try:
            after = (await reopened.query.page(NICK))["items"][0]
            self.assertEqual(after, before)
            self.assertEqual(Path(after["media"]["path"]).read_bytes(), GIF)
        finally:
            await reopened.close()

    async def test_replaced_service_cannot_publish_a_media_update_into_the_new_archive(self):
        before = len(self.events)
        old = self.bridge._history
        self.bridge._history = types.SimpleNamespace(generation=99)
        try:
            self.bridge._emit_media_info(old, {"id": 1, "path": "stale.gif", "state": "cached"})
            self.assertEqual(len(self.events), before)
        finally:
            self.bridge._history = old


if __name__ == "__main__":
    unittest.main()
