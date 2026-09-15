"""Mutation-gap pins for the AI service family.

The mutmut job over `services/bot_chat.py`, `services/bot_connections.py`
and `services/bot_grok.py` left 225 of 886 mutants alive (74.6% killed).
Reading the survivors one diff at a time, they are five families, all of
them literal shapes the behaviour tests never pinned:

  * dict-key renames in returned payloads (``"nick"`` → ``"NICK"``);
  * rewritten `Err` detail strings and log messages;
  * dropped or None-ed call arguments (``state_of(None)``,
    ``type_message(None, …)``);
  * boundary defaults (``mask`` at len 12/13, ``getattr`` fallbacks);
  * ``or``/``and`` and ``continue``/``break`` flips in small guards.

Each class below pins one family the way the user or the wire actually
sees it: whole-dict equality for payload shapes, exact strings for
details and logs, recording fakes for pass-through arguments. A handful
of survivors are genuinely equivalent (a mutated default that a second
fallback immediately re-defaults); those are named in the comments where
the pin around them explains why no test can kill them.
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from backend.config_manager import ConfigManager            # noqa: E402
from services import bot_providers                          # noqa: E402
from services.bot_chat import BotChatService                # noqa: E402
from services.bot_chat import check_recipient, deliver      # noqa: E402
from services.bot_chat import empty_detail, open_partner    # noqa: E402
from services.bot_chat import scoped_page                   # noqa: E402
from services.bot_chat import CONTEXT_LIMIT, SCOPE_TODAY    # noqa: E402
from services.bot_connections import ACTIVE_KEY, SECTION    # noqa: E402
from services.bot_connections import Connection             # noqa: E402
from services.bot_connections import ConnectionStore, slug  # noqa: E402
from services.bot_grok import GrokClient, GrokSettings      # noqa: E402
from services.bot_grok import client_for, mask, reply_text  # noqa: E402
from services.bot_presets import PresetLibrary              # noqa: E402
from services.bot_reactions import ReactionLabels           # noqa: E402
from services.bot_transcript import today_key               # noqa: E402
from stores.label_store import LabelStore                   # noqa: E402


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def tmp_config() -> ConfigManager:
    return ConfigManager(os.path.join(tempfile.mkdtemp(), "config.json"))


def row(text: str, day: str | None = None, direction: str = "in",
        who: str = "Anna") -> dict:
    return {"day": day if day is not None else today_key(),
            "dir": direction, "from": who, "text": text}


class FakeGrok:
    def __init__(self, answer):
        self.answer = answer

    async def complete(self, prompt):
        from core.result import Ok
        return Ok(self.answer)


class FakeParser:
    """Reports who the open tab talks to; `boom` makes the page unreadable."""

    def __init__(self, partner="Anna", boom=False):
        self.partner = partner
        self.boom = boom

    async def state(self):
        if self.boom:
            raise RuntimeError("page gone")
        return {"partner": self.partner}


def labeled_store(reaction="positive", nick="Anna"):
    """A REAL LabelStore with one person carrying one reaction label."""
    store = LabelStore(tmp_config())
    ReactionLabels(store).apply(nick, reaction)
    return store


class StateSpy:
    """Stands in for `reaction_state`, remembering every nick asked for."""

    def __init__(self, state):
        self.state = state
        self.nicks = []

    def __call__(self, nick):
        self.nicks.append(nick)
        return dict(self.state)


def spy_label_name(svc):
    """Record the nicks `active_label_name` is called with, pass-through."""
    calls = []
    original = svc.active_label_name

    def spy(nick):
        calls.append(nick)
        return original(nick)

    svc.active_label_name = spy
    return calls


class FakeQuery:
    def __init__(self, items):
        self._items = items
        self.calls = []

    async def page(self, nick, limit=0):
        self.calls.append((nick, limit))
        return {"items": list(self._items)}


class FakeArchive:
    def __init__(self, items, is_open=True):
        self.query = FakeQuery(items)
        self.db = type("DB", (), {"is_open": is_open})()


class _Ctx:
    def __init__(self, value):
        self._value = value

    async def __aenter__(self):
        return self._value

    async def __aexit__(self, *_exc):
        return False


class FakeResponse:
    """`status` may be absent entirely — the transport must cope."""

    def __init__(self, status="__missing__", body=None):
        if status != "__missing__":
            self.status = status
        self._body = body or {}

    async def json(self):
        return self._body


class FakeSession:
    def __init__(self, response):
        self.response = response
        self.posts = []

    def post(self, url, json=None, headers=None):
        self.posts.append((url, json, headers))
        return _Ctx(self.response)


class StubSettings:
    """The four-property contract GrokClient needs, nothing more."""

    def __init__(self, api_key="k-123", provider="grok", timeout_s=7):
        self.api_key = api_key
        self.spec = bot_providers.spec_of(provider)
        self.model = "stub-model"
        self.endpoint = "https://example.invalid/completions"
        self.timeout_s = timeout_s


def client_with(response, settings=None):
    session = FakeSession(response)
    client = GrokClient(settings=settings or StubSettings(),
                        session_factory=lambda: _Ctx(session))
    return client, session


CLOSED_PAGE = {"nick": "Anna", "items": [], "empty": True,
               "day": today_key(), "scope": SCOPE_TODAY,
               "reason": "archive_closed"}


class TestTheDeliveryGatePins(unittest.TestCase):
    """`deliver` — the irreversible act — with every literal pinned."""

    class LiveCdp:
        is_connected = True

    def deliver_with(self, text, cdp="__live__", type_ok=True, send_ok=True):
        from backend import message_injector
        cdp = self.LiveCdp() if cdp == "__live__" else cdp
        calls = []

        async def fake_type(client, message):
            calls.append(("type", client, message))
            return type_ok

        async def fake_send(client):
            calls.append(("send", client))
            return send_ok

        original = (message_injector.type_message, message_injector.click_send)
        message_injector.type_message = fake_type
        message_injector.click_send = fake_send
        try:
            result = run(deliver(cdp, "Anna", text, parser=FakeParser()))
        finally:
            message_injector.type_message, message_injector.click_send = \
                original
        return result, calls, cdp

    def test_a_none_message_is_refused_with_the_empty_reason(self):
        result, calls, _ = self.deliver_with(None)
        self.assertEqual(result.code, "bot_empty_message")
        self.assertEqual(result.detail, "there is nothing to send")
        self.assertEqual(calls, [])

    def test_a_cdp_without_the_connection_flag_is_refused(self):
        # getattr's False default is the whole guard: an object with no
        # `is_connected` at all must be refused, not crashed on.
        result, calls, _ = self.deliver_with("hi", cdp=object())
        self.assertEqual(result.code, "bot_not_connected")
        self.assertEqual(result.detail, "not connected to a chat tab")
        self.assertEqual(calls, [])

    def test_the_typing_step_receives_the_live_cdp_and_the_text(self):
        result, calls, cdp = self.deliver_with("hi")
        self.assertTrue(result.is_ok)
        self.assertEqual(calls[0], ("type", cdp, "hi"))
        self.assertEqual(calls[1], ("send", cdp))

    def test_a_failed_typing_names_the_page(self):
        result, _, _ = self.deliver_with("hi", type_ok=False)
        self.assertEqual(result.code, "bot_type_failed")
        self.assertEqual(result.detail, "the page did not accept the text")

    def test_a_failed_send_names_the_button(self):
        result, _, _ = self.deliver_with("hi", send_ok=False)
        self.assertEqual(result.code, "bot_send_failed")
        self.assertEqual(result.detail,
                         "the send button could not be clicked")


class TestTheRecipientGatePins(unittest.TestCase):
    def test_an_unreadable_page_refuses_with_its_exact_reason(self):
        result = run(check_recipient(FakeParser(boom=True), "Anna"))
        self.assertEqual(result.code, "bot_unknown_chat")
        self.assertEqual(result.detail,
                         "cannot tell which chat is open — nothing was sent")

    def test_the_read_failure_is_logged_with_the_cause(self):
        with self.assertLogs("chatbot", level="WARNING") as caught:
            run(open_partner(FakeParser(boom=True)))
        self.assertEqual(caught.output,
                         ["WARNING:chatbot:could not read the open chat: "
                          "page gone"])

    def test_a_matching_partner_is_the_value_of_the_ok(self):
        result = run(check_recipient(FakeParser("Anna"), "Anna"))
        self.assertTrue(result.is_ok)
        self.assertEqual(result.value, "Anna")

    def test_the_partner_nick_is_whitespace_collapsed(self):
        partner = run(open_partner(FakeParser("  Anna \n  Marie ")))
        self.assertEqual(partner, "Anna Marie")


class TestThePageShapePins(unittest.TestCase):
    def test_a_closed_archive_answers_the_exact_closed_dict(self):
        svc = BotChatService(archive=None)
        self.assertEqual(run(svc.load("Anna")), CLOSED_PAGE)

    def test_an_archive_without_query_or_db_is_also_closed(self):
        # A bare object() has neither attribute: the getattr defaults must
        # answer "closed", not raise AttributeError.
        svc = BotChatService(archive=object())
        self.assertEqual(run(svc.load("Anna")), CLOSED_PAGE)

    def test_an_open_db_without_a_query_is_still_closed(self):
        archive = type("A", (), {"query": None,
                                 "db": type("DB", (), {"is_open": True})()})()
        svc = BotChatService(archive=archive)
        self.assertEqual(run(svc.load("Anna")), CLOSED_PAGE)

    def test_a_db_without_the_open_flag_reads_as_closed(self):
        archive = type("A", (), {"query": FakeQuery([]), "db": object()})()
        svc = BotChatService(archive=archive)
        self.assertEqual(run(svc.load("Anna")), CLOSED_PAGE)

    def test_today_is_load_in_the_today_scope(self):
        # on the CLOSED shape: a mutated scope argument shows up verbatim
        # there, while the open path re-normalises it inside scoped_page.
        svc = BotChatService(archive=None)
        self.assertEqual(run(svc.today("Anna")),
                         run(svc.load("Anna", "today")))
        self.assertEqual(run(svc.today("Anna"))["scope"], "today")

    def test_the_open_page_carries_the_nick_through_the_scope(self):
        svc = BotChatService(archive=FakeArchive([row("hi")]))
        page = run(svc.load("Anna"))
        self.assertEqual(page["nick"], "Anna")
        self.assertEqual(page["scope"], "today")

    def test_scoped_page_pins_its_whole_payload(self):
        page = scoped_page("Anna", [row("one"), row("two")], "today")
        self.assertEqual(page, {
            "nick": "Anna",
            "items": [row("one"), row("two")],
            "empty": False,
            "day": today_key(),
            "scope": "today",
            "truncated": False,
            "total": 2,
            "reason": "",
        })

    def test_truncation_is_false_exactly_at_the_cap(self):
        rows = [row(str(i)) for i in range(CONTEXT_LIMIT)]
        self.assertFalse(scoped_page("Anna", rows, "today")["truncated"])
        rows.append(row("one more"))
        page = scoped_page("Anna", rows, "today")
        self.assertTrue(page["truncated"])
        self.assertEqual(page["total"], CONTEXT_LIMIT + 1)
        self.assertEqual(len(page["items"]), CONTEXT_LIMIT)

    def test_an_empty_scope_carries_its_own_reason(self):
        self.assertEqual(scoped_page("Anna", [], "today")["reason"],
                         "no_messages_today")
        self.assertEqual(scoped_page("Anna", [], "all")["reason"],
                         "no_messages_at_all")

    def test_empty_detail_pins_all_three_wordings(self):
        self.assertEqual(
            empty_detail("Anna", {"reason": "archive_closed"}),
            "no database is open — open a world first")
        self.assertEqual(
            empty_detail("Anna", {"reason": "no_messages_at_all"}),
            "no messages with Anna in the archive at all — "
            "collect the chat first")
        detail = empty_detail("Anna", {"reason": "no_messages_today",
                                       "day": "2026-09-13"})
        self.assertEqual(
            detail,
            "no messages with Anna archived under 2026-09-13 — "
            "collect the chat first, it may still be dated the previous "
            "day, or untick “today only” to use the whole conversation")


class TestThePromptFlowPins(unittest.TestCase):
    def service(self, items=(), answer="an answer", store=None):
        svc = BotChatService(archive=FakeArchive(list(items)),
                             grok=FakeGrok(answer), labels=store)
        return svc

    def test_preview_pins_its_whole_payload(self):
        svc = self.service([row("hello")], store=labeled_store())
        calls = spy_label_name(svc)
        shown = run(svc.preview("Anna", "suggest_reply"))
        self.assertEqual(set(shown), {"nick", "template", "prompt"})
        self.assertEqual(shown["nick"], "Anna")
        self.assertEqual(shown["template"], "suggest_reply")
        self.assertIn("hello", shown["prompt"])
        self.assertEqual(calls, ["Anna"])

    def test_suggest_on_a_closed_archive_names_the_world_problem(self):
        svc = BotChatService(archive=None, grok=FakeGrok("x"))
        result = run(svc.suggest_reply("Anna"))
        self.assertEqual(result.code, "bot_no_messages")
        self.assertEqual(result.detail,
                         "no database is open — open a world first")

    def test_an_empty_whole_conversation_names_the_person(self):
        svc = self.service([], store=None)
        result = run(svc.suggest_reply("Anna", scope="all"))
        self.assertEqual(result.code, "bot_no_messages")
        self.assertEqual(
            result.detail,
            "no messages with Anna in the archive at all — "
            "collect the chat first")
        result = run(svc.analyze_reaction("Anna", scope="all"))
        self.assertEqual(result.code, "bot_no_messages")
        self.assertEqual(
            result.detail,
            "no messages with Anna in the archive at all — "
            "collect the chat first")

    def test_a_suggestion_is_the_exact_pending_payload(self):
        svc = self.service([row("hello")], answer="hi there")
        result = run(svc.suggest_reply("Anna"))
        self.assertTrue(result.is_ok)
        self.assertEqual(result.value, {"nick": "Anna", "text": "hi there",
                                        "state": "pending"})

    def test_analyze_without_messages_names_the_world_problem(self):
        svc = BotChatService(archive=None, grok=FakeGrok("x"))
        result = run(svc.analyze_reaction("Anna"))
        self.assertEqual(result.code, "bot_no_messages")
        self.assertEqual(result.detail,
                         "no database is open — open a world first")

    def test_analyze_without_an_inbound_names_the_day(self):
        svc = self.service([row("I spoke", direction="out", who="me")])
        result = run(svc.analyze_reaction("Anna"))
        self.assertEqual(result.code, "bot_no_answer")
        self.assertEqual(
            result.detail,
            f"Anna has not answered today ({today_key()}) — "
            f"nothing to analyze")

    def test_an_analyzed_reaction_pins_its_whole_payload(self):
        svc = self.service([row("thanks for the help")],
                           answer="positive because warm",
                           store=labeled_store())
        calls = spy_label_name(svc)
        result = run(svc.analyze_reaction("Anna"))
        self.assertTrue(result.is_ok)
        value = result.value
        self.assertEqual(set(value),
                         {"reaction", "reason", "raw", "nick", "state",
                          "last_message"})
        self.assertEqual(value["nick"], "Anna")
        self.assertEqual(value["state"], "pending")
        self.assertEqual(value["last_message"], "thanks for the help")
        self.assertEqual(calls, ["Anna"])


class TestTheReactionLabelPins(unittest.TestCase):
    POSITIVE = {"id": "positive", "name": "Positive first reaction",
                "color": "#00c853"}
    NEGATIVE = {"id": "negative", "name": "Negative first reaction",
                "color": "#ff3b30"}

    def service_with_state(self, state):
        """active_label_name against an exact reaction_state shape."""
        svc = BotChatService()
        spy = StateSpy(state)
        svc.reaction_state = spy
        return svc, spy

    def test_without_a_store_the_state_is_the_exact_empty_shape(self):
        svc = BotChatService()
        self.assertEqual(svc.reaction_state("Anna"),
                         {"nick": "Anna", "active": "", "available": []})
        self.assertEqual(svc.active_label_name("Anna"), "")

    def test_the_real_store_state_names_the_label_on_the_person(self):
        svc = BotChatService(labels=labeled_store("negative"))
        state = svc.reaction_state("Anna")
        self.assertEqual(state["nick"], "Anna")
        self.assertEqual(state["active"], "negative")
        self.assertEqual([item["id"] for item in state["available"]],
                         ["positive", "negative", "uncertain"])
        self.assertEqual(svc.active_label_name("Anna"),
                         "Negative first reaction")

    def test_the_active_label_is_looked_up_under_its_own_nick(self):
        svc, spy = self.service_with_state(
            {"active": "negative",
             "available": [self.POSITIVE, self.NEGATIVE]})
        self.assertEqual(svc.active_label_name("Anna"),
                         "Negative first reaction")
        self.assertEqual(spy.nicks, ["Anna"])

    def test_an_active_id_outside_the_list_names_nothing(self):
        svc, _ = self.service_with_state({"active": "zzz",
                                          "available": [self.POSITIVE]})
        self.assertEqual(svc.active_label_name("Anna"), "")

    def test_a_nameless_available_item_falls_back_to_empty(self):
        svc, _ = self.service_with_state(
            {"active": "positive",
             "available": [{"id": "positive", "name": None}]})
        self.assertEqual(svc.active_label_name("Anna"), "")

    def test_a_missing_active_key_is_not_a_crash(self):
        svc, _ = self.service_with_state({"available": [self.POSITIVE]})
        self.assertEqual(svc.active_label_name("Anna"), "")

    def test_applying_without_a_world_says_so(self):
        svc = BotChatService()
        result = svc.apply_reaction("Anna", "positive")
        self.assertEqual(result.code, "bot_no_world")
        self.assertEqual(result.detail, "no world is open — open a database")


class TestTheServiceWiringPins(unittest.TestCase):
    def test_the_service_keeps_the_config_it_was_given(self):
        cfg = tmp_config()
        svc = BotChatService(config=cfg)
        self.assertIs(svc.config, cfg)

    def test_without_a_grok_the_service_builds_one_from_its_config(self):
        cfg = tmp_config()
        cfg.set("grok", "provider", "google")
        svc = BotChatService(config=cfg)
        self.assertIsInstance(svc.grok, GrokClient)
        self.assertEqual(svc.grok.settings.provider, "google")

    def test_a_context_is_built_under_the_person_name(self):
        svc = BotChatService(labels=labeled_store("positive"))
        context = svc.context_of("Anna", {"items": [row("hello")]})
        self.assertEqual(set(context), {"person_name", "all_msg", "last_msg",
                                        "msg", "reaction_label"})
        self.assertEqual(context["person_name"], "Anna")
        self.assertEqual(context["last_msg"], "hello")
        self.assertEqual(context["reaction_label"],
                         "Positive first reaction")


class TestTheConnectionShapePins(unittest.TestCase):
    def test_a_non_dict_row_is_an_empty_connection_not_a_crash(self):
        conn = Connection("x", "junk")
        self.assertEqual(conn.provider, "")
        self.assertEqual(conn.title, "x")

    def test_a_keyless_connection_shows_its_exact_state(self):
        conn = Connection("grok", {"title": "Grok (xAI)", "provider": "grok",
                                   "api_key": "", "model": "grok-2-latest",
                                   "url": ""})
        self.assertEqual(conn.state(), {
            "id": "grok",
            "title": "Grok (xAI)",
            "provider": "grok",
            "provider_title": "Grok (xAI)",
            "model": "grok-2-latest",
            "url": "https://api.x.ai/v1/chat/completions",
            "endpoint": "https://api.x.ai/v1/chat/completions",
            "has_key": False,
            "masked": "",
            "problem": "no API key",
            "ok": False,
        })

    def test_a_keyed_connection_shows_its_masked_key(self):
        conn = Connection("c", {"title": "T", "provider": "grok",
                                "api_key": "abcdefghijklm"})
        state = conn.state()
        self.assertTrue(state["has_key"])
        self.assertEqual(state["masked"], "abcd…jklm")
        self.assertEqual(state["problem"], "")
        self.assertTrue(state["ok"])
        self.assertNotIn("abcdefghijklm", str(state))

    def test_the_slug_pins_its_shape(self):
        self.assertEqual(slug("  Hello   World  ", "grok"), "hello-world")
        self.assertEqual(slug("--x--", "grok"), "x")
        self.assertEqual(slug(None, "grok"), "grok-connection")
        self.assertEqual(slug("", "google"), "google-connection")
        # strip() eats the CHARACTER SET, not the literal: an id that ends
        # in x must keep it.
        self.assertEqual(slug("XXHelloXX", "grok"), "xxhelloxx")


class TestTheConnectionStorePins(unittest.TestCase):
    def setUp(self):
        self.cfg = tmp_config()
        self.store = ConnectionStore(self.cfg)

    def stored(self):
        return self.cfg.named_all(SECTION)

    def test_a_fresh_store_seeds_every_provider_and_persists_the_rows(self):
        connections = self.store.all()
        self.assertEqual({c.id for c in connections},
                         set(bot_providers.PROVIDERS))
        # Both keyless seeds must be WRITTEN, not just returned: the loop
        # `continue`s per provider, and a `break` would seed only the first.
        self.assertEqual(self.stored()["google"],
                         {"title": "Google Gemini", "provider": "google",
                          "api_key": "", "model": "gemini-2.0-flash",
                          "url": ""})
        self.assertEqual(self.stored()["kimi"]["provider"], "kimi")

    def test_seeded_rows_come_back_keyless_and_honest(self):
        grok = self.store.get("grok")
        self.assertEqual(grok.problem(), "no API key")
        self.assertEqual(grok.model, "grok-2-latest")

    def test_the_active_id_of_a_fresh_config_is_empty(self):
        self.assertEqual(self.store.active_id(), "")

    def test_a_blank_title_falls_back_to_the_slug_of_the_provider(self):
        ident = self.store.save("", {"title": "", "provider": "google",
                                     "api_key": "k"})
        self.assertEqual(ident, "google-connection")

    def test_a_blank_field_keeps_its_old_value(self):
        self.store.save("c1", {"title": "T", "provider": "grok",
                               "api_key": "secret", "model": "m1",
                               "url": "u1"})
        self.store.save("c1", {"title": "", "provider": "grok",
                               "api_key": "", "model": "", "url": ""})
        self.assertEqual(self.stored()["c1"],
                         {"title": "T", "provider": "grok",
                          "api_key": "secret", "model": "m1", "url": "u1"})

    def test_deleting_the_active_connection_clears_the_active_id(self):
        self.store.save("c1", {"title": "T", "provider": "grok",
                               "api_key": "k"})
        self.assertTrue(self.store.use("c1"))
        self.assertTrue(self.store.delete("c1"))
        self.assertEqual(self.cfg.get("grok", ACTIVE_KEY, default=None), "")

    def test_deleting_another_connection_keeps_the_active_one(self):
        self.store.save("c1", {"title": "One", "provider": "grok",
                               "api_key": "k"})
        self.store.save("c2", {"title": "Two", "provider": "google",
                               "api_key": "k"})
        self.assertTrue(self.store.use("c1"))
        self.assertTrue(self.store.delete("c2"))
        self.assertEqual(self.store.active_id(), "c1")

    def test_legacy_settings_are_adopted_with_their_exact_rows(self):
        cfg = tmp_config()
        cfg.set("grok", "api_key", "xai-key-1234")
        cfg.set("grok", "model", "grok-4")
        cfg.set("grok", "providers",
                {"google": {"api_key": "g-key", "model": "gemini-x"}})
        store = ConnectionStore(cfg)
        connections = {c.id: c for c in store.all()}
        self.assertEqual(cfg.named_all(SECTION)["grok"], {
            "title": "Grok (xAI) — grok-4",
            "provider": "grok",
            "api_key": "xai-key-1234",
            "model": "grok-4",
            "url": "https://api.x.ai/v1/chat/completions",
        })
        # The adoption loop `continue`s past a keyless provider: with two
        # legacy keys BOTH must be adopted, not just the first.
        self.assertEqual(connections["google"].api_key, "g-key")
        self.assertEqual(connections["google"].model, "gemini-x")
        self.assertEqual(connections["kimi"].api_key, "")

    def test_adoption_walks_past_a_keyless_provider_to_the_next(self):
        cfg = tmp_config()
        cfg.set("grok", "providers", {"google": {"api_key": "g-key"}})
        connections = {c.id: c for c in ConnectionStore(cfg).all()}
        # grok is keyless and comes FIRST: a `break` instead of `continue`
        # would never reach google, which would then be seeded keyless too.
        self.assertEqual(connections["google"].api_key, "g-key")
        self.assertEqual(connections["grok"].api_key, "")

    def test_adoption_says_how_many_it_adopted(self):
        cfg = tmp_config()
        cfg.set("grok", "api_key", "xai-key-1234")
        cfg.set("grok", "providers", {"google": {"api_key": "g"}})
        with self.assertLogs("chatbot", level="INFO") as caught:
            ConnectionStore(cfg).all()
        # the config logs its own saves on the same logger — find the line
        self.assertIn("INFO:chatbot:adopted 2 legacy AI connection(s)",
                      caught.output)


class TestTheGrokTransportPins(unittest.TestCase):
    def test_the_mask_hides_the_middle_from_twelve_characters_up(self):
        self.assertEqual(mask("abcdefghijklm"), "abcd…jklm")
        # len > 12, not >= 12: a twelve-character key is still "set".
        self.assertEqual(mask("abcdefghijkl"), "set")
        self.assertEqual(mask(""), "")
        self.assertEqual(mask(None), "")

    def test_a_google_reply_is_read_off_the_google_wire(self):
        body = {"candidates": [{"content": {"parts": [{"text": "hi there"}]},
                               "finishReason": "STOP"}]}
        self.assertEqual(reply_text(body, "google").value, "hi there")

    def test_an_empty_prompt_is_refused_before_any_wire_call(self):
        client, session = client_with(FakeResponse(200, {}))
        for prompt in ("", None, "   "):
            result = run(client.complete(prompt))
            self.assertEqual(result.code, "grok_no_prompt")
            self.assertEqual(result.detail, "the prompt is empty")
        self.assertEqual(session.posts, [])

    def test_a_response_without_a_status_is_reported_as_unknown(self):
        client, _ = client_with(FakeResponse())
        result = run(client._post("hi"))
        self.assertEqual(result.code, "grok_http")
        self.assertEqual(result.detail, "HTTP ?")

    def test_a_failed_status_names_the_number(self):
        client, session = client_with(FakeResponse(500))
        result = run(client._post("hi"))
        self.assertEqual(result.code, "grok_http")
        self.assertEqual(result.detail, "HTTP 500")
        self.assertEqual(session.posts[0][0],
                         "https://example.invalid/completions")

    def test_an_unreachable_endpoint_is_logged_and_typed_exactly(self):
        long_boom = RuntimeError("b" * 250)

        def exploding_factory():
            raise long_boom

        client = GrokClient(settings=StubSettings(),
                            session_factory=exploding_factory)
        with self.assertLogs("chatbot", level="WARNING") as caught:
            result = run(client.complete("hi"))
        self.assertEqual(caught.output,
                         ["WARNING:chatbot:Grok request failed: " + "b" * 250])
        self.assertEqual(result.code, "grok_unreachable")
        self.assertEqual(result.detail, "b" * 200)   # str(exc)[:200]

    def test_the_default_session_carries_the_settings_timeout(self):
        cfg = tmp_config()
        cfg.set("grok", "timeout_s", 7)
        client = GrokClient(config=cfg)

        async def total():
            async with client._session() as session:
                return session.timeout.total

        self.assertEqual(run(total()), 7)

    def test_an_explicit_provider_survives_the_default_settings(self):
        cfg = tmp_config()
        client = GrokClient(config=cfg, provider="kimi")
        self.assertEqual(client.settings.provider, "kimi")

    def test_a_flat_empty_value_falls_back_to_the_read_default(self):
        cfg = tmp_config()
        cfg.set("grok", "custom", "")
        settings = GrokSettings(cfg)
        # `value in (None, "")` is the fallback rule; a mutated second
        # element lets the empty string through.
        self.assertEqual(settings._read("custom", "D"), "D")
        cfg.set("grok", "custom", None)
        self.assertEqual(settings._read("custom", "D"), "D")
        cfg.set("grok", "custom", "x")
        self.assertEqual(settings._read("custom", "D"), "x")

    def test_a_bucket_value_follows_the_same_fallback(self):
        cfg = tmp_config()
        cfg.set("grok", "providers", {"google": {"model": "", "x": "v"}})
        settings = GrokSettings(cfg, "google")
        self.assertEqual(settings.model, "gemini-2.0-flash")
        # pinned at _read itself: the property's own `or spec.model` guard
        # would hide an empty string leaking through the bucket path.
        self.assertEqual(settings._read("model", "D"), "D")
        self.assertEqual(settings._read("x", "D"), "v")


class TestTheNamedSectionPins(unittest.TestCase):
    """The shared read half of the two named libraries, pinned directly."""

    def test_without_a_config_the_section_reads_empty(self):
        from services.named_section import NamedSection

        class Mine(NamedSection):
            SECTION = "ai_connections"

        self.assertEqual(Mine(None)._all(), {})

    def test_a_non_dict_answer_reads_empty(self):
        from services.named_section import NamedSection

        class JunkConfig:
            def named_all(self, section):
                return "junk"

        class Mine(NamedSection):
            SECTION = "ai_connections"

        self.assertEqual(Mine(JunkConfig())._all(), {})

    def test_a_dict_answer_passes_through_under_its_section(self):
        from services.named_section import NamedSection
        seen = []

        class GoodConfig:
            def named_all(self, section):
                seen.append(section)
                return {"a": {"title": "A"}}

        class Mine(NamedSection):
            SECTION = "prompt_presets"

        self.assertEqual(Mine(GoodConfig())._all(), {"a": {"title": "A"}})
        self.assertEqual(seen, ["prompt_presets"])


class TestTheClientChoicePins(unittest.TestCase):
    def test_a_named_connection_beats_the_active_one(self):
        cfg = tmp_config()
        store = ConnectionStore(cfg)
        store.save("c0", {"title": "Zero", "provider": "grok",
                          "api_key": "k0"})
        store.save("c1", {"title": "One", "provider": "grok",
                          "api_key": "k1"})
        sentinel = object()
        client = client_for(cfg, session_factory=sentinel, connection="c1")
        self.assertIsInstance(client.settings, Connection)
        self.assertEqual(client.settings.api_key, "k1")
        self.assertIs(client._session_factory, sentinel)

    def test_an_unknown_connection_falls_back_to_the_provider_settings(self):
        cfg = tmp_config()
        cfg.set("grok", "providers", {"google": {"model": "m-x",
                                                 "api_key": "g-key"}})
        sentinel = object()
        client = client_for(cfg, session_factory=sentinel,
                            provider="google", connection="nope")
        self.assertEqual(client.settings.provider, "google")
        self.assertEqual(client.settings.model, "m-x")
        self.assertIs(client._session_factory, sentinel)

    def test_without_any_config_the_named_provider_still_wins(self):
        client = client_for(None, provider="google")
        self.assertEqual(client.settings.provider, "google")

    def test_the_signature_default_is_the_empty_provider(self):
        # provider="" falls through to the DEFAULT_PROVIDER inside
        # GrokSettings — a mutated signature default would name a vendor
        # the user never chose.
        self.assertEqual(client_for(None).settings.provider, "grok")


class TestTheProviderWirePins(unittest.TestCase):
    """What leaves the machine, pinned to the vendors' wire formats."""

    GROK = bot_providers.PROVIDERS["grok"]
    GOOGLE = bot_providers.PROVIDERS["google"]

    def test_the_catalog_entry_pins_its_whole_shape(self):
        self.assertEqual(self.GROK.as_dict(), {
            "id": "grok", "title": "Grok (xAI)",
            "url": "https://api.x.ai/v1/chat/completions",
            "model": "grok-2-latest", "needs_model_in_url": False})
        self.assertEqual(self.GOOGLE.as_dict(), {
            "id": "google", "title": "Google Gemini",
            "url": "https://generativelanguage.googleapis.com/v1beta/models/"
                   "{model}:generateContent",
            "model": "gemini-2.0-flash", "needs_model_in_url": True})

    def test_the_endpoint_falls_back_to_the_spec_url_and_model(self):
        self.assertEqual(
            bot_providers.endpoint(self.GOOGLE, "", ""),
            "https://generativelanguage.googleapis.com/v1beta/models/"
            "gemini-2.0-flash:generateContent")
        self.assertEqual(
            bot_providers.endpoint(self.GROK, "https://x/{model}", "m"),
            "https://x/m")

    def test_the_google_headers_pin_the_wire_auth(self):
        self.assertEqual(
            bot_providers.headers_of(self.GOOGLE, "k"),
            {"x-goog-api-key": "k", "Content-Type": "application/json"})

    def test_the_bearer_headers_pin_the_wire_auth(self):
        self.assertEqual(
            bot_providers.headers_of(self.GROK, "k"),
            {"Authorization": "Bearer k",
             "Content-Type": "application/json"})

    def test_the_gemini_body_pins_the_wire_shape(self):
        self.assertEqual(
            bot_providers.body_of(self.GOOGLE, "m", "hello"),
            {"contents": [{"role": "user", "parts": [{"text": "hello"}]}]})

    def test_the_openai_body_pins_the_wire_shape(self):
        self.assertEqual(
            bot_providers.body_of(self.GROK, "grok-2", "hello"),
            {"model": "grok-2", "stream": False,
             "messages": [{"role": "user", "content": "hello"}]})

    def test_an_openai_error_body_is_quoted_in_the_detail(self):
        result = bot_providers.openai_reply({"error": "too many requests"})
        self.assertEqual(result.code, "grok_no_choices")
        self.assertEqual(result.detail, "too many requests")

    def test_the_error_detail_is_cut_at_200_characters(self):
        result = bot_providers.openai_reply({"error": "e" * 250})
        self.assertEqual(result.detail, "e" * 200)

    def test_a_choiceless_body_without_an_error_quotes_the_body(self):
        result = bot_providers.openai_reply({"weird": 1})
        self.assertEqual(result.code, "grok_no_choices")
        self.assertEqual(result.detail, str({"weird": 1})[:200])

    def test_an_empty_openai_message_is_named_as_empty(self):
        result = bot_providers.openai_reply(
            {"choices": [{"message": {"content": "   "}}]})
        self.assertEqual(result.code, "grok_empty")
        self.assertEqual(result.detail, "the model returned an empty message")

    def test_empty_text_parts_join_to_nothing(self):
        text = bot_providers.gemini_text(
            {"content": {"parts": [{"text": ""}, {"text": "hi"}, "junk",
                                   {"no_text": 1}]}})
        self.assertEqual(text, "hi")

    def test_a_blocked_prompt_names_the_block_reason(self):
        result = bot_providers.no_candidate(
            {"promptFeedback": {"blockReason": "SAFETY"}})
        self.assertEqual(result.code, "grok_refused")
        self.assertEqual(result.detail, "the prompt was blocked: SAFETY")

    def test_a_candidateless_body_quotes_itself(self):
        result = bot_providers.no_candidate({"nothing": 1})
        self.assertEqual(result.code, "grok_no_choices")
        self.assertEqual(result.detail, str({"nothing": 1})[:200])

    def test_a_safety_refusal_is_a_refusal_not_an_empty_answer(self):
        result = bot_providers.gemini_reply(
            {"candidates": [{"finishReason": "SAFETY"}]})
        self.assertEqual(result.code, "grok_refused")
        self.assertEqual(result.detail,
                         "the model refused this prompt on safety grounds")

    def test_a_non_object_answer_is_named(self):
        result = bot_providers.reply_of(self.GROK, "not a dict")
        self.assertEqual(result.code, "grok_bad_body")
        self.assertEqual(result.detail, "the API answered with a non-object")


class TestThePresetLibraryPins(unittest.TestCase):
    def setUp(self):
        from services import bot_presets
        self.slug = bot_presets.slug
        self.lib = PresetLibrary(tmp_config())

    def test_the_preset_slug_pins_its_shape(self):
        self.assertEqual(self.slug("suggest_reply", "  Hello   World  "),
                         "suggest_reply:hello-world")
        self.assertEqual(self.slug("suggest_reply", None),
                         "suggest_reply:preset")
        self.assertEqual(self.slug("suggest_reply", "--x--"),
                         "suggest_reply:x")
        # strip("XX-XX") would be the same character set after .lower() —
        # that survivor is equivalent, and this is the case that shows it.
        self.assertEqual(self.slug("suggest_reply", "XXHelloXX"),
                         "suggest_reply:xxhelloxx")

    def test_a_saved_preset_lists_back_with_its_exact_row(self):
        self.lib.save("suggest_reply", "Casual", "Be short")
        self.assertEqual(self.lib.for_template("suggest_reply"), [{
            "id": "suggest_reply:casual",
            "title": "Casual",
            "template": "suggest_reply",
            "text": "Be short",
        }])

    def test_for_template_lists_only_its_own_template(self):
        self.lib.save("suggest_reply", "Casual", "Be short")
        self.lib.save("analyze_reaction", "Strict", "Judge hard")
        listed = self.lib.for_template("suggest_reply")
        self.assertEqual([row["id"] for row in listed],
                         ["suggest_reply:casual"])

    def test_get_pins_its_whole_row(self):
        self.lib.save("suggest_reply", "Casual", "Be short")
        self.assertEqual(self.lib.get("suggest_reply:casual"), {
            "id": "suggest_reply:casual",
            "title": "Casual",
            "template": "suggest_reply",
            "text": "Be short",
        })
        self.assertIsNone(self.lib.get("suggest_reply:nope"))

    def test_save_without_an_ident_slugs_from_template_and_title(self):
        ident = self.lib.save("suggest_reply", "My Preset", "words")
        self.assertEqual(ident, "suggest_reply:my-preset")

    def test_save_keeps_an_explicit_ident(self):
        ident = self.lib.save("suggest_reply", "T", "words",
                              ident="custom:one")
        self.assertEqual(ident, "custom:one")
        self.assertEqual(self.lib.get("custom:one")["title"], "T")

    def test_a_blank_body_or_title_is_refused(self):
        self.assertEqual(self.lib.save("suggest_reply", "", "words"), "")
        self.assertEqual(self.lib.save("suggest_reply", "T", None), "")
        self.assertEqual(self.lib.save("suggest_reply", "T", "   "), "")

    def test_an_unknown_template_is_refused(self):
        self.assertEqual(self.lib.save("no_such_template", "T", "w"), "")

    def test_delete_removes_only_the_one_preset(self):
        self.lib.save("suggest_reply", "One", "a")
        self.lib.save("suggest_reply", "Two", "b")
        self.assertTrue(self.lib.delete("suggest_reply:one"))
        self.assertEqual([row["id"] for row in
                          self.lib.for_template("suggest_reply")],
                         ["suggest_reply:two"])


if __name__ == "__main__":
    unittest.main()
