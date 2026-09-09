"""`actions.search_users` — the block's own contract (P1).

SPEC-FIRST (docs/ACTIONS_TEST_DESIGN_2026-09-09.md §6).

`tests/test_search_users.py` covers the *injector* chain (focus proof, value
read-back, input-vs-textarea setter). What was untested is the block: the
text it hands over, the placeholder its own config panel advertises, and how
it maps the injector's answer onto ActionResult.

Run with:  python3 tests/test_search_users_contract.py
"""

import asyncio
import os
import sys
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import actions.search_users as su  # noqa: E402
from actions.base_action import ActionResult  # noqa: E402
from actions.search_users import SearchUsers  # noqa: E402


def run(coro):
    return asyncio.run(coro)


class FakeEngine:
    def __init__(self, selected_nick=""):
        self.selected_nick = selected_nick
        self.lines = []

    def report(self, message, level="info"):
        self.lines.append((level, message))


class RecordingSearch:
    def __init__(self, ok=True):
        self.ok = ok
        self.calls = []

    async def __call__(self, cdp, text, report=None):
        self.calls.append({"text": text, "report": report})
        return self.ok

    @property
    def last(self):
        return self.calls[-1]


class BlockCase(unittest.TestCase):
    def setUp(self):
        self.search = RecordingSearch()
        patcher = mock.patch.object(su, "type_search", self.search)
        patcher.start()
        self.addCleanup(patcher.stop)

    def execute(self, block, user_nick="Ann", engine=None):
        return run(block.execute(user_nick, object(), engine))


class TestDelegation(BlockCase):
    """SU-01, SU-02, SU-04, SU-06."""

    def test_text_reaches_the_search_box_unchanged(self):
        """SU-01."""
        block = SearchUsers(text="Ксюша", pre_delay_ms=0)
        self.assertEqual(self.execute(block), ActionResult.OK)
        self.assertEqual(self.search.last["text"], "Ксюша")

    def test_a_failed_search_is_a_failed_block(self):
        """SU-02."""
        self.search.ok = False
        block = SearchUsers(text="x", pre_delay_ms=0)
        self.assertEqual(self.execute(block), ActionResult.FAIL)

    def test_the_report_callback_is_forwarded(self):
        """SU-04."""
        engine = FakeEngine()
        block = SearchUsers(text="x", pre_delay_ms=0)
        self.execute(block, engine=engine)
        forwarded = self.search.last["report"]
        self.assertIs(getattr(forwarded, "__self__", None), engine)

    def test_report_is_none_without_an_engine(self):
        block = SearchUsers(text="x", pre_delay_ms=0)
        self.execute(block)
        self.assertIsNone(self.search.last["report"])

    def test_empty_text_is_still_delegated(self):
        """SU-06: the injector owns the empty-text warning, not the block."""
        block = SearchUsers(text="", pre_delay_ms=0)
        self.execute(block)
        self.assertEqual(len(self.search.calls), 1)
        self.assertEqual(self.search.last["text"], "")

    def test_zero_pre_delay_does_not_wait(self):
        """SU-05."""
        block = SearchUsers(text="x", pre_delay_ms=0)
        start = time.monotonic()
        self.execute(block)
        self.assertLess(time.monotonic() - start, 0.2)

    def test_the_configured_pre_delay_is_awaited(self):
        block = SearchUsers(text="x", pre_delay_ms=180)
        start = time.monotonic()
        self.execute(block)
        self.assertGreaterEqual(time.monotonic() - start, 0.17)


class TestNickPlaceholder(BlockCase):
    """SU-03 — the block's own schema promises "{{nick}} = selected user"."""

    def test_placeholder_resolves_to_the_selected_user(self):
        block = SearchUsers(text="{{nick}}", pre_delay_ms=0)
        self.execute(block, user_nick="Queued",
                     engine=FakeEngine(selected_nick="Ксюша"))
        self.assertEqual(self.search.last["text"], "Ксюша")

    def test_placeholder_falls_back_to_the_queued_user(self):
        block = SearchUsers(text="{{nick}}", pre_delay_ms=0)
        self.execute(block, user_nick="Ксюша", engine=FakeEngine())
        self.assertEqual(self.search.last["text"], "Ксюша")

    def test_placeholder_inside_a_longer_query(self):
        block = SearchUsers(text="поиск {{nick}} !", pre_delay_ms=0)
        self.execute(block, user_nick="Ксюша")
        self.assertEqual(self.search.last["text"], "поиск Ксюша !")

    def test_text_without_a_placeholder_is_untouched(self):
        block = SearchUsers(text="plain", pre_delay_ms=0)
        self.execute(block, user_nick="Ксюша",
                     engine=FakeEngine(selected_nick="Other"))
        self.assertEqual(self.search.last["text"], "plain")

    def test_the_schema_still_advertises_the_placeholder(self):
        """If the support is ever removed, the label has to go with it."""
        label = SearchUsers().config_schema()["text"]["label"]
        self.assertIn("{{nick}}", label)


class TestSettings(unittest.TestCase):
    def test_defaults(self):
        block = SearchUsers()
        self.assertEqual(block.text, "")
        self.assertEqual(block.pre_delay_ms, 500)

    def test_settings_round_trip(self):
        block = SearchUsers(text="abc", pre_delay_ms=0, enabled=False)
        data = block.to_dict()
        clone = SearchUsers(**{k: v for k, v in data.items()
                               if k != "block_id"})
        self.assertEqual(clone.to_dict(), data)


if __name__ == "__main__":
    unittest.main(verbosity=2)
