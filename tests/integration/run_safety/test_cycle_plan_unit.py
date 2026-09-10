"""AREA C2 — pure cycle-plan decision table (no Qt/DB/CDP).

Red on baseline (module missing); green after services/run/cycle_plan.py.
"""

from __future__ import annotations

import sys
import unittest


def _load_cycle_plan():
    try:
        import services.run.cycle_plan as cp  # type: ignore

        return cp
    except ImportError as exc:
        return exc


class CyclePlanImportCase(unittest.TestCase):
    def test_module_exists_and_is_private(self):
        mod = _load_cycle_plan()
        self.assertFalse(
            isinstance(mod, ImportError), f"cycle_plan missing (red): {mod}"
        )
        # No Qt/DB/CDP imports.
        src = open(mod.__file__, encoding="utf-8").read()
        for banned in ("PySide6", "aiosqlite", "CDPClient", "QObject"):
            self.assertNotIn(banned, src)
        self.assertTrue(hasattr(mod, "StackFacts"))
        self.assertTrue(hasattr(mod, "inspect_stack"))
        self.assertTrue(hasattr(mod, "choose_cycle_mode"))


class FakeBlock:
    def __init__(self, block_id, enabled=True, **attrs):
        self.block_id = block_id
        self.enabled = enabled
        for k, v in attrs.items():
            setattr(self, k, v)


class InspectStackCase(unittest.TestCase):
    def setUp(self):
        mod = _load_cycle_plan()
        if isinstance(mod, ImportError):
            self.skipTest(f"cycle_plan missing (red): {mod}")
        self.cp = mod

    def test_empty_stack(self):
        facts = self.cp.inspect_stack([])
        self.assertTrue(facts.stack_empty)
        self.assertFalse(facts.has_mem_click)
        self.assertFalse(facts.has_take)
        self.assertEqual(tuple(facts.user_scoped_ids), ())

    def test_single_scan_rules(self):
        blocks = [
            FakeBlock("SCROLL_PARSE", True),
            FakeBlock("CLICK_USER", True, use_person_from_memory=True),
            FakeBlock("TAKE_PERSON", False),  # disabled → ignored
            FakeBlock("CONDITIONAL_SKIP", True),
            FakeBlock("TYPE_MESSAGE", True),
            FakeBlock("CUSTOM_FIND", False),
        ]
        facts = self.cp.inspect_stack(blocks)
        self.assertFalse(facts.stack_empty)
        self.assertTrue(facts.has_mem_click)
        self.assertFalse(facts.has_take)
        self.assertTrue(facts.has_conditional_skip)
        self.assertIn("SCROLL_PARSE", facts.user_scoped_ids)
        self.assertIn("CLICK_USER", facts.user_scoped_ids)
        self.assertIn("TYPE_MESSAGE", facts.user_scoped_ids)

    def test_disabled_mem_click_does_not_trigger(self):
        facts = self.cp.inspect_stack(
            [FakeBlock("CLICK_USER", False, use_person_from_memory=True)]
        )
        self.assertFalse(facts.has_mem_click)

    def test_mem_click_requires_flag(self):
        facts = self.cp.inspect_stack(
            [FakeBlock("CLICK_USER", True, use_person_from_memory=False)]
        )
        self.assertFalse(facts.has_mem_click)

    def test_scroll_block_identity(self):
        scroll = FakeBlock("SCROLL_PARSE", True)
        facts = self.cp.inspect_stack([scroll])
        self.assertIs(facts.scroll_block, scroll)

    def test_all_disabled(self):
        facts = self.cp.inspect_stack([FakeBlock("CUSTOM_FIND", False)])
        self.assertTrue(facts.all_disabled)
        facts2 = self.cp.inspect_stack([FakeBlock("CUSTOM_FIND", True)])
        self.assertFalse(facts2.all_disabled)


class ChooseModeCase(unittest.TestCase):
    def setUp(self):
        mod = _load_cycle_plan()
        if isinstance(mod, ImportError):
            self.skipTest(f"cycle_plan missing (red): {mod}")
        self.cp = mod

    def _facts(self, **kw):
        defaults = dict(
            scroll_block=None,
            has_mem_click=False,
            has_take=False,
            has_conditional_skip=False,
            user_scoped_ids=(),
            stack_empty=False,
            all_disabled=False,
        )
        defaults.update(kw)
        return self.cp.StackFacts(**defaults)

    def test_stopped_first(self):
        d = self.cp.choose_cycle_mode(
            self._facts(has_mem_click=True),
            has_queue=True,
            take_matched=True,
            stopped=True,
        )
        self.assertEqual(d.mode, "stopped")

    def test_mem_click_precedence(self):
        d = self.cp.choose_cycle_mode(
            self._facts(has_mem_click=True),
            has_queue=True,
            take_matched=False,
            stopped=False,
        )
        self.assertEqual(d.mode, "single_target")

    def test_take_miss_without_user_blocks_is_empty(self):
        d = self.cp.choose_cycle_mode(
            self._facts(has_take=True, user_scoped_ids=()),
            has_queue=False,
            take_matched=False,
            stopped=False,
        )
        self.assertEqual(d.mode, "empty")
        self.assertEqual(d.reason, "no_take_match")

    def test_queue_wins_even_with_empty_stack(self):
        # Characterized quirk: queue-nonempty is checked before empty-stack.
        d = self.cp.choose_cycle_mode(
            self._facts(stack_empty=True),
            has_queue=True,
            take_matched=False,
            stopped=False,
        )
        self.assertEqual(d.mode, "queued")

    def test_empty_stack(self):
        d = self.cp.choose_cycle_mode(
            self._facts(stack_empty=True),
            has_queue=False,
            take_matched=False,
            stopped=False,
        )
        self.assertEqual(d.mode, "empty_stack")

    def test_user_blocks_empty_queue_is_empty(self):
        d = self.cp.choose_cycle_mode(
            self._facts(user_scoped_ids=("CLICK_USER",)),
            has_queue=False,
            take_matched=False,
            stopped=False,
        )
        self.assertEqual(d.mode, "empty")

    def test_independent_only_is_standalone(self):
        d = self.cp.choose_cycle_mode(
            self._facts(user_scoped_ids=()),
            has_queue=False,
            take_matched=False,
            stopped=False,
        )
        self.assertEqual(d.mode, "standalone")


if __name__ == "__main__":
    unittest.main(verbosity=2)
