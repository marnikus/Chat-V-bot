"""BotChatService + GrokClient + PromptLibrary — the AI Bot Chat use cases.

Every test here fails if the code under it is deleted (RULE 8): the service
runs against a real `HistoryDB` file with real rows, and the Grok transport
runs against a fake aiohttp session that answers like the real endpoint.

What is pinned:
  * only the CURRENT DAY's messages are loaded, oldest first;
  * an empty day is EMPTY, not broken (RULE 4), and so is a closed archive;
  * a suggestion comes back PENDING — the service never sends it;
  * every Grok failure is a typed `Err`, never an exception;
  * an edited prompt is the one rendered, and a broken one falls back.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import unittest
from datetime import date, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from backend.config_manager import ConfigManager            # noqa: E402
from services import bot_chat                                # noqa: E402
from services import bot_connections                         # noqa: E402
from services import bot_providers                         # noqa: E402
from services.bot_connections import ConnectionStore         # noqa: E402
from services.bot_presets import PresetLibrary               # noqa: E402
from services import bot_variables                          # noqa: E402
from services.bot_chat import BotChatService, as_transcript, last_inbound  # noqa: E402
from services.bot_grok import (GrokClient, GrokSettings, client_for,  # noqa: E402
                               mask, reply_text)
from services.bot_prompts import PromptLibrary, is_usable    # noqa: E402
from backend.history_query import HistoryQuery               # noqa: E402
from stores.history_db import HistoryDB                      # noqa: E402

TODAY = date.today().isoformat()
YESTERDAY = (date.today() - timedelta(days=1)).isoformat()


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class FakeGrok:
    """A stand-in for GrokClient that records the prompt it was given."""

    def __init__(self, answer):
        self.answer = answer
        self.prompts = []

    async def complete(self, prompt):
        self.prompts.append(prompt)
        return self.answer


class FakeArchive:
    """What the service may read off the archive: the db and the query.

    `query` is the REAL `HistoryQuery` over the same handle, not a stub —
    reading the archive through it (instead of through a second hand-written
    SELECT) is what makes media reach the window at all, so a double that
    faked it would hide exactly the bug this shape fixes.

    Notably NOT a `labels` attribute: the real `HistoryService` has none (it
    keeps the store as the private `_labels`), and a double that invents one
    is how the label write came to be dead in the app while green in the
    suite. The store is injected instead.
    """

    def __init__(self, db=None):
        self.db = db
        self.query = HistoryQuery(db) if db is not None else None


#: every world `make_db` opened in this run, closed by `WorldCase.tearDown`
_WORLDS: list = []


def close_worlds() -> None:
    """Close every world this module opened.

    `HistoryDB` runs aiosqlite's connection worker, and that thread is NOT a
    daemon thread: a world left open parks the interpreter in
    `threading._shutdown` after the last test, so the run never returns even
    though every test passed (measured 2026-09-14 on this suite: 3 030 green,
    then rc 124 at 10 minutes). `close()` is idempotent — it swaps the
    connection out first — so a test that closes its own world is not
    punished, and the repo's other database suites clean up in `tearDown`
    for the same reason.
    """
    while _WORLDS:
        run(_WORLDS.pop().close())


class WorldCase(unittest.TestCase):
    """Base for the tests that open a real world through `make_db`."""

    def tearDown(self):
        close_worlds()


async def make_db(rows):
    path = os.path.join(tempfile.mkdtemp(), "world.db")
    db = await HistoryDB(path).init()
    _WORLDS.append(db)
    await db.execute("INSERT INTO persons (nick, nick_lc) VALUES (?,?)",
                     ("Anna", "anna"))
    pid = await db.scalar("SELECT id FROM persons WHERE nick='Anna'")
    for ordinal, (direction, who, text, day) in enumerate(rows, start=1):
        await db.execute(
            "INSERT INTO messages (person_id, ord, direction, from_nick, "
            "text, day, ts_display) VALUES (?,?,?,?,?,?,?)",
            (pid, ordinal, direction, who, text, day, "12:0%d" % (ordinal % 10)))
    await db.commit()
    return db


class TestTodaysMessages(WorldCase):
    def service(self, rows, grok=None):
        db = run(make_db(rows))
        return BotChatService(archive=FakeArchive(db), config=None,
                              grok=grok or FakeGrok(None))

    def test_only_the_current_day_is_loaded(self):
        svc = self.service([("in", "Anna", "old news", YESTERDAY),
                            ("out", "me", "hi", TODAY),
                            ("in", "Anna", "hello there", TODAY)])
        page = run(svc.today("Anna"))
        self.assertEqual([i["text"] for i in page["items"]],
                         ["hi", "hello there"])
        self.assertFalse(page["empty"])
        self.assertEqual(page["day"], TODAY)

    def test_a_day_without_messages_is_empty_not_broken(self):
        svc = self.service([("in", "Anna", "old news", YESTERDAY)])
        page = run(svc.today("Anna"))
        self.assertEqual(page["items"], [])
        self.assertTrue(page["empty"])
        self.assertEqual(page["reason"], "no_messages_today")

    def test_a_closed_archive_says_why(self):
        svc = BotChatService(archive=FakeArchive(None), config=None)
        page = run(svc.today("Anna"))
        self.assertTrue(page["empty"])
        self.assertEqual(page["reason"], "archive_closed")

    def test_the_two_empty_causes_do_not_share_a_message(self):
        """The user can act on one of them and not the other, so "nothing
        today" must say WHICH nothing it is — and name the day, because the
        archive dates a row from the page's clock stamps, not this process's
        calendar (just after midnight a fresh chat can still be yesterday)."""
        closed = bot_chat.empty_detail("Anna", {"reason": "archive_closed"})
        none_today = bot_chat.empty_detail(
            "Anna", {"reason": "no_messages_today", "day": TODAY})
        self.assertIn("database", closed)
        self.assertNotEqual(closed, none_today)
        self.assertIn(TODAY, none_today)
        self.assertIn("previous day", none_today)

    def test_a_closed_database_handle_is_not_read_from(self):
        """`db` outlives a world switch; `is_open` is the honest check."""
        db = run(make_db([("in", "Anna", "hi", TODAY)]))
        run(db.close())
        page = run(BotChatService(archive=FakeArchive(db),
                                  config=None).today("Anna"))
        self.assertEqual(page["reason"], "archive_closed")

    def test_deleted_messages_are_invisible(self):
        db = run(make_db([("in", "Anna", "oops", TODAY)]))
        run(db.execute("UPDATE messages SET deleted_at='2026-09-13'"))
        run(db.commit())
        svc = BotChatService(archive=FakeArchive(db), config=None)
        self.assertTrue(run(svc.today("Anna"))["empty"])


async def add_media_message(db, url, kind, cache_path, ordinal):
    """A media-only message (no text) — a GIF, exactly as the collector files it."""
    await db.execute(
        "INSERT INTO media (url, kind, state, cache_path) VALUES (?,?,?,?)",
        (url, kind, "cached" if cache_path else "pending", cache_path))
    mid = await db.scalar("SELECT id FROM media WHERE url=?", (url,))
    pid = await db.scalar("SELECT id FROM persons WHERE nick='Anna'")
    await db.execute(
        "INSERT INTO messages (person_id, ord, direction, from_nick, text, "
        "kind, media_id, day, ts_display) VALUES (?,?,?,?,?,?,?,?,?)",
        (pid, ordinal, "in", "Anna", "", kind, mid, TODAY, "12:30"))
    await db.commit()
    return mid


class TestMediaReachesTheWindow(WorldCase):
    """The GIF bug: a media message used to arrive with no media at all.

    `today()` hand-wrote its own four-column SELECT with no `media` join, so
    a GIF row reached the window as an empty message. The renderer was never
    the problem. Reading through `HistoryQuery.page` — the archive's ONE read,
    the same one the DB window uses — is what fixes it, so these tests assert
    the item shape the DB window's renderer already knows how to draw.
    """

    def service(self, cache_path=""):
        db = run(make_db([("in", "Anna", "look at this", TODAY)]))
        path = cache_path
        if path == "auto":
            handle, path = tempfile.mkstemp(suffix=".gif")
            os.close(handle)
        run(add_media_message(db, "http://x/a.gif", "gif", path, 2))
        return BotChatService(archive=FakeArchive(db), config=None,
                              grok=FakeGrok(None)), path

    def test_a_gif_message_carries_its_media_block(self):
        svc, path = self.service("auto")
        items = run(svc.today("Anna"))["items"]
        self.assertEqual(len(items), 2, "the media message must be there")
        media = items[-1]["media"]
        self.assertEqual(media["kind"], "gif")
        self.assertEqual(media["url"], "http://x/a.gif")
        self.assertEqual(media["path"], path, "the cached file the UI loads")
        self.assertEqual(media["state"], "cached")

    def test_a_media_file_that_vanished_is_reported_missing_not_broken(self):
        """The DB view downgrades it so the UI shows "click to restore"
        instead of a broken <img>. Bot Chat inherits that for free."""
        svc, _ = self.service("/nope/gone.gif")
        media = run(svc.today("Anna"))["items"][-1]["media"]
        self.assertEqual(media["state"], "missing")
        self.assertEqual(media["path"], "")

    def test_the_items_keep_the_shape_the_db_renderer_expects(self):
        svc, _ = self.service("auto")
        item = run(svc.today("Anna"))["items"][-1]
        for key in ("dir", "from", "text", "time", "day", "kind", "media"):
            self.assertIn(key, item, key)

    def test_a_media_only_message_is_not_dropped_from_the_ai_context(self):
        """A day of nothing but stickers must not reach Grok as an empty
        transcript — the model would be answering about nothing."""
        svc, _ = self.service("auto")
        page = run(svc.today("Anna"))
        transcript = bot_chat.as_transcript(page["items"])
        self.assertIn("[gif]", transcript)
        self.assertIn("look at this", transcript)

    def test_a_media_only_answer_is_the_last_message(self):
        svc, _ = self.service("auto")
        page = run(svc.today("Anna"))
        self.assertEqual(bot_chat.item_text(
            bot_chat.last_inbound(page["items"])), "[gif]")


class TestItemText(unittest.TestCase):
    def test_text_wins_media_fills_in_and_plain_empty_stays_empty(self):
        self.assertEqual(bot_chat.item_text({"text": " hi "}), "hi")
        self.assertEqual(bot_chat.item_text(
            {"text": "", "media": {"kind": "gif"}}), "[gif]")
        self.assertEqual(bot_chat.item_text(
            {"text": "", "kind": "image", "media": {}}), "[image]")
        self.assertEqual(bot_chat.item_text({"text": "", "kind": "text"}), "")
        self.assertEqual(bot_chat.item_text({}), "")


class TestItemsOfDay(unittest.TestCase):
    def test_it_keeps_only_the_named_day(self):
        items = [{"day": TODAY, "text": "a"}, {"day": YESTERDAY, "text": "b"},
                 {"text": "c"}]
        self.assertEqual([i["text"] for i in
                          bot_chat.items_of_day(items, TODAY)], ["a"])
        self.assertEqual(bot_chat.items_of_day(None, TODAY), [])


class TestTranscriptHelpers(unittest.TestCase):
    ITEMS = [{"dir": "out", "from": "me", "text": "hi"},
             {"dir": "in", "from": "Anna", "text": "hello"},
             {"dir": "in", "from": "Anna", "text": "   "}]

    def test_transcript_keeps_order_and_drops_blank_lines(self):
        self.assertEqual(as_transcript(self.ITEMS), "me: hi\nAnna: hello")

    def test_last_inbound_ignores_my_own_and_blank_messages(self):
        self.assertEqual(last_inbound(self.ITEMS)["text"], "hello")

    def test_last_inbound_of_a_one_sided_day_is_empty(self):
        self.assertEqual(last_inbound([{"dir": "out", "text": "hi"}]), {})


class TestSuggestAndAnalyze(WorldCase):
    def build(self, answer, rows=None):
        rows = rows if rows is not None else [
            ("out", "me", "hi", TODAY), ("in", "Anna", "hello you", TODAY)]
        db = run(make_db(rows))
        grok = FakeGrok(answer)
        return BotChatService(archive=FakeArchive(db), config=None,
                              grok=grok), grok

    def test_suggestion_comes_back_pending_and_is_not_sent(self):
        from core.result import Ok
        svc, grok = self.build(Ok("See you tomorrow?"))
        result = run(svc.suggest_reply("Anna"))
        self.assertTrue(result.is_ok)
        self.assertEqual(result.value["state"], "pending")
        self.assertEqual(result.value["text"], "See you tomorrow?")
        self.assertIn("me: hi", grok.prompts[0])

    def test_a_day_with_no_messages_refuses_before_calling_grok(self):
        svc, grok = self.build(None, rows=[("in", "Anna", "x", YESTERDAY)])
        result = run(svc.suggest_reply("Anna"))
        self.assertTrue(result.is_err)
        self.assertEqual(result.code, "bot_no_messages")
        self.assertEqual(grok.prompts, [])

    def test_a_grok_failure_is_returned_not_raised(self):
        from core.result import Err
        svc, _ = self.build(Err("grok_no_key", "no key"))
        self.assertTrue(run(svc.suggest_reply("Anna")).is_err)
        self.assertTrue(run(svc.analyze_reaction("Anna")).is_err)

    def test_analysis_classifies_and_writes_nothing(self):
        from core.result import Ok
        svc, grok = self.build(Ok("negative - they told me to go away"))
        result = run(svc.analyze_reaction("Anna"))
        self.assertEqual(result.value["reaction"], "negative")
        self.assertEqual(result.value["state"], "pending")
        self.assertIn("hello you", grok.prompts[0])
        self.assertIsNone(svc.labels)      # no label store touched at all

    def test_analysis_needs_an_answer_from_the_person(self):
        svc, grok = self.build(None, rows=[("out", "me", "hi", TODAY)])
        result = run(svc.analyze_reaction("Anna"))
        self.assertEqual(result.code, "bot_no_answer")
        self.assertEqual(grok.prompts, [])

    def test_preview_shows_the_rendered_prompt(self):
        svc, _ = self.build(None)
        preview = run(svc.preview("Anna", "suggest_reply"))
        self.assertIn("Anna", preview["prompt"])
        self.assertIn("hello you", preview["prompt"])


class FakeParser:
    """Stands in for the ChatParser: reports who the open tab talks to."""

    def __init__(self, partner="Anna", boom=False):
        self.partner = partner
        self.boom = boom

    async def state(self):
        if self.boom:
            raise RuntimeError("page gone")
        return {"partner": self.partner}


class TestDeliver(unittest.TestCase):
    class FakeCdp:
        is_connected = True

    def deliver(self, text, nick="Anna", parser=None):
        return run(bot_chat.deliver(self.FakeCdp(), nick, text,
                                    parser=parser or FakeParser()))

    def test_an_empty_message_is_refused(self):
        self.assertEqual(self.deliver("  ").code, "bot_empty_message")

    def test_a_disconnected_tab_is_refused(self):
        self.assertEqual(
            run(bot_chat.deliver(None, "Anna", "hi")).code,
            "bot_not_connected")

    def test_a_failed_type_stops_before_clicking_send(self):
        from backend import message_injector
        calls = []

        async def no_type(*_a, **_k):
            calls.append("type")
            return False

        async def click(*_a, **_k):
            calls.append("send")
            return True

        original = (message_injector.type_message, message_injector.click_send)
        message_injector.type_message, message_injector.click_send = (no_type,
                                                                      click)
        try:
            result = self.deliver("hi")
        finally:
            message_injector.type_message, message_injector.click_send = original
        self.assertEqual(result.code, "bot_type_failed")
        self.assertEqual(calls, ["type"])

    def test_a_delivered_message_answers_with_its_text(self):
        from backend import message_injector

        async def ok(*_a, **_k):
            return True

        original = (message_injector.type_message, message_injector.click_send)
        message_injector.type_message, message_injector.click_send = (ok, ok)
        try:
            result = self.deliver("hi")
        finally:
            message_injector.type_message, message_injector.click_send = original
        self.assertEqual(result.value, "hi")


class TestTheRecipientIsVerified(unittest.TestCase):
    """Sending is the only irreversible act here — it must hit the right chat.

    The window's person is chosen in User Memory; the browser's open tab is
    chosen by whatever the user last clicked. When they disagree the message
    must NOT go out: `chat_sync` already refuses to *read* a mismatched
    conversation (`partner_mismatch`), and writing to the wrong person is
    worse than reading the wrong one.
    """

    class FakeCdp:
        is_connected = True

    def setUp(self):
        from backend import message_injector
        self.sent = []

        async def typed(_cdp, text, *a, **k):
            self.sent.append(text)
            return True

        async def clicked(*_a, **_k):
            return True

        self._original = (message_injector.type_message,
                          message_injector.click_send)
        message_injector.type_message = typed
        message_injector.click_send = clicked
        self.injector = message_injector

    def tearDown(self):
        (self.injector.type_message,
         self.injector.click_send) = self._original

    def send(self, nick, parser):
        return run(bot_chat.deliver(self.FakeCdp(), nick, "hi", parser=parser))

    def test_the_matching_chat_is_delivered_to(self):
        self.assertTrue(self.send("Anna", FakeParser("Anna")).is_ok)
        self.assertEqual(self.sent, ["hi"])

    def test_another_persons_open_chat_refuses_and_sends_NOTHING(self):
        result = self.send("Anna", FakeParser("Boris"))
        self.assertTrue(result.is_err)
        self.assertEqual(result.code, "bot_wrong_chat")
        self.assertEqual(self.sent, [], "not one keystroke may reach the page")
        self.assertIn("Boris", result.detail)
        self.assertIn("Anna", result.detail)

    def test_the_comparison_ignores_case_and_stray_whitespace(self):
        self.assertTrue(self.send("Anna", FakeParser("  anna ")).is_ok)

    def test_an_unreadable_page_refuses_too_the_gate_fails_closed(self):
        for parser in (FakeParser(boom=True), FakeParser(""), None):
            result = self.send("Anna", parser)
            self.assertEqual(result.code, "bot_unknown_chat")
        self.assertEqual(self.sent, [])


class FakeResponse:
    def __init__(self, status, body):
        self.status = status
        self._body = body

    async def json(self):
        return self._body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False


class FakeSession:
    def __init__(self, response):
        self._response = response
        self.calls = []

    def post(self, url, json=None, headers=None):
        self.calls.append({"url": url, "json": json, "headers": headers})
        return self._response

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False


class TestGrokClient(unittest.TestCase):
    def config(self, **values):
        cfg = ConfigManager(os.path.join(tempfile.mkdtemp(), "config.json"))
        for key, value in values.items():
            cfg.set("grok", key, value)
        return cfg

    def client(self, response, **values):
        session = FakeSession(response)
        return GrokClient(config=self.config(**values),
                          session_factory=lambda: session), session

    def test_a_missing_key_never_reaches_the_network(self):
        client, session = self.client(None)
        self.assertEqual(run(client.complete("hi")).code, "grok_no_key")
        self.assertEqual(session.calls, [])

    def test_an_empty_prompt_is_refused(self):
        client, _ = self.client(None, api_key="k")
        self.assertEqual(run(client.complete(" ")).code, "grok_no_prompt")

    def test_a_successful_call_returns_the_assistant_text(self):
        body = {"choices": [{"message": {"content": " hello "}}]}
        client, session = self.client(FakeResponse(200, body), api_key="k",
                                      model="grok-test")
        self.assertEqual(run(client.complete("say hi")).value, "hello")
        self.assertEqual(session.calls[0]["json"]["model"], "grok-test")
        self.assertEqual(session.calls[0]["headers"]["Authorization"],
                         "Bearer k")

    def test_an_http_error_is_a_typed_failure(self):
        client, _ = self.client(FakeResponse(500, {}), api_key="k")
        self.assertEqual(run(client.complete("hi")).code, "grok_http")

    def test_a_raising_transport_is_a_typed_failure(self):
        def boom():
            raise OSError("network is down")

        client = GrokClient(config=self.config(api_key="k"),
                            session_factory=boom)
        self.assertEqual(run(client.complete("hi")).code, "grok_unreachable")

    def test_body_parsing_distinguishes_every_bad_shape(self):
        self.assertEqual(reply_text("nope").code, "grok_bad_body")
        self.assertEqual(reply_text({"choices": []}).code, "grok_no_choices")
        self.assertEqual(reply_text({"choices": "no"}).code, "grok_no_choices")
        # a present-but-empty choice reads as "no usable choice", not as a
        # model that answered with nothing
        self.assertEqual(reply_text({"choices": [None]}).code,
                         "grok_no_choices")
        self.assertEqual(
            reply_text({"choices": [{"message": {"content": ""}}]}).code,
            "grok_empty")


class TestTheGoogleCallEndToEnd(unittest.TestCase):
    """The whole transport against a fake session — not just the parsers.

    Unit-testing the four differing functions would pass even if the client
    never called them, which is exactly the kind of green-but-dead test this
    codebase has been bitten by before.
    """

    def client(self, response):
        cfg = ConfigManager(os.path.join(tempfile.mkdtemp(), "config.json"))
        cfg.set("grok", "provider", "google")
        cfg.set("grok", "providers",
                {"google": {"api_key": "AIza-test-key",
                            "model": "gemini-test"}})
        session = FakeSession(response)
        return GrokClient(config=cfg, session_factory=lambda: session), session

    def test_a_google_call_uses_googles_url_header_and_body(self):
        body = {"candidates": [{"content": {"parts": [{"text": " hi "}]},
                                "finishReason": "STOP"}]}
        client, session = self.client(FakeResponse(200, body))
        self.assertEqual(run(client.complete("say hi")).value, "hi")
        call = session.calls[0]
        self.assertIn("gemini-test:generateContent", call["url"])
        self.assertEqual(call["headers"]["x-goog-api-key"], "AIza-test-key")
        self.assertNotIn("Authorization", call["headers"])
        self.assertEqual(call["json"]["contents"][0]["parts"][0]["text"],
                         "say hi")

    def test_the_key_is_never_put_in_the_url(self):
        client, session = self.client(FakeResponse(200, {"candidates": []}))
        run(client.complete("hi"))
        self.assertNotIn("AIza-test-key", session.calls[0]["url"])

    def test_an_http_error_is_typed_not_raised(self):
        client, _ = self.client(FakeResponse(403, {}))
        self.assertEqual(run(client.complete("hi")).code, "grok_http")

    def test_switching_provider_switches_the_wire_format(self):
        """The same client class, two completely different requests."""
        cfg = ConfigManager(os.path.join(tempfile.mkdtemp(), "config.json"))
        cfg.set("grok", "api_key", "xai-key")
        session = FakeSession(FakeResponse(
            200, {"choices": [{"message": {"content": "ok"}}]}))
        grok = GrokClient(config=cfg, session_factory=lambda: session)
        run(grok.complete("hi"))
        self.assertIn("messages", session.calls[0]["json"])
        self.assertIn("api.x.ai", session.calls[0]["url"])


class TestGoogleProvider(unittest.TestCase):
    """Gemini's wire format, which agrees with Grok's about nothing."""

    SPEC = bot_providers.spec_of("google")

    def test_the_key_goes_in_the_header_not_the_url(self):
        """Putting an API key in a query string leaks it into every proxy
        log and browser history along the way."""
        headers = bot_providers.headers_of(self.SPEC, "SECRET")
        self.assertEqual(headers["x-goog-api-key"], "SECRET")
        self.assertNotIn("Authorization", headers)
        self.assertNotIn("SECRET", bot_providers.endpoint(
            self.SPEC, self.SPEC.url, "gemini-2.0-flash"))

    def test_the_model_goes_in_the_path(self):
        self.assertEqual(
            bot_providers.endpoint(self.SPEC, self.SPEC.url, "gemini-x"),
            "https://generativelanguage.googleapis.com/v1beta/models/"
            "gemini-x:generateContent")

    def test_the_body_is_contents_and_parts(self):
        body = bot_providers.body_of(self.SPEC, "m", "hello")
        self.assertEqual(body["contents"][0]["parts"][0]["text"], "hello")
        self.assertNotIn("messages", body)

    def test_it_reads_the_reply_out_of_candidates(self):
        body = {"candidates": [{"content": {"parts": [{"text": "hi "},
                                                      {"text": "there"}]},
                                "finishReason": "STOP"}]}
        self.assertEqual(bot_providers.reply_of(self.SPEC, body).value,
                         "hi there")

    def test_a_safety_refusal_is_named_not_called_empty(self):
        """A blocked prompt returns a candidate with no text. Reporting
        that as "empty answer" sends the user hunting the wrong bug."""
        body = {"candidates": [{"content": {"parts": []},
                                "finishReason": "SAFETY"}]}
        result = bot_providers.reply_of(self.SPEC, body)
        self.assertEqual(result.code, "grok_refused")
        self.assertIn("safety", result.detail)

    def test_a_blocked_prompt_is_reported(self):
        body = {"promptFeedback": {"blockReason": "SAFETY"}}
        self.assertEqual(bot_providers.reply_of(self.SPEC, body).code,
                         "grok_refused")

    def test_a_truncated_answer_is_still_an_answer(self):
        body = {"candidates": [{"content": {"parts": [{"text": "half a sen"}]},
                                "finishReason": "MAX_TOKENS"}]}
        self.assertEqual(bot_providers.reply_of(self.SPEC, body).value,
                         "half a sen")

    def test_no_candidates_and_a_non_object_are_typed_errors(self):
        self.assertEqual(bot_providers.reply_of(self.SPEC, {}).code,
                         "grok_no_choices")
        self.assertEqual(bot_providers.reply_of(self.SPEC, "nope").code,
                         "grok_bad_body")
        self.assertEqual(
            bot_providers.reply_of(self.SPEC,
                                   {"candidates": [{"content": {}}]}).code,
            "grok_empty")


class TestProviderCatalog(unittest.TestCase):
    def test_both_providers_are_offered_with_a_title(self):
        ids = [p["id"] for p in bot_providers.catalog()]
        self.assertIn("grok", ids)
        self.assertIn("google", ids)
        for entry in bot_providers.catalog():
            self.assertTrue(entry["title"])
            self.assertTrue(entry["model"])

    def test_an_unknown_provider_falls_back_instead_of_raising(self):
        self.assertEqual(bot_providers.spec_of("nope").id, "grok")
        self.assertEqual(bot_providers.spec_of("").id, "grok")

    def test_adding_a_provider_is_a_table_entry(self):
        """Every provider must be complete — a half-filled spec would fail
        at request time, in front of the user."""
        for spec in bot_providers.PROVIDERS.values():
            self.assertTrue(spec.url.startswith("https://"))
            self.assertIn(spec.auth, ("bearer", "x-goog-api-key"))
            self.assertIn(spec.shape, ("openai", "gemini"))


class TestMaskedKeys(unittest.TestCase):
    def test_a_key_is_shown_as_proof_not_as_a_secret(self):
        masked = mask("xai-abcdefghijklmnop")
        self.assertNotIn("efghij", masked)
        self.assertTrue(masked.startswith("xai-"))
        self.assertTrue(masked.endswith("mnop"))

    def test_a_short_key_is_never_partly_revealed(self):
        self.assertEqual(mask("tiny"), "set")
        self.assertEqual(mask(""), "")


class TestGrokConnectionSettings(unittest.TestCase):
    """The key must be settable from the app, and the error must not lie.

    Before this round the key existed only in `settings.json` — nothing in
    the UI wrote it — while `complete()` told the user to "set it in the
    Prompt Editor window", which had no such field. The feature was
    unusable out of the box and the instruction pointed nowhere.
    """

    def setUp(self):
        self.cfg = ConfigManager(os.path.join(tempfile.mkdtemp(),
                                              "config.json"))
        self.settings = GrokSettings(self.cfg)

    def test_legacy_settings_are_still_readable(self):
        """`GrokSettings` is now a READER only — the connection store uses it
        to adopt an install configured before connections existed. Writing
        moved to `ConnectionStore.save`, so there is one way to store a key."""
        self.cfg.set("grok", "api_key", "xai-old-key")
        self.assertEqual(GrokSettings(self.cfg).api_key, "xai-old-key")
        for gone in ("save", "use", "state"):
            self.assertFalse(hasattr(GrokSettings(self.cfg), gone),
                             gone + " is a second way to write a key")

    def test_the_missing_key_error_names_a_place_that_exists(self):
        client = GrokClient(config=self.cfg, session_factory=None)
        detail = run(client.complete("hi")).detail
        self.assertIn("AI Connections", detail)
        repo = os.path.dirname(ROOT)
        html = open(os.path.join(repo, "ui", "index.html"),
                    encoding="utf-8").read()
        for element in ('id="botPromptSettingsBtn"', 'id="botProviderKey"'):
            self.assertIn(element, html,
                          "the error sends the user somewhere that exists")

    def test_the_missing_key_error_names_the_provider_that_needs_one(self):
        """"No API key" is useless when two providers are configurable."""
        self.cfg.set("grok", "provider", "google")
        detail = run(GrokClient(config=self.cfg).complete("hi")).detail
        self.assertIn("Google", detail)


class TestVariableLibrary(unittest.TestCase):
    """The placeholders the Prompt Editor offers and how they resolve."""

    CTX = {"person_name": "Anna", "last_msg": "yes!", "msg": "custom text",
           "all_msg": "Anna: one\nme: two\nAnna: three\nme: four",
           "reaction_label": "Positive first reaction"}

    def test_every_advertised_variable_actually_resolves(self):
        """The library is a promise: if the editor lists it, it must work."""
        for spec in bot_variables.catalog():
            filled = bot_variables.fill(spec["token"], self.CTX)
            self.assertNotEqual(filled, spec["token"],
                                spec["token"] + " was not resolved")

    def test_the_six_documented_variables_are_offered(self):
        names = [spec["name"] for spec in bot_variables.catalog()]
        self.assertEqual(names, ["msg", "last_msg", "all_msg",
                                 "last_x_messages", "person_name",
                                 "reaction_label"])

    def test_each_variable_is_documented_with_an_example(self):
        for spec in bot_variables.catalog():
            self.assertTrue(spec["description"].strip(), spec["name"])
            self.assertTrue(spec["example"].strip(), spec["name"])

    def test_a_counted_variable_takes_that_many_messages(self):
        self.assertEqual(bot_variables.fill("{last_2_messages}", self.CTX),
                         "Anna: three\nme: four")
        self.assertEqual(bot_variables.fill("{last_1_messages}", self.CTX),
                         "me: four")

    def test_a_counted_variable_cannot_ask_for_the_whole_archive(self):
        self.assertEqual(bot_variables.count_of("last_9999_messages"),
                         bot_variables.MAX_COUNT)
        self.assertEqual(bot_variables.count_of("last_0_messages"), 1)

    def test_the_literal_x_form_has_a_sane_default(self):
        self.assertEqual(bot_variables.count_of("last_x_messages"),
                         bot_variables.DEFAULT_COUNT)

    def test_an_unknown_placeholder_survives_instead_of_exploding(self):
        self.assertEqual(bot_variables.fill("a {nope} b", self.CTX),
                         "a {nope} b")

    def test_validate_separates_known_unknown_and_malformed(self):
        report = bot_variables.validate("{person_name} {nope} {Bad Name}")
        self.assertEqual(report["used"], ["person_name"])
        self.assertEqual(report["unknown"], ["nope"])
        self.assertIn("{Bad Name}", report["malformed"])
        self.assertFalse(report["ok"])

    def test_validate_flags_an_unclosed_brace(self):
        self.assertIn("unbalanced braces",
                      bot_variables.validate("hi {person_name")["malformed"])

    def test_a_clean_template_validates(self):
        report = bot_variables.validate("Hi {person_name}, re: {last_msg}")
        self.assertTrue(report["ok"])
        self.assertEqual(report["used"], ["last_msg", "person_name"])

    def test_an_unknown_name_is_reported_once_in_order(self):
        self.assertEqual(
            bot_variables.validate("{a} {b} {a}")["unknown"], ["a", "b"])

    def test_empty_text_is_not_an_error(self):
        self.assertEqual(bot_variables.fill("", self.CTX), "")
        self.assertTrue(bot_variables.validate("")["ok"])

    def test_a_missing_context_value_becomes_empty_not_a_crash(self):
        self.assertEqual(bot_variables.fill("[{reaction_label}]", {}), "[]")


class TestPromptContext(WorldCase):
    """What the variables are resolved against — and what they cannot see."""

    def service(self):
        db = run(make_db([("in", "Anna", "hello there", TODAY)]))
        return BotChatService(archive=FakeArchive(db), config=None,
                              grok=FakeGrok(None))

    def test_the_context_carries_every_variable_the_editor_offers(self):
        svc = self.service()
        page = run(svc.today("Anna"))
        ctx = svc.context_of("Anna", page)
        for name in ("person_name", "last_msg", "all_msg", "msg",
                     "reaction_label"):
            self.assertIn(name, ctx, name)

    def test_msg_is_the_custom_text_when_there_is_one(self):
        svc = self.service()
        page = run(svc.today("Anna"))
        self.assertEqual(svc.context_of("Anna", page, "typed")["msg"], "typed")
        self.assertEqual(svc.context_of("Anna", page)["msg"], "hello there")

    def test_the_context_holds_no_private_or_system_data(self):
        """A prompt can only ever contain this conversation. Nothing reaches
        the config, the API key, the filesystem or another person, because
        the resolver is never handed them."""
        svc = self.service()
        ctx = svc.context_of("Anna", run(svc.today("Anna")))
        self.assertEqual(sorted(ctx), ["all_msg", "last_msg", "msg",
                                       "person_name", "reaction_label"])


class TestPromptLibrary(unittest.TestCase):
    def setUp(self):
        self.cfg = ConfigManager(os.path.join(tempfile.mkdtemp(),
                                              "config.json"))
        self.lib = PromptLibrary(self.cfg)

    def test_defaults_are_used_until_the_user_edits(self):
        self.assertIn("{conversation}", self.lib.text("suggest_reply"))
        self.assertFalse(self.lib.all()[0]["edited"])

    def test_an_edit_is_stored_and_survives_a_reopen(self):
        self.assertTrue(self.lib.save("suggest_reply", "Say hi to {nick}"))
        reopened = PromptLibrary(ConfigManager(self.cfg._path))
        self.assertEqual(reopened.text("suggest_reply"), "Say hi to {nick}")
        self.assertTrue(reopened.all()[0]["edited"])

    def test_an_empty_template_is_refused_and_never_stored(self):
        self.assertFalse(self.lib.save("suggest_reply", "   "))
        self.assertFalse(self.lib.save("no_such_template", "hi"))
        self.assertEqual(self.lib.text("suggest_reply"),
                         self.lib.all()[0]["default"])

    def test_an_unknown_placeholder_no_longer_destroys_the_template(self):
        """It used to: `{tone}` made the template "unusable", so the user's
        work was silently replaced by the shipped default. Now the template
        is kept, the unknown placeholder survives into the prompt visibly,
        and `validate` is what tells the user about it."""
        self.assertTrue(self.lib.save("suggest_reply", "hi {tone} {nick}"))
        self.assertEqual(self.lib.text("suggest_reply"), "hi {tone} {nick}")
        self.assertEqual(
            self.lib.render("suggest_reply", {"person_name": "Anna"}),
            "hi {tone} Anna")
        self.assertEqual(bot_variables.validate("hi {tone}")["unknown"],
                         ["tone"])

    def test_reset_forgets_the_edit(self):
        self.lib.save("analyze_reaction", "judge {last_message}")
        self.assertTrue(self.lib.reset("analyze_reaction"))
        self.assertFalse(self.lib.reset("analyze_reaction"))
        self.assertIn("{last_message}", self.lib.text("analyze_reaction"))

    def test_render_fills_every_placeholder(self):
        self.lib.save("suggest_reply", "{person_name}|{all_msg}|{last_msg}")
        self.assertEqual(
            self.lib.render("suggest_reply",
                            {"person_name": "Anna", "all_msg": "c",
                             "last_msg": "l"}),
            "Anna|c|l")

    def test_templates_saved_with_the_old_names_still_render(self):
        """`{nick}` etc. shipped first and are sitting in users' configs.
        Renaming without aliasing them would be data loss, not a rename."""
        self.lib.save("suggest_reply", "{nick}|{conversation}|{last_message}")
        self.assertEqual(
            self.lib.render("suggest_reply",
                            {"person_name": "Anna", "all_msg": "c",
                             "last_msg": "l"}),
            "Anna|c|l")

    def test_is_usable_rejects_only_non_text(self):
        self.assertFalse(is_usable(None))
        self.assertFalse(is_usable("   "))
        self.assertTrue(is_usable("{oops}"), "unknown is not broken")
        self.assertTrue(is_usable("plain text"))



class TestHistoryScope(WorldCase):
    """The "today only" checkbox — item 5.

    It must reach the AI calls, not just the message list: a box that
    changed what the user sees while the model kept reading a different
    conversation would be worse than no box.
    """

    def service(self, rows=None):
        from core.result import Ok
        db = run(make_db(rows if rows is not None else [
            ("in", "Anna", "ancient", "2020-01-01"),
            ("out", "me", "older", YESTERDAY),
            ("in", "Anna", "hello today", TODAY)]))
        grok = FakeGrok(Ok("sure"))
        return BotChatService(archive=FakeArchive(db), config=None,
                              grok=grok), grok

    def test_today_is_the_default_and_filters_by_day(self):
        svc, _ = self.service()
        page = run(svc.load("Anna"))
        self.assertEqual([i["text"] for i in page["items"]], ["hello today"])
        self.assertEqual(page["scope"], "today")

    def test_all_returns_the_whole_conversation(self):
        svc, _ = self.service()
        page = run(svc.load("Anna", "all"))
        self.assertEqual([i["text"] for i in page["items"]],
                         ["ancient", "older", "hello today"])
        self.assertEqual(page["scope"], "all")

    def test_the_scope_reaches_the_prompt_not_just_the_list(self):
        svc, grok = self.service()
        run(svc.suggest_reply("Anna", "all"))
        self.assertIn("ancient", grok.prompts[-1])
        run(svc.suggest_reply("Anna", "today"))
        self.assertNotIn("ancient", grok.prompts[-1])

    def test_the_analysis_honours_the_scope_too(self):
        """With nothing said today, "today only" has no answer to judge,
        while the wider scope can still reach the last real reply."""
        rows = [("in", "Anna", "left on read yesterday", YESTERDAY)]
        svc, grok = self.service(rows)
        self.assertEqual(run(svc.analyze_reaction("Anna", "today")).code,
                         "bot_no_messages")
        self.assertTrue(run(svc.analyze_reaction("Anna", "all")).is_ok)
        self.assertIn("left on read yesterday", grok.prompts[-1])

    def test_the_preview_honours_the_scope(self):
        """Otherwise the editor would preview a prompt the app never sends."""
        svc, _ = self.service()
        shown = run(svc.preview("Anna", "suggest_reply", "all"))["prompt"]
        self.assertIn("ancient", shown)

    def test_full_history_is_still_capped_and_says_so(self):
        """"Not restricted to today" must not mean "post the whole archive
        to a metered API" — and a silently shortened history is a wrong
        answer the user cannot see."""
        rows = [("in", "Anna", f"msg {n}", TODAY)
                for n in range(bot_chat.CONTEXT_LIMIT + 15)]
        svc, _ = self.service(rows)
        page = run(svc.load("Anna", "all"))
        self.assertEqual(len(page["items"]), bot_chat.CONTEXT_LIMIT)
        self.assertTrue(page["truncated"])
        self.assertEqual(page["total"], bot_chat.CONTEXT_LIMIT + 15)
        self.assertEqual(page["items"][-1]["text"],
                         f"msg {bot_chat.CONTEXT_LIMIT + 14}",
                         "the cap must keep the NEWEST messages")

    def test_an_empty_archive_explains_which_scope_was_empty(self):
        db = run(make_db([]))
        svc = BotChatService(archive=FakeArchive(db), config=None,
                             grok=FakeGrok(None))
        every = run(svc.load("Anna", "all"))
        self.assertEqual(every["reason"], "no_messages_at_all")
        self.assertIn("at all", bot_chat.empty_detail("Anna", every))
        just_today = run(svc.load("Anna", "today"))
        self.assertEqual(just_today["reason"], "no_messages_today")
        self.assertIn("today only", bot_chat.empty_detail("Anna", just_today))

    def test_today_stays_available_as_its_own_call(self):
        svc, _ = self.service()
        self.assertEqual(run(svc.today("Anna"))["scope"], "today")


class TestConnections(unittest.TestCase):
    """Named connections — several may share one provider."""

    def config(self):
        return ConfigManager(os.path.join(tempfile.mkdtemp(), "config.json"))

    def store(self):
        return ConnectionStore(self.config())

    def test_a_connection_resolves_its_provider_endpoint_and_model(self):
        store = self.store()
        ident = store.save("", {"title": "Work Gemini", "provider": "google",
                                "api_key": "AIza-k", "model": "gemini-x"})
        conn = store.get(ident)
        self.assertEqual(conn.spec.id, "google")
        self.assertIn("gemini-x:generateContent", conn.endpoint)
        self.assertEqual(conn.title, "Work Gemini")

    def test_a_connection_falls_back_to_its_providers_defaults(self):
        store = self.store()
        ident = store.save("", {"title": "Bare", "provider": "grok",
                                "api_key": "k"})
        conn = store.get(ident)
        self.assertEqual(conn.model, bot_providers.spec_of("grok").model)
        self.assertEqual(conn.url, bot_providers.spec_of("grok").url)

    def test_the_problem_is_named_rather_than_silently_skipped(self):
        store = self.store()
        keyless = store.get(store.save("", {"title": "No key",
                                            "provider": "grok"}))
        self.assertEqual(keyless.problem(), "no API key")
        self.assertFalse(keyless.state()["ok"])

    def test_a_connection_whose_provider_vanished_says_so(self):
        """Config outlives code: a provider id can disappear in an update."""
        conn = bot_connections.Connection("x", {"provider": "obsolete",
                                                "api_key": "k"})
        self.assertIn("unknown provider", conn.problem())

    def test_the_state_never_contains_the_key(self):
        store = self.store()
        conn = store.get(store.save("", {"title": "T", "provider": "grok",
                                         "api_key": "xai-very-secret-key"}))
        self.assertNotIn("very-secret", json.dumps(conn.state()))
        self.assertTrue(conn.state()["masked"])

    def test_two_connections_of_one_provider_keep_separate_models(self):
        store = self.store()
        big = store.save("", {"title": "Big", "provider": "grok",
                              "api_key": "k1", "model": "grok-4.3"})
        cheap = store.save("", {"title": "Cheap", "provider": "grok",
                                "api_key": "k2", "model": "grok-2-latest"})
        self.assertNotEqual(big, cheap)
        self.assertEqual(store.get(big).model, "grok-4.3")
        self.assertEqual(store.get(cheap).model, "grok-2-latest")

    def test_active_falls_back_to_the_first_usable_connection(self):
        """A prompt should run rather than fail because nobody pressed
        "use this one" yet."""
        store = self.store()
        first = store.save("", {"title": "First", "provider": "grok",
                                "api_key": "k"})
        self.assertEqual(store.active().id, first)

    def test_use_refuses_an_unknown_id(self):
        store = self.store()
        self.assertFalse(store.use("nonesuch"))

    def test_ids_do_not_collide_for_similar_names(self):
        store = self.store()
        one = store.save("", {"title": "Grok 4.3", "provider": "grok",
                              "api_key": "k"})
        two = store.save("", {"title": "Grok 2", "provider": "grok",
                              "api_key": "k"})
        self.assertNotEqual(one, two)


class TestLegacySettingsBecomeAConnection(unittest.TestCase):
    """An install configured before connections existed must keep working
    without the user re-typing a key."""

    def config(self):
        cfg = ConfigManager(os.path.join(tempfile.mkdtemp(), "config.json"))
        cfg.set("grok", "api_key", "xai-legacy-key-1")
        cfg.set("grok", "model", "grok-legacy")
        cfg.save()
        return cfg

    def test_an_old_grok_key_is_adopted_as_a_connection(self):
        store = ConnectionStore(self.config())
        keyed = [c for c in store.all() if c.api_key]
        self.assertEqual(len(keyed), 1)
        self.assertEqual(keyed[0].api_key, "xai-legacy-key-1")
        self.assertEqual(keyed[0].model, "grok-legacy")

    def test_the_adopted_connection_is_what_the_client_uses(self):
        cfg = self.config()
        self.assertEqual(client_for(cfg).settings.model, "grok-legacy")

    def test_adoption_does_not_run_twice(self):
        cfg = self.config()
        before = len(ConnectionStore(cfg).all())
        store = ConnectionStore(cfg)
        store.save("", {"title": "Mine", "provider": "google",
                        "api_key": "AIza-k"})
        self.assertEqual(len(ConnectionStore(cfg).all()), before + 1)

    def test_a_fresh_install_is_seeded_but_still_refuses_to_send(self):
        """Seeded rows exist so every provider is SELECTABLE; none of them
        has a key, so nothing can be sent until the user adds one."""
        blank = ConfigManager(os.path.join(tempfile.mkdtemp(), "config.json"))
        store = ConnectionStore(blank)
        self.assertTrue(store.all())
        self.assertFalse(any(c.api_key for c in store.all()))
        self.assertEqual(run(client_for(blank).complete("hi")).code,
                         "grok_no_key")


class TestConnectionsAreSeededPerProvider(unittest.TestCase):
    """Every provider must be reachable from the connections window.

    The bug: the window offered Grok alone, because a connection is created
    by the user and a fresh install had none — Google was a provider the app
    supported and the UI could not reach. Seeding one keyless row per
    provider is what makes "add a Google key" a thing you can DO.
    """

    def config(self):
        return ConfigManager(os.path.join(tempfile.mkdtemp(), "config.json"))

    def test_every_provider_has_a_row_on_a_fresh_install(self):
        listed = {c.provider for c in ConnectionStore(self.config()).all()}
        self.assertEqual(listed, set(bot_providers.PROVIDERS))

    def test_a_seeded_row_is_usable_once_a_key_is_added(self):
        store = ConnectionStore(self.config())
        google = [c for c in store.all() if c.provider == "google"][0]
        self.assertEqual(google.problem(), "no API key")
        store.save(google.id, {"title": google.title, "provider": "google",
                               "api_key": "AIza-typed", "model": ""})
        self.assertEqual(store.get(google.id).problem(), "")

    def test_seeding_never_overwrites_a_configured_connection(self):
        cfg = self.config()
        store = ConnectionStore(cfg)
        ident = store.save("", {"title": "My Grok", "provider": "grok",
                                "api_key": "xai-mine", "model": "grok-4.3"})
        again = ConnectionStore(cfg)
        self.assertEqual(again.get(ident).api_key, "xai-mine")
        self.assertEqual(again.get(ident).model, "grok-4.3")

    def test_a_provider_that_already_has_one_is_not_seeded_again(self):
        """Otherwise every restart would add another blank Grok row."""
        cfg = self.config()
        ConnectionStore(cfg).all()
        first = len(ConnectionStore(cfg).all())
        self.assertEqual(len(ConnectionStore(cfg).all()), first)

    def test_a_legacy_install_is_not_given_a_duplicate_grok(self):
        cfg = self.config()
        cfg.set("grok", "api_key", "xai-legacy")
        cfg.save()
        groks = [c for c in ConnectionStore(cfg).all()
                 if c.provider == "grok"]
        self.assertEqual(len(groks), 1, "adoption and seeding both fired")
        self.assertEqual(groks[0].api_key, "xai-legacy")

    def test_seeding_needs_a_config_and_survives_without_one(self):
        self.assertEqual(ConnectionStore(None).all(), [])


class TestConnectionsWithoutAConfig(unittest.TestCase):
    """The services are built before a config exists (headless runs, several
    bridge tests). Every verb must answer, not raise."""

    def store(self):
        return ConnectionStore(None)

    def test_reads_are_empty(self):
        store = self.store()
        self.assertEqual(store.all(), [])
        self.assertEqual(store.active_id(), "")
        self.assertIsNone(store.get("anything"))

    def test_writes_refuse_rather_than_pretend(self):
        store = self.store()
        self.assertEqual(store.save("", {"title": "T", "provider": "grok"}), "")
        self.assertFalse(store.delete("x"))
        self.assertFalse(store.use("x"))


class TestPresetLibrary(unittest.TestCase):
    def library(self):
        return PresetLibrary(
            ConfigManager(os.path.join(tempfile.mkdtemp(), "config.json")))

    def test_a_preset_round_trips(self):
        lib = self.library()
        ident = lib.save("suggest_reply", "Casual", "hey {person_name}")
        self.assertEqual(lib.get(ident)["text"], "hey {person_name}")
        self.assertEqual(lib.for_template("suggest_reply")[0]["title"],
                         "Casual")

    def test_an_unknown_template_is_refused(self):
        self.assertEqual(self.library().save("nope", "T", "text"), "")

    def test_deleting_an_absent_preset_is_false_not_an_error(self):
        self.assertFalse(self.library().delete("nothing-here"))

    def test_a_preset_only_lists_under_its_own_template(self):
        lib = self.library()
        lib.save("suggest_reply", "A", "a")
        self.assertEqual(lib.for_template("analyze_reaction"), [])

    def test_no_config_is_empty_not_broken(self):
        lib = PresetLibrary(None)
        self.assertEqual(lib.for_template("suggest_reply"), [])
        self.assertEqual(lib.save("suggest_reply", "T", "x"), "")
        self.assertFalse(lib.delete("x"))



if __name__ == "__main__":
    unittest.main()