"""{{nick}} in any field → the remembered selected-user nickname.

FEATURE — when a Click User block clicks a person, the engine remembers
that nickname until the next selection happens, and EVERY text field of
every block resolves the {{nick}} marker to it (not just the Type Message
text). Example use: a "close tab" Find & Click whose "Text it must contain"
field holds {{nick}} matches the tab of the person selected earlier in the
loop.

Rules:
  * after a successful Click User click, {{nick}} = that nickname, kept for
    the rest of the run until another Click User selects someone else;
  * before any selection (or in a stack without Click User), {{nick}} =
    the queued user of the current step — the long-standing Type Message
    behaviour, unchanged;
  * a new run press forgets the selection;
  * block settings are only expanded for the duration of the step — the
    stored {{nick}} literal is always restored afterwards.

Run with:  python3 tests/test_nick_placeholder.py
"""

import asyncio
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import actions.click_user as click_user_mod  # noqa: E402
import actions.custom_find as custom_find_mod  # noqa: E402
import actions.type_message as type_message_mod  # noqa: E402
from actions.base_action import BaseAction, ActionResult  # noqa: E402
from actions.click_user import ClickUser  # noqa: E402
from actions.custom_find import CustomFind  # noqa: E402
from actions.type_message import TypeMessage  # noqa: E402
from backend.action_engine import ActionEngine  # noqa: E402
from backend.user_memory import UserMemory, UserRecord  # noqa: E402


def run(coro):
    return asyncio.run(coro)


class FakeEngine:
    """Engine stand-in for direct block tests (note_selected + composer)."""

    def __init__(self, selected_nick="", composer_text=""):
        self.selected_nick = selected_nick
        self.composer_text = composer_text
        self.noted = []

    def note_selected(self, nick):
        if nick:
            self.noted.append(nick)
            self.selected_nick = nick

    def report(self, msg, level="info"):
        pass


class MemHarness:
    def __init__(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.memory = UserMemory(os.path.join(self._tmp.name, "t.db"))

    async def __aenter__(self):
        await self.memory.init()
        return self.memory

    async def __aexit__(self, *exc):
        await self.memory.close()
        self._tmp.cleanup()


def in_tmp_cwd(coro_fn):
    """Run a coroutine with cwd in a throwaway dir (the tracer writes logs/)."""
    cwd = os.getcwd()
    os.chdir(tempfile.mkdtemp())
    try:
        return run(coro_fn())
    finally:
        os.chdir(cwd)


def seed_user(mem, nick, messaged=False):
    return mem.upsert_user(UserRecord(nick=nick, gender="female", guest=True,
                                      messaged=messaged))


class StubClick(BaseAction):
    """CLICK_USER stand-in: OK per user, remembers the selection on the
    engine exactly like the real block (which cannot click in unit tests)."""
    block_id = "CLICK_USER"
    name = "Click User"
    icon = "👤"

    def __init__(self, enabled=True, **kw):
        super().__init__(pre_delay_ms=0)
        self.enabled = bool(enabled)
        self.calls = []

    async def execute(self, user_nick, cdp, engine=None):
        self.calls.append(user_nick)
        if engine is not None:
            note = getattr(engine, "note_selected", None)
            if note is not None:
                note(user_nick)
        return ActionResult.OK


class Consumer(BaseAction):
    """Records what its {{nick}}-bearing match_text looked like when it ran."""
    block_id = "CONSUMER"
    name = "Consumer"
    icon = "🧪"

    def __init__(self, match_text="", **kw):
        super().__init__(pre_delay_ms=0)
        self.match_text = match_text
        self.seen = []

    async def execute(self, user_nick, cdp, engine=None):
        self.seen.append((user_nick, self.match_text))
        return ActionResult.OK


class Boom(BaseAction):
    """Raises mid-run so the {{nick}} restore path is exercised."""
    block_id = "BOOM"
    name = "Boom"
    icon = "💥"

    def __init__(self, label="x {{nick}} y", **kw):
        super().__init__(pre_delay_ms=0)
        self.label = label

    async def execute(self, user_nick, cdp, engine=None):
        raise RuntimeError("boom")


class FakeInjector:
    """Stands in for backend.message_injector.type_message."""

    def __init__(self):
        self.typed = None

    async def __call__(self, cdp, text, typing_speed_ms=30, report=None):
        self.typed = text
        return True


# ── the Click User block remembers the selection ─────────────────
class TestClickUserNotesSelection(unittest.TestCase):
    def test_ok_click_remembers_the_nick(self):
        async def go():
            engine = FakeEngine()
            blk = ClickUser(verify_new_tab=False, pre_delay_ms=0)
            with mock.patch.object(click_user_mod, "find_and_click_exact",
                                   new=mock.AsyncMock(return_value=ActionResult.OK)):
                result = await blk.execute("Anna", None, engine)
            self.assertEqual(result, ActionResult.OK)
            self.assertEqual(engine.noted, ["Anna"])
            self.assertEqual(engine.selected_nick, "Anna")
        run(go())

    def test_failed_click_does_not_remember(self):
        async def go():
            engine = FakeEngine()
            blk = ClickUser(verify_new_tab=False, pre_delay_ms=0)
            with mock.patch.object(click_user_mod, "find_and_click_exact",
                                   new=mock.AsyncMock(return_value=ActionResult.FAIL)):
                result = await blk.execute("Anna", None, engine)
            self.assertEqual(result, ActionResult.FAIL)
            self.assertEqual(engine.noted, [])
        run(go())

    def test_no_engine_is_fine(self):
        async def go():
            blk = ClickUser(verify_new_tab=False, pre_delay_ms=0)
            with mock.patch.object(click_user_mod, "find_and_click_exact",
                                   new=mock.AsyncMock(return_value=ActionResult.OK)):
                result = await blk.execute("Anna", None, None)
            self.assertEqual(result, ActionResult.OK)
        run(go())


# ── engine expands {{nick}} on every block, per step ─────────────
class TestEngineNickExpansion(unittest.TestCase):
    async def _engine(self, mem, *blocks):
        eng = ActionEngine(cdp=None, memory=mem, criteria=None)
        eng._stack = list(blocks)
        await eng.execute(None)
        return eng

    def test_fields_see_the_selected_user_of_this_step(self):
        async def go():
            async with MemHarness() as mem:
                await seed_user(mem, "Anna")
                await seed_user(mem, "Bella")
                click = StubClick()
                consumer = Consumer(match_text="close tab {{nick}}")
                eng = await self._engine(mem, click, consumer)
                return eng, click, consumer

        eng, click, consumer = in_tmp_cwd(go)
        self.assertEqual(click.calls, ["Anna", "Bella"])
        self.assertEqual(consumer.seen, [("Anna", "close tab Anna"),
                                         ("Bella", "close tab Bella")])
        self.assertEqual(eng.selected_nick, "Bella")
        # The block setting itself was restored — never mutated permanently.
        self.assertEqual(consumer.match_text, "close tab {{nick}}")

    def test_remembered_until_the_next_selection(self):
        """A block BEFORE this step's Click User still sees the previous
        selection — the memory persists until a new click happens."""
        async def go():
            async with MemHarness() as mem:
                await seed_user(mem, "Anna")
                await seed_user(mem, "Bella")
                consumer = Consumer(match_text="tab {{nick}}")
                click = StubClick()
                eng = await self._engine(mem, consumer, click)
                return eng, consumer

        eng, consumer = in_tmp_cwd(go)
        # Anna's iteration: no selection yet → her own nick. Bella's
        # iteration: Click User for Bella runs AFTER the consumer → Anna
        # is still the remembered selection.
        self.assertEqual(consumer.seen, [("Anna", "tab Anna"),
                                         ("Bella", "tab Anna")])
        self.assertEqual(eng.selected_nick, "Bella")

    def test_no_click_user_falls_back_to_the_step_user(self):
        async def go():
            async with MemHarness() as mem:
                await seed_user(mem, "Anna")
                await seed_user(mem, "Bella")
                consumer = Consumer(match_text="greet {{nick}}")
                eng = await self._engine(mem, consumer)
                return eng, consumer

        eng, consumer = in_tmp_cwd(go)
        self.assertEqual(consumer.seen, [("Anna", "greet Anna"),
                                         ("Bella", "greet Bella")])
        self.assertEqual(eng.selected_nick, "")

    def test_new_run_forgets_the_selection(self):
        async def go():
            async with MemHarness() as mem:
                await seed_user(mem, "Anna")
                eng = ActionEngine(cdp=None, memory=mem, criteria=None)
                eng._stack = [StubClick()]
                await eng.execute(None)
                self.assertEqual(eng.selected_nick, "Anna")
                # Second press: everyone is messaged → empty run, but the
                # remembered nick must NOT survive from the previous run.
                await eng.execute(None)
                return eng.selected_nick

        selected = in_tmp_cwd(go)
        self.assertEqual(selected, "")

    def test_settings_restored_even_when_a_block_raises(self):
        async def go():
            async with MemHarness() as mem:
                await seed_user(mem, "Anna")
                boom = Boom(label="boom {{nick}} now")
                consumer = Consumer(match_text="after {{nick}}")
                eng = ActionEngine(cdp=None, memory=mem, criteria=None)
                eng._stack = [boom, consumer]
                await eng.execute(None)      # must not raise
                return boom, consumer

        boom, consumer = in_tmp_cwd(go)
        self.assertEqual(boom.label, "boom {{nick}} now")
        self.assertEqual(consumer.match_text, "after {{nick}}")


# ── the real Find & Click block uses the resolved text ───────────
class TestRealCustomFindWiring(unittest.TestCase):
    def test_match_text_reaches_find_with_the_selected_nick(self):
        async def go():
            captured = {}

            async def fake_find(cdp, **kw):
                captured.update(kw)
                return ActionResult.OK

            async with MemHarness() as mem:
                await seed_user(mem, "Anna")
                click = StubClick()
                finder = CustomFind(
                    selector="div[role='tab'].tab-item",
                    label_selector="p.chat-title",
                    match_text="{{nick}}",
                    pre_delay_ms=0)
                eng = ActionEngine(cdp=None, memory=mem, criteria=None)
                eng._stack = [click, finder]
                with mock.patch.object(custom_find_mod, "find_and_click",
                                       new=fake_find):
                    await eng.execute(None)
                return finder, captured

        finder, captured = in_tmp_cwd(go)
        self.assertEqual(captured.get("match_text"), "Anna")
        self.assertEqual(finder.match_text, "{{nick}}",
                         "the stored setting must stay a literal marker")


# ── Type Message keeps working, now selection-aware ──────────────
class TestTypeMessageNick(unittest.TestCase):
    async def _typed(self, message, user_nick, engine, use_composer=False):
        blk = TypeMessage(message=message, use_composer=use_composer,
                          pre_delay_ms=0)
        fake = FakeInjector()
        patcher = mock.patch.object(type_message_mod, "type_message", fake)
        with patcher:
            await blk.execute(user_nick, None, engine)
        return fake.typed

    def test_block_text_uses_the_selected_nick(self):
        async def go():
            engine = FakeEngine(selected_nick="Anna")
            typed = await self._typed("Hello {{nick}}!", "Bob", engine)
            return typed

        self.assertEqual(in_tmp_cwd(go), "Hello Anna!")

    def test_no_selection_keeps_the_step_user(self):
        async def go():
            typed = await self._typed("Hello {{nick}}!", "Bob",
                                      FakeEngine())
            return typed

        self.assertEqual(in_tmp_cwd(go), "Hello Bob!")

    def test_no_engine_keeps_the_step_user(self):
        async def go():
            typed = await self._typed("Hello {{nick}}!", "Bob", None)
            return typed

        self.assertEqual(in_tmp_cwd(go), "Hello Bob!")

    def test_composer_text_uses_the_selected_nick(self):
        async def go():
            engine = FakeEngine(selected_nick="Anna",
                                composer_text="Hi {{nick}}, from composer")
            typed = await self._typed("ignored", "Bob", engine,
                                      use_composer=True)
            return typed

        self.assertEqual(in_tmp_cwd(go), "Hi Anna, from composer")


if __name__ == "__main__":
    unittest.main(verbosity=2)
