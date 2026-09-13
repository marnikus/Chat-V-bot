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
from bridge.context import BridgeContext  # noqa: E402
from core.result import Err, Ok  # noqa: E402
from services.bot_grok import GrokSettings  # noqa: E402
from stores.history_db import HistoryDB  # noqa: E402
from stores.label_store import LabelStore  # noqa: E402

TODAY = date.today().isoformat()

BOT_SLOTS = ["bot_load_today", "bot_suggest_reply", "bot_analyze_reaction",
             "bot_preview_prompt", "bot_send_message", "bot_reaction_state",
             "bot_apply_reaction", "bot_get_prompts", "bot_save_prompt",
             "bot_reset_prompt", "bot_connection", "bot_save_connection"]
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
        self.bridge.bot_load_today("r1", "Anna")
        self.drain()
        page = self.answer("r1")
        self.assertEqual([i["text"] for i in page["items"]],
                         ["hi", "hello you"])

    def test_two_requests_do_not_cross(self):
        self.bridge.bot_load_today("a", "Anna")
        self.bridge.bot_load_today("b", "Nobody")
        self.drain()
        self.assertFalse(self.answer("a")["empty"])
        self.assertTrue(self.answer("b")["empty"])

    def test_a_grok_failure_answers_on_the_error_signal(self):
        self.bridge.service.grok = FakeGrok(Err("grok_no_key", "no key"))
        self.bridge.bot_suggest_reply("r2", "Anna")
        self.drain()
        self.assertEqual(self.errors[0][0], "r2")
        self.assertIn("no key", self.errors[0][1])
        self.assertEqual(self.replies, [])

    def test_a_raising_service_becomes_an_error_not_a_dead_request(self):
        async def boom(_nick):
            raise RuntimeError("database exploded")

        self.bridge.service.today = boom
        self.bridge.bot_load_today("r3", "Anna")
        self.drain()
        self.assertEqual(self.errors[0][0], "r3")


class TestVerificationFlow(BotBridgeCase):
    def test_a_suggestion_is_pending_and_sends_nothing(self):
        sent = []
        self.patch_deliver(sent)
        self.bridge.bot_suggest_reply("s1", "Anna")
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
        self.bridge.bot_analyze_reaction("a1", "Anna")
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
        self.bridge.bot_suggest_reply("p1", "Anna")
        self.drain()
        self.assertEqual(self.grok.prompts[0], "Reply to Anna now")

    def test_preview_shows_the_rendered_prompt(self):
        answers = []
        chat = self.editor._chat_bridge()
        chat.bot_reply_ready.connect(
            lambda req, payload: answers.append((req, payload)))
        self.editor.bot_preview_prompt("p2", "Anna", "analyze_reaction")
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
            self.bridge.bot_suggest_reply("v" + spec["name"], "Anna")
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
        from backend import message_injector
        seen = []

        async def typing(_cdp, text, *a, **k):
            seen.append(text)
            return True

        async def clicking(*_a, **_k):
            return True

        original = (message_injector.type_message, message_injector.click_send)
        message_injector.type_message = typing
        message_injector.click_send = clicking
        self.addCleanup(lambda: setattr(message_injector, "type_message",
                                        original[0]))
        self.addCleanup(lambda: setattr(message_injector, "click_send",
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


class TestTheConnectionSettings(PromptBridgeCase):
    def test_saving_a_key_makes_it_the_one_used(self):
        self.assertTrue(self.editor.bot_save_connection("xai-9", "grok-x"))
        state = json.loads(self.editor.bot_connection())
        self.assertTrue(state["has_key"])
        self.assertEqual(state["model"], "grok-x")

    def test_the_key_never_travels_back_over_the_wire(self):
        self.editor.bot_save_connection("xai-secret", "")
        self.assertNotIn("xai-secret", self.editor.bot_connection())


if __name__ == "__main__":
    unittest.main()


class SettingsBridgeCase(BotBridgeCase):
    """The AI Settings dialog is its own surface, so its own bridge."""

    def setUp(self):
        super().setUp()
        self.settings = BotSettingsBridge(self.ctx)

    def entry(self, provider):
        data = json.loads(self.settings.bot_providers())
        return next(p for p in data["providers"] if p["id"] == provider)


class TestProviderSettingsOverTheWire(SettingsBridgeCase):
    def test_the_dialog_lists_every_provider_with_its_state(self):
        data = json.loads(self.settings.bot_providers())
        ids = [p["id"] for p in data["providers"]]
        self.assertIn("grok", ids)
        self.assertIn("google", ids)
        self.assertEqual(data["active"], "grok")

    def test_a_saved_key_is_reported_masked_and_never_in_full(self):
        self.settings.bot_save_provider("google", "AIza-supersecret-key",
                                        "", "")
        entry = self.entry("google")
        self.assertTrue(entry["has_key"])
        self.assertNotIn("supersecret", json.dumps(entry))
        self.assertTrue(entry["masked"])

    def test_each_provider_keeps_its_own_key(self):
        self.settings.bot_save_provider("grok", "xai-one-key-here", "", "")
        self.settings.bot_save_provider("google", "AIza-other-key-x", "", "")
        self.assertTrue(self.entry("grok")["has_key"])
        self.assertTrue(self.entry("google")["has_key"])
        self.assertNotEqual(self.entry("grok")["masked"],
                            self.entry("google")["masked"])

    def test_switching_provider_keeps_the_prompt_templates(self):
        """The acceptance criterion, tested the only way that means
        anything: save a template, switch, read it back."""
        editor = BotPromptBridge(self.ctx)
        editor.bot_save_prompt("suggest_reply", "my careful template {nick}")
        self.assertTrue(self.settings.bot_use_provider("google"))
        self.assertEqual(json.loads(editor.bot_get_prompts())[0]["text"],
                         "my careful template {nick}")

    def test_switching_provider_keeps_the_other_provider_key(self):
        self.settings.bot_save_provider("grok", "xai-keep-me-please", "", "")
        self.settings.bot_use_provider("google")
        self.settings.bot_save_provider("google", "AIza-new-key-here", "", "")
        self.assertTrue(self.entry("grok")["has_key"],
                        "switching away must not erase a stored key")

    def test_the_active_provider_survives_a_restart(self):
        self.settings.bot_use_provider("google")
        reopened = ConfigManager(self.cfg._path)
        self.assertEqual(GrokSettings.active_id(reopened), "google")

    def test_an_unknown_provider_is_refused(self):
        self.assertFalse(self.settings.bot_use_provider("nope"))
        self.assertEqual(json.loads(self.settings.bot_providers())["active"],
                         "grok")

    def test_saving_a_blank_key_keeps_the_stored_one(self):
        """The field never echoes the key back, so blank means "unchanged" —
        if it meant "erase", re-saving the model would silently log you out."""
        self.settings.bot_save_provider("google", "AIza-original-key", "", "")
        self.settings.bot_save_provider("google", "", "gemini-2.0-flash", "")
        self.assertTrue(self.entry("google")["has_key"])
        self.assertEqual(self.entry("google")["model"], "gemini-2.0-flash")

    def test_the_endpoint_is_built_for_the_provider(self):
        self.assertIn(":generateContent", self.entry("google")["endpoint"])
        self.assertIn("api.x.ai", self.entry("grok")["endpoint"])


class TestConnectionTest(SettingsBridgeCase):
    def test_a_provider_with_no_key_fails_the_test_with_a_reason(self):
        answers = []
        chat = self.settings._chat_bridge()
        chat.bot_reply_ready.connect(
            lambda req, payload: answers.append((req, payload)))
        self.settings.bot_test_provider("t1", "google")
        self.drain()
        report = json.loads(answers[0][1])
        self.assertFalse(report["ok"])
        self.assertEqual(report["code"], "grok_no_key")
        self.assertIn("Google", report["detail"])

    def test_the_test_names_the_provider_it_tested(self):
        answers = []
        chat = self.settings._chat_bridge()
        chat.bot_reply_ready.connect(
            lambda req, payload: answers.append((req, payload)))
        self.settings.bot_test_provider("t2", "grok")
        self.drain()
        self.assertEqual(json.loads(answers[0][1])["provider"], "grok")


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
