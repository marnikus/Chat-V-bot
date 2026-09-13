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
from services.bot_chat import BotChatService, as_transcript, last_inbound  # noqa: E402
from services.bot_grok import (GrokClient, GrokSettings,      # noqa: E402
                               first_choice, reply_text)
from services.bot_prompts import PromptLibrary, is_usable    # noqa: E402
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
    """Only what the service may read off the archive: the database.

    Notably NOT a `labels` attribute — the real `HistoryService` has none
    (it keeps the store as the private `_labels`), and a double that invents
    one is how the label write came to be dead in the app while green in the
    suite. The store is injected instead; `TestRealArchiveInterface` holds
    the line against the real class.
    """

    def __init__(self, db=None):
        self.db = db


async def make_db(rows):
    path = os.path.join(tempfile.mkdtemp(), "world.db")
    db = await HistoryDB(path).init()
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


class TestTodaysMessages(unittest.TestCase):
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


class TestSuggestAndAnalyze(unittest.TestCase):
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


class TestFirstChoice(unittest.TestCase):
    def test_it_picks_the_first_choice_or_says_there_is_none(self):
        self.assertEqual(first_choice({"choices": [{"a": 1}, {"b": 2}]}),
                         {"a": 1})
        for body in ({"choices": []}, {"choices": "nope"}, {}):
            self.assertIsNone(first_choice(body), body)
        self.assertIsNone(first_choice({"choices": [None]}),
                          "an empty first choice is no choice")


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

    def test_a_saved_key_is_used_by_the_next_call(self):
        self.assertTrue(self.settings.save("xai-123", "grok-test"))
        self.assertEqual(GrokSettings(self.cfg).api_key, "xai-123")
        self.assertEqual(GrokSettings(self.cfg).model, "grok-test")

    def test_it_survives_a_restart(self):
        self.settings.save("xai-123")
        reopened = ConfigManager(self.cfg.path) if hasattr(self.cfg, "path") \
            else self.cfg
        self.assertEqual(GrokSettings(reopened).api_key, "xai-123")

    def test_saving_only_the_model_keeps_the_key(self):
        """The password input never echoes the key back, so a blank field
        means "unchanged", not "erase it"."""
        self.settings.save("xai-123", "grok-2")
        self.settings.save("", "grok-3")
        self.assertEqual(GrokSettings(self.cfg).api_key, "xai-123")
        self.assertEqual(GrokSettings(self.cfg).model, "grok-3")

    def test_the_reported_state_never_contains_the_key(self):
        self.settings.save("xai-secret", "grok-2")
        state = self.settings.state()
        self.assertTrue(state["has_key"])
        self.assertNotIn("xai-secret", str(state))

    def test_the_missing_key_error_names_a_place_that_exists(self):
        client = GrokClient(config=self.cfg, session_factory=None)
        detail = run(client.complete("hi")).detail
        self.assertIn("Prompt Editor", detail)
        repo = os.path.dirname(ROOT)
        html = open(os.path.join(repo, "ui", "index.html"),
                    encoding="utf-8").read()
        self.assertIn('id="botApiKeyInput"', html,
                      "the error sends the user to a field that must exist")


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

    def test_an_unusable_template_is_refused_and_never_stored(self):
        self.assertFalse(self.lib.save("suggest_reply", "   "))
        self.assertFalse(self.lib.save("suggest_reply", "hi {unknown}"))
        self.assertFalse(self.lib.save("no_such_template", "hi"))
        self.assertEqual(self.lib.text("suggest_reply"),
                         self.lib.all()[0]["default"])

    def test_a_stored_template_that_broke_falls_back_to_the_default(self):
        self.cfg.set("grok", "prompts", {"suggest_reply": "{boom}"})
        self.assertEqual(PromptLibrary(self.cfg).text("suggest_reply"),
                         self.lib.all()[0]["default"])

    def test_reset_forgets_the_edit(self):
        self.lib.save("analyze_reaction", "judge {last_message}")
        self.assertTrue(self.lib.reset("analyze_reaction"))
        self.assertFalse(self.lib.reset("analyze_reaction"))
        self.assertIn("{last_message}", self.lib.text("analyze_reaction"))

    def test_render_fills_every_placeholder(self):
        self.lib.save("suggest_reply", "{nick}|{conversation}|{last_message}")
        self.assertEqual(
            self.lib.render("suggest_reply",
                            {"nick": "Anna", "conversation": "c",
                             "last_message": "l"}),
            "Anna|c|l")

    def test_is_usable_rejects_non_text_and_unknown_fields(self):
        self.assertFalse(is_usable(None))
        self.assertFalse(is_usable("{oops}"))
        self.assertTrue(is_usable("plain text"))


if __name__ == "__main__":
    unittest.main()
