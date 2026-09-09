"""`actions.type_message` — payload, inject, failure (P1).

SPEC-FIRST (docs/ACTIONS_TEST_DESIGN_2026-09-09.md §3). Contract:

  * module docstring — the block sends either its own stored text or, with
    "use composer" on, the live Message Composer text;
  * inline contract — "{{nick}} -> the remembered selected user (Click User)
    of this run; falls back to the queued user of this step";
  * composer on but empty => warn + nothing typed (the injector must not be
    called with an empty string);
  * `config_schema` exposes use_composer / message / typing_speed_ms.

Run with:  python3 tests/test_type_message_block.py
"""

import asyncio
import os
import sys
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import actions.type_message as tm  # noqa: E402
from actions.base_action import ActionResult  # noqa: E402
from actions.type_message import TypeMessage  # noqa: E402


def run(coro):
    return asyncio.run(coro)


class FakeEngine:
    def __init__(self, selected_nick="", composer_text=""):
        self.selected_nick = selected_nick
        self.composer_text = composer_text
        self.lines = []

    def report(self, message, level="info"):
        self.lines.append((level, message))

    def text(self):
        return " | ".join(m for _lvl, m in self.lines)


class RecordingInjector:
    """Stands in for backend.message_injector.type_message."""

    def __init__(self, ok=True):
        self.ok = ok
        self.calls = []

    async def __call__(self, cdp, text, typing_speed_ms=30, report=None):
        self.calls.append({"text": text, "speed": typing_speed_ms,
                           "report": report})
        return self.ok

    @property
    def last(self):
        return self.calls[-1]


class BlockCase(unittest.TestCase):
    def setUp(self):
        self.injector = RecordingInjector()
        patcher = mock.patch.object(tm, "type_message", self.injector)
        patcher.start()
        self.addCleanup(patcher.stop)

    def execute(self, block, user_nick="Ann", engine=None):
        return run(block.execute(user_nick, object(), engine))


class TestPayload(BlockCase):
    """TYPE-01, TYPE-02, TYPE-04 .. TYPE-06, TYPE-11."""

    def test_defaults(self):
        """TYPE-01."""
        block = TypeMessage()
        self.assertEqual(block.message, "")
        self.assertFalse(block.use_composer)
        self.assertEqual(block.typing_speed_ms, 30)
        self.assertEqual(block.pre_delay_ms, 500)

    def test_own_message_reaches_the_injector(self):
        """TYPE-02."""
        block = TypeMessage(message="Hello", pre_delay_ms=0)
        self.assertEqual(self.execute(block), ActionResult.OK)
        self.assertEqual(self.injector.last["text"], "Hello")
        self.assertEqual(self.injector.last["speed"], 30)

    def test_custom_typing_speed_is_forwarded(self):
        block = TypeMessage(message="x", typing_speed_ms=75, pre_delay_ms=0)
        self.execute(block)
        self.assertEqual(self.injector.last["speed"], 75)

    def test_nick_placeholder_uses_the_selected_user(self):
        """TYPE-04."""
        block = TypeMessage(message="Hi {{nick}}!", pre_delay_ms=0)
        self.execute(block, user_nick="Queued",
                     engine=FakeEngine(selected_nick="Ann"))
        self.assertEqual(self.injector.last["text"], "Hi Ann!")

    def test_nick_placeholder_falls_back_to_the_queued_user(self):
        """TYPE-05."""
        block = TypeMessage(message="Hi {{nick}}!", pre_delay_ms=0)
        self.execute(block, user_nick="Queued", engine=FakeEngine())
        self.assertEqual(self.injector.last["text"], "Hi Queued!")

    def test_nick_placeholder_without_an_engine(self):
        block = TypeMessage(message="Hi {{nick}}!", pre_delay_ms=0)
        self.execute(block, user_nick="Ann")
        self.assertEqual(self.injector.last["text"], "Hi Ann!")

    def test_every_occurrence_is_replaced(self):
        """TYPE-06."""
        block = TypeMessage(message="{{nick}}/{{nick}}", pre_delay_ms=0)
        self.execute(block, user_nick="Ann")
        self.assertEqual(self.injector.last["text"], "Ann/Ann")

    def test_report_callable_is_handed_to_the_injector(self):
        """TYPE-11."""
        engine = FakeEngine()
        block = TypeMessage(message="x", pre_delay_ms=0)
        self.execute(block, engine=engine)
        forwarded = self.injector.last["report"]
        self.assertIsNotNone(forwarded)
        self.assertIs(getattr(forwarded, "__self__", None), engine)

    def test_report_is_none_without_an_engine(self):
        block = TypeMessage(message="x", pre_delay_ms=0)
        self.execute(block)
        self.assertIsNone(self.injector.last["report"])


class TestFailure(BlockCase):
    """TYPE-03, TYPE-08, TYPE-09."""

    def test_injector_failure_maps_to_fail(self):
        """TYPE-03."""
        self.injector.ok = False
        block = TypeMessage(message="x", pre_delay_ms=0)
        self.assertEqual(self.execute(block), ActionResult.FAIL)

    def test_empty_composer_fails_without_calling_the_injector(self):
        """TYPE-08: "composer is on but empty - nothing typed"."""
        block = TypeMessage(message="own text", use_composer=True,
                            pre_delay_ms=0)
        engine = FakeEngine(composer_text="")
        self.assertEqual(self.execute(block, engine=engine),
                         ActionResult.FAIL)
        self.assertEqual(self.injector.calls, [])
        self.assertIn("warn", [lvl for lvl, _m in engine.lines])
        self.assertIn("composer is empty", engine.text())

    def test_whitespace_only_composer_is_treated_as_empty(self):
        block = TypeMessage(use_composer=True, pre_delay_ms=0)
        engine = FakeEngine(composer_text="   \n\t ")
        self.assertEqual(self.execute(block, engine=engine),
                         ActionResult.FAIL)
        self.assertEqual(self.injector.calls, [])

    def test_an_engine_without_composer_mirroring_is_treated_as_empty(self):
        """An older engine that has no composer_text attribute at all."""
        class LegacyEngine:
            """Reports, but predates composer mirroring entirely."""

            def __init__(self):
                self.lines = []

            def report(self, message, level="info"):
                self.lines.append((level, message))

        block = TypeMessage(message="own text", use_composer=True,
                            pre_delay_ms=0)
        engine = LegacyEngine()
        self.assertFalse(hasattr(engine, "composer_text"))
        self.assertEqual(self.execute(block, engine=engine),
                         ActionResult.FAIL)
        self.assertEqual(self.injector.calls, [])

    def test_composer_mode_without_an_engine_fails_quietly(self):
        """TYPE-09: no engine at all must not raise."""
        block = TypeMessage(message="own text", use_composer=True,
                            pre_delay_ms=0)
        self.assertEqual(self.execute(block), ActionResult.FAIL)
        self.assertEqual(self.injector.calls, [])


class TestComposerSource(BlockCase):
    """TYPE-07."""

    def test_composer_text_wins_over_the_stored_message(self):
        block = TypeMessage(message="stored", use_composer=True,
                            pre_delay_ms=0)
        engine = FakeEngine(selected_nick="Ann",
                            composer_text="from the composer")
        self.assertEqual(self.execute(block, engine=engine),
                         ActionResult.OK)
        self.assertEqual(self.injector.last["text"], "from the composer")

    def test_composer_text_is_nick_expanded_too(self):
        block = TypeMessage(use_composer=True, pre_delay_ms=0)
        engine = FakeEngine(selected_nick="Ann",
                            composer_text="Hi {{nick}}")
        self.execute(block, engine=engine)
        self.assertEqual(self.injector.last["text"], "Hi Ann")

    def test_composer_off_ignores_the_composer_text(self):
        block = TypeMessage(message="stored", use_composer=False,
                            pre_delay_ms=0)
        engine = FakeEngine(composer_text="ignored")
        self.execute(block, engine=engine)
        self.assertEqual(self.injector.last["text"], "stored")


class TestTimingAndSchema(BlockCase):
    """TYPE-10, TYPE-12."""

    def test_zero_pre_delay_does_not_wait(self):
        """TYPE-10."""
        block = TypeMessage(message="x", pre_delay_ms=0)
        start = time.monotonic()
        self.execute(block)
        self.assertLess(time.monotonic() - start, 0.2)

    def test_pre_delay_is_awaited_before_typing(self):
        block = TypeMessage(message="x", pre_delay_ms=200)
        start = time.monotonic()
        self.execute(block)
        self.assertGreaterEqual(time.monotonic() - start, 0.19)

    def test_schema_exposes_every_setting_and_keeps_pre_delay(self):
        """TYPE-12."""
        schema = TypeMessage().config_schema()
        for key in ("use_composer", "message", "typing_speed_ms",
                    "pre_delay_ms"):
            self.assertIn(key, schema, f"{key} missing from the schema")

    def test_settings_round_trip(self):
        block = TypeMessage(message="m", use_composer=True,
                            typing_speed_ms=11, pre_delay_ms=0)
        data = block.to_dict()
        clone = TypeMessage(**{k: v for k, v in data.items()
                               if k != "block_id"})
        self.assertEqual(clone.to_dict(), data)


if __name__ == "__main__":
    unittest.main(verbosity=2)
