"""ReactionLabels — three labels available, exactly ONE active, user wins.

Driven against the REAL `LabelStore` (config mode), not a mock, so the
"one active label" invariant is proved against the store that actually
persists it (RULE 8).

Pinned here:
  * applying a reaction removes the other two in ONE write;
  * a manual click after an AI application overwrites it — the latest
    decision is the final one;
  * analysing writes nothing: only `apply_reaction` does;
  * non-reaction labels a person carries are never disturbed.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from backend.config_manager import ConfigManager            # noqa: E402
from services.bot_chat import BotChatService                 # noqa: E402
from services.bot_reactions import REACTIONS, ReactionLabels, parse  # noqa: E402
from stores.label_store import LabelStore                    # noqa: E402


def store():
    cfg = ConfigManager(os.path.join(tempfile.mkdtemp(), "config.json"))
    return LabelStore(cfg)


class TestParse(unittest.TestCase):
    def test_the_documented_answer_shape(self):
        got = parse("positive - she answered warmly")
        self.assertEqual(got["reaction"], "positive")
        self.assertEqual(got["reason"], "she answered warmly")

    def test_a_chatty_answer_still_classifies(self):
        self.assertEqual(parse("I would say this is negative.")["reaction"],
                         "negative")

    def test_the_first_reaction_word_wins(self):
        self.assertEqual(
            parse("negative, definitely not positive")["reaction"], "negative")

    def test_an_answer_naming_nothing_is_uncertain(self):
        self.assertEqual(parse("hmm, hard to say")["reaction"], "uncertain")
        self.assertEqual(parse("")["reaction"], "uncertain")


class TestReactionLabels(unittest.TestCase):
    def setUp(self):
        self.store = store()
        self.labels = ReactionLabels(self.store)

    def test_no_label_exists_until_one_is_applied(self):
        self.assertEqual(self.labels.reaction_ids(), {})
        self.assertEqual(self.labels.active("Anna"), "")

    def test_applying_creates_the_definition_and_activates_it(self):
        self.assertTrue(self.labels.apply("Anna", "positive"))
        self.assertEqual(self.labels.active("Anna"), "positive")
        self.assertEqual(len(self.store.ids_for("Anna")), 1)

    def test_only_one_reaction_can_be_active(self):
        self.labels.apply("Anna", "positive")
        self.labels.apply("Anna", "negative")
        self.assertEqual(self.labels.active("Anna"), "negative")
        self.assertEqual(len(self.store.ids_for("Anna")), 1)

    def test_the_latest_manual_decision_wins_over_the_ai_one(self):
        self.labels.apply("Anna", "uncertain")        # AI-confirmed
        self.labels.apply("Anna", "positive")         # user clicked a pill
        self.assertEqual(self.labels.state_of("Anna")["active"], "positive")

    def test_re_applying_the_same_reaction_changes_nothing(self):
        self.labels.apply("Anna", "positive")
        self.assertFalse(self.labels.apply("Anna", "positive"))

    def test_an_unknown_reaction_or_empty_nick_is_refused(self):
        self.assertFalse(self.labels.apply("Anna", "furious"))
        self.assertFalse(self.labels.apply("  ", "positive"))
        self.assertEqual(self.store.assignments(), {})

    def test_the_id_set_swaps_one_reaction_for_the_other(self):
        """`_one_reaction` is the whole one-active-label rule: it returns the
        ids to keep, never writes, and can only ever contain one reaction."""
        self.labels.apply("Anna", "positive")
        keep = self.labels._one_reaction("Anna", "negative")
        ids = self.labels.reaction_ids()
        self.assertIn(ids["negative"], keep)
        self.assertNotIn(ids["positive"], keep)
        self.assertEqual(self.labels.active("Anna"), "positive",
                         "computing the set must not write anything")

    def test_other_labels_of_the_person_survive(self):
        other = self.store.create("Rude", "#ff0000")
        self.store.assign("Anna", other["id"])
        self.labels.apply("Anna", "negative")
        self.assertIn(other["id"], self.store.ids_for("Anna"))
        self.assertEqual(self.labels.active("Anna"), "negative")

    def test_clearing_removes_only_the_reaction_label(self):
        other = self.store.create("Rude", "#ff0000")
        self.store.assign("Anna", other["id"])
        self.labels.apply("Anna", "negative")
        self.assertTrue(self.labels.clear("Anna"))
        self.assertEqual(self.store.ids_for("Anna"), [other["id"]])
        self.assertFalse(self.labels.clear("Anna"))

    def test_state_offers_all_three_colour_coded_labels(self):
        state = self.labels.state_of("Anna")
        self.assertEqual([item["id"] for item in state["available"]],
                         list(REACTIONS))
        colours = {item["id"]: item["color"] for item in state["available"]}
        self.assertEqual(colours["positive"], "#00c853")
        self.assertEqual(colours["negative"], "#ff3b30")
        self.assertEqual(colours["uncertain"], "#ffcc00")


class TestServiceApplication(unittest.TestCase):
    def setUp(self):
        self.store = store()
        # The store is INJECTED, exactly as the bridge injects
        # `ctx.label_store()`. It is deliberately not hung off an archive
        # double: HistoryService keeps its label store private, so a double
        # with a public `.labels` would test an interface nobody implements.
        self.svc = BotChatService(archive=None, config=None,
                                  labels=self.store)

    def test_apply_reaction_reports_the_new_state(self):
        result = self.svc.apply_reaction("Anna", "positive")
        self.assertTrue(result.is_ok)
        self.assertEqual(result.value["active"], "positive")
        self.assertTrue(result.value["changed"])

    def test_applying_twice_reports_no_change(self):
        self.svc.apply_reaction("Anna", "positive")
        self.assertFalse(self.svc.apply_reaction("Anna", "positive")
                         .value["changed"])

    def test_without_a_world_nothing_is_written_and_the_error_says_so(self):
        svc = BotChatService(archive=None, config=None, labels=None)
        result = svc.apply_reaction("Anna", "positive")
        self.assertTrue(result.is_err)
        self.assertEqual(result.code, "bot_no_world")
        self.assertEqual(svc.reaction_state("Anna")["available"], [])


class TestRealArchiveInterface(unittest.TestCase):
    """The regression that the doubles hid.

    `BotChatService` used to dig the label store out of `archive.labels`.
    `HistoryService` has no such attribute — it keeps the store private as
    `_labels` — so in the running app the whole labelling half of the window
    returned `bot_no_world` forever, while every test passed because the
    archive DOUBLE had invented the attribute. These tests use the REAL
    class, so the mistake cannot come back.
    """

    def test_the_real_archive_does_not_expose_a_label_store(self):
        from services.history import HistoryDeps, HistoryService
        archive = HistoryService(HistoryDeps())
        self.assertFalse(hasattr(archive, "labels"),
                         "if HistoryService ever grows a public `labels`, "
                         "this test may be deleted — until then, reading one "
                         "off the archive silently yields None")

    def test_a_label_applies_with_the_real_archive_wired_in(self):
        from services.history import HistoryDeps, HistoryService
        svc = BotChatService(archive=HistoryService(HistoryDeps()), config=None,
                             labels=store())
        result = svc.apply_reaction("Anna", "positive")
        self.assertTrue(result.is_ok, getattr(result, "detail", ""))
        self.assertEqual(result.value["active"], "positive")


class TestTheWriteIsOneUndoableEdit(unittest.TestCase):
    """RULE 12: an AI label is ONE entry on the global timeline.

    `ReactionLabels.apply` writing straight to the store would leave the AI
    path outside the undo history, with the Label Manager and the People
    count stale. The service therefore runs the write through the injected
    `edit` transaction — the bridge passes `LabelBridge._labels_edit`.
    """

    def setUp(self):
        self.store = store()
        self.svc = BotChatService(archive=None, config=None,
                                  labels=self.store)
        self.edits = []

    def _record(self, mutate):
        """Stands in for `_labels_edit`: one call per confirmed label."""
        self.edits.append(mutate)
        return mutate(self.store)

    def test_the_label_write_goes_through_the_undo_transaction(self):
        self.svc.edit = self._record
        result = self.svc.apply_reaction("Anna", "positive")
        self.assertTrue(result.value["changed"])
        self.assertEqual(len(self.edits), 1,
                         "exactly one reversible entry per applied label")
        self.assertEqual(self.svc.labels.active("Anna"), "positive")

    def test_a_no_op_still_reports_no_change_through_the_transaction(self):
        self.svc.edit = self._record
        self.svc.apply_reaction("Anna", "positive")
        again = self.svc.apply_reaction("Anna", "positive")
        self.assertFalse(again.value["changed"],
                         "an unchanged label must not push an undo entry")

    def test_without_a_transaction_the_write_still_happens(self):
        """Headless use (no bridge) must not lose the write."""
        self.assertIsNone(self.svc.edit)
        self.assertTrue(self.svc.apply_reaction("Anna", "negative")
                        .value["changed"])
        self.assertEqual(self.svc.labels.active("Anna"), "negative")


if __name__ == "__main__":
    unittest.main()
