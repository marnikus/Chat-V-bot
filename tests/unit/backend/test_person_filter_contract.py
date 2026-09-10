"""backend/person_filter — tri-state contract (first direct unit tests).

Design refs: docs/archive/2026-09-09-test-suite/BACKEND_TESTS_DESIGN_2026-09-09.md §PF#1–4.

The module docstring defines the tri-state ("any"/"yes"/"no") and the
legacy coercions; the scroll pipeline leans on `check()` verdicts,
`sort_people` ordering and `normalize()` never leaking a garbage rule
into a preset. Missing person keys must behave as "attribute unknown =
False", and an all-`any` filter must accept everything.

Run with:  python3 tests/unit/backend/test_person_filter_contract.py
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))))

from backend.person_filter import (  # noqa: E402
    ANY,
    NO,
    YES,
    PersonFilter,
    normalize,
    sort_people,
)


class TestNormalize(unittest.TestCase):

    def test_every_garbage_value_lands_on_a_valid_tristate(self):
        for value, expected in [
            (YES, YES), (NO, NO), (ANY, ANY),
            ("YES", YES), (" Yes ", YES),
            (True, YES),          # legacy presets stored booleans
            (False, ANY),
            ("true", YES), ("1", YES), ("must", YES), ("require", YES),
            ("false", NO), ("0", NO), ("must_not", NO), ("exclude", NO),
            (None, ANY), ("", ANY), ("banana", ANY), (7, ANY),
        ]:
            self.assertEqual(normalize(value), expected, repr(value))

    def test_default_is_honoured_for_unrecognisable_values(self):
        self.assertEqual(normalize("banana", default=NO), NO)
        self.assertEqual(normalize(None, default=YES), YES)
        # a recognised value ignores the default
        self.assertEqual(normalize("no", default=ANY), NO)


class TestCheck(unittest.TestCase):

    def test_required_rule_rejects_a_missing_key(self):
        f = PersonFilter(female=YES, registered=NO, guest=ANY, anonymous=ANY)
        verdict = f.check({"nick": "Ghost"})          # no 'female' key
        self.assertFalse(verdict)
        self.assertTrue(verdict.reason)

    def test_forbidden_rule_accepts_a_missing_key(self):
        f = PersonFilter(female=ANY, registered=NO, guest=ANY, anonymous=ANY)
        self.assertTrue(f.check({"nick": "Ghost"}) )

    def test_yes_no_and_any_matrix(self):
        f = PersonFilter(female=YES, registered=NO, guest=ANY, anonymous=ANY)
        self.assertTrue(f.check({"female": True, "registered": False}))
        self.assertFalse(f.check({"female": True, "registered": True}))
        self.assertFalse(f.check({"female": False, "registered": False}))

    def test_verdict_reason_is_set_on_every_rejection(self):
        f = PersonFilter(female=YES, registered=NO, guest=ANY, anonymous=ANY)
        why = f.check({"female": False})
        self.assertFalse(why.passed)
        self.assertEqual(why.reason, "not female")
        why = f.check({"female": True, "registered": True})
        self.assertFalse(why.passed)
        self.assertEqual(why.reason, "registered")

    def test_panel_criteria_are_anded_and_fail_open(self):
        class Ok:
            def evaluate_user(self, p):
                return True
        class Broken:
            def evaluate_user(self, p):
                raise RuntimeError("boom")
        base = {"female": True, "registered": False}
        anyf = dict(female=ANY, registered=ANY, guest=ANY, anonymous=ANY)
        f = PersonFilter(panel_criteria=Ok(), **anyf)
        self.assertTrue(f.check(base))
        f = PersonFilter(panel_criteria=Broken(), **anyf)
        self.assertTrue(f.check(base),
                        "a broken criteria engine must not kill the filter")


class TestEmptyFilter(unittest.TestCase):

    def test_all_any_accepts_everyone_and_describes_itself(self):
        f = PersonFilter(female=ANY, registered=ANY, guest=ANY,
                         anonymous=ANY)
        self.assertTrue(f.is_empty)
        self.assertEqual(f.rules(), [])
        self.assertIn("accept all", f.describe())
        self.assertTrue(f.check({}))
        self.assertTrue(f.check({"female": True, "guest": False}))

    def test_rules_and_describe_tell_the_truth(self):
        f = PersonFilter(female=YES, registered=NO, guest=ANY, anonymous=ANY)
        self.assertEqual(f.rules(), ["must be female",
                                     "must NOT be registered"])
        self.assertNotIn("accept all", f.describe())
        self.assertFalse(f.is_empty)


class TestSortPeople(unittest.TestCase):

    def test_unmessaged_first_then_alphabetical(self):
        people = [{"nick": "vera", "messaged": True},
                  {"nick": "Belle", "messaged": False},
                  {"nick": "anna", "messaged": False},
                  {"nick": "Zoe", "messaged": True}]
        order = [p["nick"] for p in sort_people(people)]
        self.assertEqual(order, ["anna", "Belle", "vera", "Zoe"])

    def test_objects_and_missing_keys_are_handled(self):
        class P:
            def __init__(self, nick, messaged=False):
                self.nick, self.messaged = nick, messaged
        order = [p.nick for p in sort_people(
            [P("b", True), P("a")])]
        self.assertEqual(order, ["a", "b"])
        self.assertEqual(sort_people([]), [])
        self.assertEqual([p["nick"] for p in sort_people(
            [{"nick": "solo"}])], ["solo"])

    def test_casefold_handles_cyrillic(self):
        order = [p["nick"] for p in sort_people(
            [{"nick": "Анна"}, {"nick": "борис"}, {"nick": "Артур"}])]
        self.assertEqual(order, ["Анна", "Артур", "борис"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
