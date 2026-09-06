"""Search Users — verified typing into the users-list Поиск search box.

FEATURE —
  * the search input (`.search-field input[matinput]`) can receive text via
    the same verified chain as the private-message textarea;
  * the block VERIFIES the field was really clicked / the cursor is inside
    (document.activeElement === field, with a real-click fallback) and that
    the text actually landed (value read-back), naming each stage;
  * typing into an <input> uses the HTMLInputElement value setter (the old
    code would call the textarea setter on inputs);
  * Type Message (textarea) behaviour stays byte-identical.

Run with:  python3 tests/test_search_users.py
"""

import asyncio
import inspect
import json
import os
import re
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import actions.search_users  # noqa: E402,F401  (registers SEARCH_USERS)
import backend.message_injector as injector  # noqa: E402
from actions.base_action import ActionResult  # noqa: E402
from actions.search_users import SearchUsers  # noqa: E402
from actions.take_person import TakePerson  # noqa: E402
from backend.action_engine import ActionEngine  # noqa: E402
from backend.user_memory import UserMemory, UserRecord  # noqa: E402


def run(coro):
    return asyncio.run(coro)


def in_tmp_cwd(coro_fn):
    """Run a coroutine with cwd in a throwaway dir (the tracer writes logs/)."""
    cwd = os.getcwd()
    os.chdir(tempfile.mkdtemp())
    try:
        return run(coro_fn())
    finally:
        os.chdir(cwd)


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


def rec(nick, messaged=False):
    return UserRecord(nick=nick, gender="female", guest=True,
                      messaged=messaged)


async def seed(mem, *people):
    for u in people:
        await mem.upsert_user(u)
        if u.messaged:
            await mem.mark_messaged(u.nick)


class RecordingEngine:
    def __init__(self):
        self.messages = []

    def report(self, msg, level="info"):
        self.messages.append((msg, level))


_EMBEDDED_TEXT = re.compile(
    r'(?:setter\.call\(ta,\s*|ta\.value\s*=\s*|writeText\()("(?:[^"\\]|\\.)*")')


class SearchCDP:
    """Scriptable CDP stand-in simulating the real search input page state.

    Behaves like a browser page:
      * focused — whether document.activeElement is the search input;
      * value   — what the input currently contains (the read-back);
      * accept_writes — whether the page accepts programmatic writes
        (setter / paste / insertText); when False nothing ever lands and
        every strategy must fail its verification;
      * click_focuses — whether a real click puts the cursor in the field.
    """

    def __init__(self, value="", focused=False, click_focuses=True,
                 accept_writes=True):
        self.value = value
        self.focused = focused
        self.click_focuses = click_focuses
        self.accept_writes = accept_writes
        self.evals = []
        self.clicked_at = []
        self.key_events = []
        self.writes = []  # every text that landed in the field

    async def evaluate(self, expression):
        self.evals.append(expression)
        if "document.activeElement" in expression:
            # focus-state probe -> JSON
            return json.dumps({"found": True, "focused": self.focused,
                               "visible": True})
        if "querySelectorAll(" in expression:
            # element probe (build_probe) -> JSON
            return json.dumps({"found": True, "visible": True,
                               "disabled": False, "clickable": True,
                               "total": 1, "clicked": False,
                               "error": None, "rows": []})
        if "dispatchEvent(new Event('input'" in expression:
            # strategy 1 — native prototype setter: the page accepts it
            # when accept_writes and the field holds the text afterwards
            self.focused = True
            if self.accept_writes:
                m = _EMBEDDED_TEXT.search(expression)
                if m:
                    try:
                        self.value = json.loads(m.group(1))
                        self.writes.append(self.value)
                    except Exception:
                        pass
            return "ok"
        if "navigator.clipboard.writeText" in expression:
            # clipboard write succeeds, but the paste only lands when the
            # page accepts writes (handled in send())
            return "ok"
        if "setSelectionRange" in expression:
            # select-all helper focused the field
            self.focused = True
            return True
        if "('value' in el" in expression:
            # read-back probe -> plain value
            return self.value
        raise AssertionError(f"unhandled evaluate: {expression[:90]}")

    async def send(self, method, params=None):
        if method == "Input.dispatchKeyEvent":
            self.key_events.append(params or {})
            if (params or {}).get("key") == "v" and self.accept_writes:
                self.value = "ctrl-v-pasted"
        if method == "Input.insertText" and self.accept_writes:
            self.value = (params or {}).get("text", "")
        return {}

    async def get_element_rect(self, selector):
        return {"x": 10, "y": 10, "width": 100, "height": 24}

    async def click_at(self, x, y):
        self.clicked_at.append((x, y))
        if self.click_focuses:
            self.focused = True


# ── injector: type_search (the verified chain) ───────────────────
class TestTypeSearch(unittest.TestCase):
    def test_types_into_the_search_input_and_verifies(self):
        async def go():
            cdp = SearchCDP()
            logs = []
            ok = await injector.type_search(
                cdp, "Lena", report=lambda m, lvl="info": logs.append(m))
            return ok, logs
        ok, logs = run(go())
        self.assertTrue(ok, "text must land in the search box")
        joined = " ".join(logs)
        self.assertIn("search", joined.lower())
        self.assertTrue(any("focused" in m.lower() or "cursor" in m.lower()
                            for m in logs),
                        "the log must confirm the cursor is in the field")

    def test_setter_prototype_is_picked_by_element_tag(self):
        """The value setter must come from the element's OWN prototype.

        The old code fell back to the HTMLInputElement setter only when the
        textarea setter was missing (it never is), so every <input> write
        used the textarea setter. The JS must decide by tagName first.
        """
        src = inspect.getsource(injector._try_set_value)
        self.assertIn("isTextarea", src,
                      "the setter choice must depend on the element tag")
        self.assertIn("HTMLInputElement.prototype", src,
                      "<input> needs the input setter")
        self.assertNotIn("ta.tagName !== 'TEXTAREA'", src,
                         "textarea-only fallback logic is gone")

    def test_focus_failure_triggers_a_real_click_then_types(self):
        async def go():
            cdp = SearchCDP(focused=False)
            # activeElement check reports unfocused until a click happens
            await injector.type_search(cdp, "Bella")
            return cdp.clicked_at, cdp.evals
        clicked, evals = run(go())
        self.assertTrue(clicked, "a real click must be issued when the "
                                 "field is not focused")
        self.assertTrue(any("activeElement" in e for e in evals),
                        "focus must be verified after the click")

    def test_unfocusable_field_fails_with_stage_name(self):
        async def go():
            cdp = SearchCDP(focused=False, click_focuses=False)
            logs = []
            ok = await injector.type_search(
                cdp, "X", report=lambda m, lvl="info": logs.append(m))
            return ok, " ".join(logs)
        ok, joined = run(go())
        self.assertFalse(ok)
        self.assertIn("focus", joined, "failure must name the focus stage")

    def test_unmatched_text_never_returns_ok(self):
        async def go():
            # page that never accepts a write: value stays "different" no
            # matter which strategy runs
            cdp = SearchCDP(value="different", accept_writes=False)
            ok = await injector.type_search(cdp, "Lena")
            return ok
        # none of the strategies may claim success when the value does not
        # match after every fallback
        self.assertFalse(run(go()))

    def test_missing_field_fails(self):
        async def go():
            class NoField:
                async def evaluate(self, expression):
                    if "probe" in expression.lower():
                        return json.dumps({"found": False, "total": 0})
                    raise AssertionError(expression[:60])
            logs = []
            ok = await injector.type_search(
                NoField(), "X", report=lambda m, lvl="info": logs.append(m))
            return ok, " ".join(logs)
        ok, joined = run(go())
        self.assertFalse(ok)
        self.assertIn("search", joined.lower())

    def test_search_selectors_are_structural(self):
        self.assertEqual(injector.SEARCH_SELECTOR, ".search-field input[matinput]")
        self.assertNotIn("mat-input-", injector.SEARCH_SELECTOR)
        self.assertNotIn("placeholder", injector.SEARCH_SELECTOR)


# ── the Search Users block ───────────────────────────────────────
class TestSearchUsersBlock(unittest.TestCase):
    def test_block_ok_when_text_lands(self):
        async def go():
            blk = SearchUsers(text="Lena", pre_delay_ms=0)
            cdp = SearchCDP()
            eng = RecordingEngine()
            result = await blk.execute("—", cdp, eng)
            return result, eng.messages
        result, messages = run(go())
        self.assertEqual(result, ActionResult.OK)
        self.assertTrue(messages, "the block must report through engine")

    def test_block_fails_when_text_does_not_land(self):
        async def go():
            blk = SearchUsers(text="Ghost", pre_delay_ms=0)
            # page keeps its old content: no strategy may claim success
            cdp = SearchCDP(value="other", accept_writes=False)
            result = await blk.execute("—", cdp, RecordingEngine())
            return result
        self.assertEqual(run(go()), ActionResult.FAIL)

    def test_default_text_empty(self):
        self.assertEqual(SearchUsers().text, "")

    def test_settings_round_trip(self):
        d = SearchUsers(text="Lena").to_dict()
        again = SearchUsers(**{k: v for k, v in d.items()
                               if k != "block_id"})
        self.assertEqual(again.text, "Lena")

    def test_schema_exposes_text(self):
        schema = SearchUsers().config_schema()
        self.assertIn("text", schema)


# ── engine integration ───────────────────────────────────────────
class TestEngineSearchUsers(unittest.TestCase):
    def test_search_users_stack_runs_standalone_and_types(self):
        async def go():
            async with MemHarness() as mem:
                cdp = SearchCDP()
                logs, details = [], []
                eng = ActionEngine(cdp=cdp, memory=mem, criteria=None)
                eng.log_msg.connect(lambda m: logs.append(m))
                eng.debug_msg.connect(lambda m, lvl: details.append(m))
                eng.load_stack([{"block_id": "SEARCH_USERS", "text": "Lena",
                                 "enabled": True}])
                await eng.execute(None)
                return cdp.value, cdp.writes, eng.is_running, logs, details
        value, writes, running, logs, details = in_tmp_cwd(go)
        self.assertEqual(value, "Lena", "the text must land in the search box")
        self.assertEqual(len(writes), 1,
                         "no users anywhere → standalone run types once")
        self.assertFalse(running)
        self.assertTrue(any("Search" in m for m in logs + details),
                        "the run log must mention the search action")

    def test_nick_from_pick_person_is_typed_into_search(self):
        async def go():
            async with MemHarness() as mem:
                await seed(mem, rec("Anna"), rec("Bella"))
                # Order (#) is derived from first_seen: Anna = #1
                # Order (#) is newest-first by first_seen: Anna = #1
                await mem._db.execute(
                    "UPDATE users SET first_seen=? WHERE nick=?",
                    ("2026-09-02T10:00:00", "Anna"))
                await mem._db.execute(
                    "UPDATE users SET first_seen=? WHERE nick=?",
                    ("2026-09-01T10:00:00", "Bella"))
                await mem._db.commit()
                cdp = SearchCDP()
                eng = ActionEngine(cdp=cdp, memory=mem, criteria=None)
                eng.load_stack([
                    {"block_id": "TAKE_PERSON", "pick_mode": "order_first"},
                    {"block_id": "SEARCH_USERS", "text": "find {{nick}}"}])
                await eng.execute(None)
                return cdp.writes
        writes = in_tmp_cwd(go)
        self.assertEqual(writes, ["find Anna", "find Anna"],
                         "Pick Person remembered Anna; {{nick}} expanded in "
                         "every typed search text")


if __name__ == "__main__":
    unittest.main(verbosity=2)
