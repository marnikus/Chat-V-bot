"""BotBridge — the AI Bot Chat / Prompt Editor wire over QWebChannel.

The window is driven the way the page drives it: a slot is called with a
`req_id`, the answer arrives on `bot_reply_ready` carrying the same id, and a
failure arrives on `bot_error` instead of nothing at all.

The acceptance criteria this file pins:
  * every bot slot and signal is published by the Router (the ONE object
    registered on the channel — a slot missing there is a dead button);
  * two windows can ask at once without their answers crossing;
  * approving is NOT sending: nothing reaches the page until
    `bot_send_message` is called;
  * `bot_analyze_reaction` writes no label, `bot_apply_reaction` does;
  * an edited prompt round-trips through the bridge and persists.

Run with:  python3 tests/test_bot_bridge.py
"""

import asyncio
import json
import os
import re
import sys
import tempfile
import unittest
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QObject  # noqa: E402

from backend.bridge import Bridge  # noqa: E402
from backend.config_manager import ConfigManager  # noqa: E402
from backend.history_query import HistoryQuery  # noqa: E402
from bridge.bot_bridge import BotBridge  # noqa: E402
from bridge.bot_prompt_bridge import BotPromptBridge  # noqa: E402
from bridge.bot_settings_bridge import BotSettingsBridge  # noqa: E402
from services import bot_providers  # noqa: E402
from services.bot_connections import ConnectionStore  # noqa: E402
from bridge.context import BridgeContext  # noqa: E402
from core.result import Err, Ok  # noqa: E402
from services.bot_grok import client_for  # noqa: E402
from stores.history_db import HistoryDB  # noqa: E402
from stores.label_store import LabelStore  # noqa: E402

TODAY = date.today().isoformat()

BOT_SLOTS = ["bot_load_today", "bot_suggest_reply", "bot_analyze_reaction",
             "bot_preview_prompt", "bot_send_message", "bot_reaction_state",
             "bot_apply_reaction", "bot_get_prompts", "bot_save_prompt",
             "bot_reset_prompt", "bot_get_variables", "bot_check_prompt",
             # presets (Prompt Editor) and connections (AI Connections)
             "bot_get_presets", "bot_save_preset", "bot_delete_preset",
             "bot_connections", "bot_save_connection",
             "bot_delete_connection", "bot_use_connection",
             "bot_test_connection"]
BOT_SIGNALS = ["bot_reply_ready", "bot_error", "bot_prompts_changed"]


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class FakeGrok:
    def __init__(self, answer=None):
        self.answer = answer if answer is not None else Ok("suggested text")
        self.prompts = []

    async def complete(self, prompt):
        self.prompts.append(prompt)
        return self.answer


class FakeArchive:
    """What the bridge may read off the archive: db, query and parser.

    `query` is the REAL `HistoryQuery`, the same one the DB window reads
    through — that is how media reaches the Bot Chat window at all.

    Deliberately NO `labels`: the real HistoryService has none, and the
    bridge injects `ctx.label_store()` instead.
    """

    def __init__(self, db, parser=None):
        self.db = db
        self.query = HistoryQuery(db) if db is not None else None
        self.parser = parser or FakeParser()


class FakeParser:
    """Reports which chat the browser has open, for the recipient gate."""

    def __init__(self, partner="Anna"):
        self.partner = partner

    async def state(self):
        return {"partner": self.partner}


async def make_db():
    path = os.path.join(tempfile.mkdtemp(), "world.db")
    db = await HistoryDB(path).init()
    await db.execute("INSERT INTO persons (nick, nick_lc) VALUES ('Anna','anna')")
    pid = await db.scalar("SELECT id FROM persons WHERE nick='Anna'")
    for ordinal, (direction, who, text) in enumerate(
            [("out", "me", "hi"), ("in", "Anna", "hello you")], start=1):
        await db.execute(
            "INSERT INTO messages (person_id, ord, direction, from_nick, "
            "text, day) VALUES (?,?,?,?,?,?)",
            (pid, ordinal, direction, who, text, TODAY))
    await db.commit()
    return db


class BotBridgeCase(unittest.TestCase):
    """One wired BotBridge with a real archive, a real label store, fake Grok."""

    def setUp(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.cfg = ConfigManager(os.path.join(tempfile.mkdtemp(),
                                              "config.json"))
        self.labels = LabelStore(self.cfg)
        self.db = run(make_db())
        self.ctx = BridgeContext(config=self.cfg)
        self.ctx.labels = self.labels          # what ctx.label_store() hands out
        self.parser = FakeParser()
        self.ctx.archive = FakeArchive(self.db, self.parser)
        self.bridge = BotBridge(self.ctx)
        self.grok = FakeGrok()
        self.bridge.service.grok = self.grok
        self.replies, self.errors = [], []
        self.bridge.bot_reply_ready.connect(
            lambda req, payload: self.replies.append((req, payload)))
        self.bridge.bot_error.connect(
            lambda req, message: self.errors.append((req, message)))

    def tearDown(self):
        self.drain()
        self.loop.run_until_complete(self.db.close())
        self.loop.close()

    def drain(self):
        """Run the scheduled bot tasks to completion (bounded, never hangs)."""
        for _ in range(50):
            pending = [t for t in asyncio.all_tasks(self.loop)
                       if not t.done()]
            if not pending:
                return
            self.loop.run_until_complete(
                asyncio.wait(pending, timeout=5,
                             return_when=asyncio.ALL_COMPLETED))

    def answer(self, req_id):
        for req, payload in self.replies:
            if req == req_id:
                return json.loads(payload)
        return None


class TestRouterPublishesTheBotWire(unittest.TestCase):
    def test_every_slot_is_on_the_router(self):
        missing = [name for name in BOT_SLOTS if not hasattr(Bridge, name)]
        self.assertEqual(missing, [])

    def test_every_signal_is_on_the_router(self):
        missing = [name for name in BOT_SIGNALS if not hasattr(Bridge, name)]
        self.assertEqual(missing, [])

    def test_the_bot_bridge_is_wired_into_the_router(self):
        from bridge.router import BRIDGE_CLASSES
        self.assertIn(BotBridge, BRIDGE_CLASSES)


class TestLoadingAndAnswering(BotBridgeCase):
    def test_todays_messages_come_back_under_the_callers_id(self):
        self.bridge.bot_load_today("r1", "Anna", "today")
        self.drain()
        page = self.answer("r1")
        self.assertEqual([i["text"] for i in page["items"]],
                         ["hi", "hello you"])

    def test_two_requests_do_not_cross(self):
        self.bridge.bot_load_today("a", "Anna", "today")
        self.bridge.bot_load_today("b", "Nobody", "today")
        self.drain()
        self.assertFalse(self.answer("a")["empty"])
        self.assertTrue(self.answer("b")["empty"])

    def test_a_grok_failure_answers_on_the_error_signal(self):
        self.bridge.service.grok = FakeGrok(Err("grok_no_key", "no key"))
        self.bridge.bot_suggest_reply("r2", "Anna", "today")
        self.drain()
        self.assertEqual(self.errors[0][0], "r2")
        self.assertIn("no key", self.errors[0][1])
        self.assertEqual(self.replies, [])

    def test_a_raising_service_becomes_an_error_not_a_dead_request(self):
        async def boom(_nick, _scope="today"):
            raise RuntimeError("database exploded")

        self.bridge.service.load = boom
        self.bridge.bot_load_today("r3", "Anna", "today")
        self.drain()
        self.assertEqual(self.errors[0][0], "r3")


class TestVerificationFlow(BotBridgeCase):
    def test_a_suggestion_is_pending_and_sends_nothing(self):
        sent = []
        self.patch_deliver(sent)
        self.bridge.bot_suggest_reply("s1", "Anna", "today")
        self.drain()
        self.assertEqual(self.answer("s1")["state"], "pending")
        self.assertEqual(sent, [])                 # approval is a UI act only

    def test_send_message_is_the_only_path_to_the_page(self):
        sent = []
        self.patch_deliver(sent)
        self.bridge.bot_send_message("s2", "Anna", "approved text")
        self.drain()
        self.assertEqual(sent, [("Anna", "approved text")])
        self.assertEqual(self.answer("s2"), "approved text")

    def test_a_direct_message_uses_the_same_verified_path(self):
        sent = []
        self.patch_deliver(sent)
        self.bridge.bot_send_message("s3", "Anna", "my own words")
        self.drain()
        self.assertEqual(sent, [("Anna", "my own words")])

    def patch_deliver(self, sink):
        import bridge.bot_bridge as module

        async def fake(_cdp, nick, text, parser=None):
            sink.append((nick, text))
            return Ok(text)

        original = module.deliver
        module.deliver = fake
        self.addCleanup(lambda: setattr(module, "deliver", original))


class TestReactionLabelsOverTheWire(BotBridgeCase):
    def test_analysis_applies_no_label(self):
        self.bridge.service.grok = FakeGrok(Ok("positive - warm answer"))
        self.bridge.bot_analyze_reaction("a1", "Anna", "today")
        self.drain()
        self.assertEqual(self.answer("a1")["reaction"], "positive")
        self.assertEqual(self.labels.ids_for("Anna"), [])

    def test_confirming_applies_exactly_one_label(self):
        state = json.loads(self.bridge.bot_apply_reaction("Anna", "positive"))
        self.assertEqual(state["active"], "positive")
        self.assertEqual(len(self.labels.ids_for("Anna")), 1)

    def test_a_manual_choice_replaces_the_previous_one(self):
        self.bridge.bot_apply_reaction("Anna", "positive")
        state = json.loads(self.bridge.bot_apply_reaction("Anna", "negative"))
        self.assertEqual(state["active"], "negative")
        self.assertEqual(len(self.labels.ids_for("Anna")), 1)

    def test_the_state_slot_offers_three_colour_coded_labels(self):
        state = json.loads(self.bridge.bot_reaction_state("Anna"))
        self.assertEqual(len(state["available"]), 3)
        self.assertEqual(state["active"], "")

    def test_an_unknown_reaction_changes_nothing(self):
        state = json.loads(self.bridge.bot_apply_reaction("Anna", "grumpy"))
        self.assertFalse(state["changed"])
        self.assertEqual(self.labels.ids_for("Anna"), [])


class PromptBridgeCase(BotBridgeCase):
    """The Prompt Editor is its OWN window, so it is its own bridge.

    It borrows the Bot Chat bridge for the shared template library and for
    the two answer signals; with no router to ask, it builds one on the same
    context, which is what `self.bridge` already is here — so the preview's
    answer lands on a bridge this case is not listening to. `editor` therefore
    points at the same context, and the preview test listens where the answer
    really goes.
    """

    def setUp(self):
        super().setUp()
        self.editor = BotPromptBridge(self.ctx)


class TestPromptEditorOverTheWire(PromptBridgeCase):
    def test_the_editor_lists_both_templates(self):
        templates = json.loads(self.editor.bot_get_prompts())
        self.assertEqual([t["id"] for t in templates],
                         ["suggest_reply", "analyze_reaction"])

    def test_saving_announces_the_change_and_persists_it(self):
        announced = []
        self.editor.bot_prompts_changed.connect(announced.append)
        self.assertTrue(self.editor.bot_save_prompt("suggest_reply",
                                                    "Write to {nick}"))
        self.assertTrue(announced)
        reopened = ConfigManager(self.cfg._path)
        self.assertEqual(reopened.get("grok", "prompts")["suggest_reply"],
                         "Write to {nick}")

    def test_an_empty_template_is_refused_without_announcing(self):
        announced = []
        self.editor.bot_prompts_changed.connect(announced.append)
        self.assertFalse(self.editor.bot_save_prompt("suggest_reply", "   "))
        self.assertEqual(announced, [])

    def test_a_template_with_an_unknown_variable_is_still_saved(self):
        """Saving is not validation: the editor warns about `{x}`, it does
        not refuse the user's work and revert to the shipped default."""
        self.assertTrue(self.editor.bot_save_prompt("suggest_reply", "a {x}"))

    def test_a_saved_template_is_what_gets_sent_to_grok(self):
        """One library: what the editor saves is what the chat window sends."""
        self.editor.bot_save_prompt("suggest_reply", "Reply to {nick} now")
        self.bridge.bot_suggest_reply("p1", "Anna", "today")
        self.drain()
        self.assertEqual(self.grok.prompts[0], "Reply to Anna now")

    def test_preview_shows_the_rendered_prompt(self):
        answers = []
        chat = self.editor._chat_bridge()
        chat.bot_reply_ready.connect(
            lambda req, payload: answers.append((req, payload)))
        self.editor.bot_preview_prompt("p2", "Anna", "analyze_reaction", "today")
        self.drain()
        self.assertEqual(answers[0][0], "p2")
        self.assertIn("hello you", json.loads(answers[0][1])["prompt"])

    def test_the_variable_library_reaches_the_editor(self):
        catalog = json.loads(self.editor.bot_get_variables())
        self.assertTrue(catalog)
        for spec in catalog:
            self.assertTrue(spec["token"].startswith("{"))
            self.assertTrue(spec["description"])

    def test_every_advertised_variable_resolves_in_a_real_prompt(self):
        """The library is only useful if the editor and the renderer agree."""
        for spec in json.loads(self.editor.bot_get_variables()):
            self.editor.bot_save_prompt("suggest_reply", spec["token"])
            self.bridge.bot_suggest_reply("v" + spec["name"], "Anna", "today")
            self.drain()
            self.assertNotEqual(self.grok.prompts[-1], spec["token"],
                                spec["token"] + " reached Grok unresolved")

    def test_the_editor_can_check_a_template_without_saving_it(self):
        report = json.loads(self.editor.bot_check_prompt("{person_name} {no}"))
        self.assertEqual(report["unknown"], ["no"])
        self.assertEqual(report["used"], ["person_name"])
        self.assertFalse(report["ok"])
        self.assertTrue(json.loads(
            self.editor.bot_check_prompt("hi {person_name}"))["ok"])

    def test_reset_restores_the_shipped_template(self):
        self.editor.bot_save_prompt("suggest_reply", "Reply to {nick} now")
        self.assertTrue(self.editor.bot_reset_prompt("suggest_reply"))
        self.assertFalse(self.editor.bot_reset_prompt("suggest_reply"))
        templates = json.loads(self.editor.bot_get_prompts())
        self.assertFalse(templates[0]["edited"])


class TestTheSendGateOverTheWire(BotBridgeCase):
    """The slot really refuses the wrong chat — `deliver` is NOT patched out.

    The other send tests replace `deliver` to observe the call; this one lets
    the real gate run, because the value of the gate is precisely that the
    slot cannot be talked into typing.
    """

    def typed(self):
        """Every text the page was asked to accept (should stay empty)."""
        # H5 moved click_send into backend/send_button.py; each half of the
        # two-step is patched on the module that defines it.
        from backend import message_injector, send_button
        seen = []

        async def typing(_cdp, text, *a, **k):
            seen.append(text)
            return True

        async def clicking(*_a, **_k):
            return True

        original = (message_injector.type_message, send_button.click_send)
        message_injector.type_message = typing
        send_button.click_send = clicking
        self.addCleanup(lambda: setattr(message_injector, "type_message",
                                        original[0]))
        self.addCleanup(lambda: setattr(send_button, "click_send",
                                        original[1]))
        return seen

    def test_a_message_for_another_person_is_refused_at_the_slot(self):
        seen = self.typed()
        self.ctx.cdp = type("Cdp", (), {"is_connected": True})()
        self.parser.partner = "Boris"          # the browser moved on
        self.bridge.bot_send_message("w1", "Anna", "see you tomorrow")
        self.drain()
        self.assertEqual(seen, [], "nothing may be typed into Boris's chat")
        self.assertTrue(self.errors, "the window must be told why")
        self.assertIn("Boris", self.errors[0][1])

    def test_the_right_chat_still_goes_through(self):
        seen = self.typed()
        self.ctx.cdp = type("Cdp", (), {"is_connected": True})()
        self.bridge.bot_send_message("w2", "Anna", "see you tomorrow")
        self.drain()
        self.assertEqual(seen, ["see you tomorrow"])


class TestTheLabelWriteIsUndoable(BotBridgeCase):
    """RULE 12: a label set here is one entry on the ONE global timeline."""

    def test_the_service_is_wired_to_the_label_transaction(self):
        self.assertIsNotNone(self.bridge.service.edit,
                             "the bridge must hand the service the "
                             "LabelBridge transaction, not let it write raw")

    def test_applying_a_label_pushes_exactly_one_undo_entry(self):
        pushed = []
        self.ctx.undo.push = lambda kind, value: pushed.append(kind)
        self.bridge.bot_apply_reaction("Anna", "positive")
        self.assertEqual(pushed, ["labels"])

    def test_an_unchanged_label_pushes_nothing(self):
        self.bridge.bot_apply_reaction("Anna", "positive")
        pushed = []
        self.ctx.undo.push = lambda kind, value: pushed.append(kind)
        self.bridge.bot_apply_reaction("Anna", "positive")
        self.assertEqual(pushed, [])

    def test_the_label_manager_window_is_told_to_refresh(self):
        """Without this the pills in the other window go stale."""
        from core.events import LabelsChanged, PeopleChanged
        seen = []
        self.ctx.bus.subscribe(LabelsChanged, lambda e: seen.append("labels"))
        self.ctx.bus.subscribe(PeopleChanged, lambda e: seen.append("people"))
        self.bridge.bot_apply_reaction("Anna", "negative")
        self.assertIn("people", seen)


class TestTheEditorHoldsNoConnectionSettings(PromptBridgeCase):
    """Acceptance: "API settings are absent from the Prompt Editor body".

    Enforced on the bridge AND on the markup, because "absent" has to mean
    absent — a hidden-but-wired key field would pass a screenshot review and
    still be the thing the spec asked to remove.
    """

    def test_the_key_slots_are_gone_from_the_editor_bridge(self):
        for slot in ("bot_connection", "bot_save_connection"):
            self.assertFalse(hasattr(self.editor, slot),
                             f"{slot} belongs to the connections window now")

    def test_the_editor_markup_has_no_key_or_endpoint_field(self):
        repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        html = open(os.path.join(repo, "ui", "index.html"),
                    encoding="utf-8").read()
        editor = html[html.index('id="winBotPrompt"'):]
        editor = editor[:editor.index("</main>")]
        for gone in ('id="botApiKeyInput"', 'id="botModelInput"',
                     'id="botConnSaveBtn"'):
            self.assertNotIn(gone, editor, f"{gone} is still in the editor")

    def test_the_editor_cannot_choose_a_connection_either(self):
        """One setting, one home. The editor used to carry a connection
        dropdown beside the preset one, which meant two windows could change
        which AI runs and the user had to guess which one won. Prompts now
        run on whichever connection the AI Connections popup marks in use."""
        for slot in ("bot_prompt_connections",
                     "bot_use_connection_for_prompts"):
            self.assertFalse(hasattr(self.editor, slot),
                             f"{slot} is a second way to switch connection")

    def test_the_editor_markup_has_no_connection_dropdown(self):
        repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        html = open(os.path.join(repo, "ui", "index.html"),
                    encoding="utf-8").read()
        editor = html[html.index('id="winBotPrompt"'):]
        editor = editor[:editor.index("</main>")]
        for gone in ('id="botConnSelect"', 'id="botConnWarn"'):
            self.assertNotIn(gone, editor, f"{gone} is still in the editor")
        self.assertIn('id="botPromptSettingsBtn"', editor,
                      "the popup must still be reachable from the editor")


class SettingsBridgeCase(BotBridgeCase):
    """The AI Connections window is its own surface, so its own bridge."""

    def setUp(self):
        super().setUp()
        self.settings = BotSettingsBridge(self.ctx)

    def add(self, title, provider="grok", key="xai-secret-key-1", model="m1"):
        return self.settings.bot_save_connection("", json.dumps(
            {"title": title, "provider": provider, "api_key": key,
             "model": model, "url": ""}))

    def entry(self, ident):
        data = json.loads(self.settings.bot_connections())
        return next((c for c in data["connections"] if c["id"] == ident), None)

    def listed(self):
        return json.loads(self.settings.bot_connections())["connections"]

    def added(self):
        """Only the connections this test made.

        Every provider is seeded with a keyless row so it is selectable on a
        fresh install (that IS the connection list the user sees), so a test
        about saving has to look past the seeds.

        The seed titles come from the provider table rather than a literal
        set, so adding a provider does not silently break every test that
        counts connections."""
        seeded = {spec.title for spec in bot_providers.PROVIDERS.values()}
        return [c for c in self.listed()
                if c["has_key"] or c["title"] not in seeded]


class TestConnectionsOverTheWire(SettingsBridgeCase):
    def test_a_malformed_payload_is_refused_rather_than_crashing(self):
        """The fields cross the bridge as JSON; a broken string must come
        back as "not saved", not as an exception through QWebChannel."""
        self.assertEqual(self.settings.bot_save_connection("", "{oops"), "")
        self.assertEqual(self.settings.bot_save_connection("", "[1,2]"), "")
        self.assertEqual(self.added(), [])

    def test_a_connection_is_created_and_listed(self):
        ident = self.add("Grok — grok-4.3", model="grok-4.3")
        self.assertTrue(ident)
        entry = self.entry(ident)
        self.assertEqual(entry["title"], "Grok — grok-4.3")
        self.assertEqual(entry["model"], "grok-4.3")
        self.assertTrue(entry["ok"])

    def test_several_connections_can_share_one_provider(self):
        """The whole reason connections are not providers: the user wants
        "Grok grok-4.3" AND "Grok grok-2 (cheap)" at the same time."""
        first = self.add("Grok — grok-4.3", model="grok-4.3")
        second = self.add("Grok — cheap", model="grok-2-latest")
        self.assertNotEqual(first, second)
        models = {c["id"]: c["model"] for c in self.listed()}
        self.assertEqual(models[first], "grok-4.3")
        self.assertEqual(models[second], "grok-2-latest")

    def test_a_google_connection_sits_beside_a_grok_one(self):
        self.add("Grok", provider="grok")
        google = self.add("Work Gemini", provider="google",
                          key="AIza-key-1234", model="gemini-2.0-flash")
        self.assertEqual(self.entry(google)["provider"], "google")
        self.assertEqual(len(self.added()), 2)

    def test_the_key_is_masked_and_never_sent_in_full(self):
        ident = self.add("Grok", key="xai-supersecret-key")
        entry = self.entry(ident)
        self.assertTrue(entry["has_key"])
        self.assertNotIn("supersecret", self.settings.bot_connections())
        self.assertTrue(entry["masked"])

    def test_a_blank_key_on_update_keeps_the_stored_one(self):
        ident = self.add("Grok", key="xai-original-key-x")
        self.settings.bot_save_connection(ident, json.dumps(
            {"title": "Grok", "provider": "grok", "api_key": "",
             "model": "grok-4.3", "url": ""}))
        entry = self.entry(ident)
        self.assertTrue(entry["has_key"], "blank means unchanged, not erase")
        self.assertEqual(entry["model"], "grok-4.3")

    def test_a_connection_without_a_key_says_why(self):
        entry = self.entry(self.add("Half-configured", key=""))
        self.assertFalse(entry["ok"])
        self.assertIn("no API key", entry["problem"])

    def test_an_unknown_provider_is_refused(self):
        self.assertEqual(self.settings.bot_save_connection(
            "", json.dumps({"title": "Nope", "provider": "nonesuch",
                            "api_key": "k", "model": "m"})), "")
        self.assertEqual(self.added(), [])

    def test_deleting_one_connection_leaves_the_others(self):
        keep, drop = self.add("Keep me"), self.add("Drop me")
        self.assertTrue(self.settings.bot_delete_connection(drop))
        ids = [c["id"] for c in self.listed()]
        self.assertIn(keep, ids)
        self.assertNotIn(drop, ids)

    def test_connections_survive_a_restart(self):
        ident = self.add("Persistent", model="grok-4.3")
        store = ConnectionStore(ConfigManager(self.cfg._path))
        found = store.get(ident)
        self.assertIsNotNone(found)
        self.assertEqual(found.model, "grok-4.3")
        self.assertEqual(found.api_key, "xai-secret-key-1")

    def test_the_active_connection_survives_a_restart(self):
        ident = self.add("Chosen")
        self.assertTrue(self.settings.bot_use_connection(ident))
        reopened = ConfigManager(self.cfg._path)
        self.assertEqual(ConnectionStore(reopened).active().id, ident)

    def test_deleting_the_active_connection_clears_the_choice(self):
        ident = self.add("Only one")
        self.settings.bot_use_connection(ident)
        self.settings.bot_delete_connection(ident)
        self.assertEqual(ConnectionStore(self.cfg).active_id(), "")

    def test_the_dialog_offers_the_provider_kinds(self):
        ids = [p["id"] for p in
               json.loads(self.settings.bot_connections())["providers"]]
        self.assertIn("grok", ids)
        self.assertIn("google", ids)

    def test_the_selected_connection_is_the_one_that_runs(self):
        """The dropdown has to actually route the request, not just look
        selected — that is the acceptance criterion."""
        self.add("Grok one", model="grok-4.3")
        google = self.add("Gemini", provider="google",
                          key="AIza-key-9999", model="gemini-2.0-flash")
        self.settings.bot_use_connection(google)
        client = client_for(self.cfg)
        self.assertEqual(client.settings.model, "gemini-2.0-flash")
        self.assertIn("generativelanguage", client.settings.endpoint)


class TestConnectionsAndPresetsAreIndependent(SettingsBridgeCase):
    """Acceptance: deleting a preset must not affect AI connections — and
    the converse, which is the more dangerous direction."""

    def test_deleting_a_connection_keeps_the_prompt_presets(self):
        editor = BotPromptBridge(self.ctx)
        editor.bot_save_preset("suggest_reply", "Short", "be brief", "")
        self.settings.bot_delete_connection(self.add("Doomed"))
        presets = json.loads(editor.bot_get_presets("suggest_reply"))
        self.assertEqual([p["title"] for p in presets], ["Short"])

    def test_deleting_a_preset_keeps_the_connections(self):
        editor = BotPromptBridge(self.ctx)
        ident = self.add("Safe")
        preset = editor.bot_save_preset("suggest_reply", "Short", "brief", "")
        self.assertTrue(editor.bot_delete_preset(preset))
        self.assertTrue(self.entry(ident)["has_key"])

    def test_editing_a_preset_never_touches_a_key(self):
        editor = BotPromptBridge(self.ctx)
        ident = self.add("Keyed", key="xai-untouched-key")
        editor.bot_save_preset("suggest_reply", "V2", "different text", "")
        self.assertEqual(ConnectionStore(self.cfg).get(ident).api_key,
                         "xai-untouched-key")


class TestPromptPresets(PromptBridgeCase):
    def titles(self, template="suggest_reply"):
        return [p["title"] for p in
                json.loads(self.editor.bot_get_presets(template))]

    def test_a_preset_is_saved_and_listed(self):
        self.assertTrue(self.editor.bot_save_preset(
            "suggest_reply", "Short and casual", "be brief with {nick}", ""))
        self.assertEqual(self.titles(), ["Short and casual"])

    def test_a_new_preset_does_not_overwrite_another(self):
        self.editor.bot_save_preset("suggest_reply", "One", "text one", "")
        self.editor.bot_save_preset("suggest_reply", "Two", "text two", "")
        self.assertEqual(sorted(self.titles()), ["One", "Two"])

    def test_an_existing_preset_is_updated_in_place(self):
        ident = self.editor.bot_save_preset("suggest_reply", "One", "old", "")
        self.editor.bot_save_preset("suggest_reply", "One", "new text", ident)
        presets = json.loads(self.editor.bot_get_presets("suggest_reply"))
        self.assertEqual(len(presets), 1, "update must not create a second")
        self.assertEqual(presets[0]["text"], "new text")

    def test_a_preset_can_be_deleted(self):
        ident = self.editor.bot_save_preset("suggest_reply", "Bye", "x", "")
        self.assertTrue(self.editor.bot_delete_preset(ident))
        self.assertEqual(self.titles(), [])
        self.assertFalse(self.editor.bot_delete_preset(ident))

    def test_presets_belong_to_their_template(self):
        self.editor.bot_save_preset("suggest_reply", "For replies", "a", "")
        self.editor.bot_save_preset("analyze_reaction", "For analysis", "b", "")
        self.assertEqual(self.titles("suggest_reply"), ["For replies"])
        self.assertEqual(self.titles("analyze_reaction"), ["For analysis"])

    def test_presets_survive_a_restart(self):
        self.editor.bot_save_preset("suggest_reply", "Durable", "keep me", "")
        reopened = BotPromptBridge(
            BridgeContext(config=ConfigManager(self.cfg._path)))
        self.assertEqual(
            [p["title"] for p in
             json.loads(reopened.bot_get_presets("suggest_reply"))],
            ["Durable"])

    def test_an_empty_or_unnamed_preset_is_refused(self):
        self.assertEqual(self.editor.bot_save_preset(
            "suggest_reply", "Named", "   ", ""), "")
        self.assertEqual(self.editor.bot_save_preset(
            "suggest_reply", "", "text", ""), "")
        self.assertEqual(self.titles(), [])

    def test_a_preset_with_an_unknown_variable_is_still_saved(self):
        """Same rule as templates (I-27): unknown is a warning, not a
        refusal that silently discards the user's wording."""
        self.assertTrue(self.editor.bot_save_preset(
            "suggest_reply", "Draft", "hi {tone}", ""))

    def test_saving_a_preset_does_not_change_the_live_template(self):
        """Presets are a library: nothing is sent differently until the
        user presses Save in the editor."""
        before = json.loads(self.editor.bot_get_prompts())[0]["text"]
        self.editor.bot_save_preset("suggest_reply", "Other", "different", "")
        after = json.loads(self.editor.bot_get_prompts())[0]["text"]
        self.assertEqual(before, after)


class TestConnectionTest(SettingsBridgeCase):
    def answers(self):
        got = []
        self.settings._chat_bridge().bot_reply_ready.connect(
            lambda req, payload: got.append((req, payload)))
        return got

    def test_an_unsaved_connection_cannot_be_tested(self):
        got = self.answers()
        self.settings.bot_test_connection("t0", "nope")
        self.drain()
        report = json.loads(got[0][1])
        self.assertFalse(report["ok"])
        self.assertEqual(report["code"], "bot_no_connection")

    def test_a_connection_with_no_key_fails_with_a_reason(self):
        ident = self.add("Keyless", key="")
        got = self.answers()
        self.settings.bot_test_connection("t1", ident)
        self.drain()
        report = json.loads(got[0][1])
        self.assertFalse(report["ok"])
        self.assertIn("no API key", report["detail"])

    def test_the_test_names_the_connection_it_tested(self):
        ident = self.add("Named one")
        got = self.answers()
        self.settings.bot_test_connection("t2", ident)
        self.drain()
        self.assertEqual(json.loads(got[0][1])["connection"], ident)


class TestTheUiCallsSlotsThatExist(unittest.TestCase):
    """Every `App.bridge.x(...)` in the AI windows must be a real slot.

    A JS test can only stub what it knows about, so a slot renamed on the
    Python side stays green in both suites and dies only in the app. This
    reads the shipped JS and checks the router that the app actually builds.
    """

    SLOT = re.compile(r"App\.bridge\.([a-z_]+)")

    def test_every_slot_the_ai_windows_call_is_on_the_router(self):
        from bridge.router import _build_router_class
        router = _build_router_class()
        repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        ui = os.path.join(repo, "ui", "js")
        for name in ("bot-chat.js", "bot-prompt.js", "bot-settings.js"):
            text = open(os.path.join(ui, name), encoding="utf-8").read()
            for slot in sorted(set(self.SLOT.findall(text))):
                self.assertTrue(hasattr(router, slot),
                                f"{name} calls App.bridge.{slot}(), which "
                                f"no bridge provides")
