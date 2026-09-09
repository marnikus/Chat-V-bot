"""Tests for the action registry split (actions/base|registry|context).

Run:  python -m pytest tests/test_action_registry.py
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import actions
from actions.base import BaseAction, ActionResult
from actions.registry import ActionRegistry
from actions.context import ActionContext


ALL_SHIPPED_BLOCKS = [
    "ATTACH_IMAGE", "CLICK_BACK", "CLICK_MAIN_TAB", "CLICK_SEND",
    "CLICK_USER", "COLLECT_HISTORY", "CONDITIONAL_SKIP", "CUSTOM_FIND",
    "MARK_MESSAGED", "PAUSE", "REPEAT_LOOP", "SCROLL_PARSE",
    "SEARCH_USERS", "TAKE_PERSON", "TYPE_MESSAGE", "WAIT_PAGE_LOAD",
]


class TestScan(unittest.TestCase):
    def test_importing_actions_registers_every_block(self):
        # actions/__init__.py ran the scan at import time
        registered = ActionRegistry.all_ids()
        for block_id in ALL_SHIPPED_BLOCKS:
            self.assertIn(block_id, registered,
                          f"{block_id} not registered by the package scan")

    def test_no_manual_import_list_needed(self):
        # a new module dropped into actions/ self-registers on scan
        import types
        import importlib
        mod = types.ModuleType("actions._test_block_tmp")
        src = (
            "from actions.base import BaseAction\n"
            "from actions.base import ActionResult\n"
            "class TempProbe(BaseAction):\n"
            "    block_id = 'TEMP_PROBE_TEST'\n"
            "    name = 'Temp Probe'\n"
            "    async def execute(self, user_nick, cdp, engine=None):\n"
            "        return ActionResult.OK\n"
        )
        exec(src, mod.__dict__)
        sys.modules["actions._test_block_tmp"] = mod
        try:
            ActionRegistry.register_class(mod.TempProbe)
            self.assertIs(ActionRegistry.get("TEMP_PROBE_TEST"),
                          mod.TempProbe)
        finally:
            del sys.modules["actions._test_block_tmp"]
            ActionRegistry._classes.pop("TEMP_PROBE_TEST", None)

    def test_in_package_duplicate_id_rejected(self):
        """Two blocks inside actions/ fighting over an id fail loudly."""
        import sys
        import types

        class ShippedOne(BaseAction):
            block_id = "DUP_TEST_ID"
            name = "One"

            async def execute(self, user_nick, cdp, engine=None):
                return ActionResult.OK
        # pretend ShippedOne lives inside the package
        real_module = ShippedOne.__module__
        ShippedOne.__module__ = "actions._fake_one"
        sys.modules["actions._fake_one"] = types.ModuleType(
            "actions._fake_one")
        try:
            with self.assertRaises(ValueError):
                # define inside a fake actions.* module namespace so the
                # registry sees BOTH classes as in-package
                fake_two = types.ModuleType("actions._fake_two")
                exec(
                    "from actions.base import BaseAction\n"
                    "class ShippedTwo(BaseAction):\n"
                    "    block_id = 'DUP_TEST_ID'\n"
                    "    name = 'Two'\n"
                    "    async def execute(self, user_nick, cdp, engine=None):\n"
                    "        return 'ok'\n",
                    fake_two.__dict__)
            self.assertIs(ActionRegistry.get("DUP_TEST_ID"), ShippedOne)
        finally:
            ShippedOne.__module__ = real_module
            del sys.modules["actions._fake_one"]
            ActionRegistry._classes.pop("DUP_TEST_ID", None)

    def test_out_of_package_shadowing_is_allowed_and_warned(self):
        """Test stubs deliberately shadow shipped ids (last wins, loudly)."""
        import logging

        klass = ActionRegistry.get("PAUSE")
        with self.assertLogs("chatbot", level="WARNING"):
            class TestStubOfPause(BaseAction):
                block_id = "PAUSE"
                name = "Stub"

                async def execute(self, user_nick, cdp, engine=None):
                    return ActionResult.OK
        self.assertIsNot(ActionRegistry.get("PAUSE"), klass)
        # restore the real one for the other tests
        ActionRegistry.register_class(klass)

    def test_explicit_decorator_registers(self):
        @ActionRegistry.register("DECORATED_TEST")
        class Decorated(BaseAction):
            name = "Decorated"

            async def execute(self, user_nick, cdp, engine=None):
                return ActionResult.OK

        self.assertIs(ActionRegistry.get("DECORATED_TEST"), Decorated)
        ActionRegistry._classes.pop("DECORATED_TEST", None)

    def test_engine_lookup_unchanged(self):
        # the ActionEngine resolves blocks through the same table
        from actions.base_action import get_action_class
        self.assertIs(get_action_class("PAUSE"), ActionRegistry.get("PAUSE"))


class TestActionContext(unittest.TestCase):
    def test_reports_through_injected_fn(self):
        seen = []
        ctx = ActionContext(report_fn=lambda m, l="info": seen.append((m, l)))
        ctx.report("looking for .send", "debug")
        self.assertEqual(seen, [("looking for .send", "debug")])

    def test_selected_nick_roundtrip(self):
        ctx = ActionContext()
        self.assertEqual(ctx.selected_nick, "")
        ctx.note_selected("Ann")
        self.assertEqual(ctx.selected_nick, "Ann")
        ctx.note_selected("")            # empty never clears a selection
        self.assertEqual(ctx.selected_nick, "Ann")

    def test_stop_checker(self):
        ctx = ActionContext()
        self.assertFalse(ctx.is_stopping())
        ctx._stop_checker = lambda: True
        self.assertTrue(ctx.is_stopping())

    def test_mark_messaged_delegates(self):
        import asyncio

        async def mark(nick):
            return "ok" if nick == "Ann" else "missing"

        ctx = ActionContext(_mark_messaged=mark)
        self.assertEqual(asyncio.run(ctx.mark_person_messaged("Ann")), "ok")
        self.assertEqual(asyncio.run(ctx.mark_person_messaged("Bob")),
                         "missing")
        # no hook installed → the safe default
        self.assertEqual(asyncio.run(ActionContext().
                                     mark_person_messaged("Ann")),
                         "missing")

    def test_queue_order_projection(self):
        class U:
            def __init__(self, nick):
                self.nick = nick
        ctx = ActionContext(_queue_order=lambda users:
                            [u.nick for u in reversed(users)])
        self.assertEqual(ctx.queue_order([U("a"), U("b")]), ["b", "a"])
        # default projection without a hook
        self.assertEqual(ActionContext().queue_order([U("a"), U("b")]),
                         ["a", "b"])


if __name__ == "__main__":
    unittest.main()
