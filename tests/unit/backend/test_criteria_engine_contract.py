"""backend/criteria_engine — operators, compound rules, empty states.

Design refs: docs/archive/2026-09-09-test-suite/BACKEND_TESTS_DESIGN_2026-09-09.md §CE#1–5.

The engine's two "operators" are MUST_HAVE_CLASS / MUST_NOT_HAVE_CLASS
mapped onto user attributes (female/guest/registered/anonymous); the
default profile is "female AND NOT registered". Proven here:

  * compound AND semantics — failing EITHER enabled rule rejects;
  * all rules disabled = match everything (empty = match all);
  * empty input list, wrong-shape JSON and unknown class names never
    raise and never corrupt the loaded rules;
  * save_to_db → load_from_db round-trips the exact state.

Run with:  python3 tests/unit/backend/test_criteria_engine_contract.py
"""

import asyncio
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))))

import aiosqlite  # noqa: E402
from backend.criteria_engine import CriteriaEngine  # noqa: E402


def user(female=False, registered=False, guest=False, anonymous=False):
    return {"nick": "x", "female": female, "registered": registered,
            "guest": guest, "anonymous": anonymous}


class TestCompound(unittest.TestCase):

    def test_default_profile_is_female_and_not_registered(self):
        e = CriteriaEngine()
        self.assertTrue(e.evaluate_user(user(female=True)))
        self.assertFalse(e.evaluate_user(user(female=False)),
                         "male passed a female-only profile")
        self.assertFalse(e.evaluate_user(user(female=True, registered=True)),
                         "registered passed a NOT-registered profile")

    def test_one_failing_enabled_rule_rejects(self):
        e = CriteriaEngine()
        for c in e.criteria:
            c.enabled = c.check_type == "MUST_HAVE_CLASS" \
                and c.class_name == "guest-avatar"
        self.assertTrue(e.evaluate_user(user(guest=True)))
        self.assertFalse(e.evaluate_user(user(guest=False)))

    def test_disabled_rules_never_vote(self):
        e = CriteriaEngine()
        for c in e.criteria:
            c.enabled = False
        self.assertTrue(e.evaluate_user(user()), "all-disabled must match all")
        self.assertTrue(e.evaluate_user(user(female=True, registered=True,
                                             guest=True, anonymous=True)))
        self.assertEqual(len(e.filter_users([user(), user(female=True)])), 2)


class TestEmpty(unittest.TestCase):

    def test_empty_user_list_gives_empty_result(self):
        self.assertEqual(CriteriaEngine().filter_users([]), [])

    def test_all_disabled_matches_everything(self):
        e = CriteriaEngine()
        for c in e.criteria:
            c.enabled = False
        users = [user(), user(female=True), user(registered=True)]
        self.assertEqual(len(e.filter_users(users)), 3)


class TestJsonShapes(unittest.TestCase):

    def test_wrong_shapes_never_raise_and_keep_the_rules(self):
        e = CriteriaEngine()
        before = e.to_json()
        for garbage in ("null", '"x"', "5", "{not json",
                        '[{"label":1}]',                # missing keys
                        '[{"nope": 1}]'):
            e.load_json(garbage)                        # must not raise
        e.load_json(None)
        e.load_json(b"bytes")
        self.assertEqual(e.to_json(), before,
                         "a failed load must keep the previous rules")

    def test_an_empty_ruleset_is_legal_and_matches_everything(self):
        """Decided contract: "[]" is a legal all-deleted profile (the UI
        can delete rules), so it empties the engine rather than being
        refused — and an empty engine matches every user."""
        e = CriteriaEngine()
        e.load_json("[]")
        self.assertEqual(e.criteria, [])
        self.assertTrue(e.evaluate_user(user(registered=True)))

    def test_valid_load_replaces_everything(self):
        e = CriteriaEngine()
        e.load_json('[{"label": "Guests only", "enabled": true,'
                    ' "selector": ".a", "class_name": "guest-avatar",'
                    ' "check_type": "MUST_HAVE_CLASS"}]')
        self.assertEqual(len(e.criteria), 1)
        self.assertTrue(e.evaluate_user(user(guest=True)))
        self.assertFalse(e.evaluate_user(user(female=True)))

    def test_unknown_class_name_never_matches(self):
        e = CriteriaEngine()
        e.load_json('[{"label": "VIP", "enabled": true, "selector": ".x",'
                    ' "class_name": "vip-aura",'
                    ' "check_type": "MUST_HAVE_CLASS"}]')
        self.assertFalse(e.evaluate_user(user(female=True, guest=True)),
                         "an unknown class must not silently match")
        e.load_json('[{"label": "No ghosts", "enabled": true,'
                    ' "selector": ".x", "class_name": "vip-aura",'
                    ' "check_type": "MUST_NOT_HAVE_CLASS"}]')
        self.assertTrue(e.evaluate_user(user(female=True, guest=True)))


class TestDbRoundTrip(unittest.TestCase):

    def test_save_then_load_restores_the_exact_state(self):
        async def scenario():
            path = os.path.join(tempfile.mkdtemp(), "w.db")
            db = await aiosqlite.connect(path)
            try:
                writer = CriteriaEngine()
                writer.criteria[0].enabled = False
                await writer.save_to_db(db, "profile1")

                reader = CriteriaEngine()
                self.assertTrue(await reader.load_from_db(db, "profile1"))
                self.assertEqual(reader.to_json(), writer.to_json())

                stranger = CriteriaEngine()
                self.assertFalse(await stranger.load_from_db(db, "ghost"),
                                 "a missing profile must report False")
                self.assertEqual(len(stranger.criteria), 4,
                                 "a failed load must keep the defaults")
            finally:
                await db.close()
        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main(verbosity=2)
