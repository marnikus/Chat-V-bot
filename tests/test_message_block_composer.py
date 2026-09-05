"""Type Message block “use composer” checkbox + paste/Ctrl+V fallback.

FEATURE — the ⌨️ Type Message block can send the text of the Message
         Composer window (use_composer checkbox) instead of its own stored
         text; the composer text is mirrored live onto the engine.
BUG     — “Textarea value injection failed (page did not accept input)”:
         direct .value injection is not accepted everywhere, so the
         injector now verifies each attempt and falls back to copying the
         text and pasting with a real Ctrl+V into the focused field (and to
         CDP Input.insertText when the clipboard is unavailable).

Run with:  python3 tests/test_message_block_composer.py
"""

import asyncio
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import actions.type_message as type_message_mod  # noqa: E402
from actions.base_action import ActionResult  # noqa: E402
from actions.type_message import TypeMessage  # noqa: E402
from backend.action_engine import ActionEngine  # noqa: E402
import backend.message_injector as injector  # noqa: E402
from backend.bridge import Bridge  # noqa: E402
from backend.cdp_client import CDPClient  # noqa: E402
from backend.config_manager import ConfigManager  # noqa: E402
from backend.criteria_engine import CriteriaEngine  # noqa: E402
from backend.user_memory import UserMemory  # noqa: E402

UI_DIR = os.path.join(os.path.dirname(__file__), "..", "ui")


def run(coro):
    return asyncio.run(coro)


class RecordingEngine:
    """Minimal engine stand-in: exposes report() and composer_text."""

    def __init__(self, composer_text=""):
        self.composer_text = composer_text
        self.messages = []

    def report(self, msg, level="info"):
        self.messages.append((msg, level))


class FakeInjector:
    """Stands in for backend.message_injector.type_message: records the
    text it was asked to type."""

    def __init__(self, result=True):
        self.result = result
        self.typed = None
        self.speed = None

    async def __call__(self, cdp, text, typing_speed_ms=30, report=None):
        self.typed = text
        self.speed = typing_speed_ms
        if report:
            report(f"typed {len(text)} chars", "info")
        return self.result


class FakeCDP:
    """Scriptable stand-in for CDPClient used by the injector tests."""

    def __init__(self):
        self.sent = []
        self.readback = ""         # what _field_value returns
        self.readback_after_paste = None
        self.pasted = False
        self.clipboard_ok = True
        self.setter_ok = True
        self.clipboard_write_attempted = False

    async def evaluate(self, expression):
        if "navigator.clipboard.writeText" in expression:
            self.clipboard_write_attempted = True
            return "ok" if self.clipboard_ok else "err:denied"
        if "location.origin" in expression:
            return "http://localhost"
        if "HTMLTextAreaElement.prototype" in expression or \
                "HTMLInputElement.prototype" in expression:
            return "ok" if self.setter_ok else "no-element"
        if "setSelectionRange" in expression or "selectNodeContents" in expression:
            return True
        if "('value' in el" in expression or '"value" in el' in expression:
            return self.readback_after_paste if (self.pasted and
                                                 self.readback_after_paste
                                                 is not None) else self.readback
        if "querySelectorAll(" in expression or "probe" in expression.lower():
            return json.dumps({"found": True, "visible": True,
                               "disabled": False, "clickable": True,
                               "text": "", "total": 1, "error": None})
        raise AssertionError(f"unhandled evaluate: {expression[:80]}")

    async def send(self, method, params=None):
        self.sent.append((method, params or {}))
        if method == "Input.dispatchKeyEvent":
            # after the Ctrl+V key sequence the field holds the pasted text
            if any(p.get("key") == "v" for _, p in self.sent):
                self.pasted = True
        return {}


def build_block(engine, message="", use_composer=False, speed=25):
    blk = TypeMessage(message=message, use_composer=use_composer,
                      typing_speed_ms=speed, pre_delay_ms=0)
    fake = FakeInjector()
    patcher = mock.patch.object(type_message_mod, "type_message", fake)
    return blk, fake, patcher


class TestComposerTextSelection(unittest.TestCase):
    def test_default_block_types_its_own_text(self):
        async def go():
            blk, fake, patcher = build_block(
                engine=RecordingEngine(composer_text="composer msg"),
                message="Hello {{nick}}!")
            with patcher:
                result = await blk.execute("Alice", None, RecordingEngine())
            self.assertEqual(result, ActionResult.OK)
            self.assertEqual(fake.typed, "Hello Alice!")
        run(go())

    def test_use_composer_sends_the_composer_text(self):
        async def go():
            engine = RecordingEngine(composer_text="Hi {{nick}}, from composer")
            blk, fake, patcher = build_block(
                engine=engine, message="block text (must be ignored)",
                use_composer=True)
            with patcher:
                result = await blk.execute("Bob", None, engine)
            self.assertEqual(result, ActionResult.OK)
            self.assertEqual(fake.typed, "Hi Bob, from composer")
            self.assertEqual(fake.speed, 25)
        run(go())

    def test_use_composer_with_empty_composer_fails_with_warning(self):
        async def go():
            engine = RecordingEngine(composer_text="   ")
            blk, fake, patcher = build_block(
                engine=engine, message="block text", use_composer=True)
            with patcher:
                result = await blk.execute("Bob", None, engine)
            self.assertEqual(result, ActionResult.FAIL)
            self.assertIsNone(fake.typed, "nothing must be typed")
            self.assertTrue(any("composer is empty" in m
                                for m, _ in engine.messages))
        run(go())

    def test_failed_injection_returns_fail(self):
        async def go():
            blk, fake, patcher = build_block(
                engine=RecordingEngine(), message="Hi {{nick}}")
            fake.result = False
            with patcher:
                result = await blk.execute("Bob", None, RecordingEngine())
            self.assertEqual(result, ActionResult.FAIL)
        run(go())

    def test_config_schema_exposes_the_checkbox(self):
        schema = TypeMessage().config_schema()
        self.assertIn("use_composer", schema)
        self.assertEqual(schema["use_composer"]["default"], False)

    def test_saved_block_round_trips_use_composer(self):
        blk = TypeMessage(message="x", use_composer=True)
        d = blk.to_dict()
        self.assertTrue(d["use_composer"])
        again = TypeMessage(**{k: v for k, v in d.items()
                               if k != "block_id"})
        self.assertTrue(again.use_composer)


class TestComposerMirror(unittest.TestCase):
    def test_bridge_mirrors_composer_text_onto_the_engine(self):
        async def go():
            with tempfile.TemporaryDirectory() as tmp:
                mem = UserMemory(os.path.join(tmp, "u.db"))
                await mem.init()
                try:
                    cfg = ConfigManager(os.path.join(tmp, "cfg.json"))
                    cdp = CDPClient()
                    eng = ActionEngine(cdp=cdp, memory=mem,
                                       criteria=CriteriaEngine())
                    br = Bridge(cdp=cdp, memory=mem, criteria=CriteriaEngine(),
                                engine=eng, config=cfg)
                    br.save_message("Hello from the window")
                    self.assertEqual(eng.composer_text,
                                     "Hello from the window")
                finally:
                    await mem.close()
        run(go())


class TestInjectorFallback(unittest.TestCase):
    def test_direct_value_set_succeeds(self):
        async def go():
            cdp = FakeCDP()
            cdp.readback = "hello"
            messages = []
            ok = await injector.type_message(
                cdp, "hello", 30,
                lambda m, l="info": messages.append((m, l)))
            self.assertTrue(ok)
            self.assertTrue(any("Typed 5 char(s)" in m for m, _ in messages))
        run(go())

    def test_paste_with_ctrl_v_fallback_when_page_rejects_setter(self):
        async def go():
            cdp = FakeCDP()
            # page refuses the direct .value write: readback stays empty
            cdp.readback = ""
            cdp.readback_after_paste = "pasted text"
            messages = []
            ok = await injector.type_message(
                cdp, "pasted text", 30,
                lambda m, l="info": messages.append((m, l)))
            self.assertTrue(ok, messages)
            keys = [p for m, p in cdp.sent
                    if m == "Input.dispatchKeyEvent"]
            self.assertEqual(len(keys), 2, "rawKeyDown + keyUp expected")
            self.assertTrue(all(p.get("modifiers") == 2 for p in keys))
            self.assertTrue(all(p.get("key") == "v" for p in keys))
            self.assertTrue(any("Ctrl+V" in m for m, _ in messages))
            self.assertTrue(cdp.clipboard_write_attempted,
                            "the text must be copied to the clipboard first")
        run(go())

    def test_insert_text_fallback_when_clipboard_unavailable(self):
        async def go():
            cdp = FakeCDP()
            cdp.readback = ""
            cdp.clipboard_ok = False          # clipboard strategy unavailable
            cdp.sent = []                     # reset recorded sends
            # After Input.insertText the field finally holds the text.
            orig_send = cdp.send

            async def send2(method, params=None):
                await orig_send(method, params)
                if method == "Input.insertText":
                    cdp.pasted = True
                    cdp.readback = params.get("text", "")
                return {}

            cdp.send = send2
            messages = []
            ok = await injector.type_message(
                cdp, "inserted text", 30,
                lambda m, l="info": messages.append((m, l)))
            self.assertTrue(ok, messages)
            self.assertTrue(any("Input.insertText" in m for m, _ in messages))
            methods = [m for m, _ in cdp.sent]
            self.assertIn("Input.insertText", methods)
        run(go())

    def test_total_failure_reports_all_attempts(self):
        async def go():
            cdp = FakeCDP()
            cdp.readback = ""
            cdp.clipboard_ok = False
            cdp.readback_after_paste = ""
            cdp.pasted = False
            cdp.sent = []
            messages = []
            ok = await injector.type_message(
                cdp, "never lands", 30,
                lambda m, l="info": messages.append((m, l)))
            self.assertFalse(ok)
            errs = [m for m, _ in messages if m.startswith("❌")]
            self.assertTrue(errs)
            text = " ".join(errs)
            self.assertIn("did not accept input", text)
        run(go())

    def test_empty_text_warns_without_typing(self):
        async def go():
            cdp = FakeCDP()
            messages = []
            ok = await injector.type_message(
                cdp, "", 30, lambda m, l="info": messages.append((m, l)))
            self.assertFalse(ok)
            self.assertTrue(any("empty" in m for m, _ in messages))
        run(go())

    def test_embedding_survives_hostile_characters(self):
        """CR / U+2028 / quotes must not break the generated JS."""
        from backend.message_injector import _js
        hostile = "line1\r\nline2\u2028quote'\" end"
        literal = _js(hostile)
        # json.dumps(ensure_ascii=True) output is a double-quoted JS literal
        self.assertTrue(literal.startswith('"') and literal.endswith('"'))
        self.assertEqual(json.loads(literal), hostile)


class TestUiContract(unittest.TestCase):
    def test_stack_dnd_offers_the_checkbox_and_textarea_field(self):
        with open(os.path.join(UI_DIR, "js", "stack-dnd.js"),
                  encoding="utf-8") as fh:
            js = fh.read()
        self.assertIn("use_composer:false", js)
        self.assertIn("Use text from the Message Composer window", js)
        self.assertIn("textarea[data-key]", js)
        self.assertIn("data-key=\"message\" rows=\"3\"", js)
        self.assertIn("text: Message Composer", js)
        self.assertIn("disabled: text comes from the Message Composer window", js)

    def test_css_styles_the_disabled_field(self):
        with open(os.path.join(UI_DIR, "css", "stack.css"),
                  encoding="utf-8") as fh:
            css = fh.read()
        self.assertIn("textarea:disabled", css)


if __name__ == "__main__":
    unittest.main(verbosity=2)
