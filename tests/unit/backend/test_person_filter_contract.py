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

    def test_a_rejecting_verdict_is_falsy_but_is_still_a_verdict(self):
        """G6 pin on a trap this refactor walked straight into.

        FilterVerdict.__bool__ is `passed`, so a rejection is FALSY. Any
        `first_reject(p) or fallback` style chain therefore discards every
        rejection and passes everyone — a total filter bypass that reads as
        correct. `check` must distinguish "no verdict" (None) from "a verdict
        that says no".
        """
        reject = PersonFilter(female=YES, registered=ANY, guest=ANY,
                              anonymous=ANY).check({"female": False})
        self.assertFalse(bool(reject), "a rejection must stay falsy")
        self.assertIsNotNone(reject)
        self.assertFalse(reject.passed)
        self.assertNotEqual(reject.reason, "matches all criteria",
                            "the rejection reason was overwritten by the "
                            "pass-through fallback")

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

    def test_panel_criteria_actually_reject(self):
        """G5 gap. The suite only ever asserted the PASSING panel path, so
        mutation testing showed 17 survivors in `_panel_reject` — including
        inverting its `is None` guard, which disables panel criteria entirely.
        Every one of those is a filter that silently stops filtering.
        """
        seen = []

        class Rejects:
            def evaluate_user(self, p):
                seen.append(p)
                return False

        anyf = dict(female=ANY, registered=ANY, guest=ANY, anonymous=ANY)
        person = {"nick": "Ann", "female": True}
        verdict = PersonFilter(panel_criteria=Rejects(), **anyf).check(person)

        self.assertFalse(verdict.passed)
        self.assertEqual(verdict.reason, "rejected by Filter panel criteria")
        self.assertEqual(seen, [person],
                         "the panel must be asked about THIS person")

    def test_no_panel_criteria_means_no_panel_verdict(self):
        anyf = dict(female=ANY, registered=ANY, guest=ANY, anonymous=ANY)
        f = PersonFilter(panel_criteria=None, **anyf)
        self.assertIsNone(f._panel_reject({"nick": "Ann"}))
        self.assertTrue(f.check({"nick": "Ann"}))

    def test_a_tristate_rejection_short_circuits_before_the_panel(self):
        """Order matters: the cheap local rules run first, so a person already
        rejected on an attribute never reaches the panel engine."""
        asked = []

        class Spy:
            def evaluate_user(self, p):
                asked.append(p)
                return True

        f = PersonFilter(female=YES, registered=ANY, guest=ANY,
                         anonymous=ANY, panel_criteria=Spy())
        self.assertFalse(f.check({"female": False}).passed)
        self.assertEqual(asked, [], "the panel was consulted needlessly")

    def test_describe_names_the_panel_only_when_one_is_attached(self):
        anyf = dict(female=ANY, registered=ANY, guest=ANY, anonymous=ANY)

        class Ok:
            def evaluate_user(self, p):
                return True

        self.assertIn("Filter panel criteria",
                      PersonFilter(panel_criteria=Ok(), **anyf).describe())
        self.assertNotIn("Filter panel criteria",
                         PersonFilter(**anyf).describe())

    def test_a_panel_makes_the_filter_non_empty(self):
        anyf = dict(female=ANY, registered=ANY, guest=ANY, anonymous=ANY)

        class Ok:
            def evaluate_user(self, p):
                return True

        self.assertTrue(PersonFilter(**anyf).is_empty)
        self.assertFalse(PersonFilter(panel_criteria=Ok(), **anyf).is_empty,
                         "a filter with panel criteria filters something")


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

    def test_a_missing_messaged_key_counts_as_not_messaged(self):
        """G5 gap: the default in `p.get("messaged", False)` was never pinned.
        Flipping it to True reorders the whole queue — people who have never
        been contacted would sink below people who have."""
        order = [p["nick"] for p in sort_people(
            [{"nick": "b", "messaged": True}, {"nick": "a"}])]
        self.assertEqual(order, ["a", "b"])

    def test_a_missing_nick_sorts_first_and_does_not_raise(self):
        order = [p.get("nick", "") for p in sort_people(
            [{"nick": "a"}, {"messaged": False}])]
        self.assertEqual(order, ["", "a"])

    def test_objects_and_dicts_sort_together_by_the_same_key(self):
        """Both shapes reach this function from different callers; a key that
        read only one of them would silently group all of the other first."""
        class P:
            def __init__(self, nick, messaged=False):
                self.nick, self.messaged = nick, messaged

        people = [P("d", True), {"nick": "c", "messaged": True},
                  P("b"), {"nick": "a"}]
        names = [p["nick"] if isinstance(p, dict) else p.nick
                 for p in sort_people(people)]
        self.assertEqual(names, ["a", "b", "c", "d"])

    def test_messaged_beats_alphabetical(self):
        """The two key components are ordered, not independent: a messaged
        'anna' still sorts below an un-messaged 'zoe'."""
        order = [p["nick"] for p in sort_people(
            [{"nick": "anna", "messaged": True},
             {"nick": "zoe", "messaged": False}])]
        self.assertEqual(order, ["zoe", "anna"])

    def test_a_truthy_non_bool_messaged_counts_as_messaged(self):
        order = [p["nick"] for p in sort_people(
            [{"nick": "a", "messaged": 1}, {"nick": "z", "messaged": 0}])]
        self.assertEqual(order, ["z", "a"])

    def test_the_input_list_is_not_mutated(self):
        people = [{"nick": "b"}, {"nick": "a"}]
        sort_people(people)
        self.assertEqual([p["nick"] for p in people], ["b", "a"])

    def test_casefold_handles_cyrillic(self):
        order = [p["nick"] for p in sort_people(
            [{"nick": "Анна"}, {"nick": "борис"}, {"nick": "Артур"}])]
        self.assertEqual(order, ["Анна", "Артур", "борис"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
