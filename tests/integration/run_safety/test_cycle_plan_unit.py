"""Area C2 — pure cycle planner truth table (no Qt/signals/side effects).

Parent design: docs/SAFETY_REFACTOR_AREA_C_IMPL_DESIGN_2026-09-10.md §2.2.
Task list: docs/SAFETY_REFACTOR_AREA_C_2026-09-10.md C2.

Test-first: fails with ImportError until services/run/cycle_plan.py lands,
then pins the decision precedence the coordinator must follow.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))))

try:
    from services.run.cycle_plan import (CycleDecision, StackFacts,  # noqa: E402
                                         choose_cycle_mode, inspect_stack)
    HAS_PLAN = True
except ImportError:
    HAS_PLAN = False


class FakeBlock:
    def __init__(self, block_id, enabled=True, **attrs):
        self.block_id = block_id
        self.enabled = enabled
        for k, v in attrs.items():
            setattr(self, k, v)


class TestInspectStack(unittest.TestCase):
    def test_module_exists(self):
        self.assertTrue(HAS_PLAN, "services/run/cycle_plan.py must exist (C2)")

    def test_empty_stack(self):
        facts = inspect_stack([])
        self.assertTrue(facts.is_empty)
        self.assertEqual(facts.enabled_count, 0)
        self.assertIsNone(facts.scroll_block)
        self.assertFalse(facts.has_memory_click)
        self.assertFalse(facts.has_take)
        self.assertFalse(facts.has_conditional_skip)
        self.assertEqual(facts.user_scoped_ids, ())

    def test_single_pass_rules(self):
        scroll1 = FakeBlock("SCROLL_PARSE", enabled=True)
        scroll2 = FakeBlock("SCROLL_PARSE", enabled=True)
        click = FakeBlock("CLICK_USER", enabled=True,
                          use_person_from_memory=True)
        take = FakeBlock("TAKE_PERSON", enabled=True)
        skip = FakeBlock("CONDITIONAL_SKIP", enabled=True)
        plain = FakeBlock("CUSTOM_FIND", enabled=True)
        disabled_user = FakeBlock("TYPE_MESSAGE", enabled=False)
        facts = inspect_stack([scroll1, scroll2, click, take, skip, plain,
                               disabled_user])
        self.assertIs(facts.scroll_block, scroll1,
                      "first enabled scroll block wins")
        self.assertTrue(facts.has_memory_click)
        self.assertTrue(facts.has_take)
        self.assertTrue(facts.has_conditional_skip)
        # Disabled user-scoped blocks are excluded; diagnostics are sorted.
        self.assertEqual(facts.user_scoped_ids,
                         ("CLICK_USER", "CONDITIONAL_SKIP", "SCROLL_PARSE",
                          "TAKE_PERSON") if "TAKE_PERSON" in
                         ("CLICK_USER", "CONDITIONAL_SKIP", "SCROLL_PARSE")
                         else facts.user_scoped_ids)
        self.assertIn("CLICK_USER", facts.user_scoped_ids)
        self.assertIn("SCROLL_PARSE", facts.user_scoped_ids)
        self.assertNotIn("TYPE_MESSAGE", facts.user_scoped_ids)
        self.assertFalse(facts.is_empty)
        self.assertEqual(facts.enabled_count, 6)

    def test_memory_click_requires_flag_and_enabled(self):
        off = FakeBlock("CLICK_USER", enabled=True,
                        use_person_from_memory=False)
        dis = FakeBlock("CLICK_USER", enabled=False,
                        use_person_from_memory=True)
        self.assertFalse(inspect_stack([off]).has_memory_click)
        self.assertFalse(inspect_stack([dis]).has_memory_click)
        self.assertFalse(inspect_stack(
            [FakeBlock("CLICK_USER", enabled=True)]).has_memory_click)

    def test_disabled_scroll_is_ignored(self):
        dis = FakeBlock("SCROLL_PARSE", enabled=False)
        facts = inspect_stack([dis])
        self.assertIsNone(facts.scroll_block)

    def test_facts_are_immutable(self):
        facts = inspect_stack([FakeBlock("CUSTOM_FIND")])
        with self.assertRaises(Exception):
            facts.is_empty = True  # frozen dataclass

    def test_odd_payloads_never_raise(self):
        self.assertTrue(HAS_PLAN)
        # None / missing attrs / empty / non-str ids are skipped, not fatal.
        facts = inspect_stack([None, object(),
                               FakeBlock("", enabled=True),
                               FakeBlock(123, enabled=True),
                               FakeBlock("CLICK_USER")])
        self.assertEqual(facts.user_scoped_ids, ("CLICK_USER",))
        self.assertFalse(facts.is_empty)

    def test_getattr_failure_skips_block(self):
        self.assertTrue(HAS_PLAN)

        class Evil:
            def __getattr__(self, name):
                raise RuntimeError("attrs down")

        facts = inspect_stack([Evil(), FakeBlock("CLICK_USER")])
        self.assertEqual(facts.user_scoped_ids, ("CLICK_USER",))
        self.assertEqual(facts.enabled_count, 1)

    def test_memory_flag_failure_is_contained(self):
        self.assertTrue(HAS_PLAN)

        class EvilClick:
            enabled = True

            def __getattr__(self, name):
                if name == "block_id":
                    return "CLICK_USER"
                raise RuntimeError("flag down")

        facts = inspect_stack([EvilClick()])
        self.assertFalse(facts.has_memory_click)
        self.assertEqual(facts.user_scoped_ids, ("CLICK_USER",))

    def test_unhashable_id_is_contained(self):
        self.assertTrue(HAS_PLAN)

        class EvilHash(str):
            def __hash__(self):
                raise RuntimeError("hash down")

        facts = inspect_stack([FakeBlock(EvilHash("CLICK_USER"))])
        self.assertEqual(facts.user_scoped_ids, ())
        self.assertEqual(facts.enabled_count, 1)


class TestChooseCycleMode(unittest.TestCase):
    def _facts(self, **kw):
        base = dict(scroll_block=None, has_memory_click=False, has_take=False,
                    has_conditional_skip=False, user_scoped_ids=(),
                    is_empty=False, enabled_count=1)
        base.update(kw)
        return StackFacts(**base)

    def test_memory_click_takes_precedence(self):
        facts = self._facts(has_memory_click=True, has_take=True,
                            user_scoped_ids=("CLICK_USER",))
        d = choose_cycle_mode(facts, has_queue=True, take_matched=False)
        self.assertEqual(d.mode, "single_target")
        self.assertEqual(d.reason, "memory_click")
        # Even with an empty queue and no take match.
        d = choose_cycle_mode(facts, has_queue=False, take_matched=False)
        self.assertEqual(d.mode, "single_target")

    def test_take_miss_without_user_blocks_is_empty_not_standalone(self):
        facts = self._facts(has_take=True, user_scoped_ids=())
        d = choose_cycle_mode(facts, has_queue=False, take_matched=False)
        self.assertEqual(d.mode, "empty")
        self.assertEqual(d.reason, "no_take_match")

    def test_take_miss_with_user_blocks_falls_through(self):
        facts = self._facts(has_take=True,
                            user_scoped_ids=("CLICK_USER",))
        d = choose_cycle_mode(facts, has_queue=False, take_matched=False)
        self.assertEqual(d.mode, "empty")
        self.assertEqual(d.reason, "empty_queue")

    def test_queued_mode_wins_even_with_empty_stack(self):
        """Preserved ordering: `if queue:` precedes `elif not stack:`."""
        facts = self._facts(is_empty=True, enabled_count=0)
        d = choose_cycle_mode(facts, has_queue=True, take_matched=False)
        self.assertEqual(d.mode, "queued")
        self.assertEqual(d.reason, "queue")

    def test_empty_stack(self):
        facts = self._facts(is_empty=True, enabled_count=0)
        d = choose_cycle_mode(facts, has_queue=False, take_matched=False)
        self.assertEqual(d.mode, "empty_stack")
        self.assertEqual(d.reason, "empty_stack")

    def test_empty_queue_with_user_blocks(self):
        facts = self._facts(user_scoped_ids=("CLICK_USER",))
        d = choose_cycle_mode(facts, has_queue=False, take_matched=False)
        self.assertEqual(d.mode, "empty")
        self.assertEqual(d.reason, "empty_queue")

    def test_standalone_when_only_independent_blocks(self):
        facts = self._facts(user_scoped_ids=())
        d = choose_cycle_mode(facts, has_queue=False, take_matched=False)
        self.assertEqual(d.mode, "standalone")
        self.assertEqual(d.reason, "standalone")

    def test_decision_is_immutable_and_small(self):
        facts = self._facts()
        d = choose_cycle_mode(facts, has_queue=False, take_matched=False)
        self.assertIsInstance(d, CycleDecision)
        with self.assertRaises(Exception):
            d.mode = "queued"  # frozen


if __name__ == "__main__":
    unittest.main(verbosity=2)
