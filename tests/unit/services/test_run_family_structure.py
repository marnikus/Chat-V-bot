"""Round H step H-C1 exit gates — the run-ladder split must not rot.

Design ref: docs/archive/2026-09-14-round-h/AREA_C_SERVICES_STORES_DESIGN_2026-09-14.md §3 (H-C1)

`services/run/progress.py` was 314 lines with MI 31.0 and a 227-LOC /
22-method `RunQueueMixin`; `RunCoordinator` was 17 methods. H-C1 split both
by *phase*, the vocabulary the ladder already uses:

    queue_select.LabelGateMixin     label filter (fail-open)
    queue_select.QueueOrderMixin    queue order + the pause gate
    queue_select.TakePhaseMixin     the Pick Person phase
    single_target.SingleTargetMixin the one-saved-nick cycle
    cycle_body.CycleBodyMixin       one cycle: prepare the queue, work it

Four things are load-bearing, so each gets a gate rather than a comment:

  * a method lost in the move is an AttributeError on a path only some runs
    take (the Order (#) column, a single-target cycle, Pick Person) — the
    suite would not necessarily notice, so the full old method list is
    asserted to resolve on `RunCoordinator` by name and owner;
  * `services.run.progress.UserRecord` is a runtime pin
    (tests/integration/services/test_run_engine_p0_pins.py P0-2) and the
    binding moved to `requests.py`, so the identity is asserted here too;
  * the stop announcement was five copies of the same two lines; it is now
    `_announce_stopped` on `RunLifecycleMixin` and nothing else may re-emit
    it, or the §16.4 duplicate comes back;
  * a part that imports `coordinator` would make the import order
    load-bearing again, so the leaves are checked.

Run with:  python3 tests/unit/services/test_run_family_structure.py
"""

from __future__ import annotations

import ast
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)

PACKAGE = os.path.join(ROOT, "services", "run")

#: The 22 methods `RunQueueMixin` had before H-C1, and where each must live
#: now. The key is the method name; the value is the module that owns it.
QUEUE_HALVES = {
    "label_allows": "queue_select",
    "filter_by_labels": "queue_select",
    "_label_reason_for": "queue_select",
    "_announce_label_skips": "queue_select",
    "_enabled_block": "queue_select",
    "_unmessaged": "queue_select",
    "_order_by_recency": "queue_select",
    "queue_order": "queue_select",
    "_repeat_cycles": "queue_select",
    "_respect_order_wanted": "queue_select",
    "_rank_queue": "queue_select",
    "_order_queue_by_column": "queue_select",
    "_wait_if_paused": "queue_select",
    "_run_take_phase": "queue_select",
    "_take_one_block": "queue_select",
    "_announce_single_target": "single_target",
    "_work_single_target": "single_target",
    "_account_single_target": "single_target",
    "_run_single_target_cycle": "single_target",
    "_single_target_guard": "single_target",
    "_stopped_single_target": "single_target",
    # the step-outcome report split out of `RunExecutionMixin` (class-LOC cap)
    "_handle_step_result": "step_report",
    "_step_failed": "step_report",
    "_call_action_hook": "step_report",
}

#: The eight cycle phases that moved out of `RunCoordinator`.
CYCLE_PHASES = (
    "_prepare_cycle_queue", "_try_prepare_cycle_queue", "_prepare_user_queue",
    "_announce_empty_mode", "_execute_one_queued_user", "_finalize_user_status",
    "_run_user_queue", "_execute_cycle",
)

STOP_LINE = "Stack stopped by user"


def _classes(path):
    """{class name: {method name: defining line}} for one module file."""
    with open(path, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    out = {}
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        out[node.name] = {
            b.name: b.lineno for b in node.body
            if isinstance(b, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
    return out


def _module_classes(stem):
    return _classes(os.path.join(PACKAGE, stem + ".py"))


class TestEveryMovedMethodStillResolves(unittest.TestCase):
    """The split moved 30 methods between modules; none may be lost."""

    def setUp(self):
        from services.run import RunCoordinator
        self.engine = RunCoordinator

    def test_queue_half_methods_resolve_on_the_coordinator(self):
        for name in QUEUE_HALVES:
            self.assertTrue(hasattr(self.engine, name),
                            f"{name} was lost in the H-C1 split")

    def test_queue_half_methods_live_in_the_module_that_owns_them(self):
        for name, stem in QUEUE_HALVES.items():
            owners = [cls for cls, methods in _module_classes(stem).items()
                      if name in methods]
            self.assertEqual(len(owners), 1,
                             f"{name} must be defined exactly once in "
                             f"{stem}.py, found {owners}")

    def test_cycle_phases_left_the_coordinator(self):
        own = _module_classes("coordinator")["RunCoordinator"]
        for name in CYCLE_PHASES:
            self.assertNotIn(name, own,
                             f"{name} belongs to CycleBodyMixin, not the "
                             f"coordinator")
            self.assertTrue(hasattr(self.engine, name),
                            f"{name} is not reachable on RunCoordinator")

    def test_stop_announcement_is_defined_once(self):
        """Five copies of the same two lines became one named helper."""
        found = []
        for stem in sorted(os.listdir(PACKAGE)):
            if not stem.endswith(".py"):
                continue
            for cls, methods in _module_classes(stem[:-3]).items():
                if "_announce_stopped" in methods:
                    found.append(f"{stem}::{cls}")
        self.assertEqual(found, ["run_lifecycle.py::RunLifecycleMixin"], found)

    def test_no_module_re_emits_the_stop_line(self):
        """Callers use the helper; only it may hold the literal."""
        holders = []
        for stem in sorted(os.listdir(PACKAGE)):
            if not stem.endswith(".py"):
                continue
            with open(os.path.join(PACKAGE, stem), encoding="utf-8") as fh:
                if STOP_LINE in fh.read():
                    holders.append(stem)
        self.assertEqual(holders, ["run_lifecycle.py"], holders)


class TestTheRunPackageShape(unittest.TestCase):
    """H-C1's targets: no class over 15 methods, no file over 300 lines."""

    def test_no_class_over_the_rule16_caps(self):
        offenders = []
        for stem in sorted(os.listdir(PACKAGE)):
            if not stem.endswith(".py"):
                continue
            path = os.path.join(PACKAGE, stem)
            with open(path, encoding="utf-8") as fh:
                tree = ast.parse(fh.read())
            for node in tree.body:
                if not isinstance(node, ast.ClassDef):
                    continue
                methods = sum(1 for b in ast.walk(node)
                              if isinstance(b, (ast.FunctionDef,
                                                ast.AsyncFunctionDef)))
                loc = node.end_lineno - node.lineno + 1
                if methods > 15 or loc > 150:
                    offenders.append(f"{stem}::{node.name} "
                                     f"({loc} LOC / {methods} methods)")
        self.assertEqual(offenders, [], offenders)

    def test_no_file_over_300_lines(self):
        over = []
        for stem in sorted(os.listdir(PACKAGE)):
            if not stem.endswith(".py"):
                continue
            with open(os.path.join(PACKAGE, stem), encoding="utf-8") as fh:
                lines = len(fh.read().splitlines())
            if lines > 300:
                over.append(f"{stem} ({lines})")
        self.assertEqual(over, [], over)

    def test_parts_do_not_import_the_coordinator(self):
        """`__init__.py` is the composition root; nothing else may be."""
        for stem in sorted(os.listdir(PACKAGE)):
            if not stem.endswith(".py") or stem in ("coordinator.py",
                                                    "__init__.py"):
                continue
            with open(os.path.join(PACKAGE, stem), encoding="utf-8") as fh:
                tree = ast.parse(fh.read())
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module:
                    self.assertNotIn("coordinator", node.module,
                                     f"{stem} imports the coordinator")


class TestUserRecordPinSurvivedTheMove(unittest.TestCase):
    def test_progress_still_exposes_the_real_record(self):
        import services.run.progress as progress
        from stores.user_memory import UserRecord
        self.assertIs(progress.UserRecord, UserRecord)

    def test_every_construction_site_uses_the_shared_binding(self):
        from services.run.requests import UserRecord
        from services.run.cycle_body import UserRecord as CycleRecord
        from services.run.single_target import UserRecord as TargetRecord
        self.assertIs(CycleRecord, UserRecord)
        self.assertIs(TargetRecord, UserRecord)


class TestTakeMissPredicate(unittest.TestCase):
    """`_take_miss` is the one genuinely new function in H-C1."""

    @staticmethod
    def _facts(**kw):
        from services.run.cycle_plan import StackFacts
        return StackFacts(**kw)

    def test_take_miss_needs_all_four_conditions(self):
        from services.run.cycle_plan import _take_miss
        facts = self._facts(has_take=True)
        self.assertTrue(_take_miss(facts, has_queue=False, take_matched=False))
        self.assertFalse(_take_miss(facts, has_queue=True, take_matched=False))
        self.assertFalse(_take_miss(facts, has_queue=False, take_matched=True))
        scoped = self._facts(has_take=True, user_scoped_ids=("CLICK_USER",))
        self.assertFalse(_take_miss(scoped, has_queue=False,
                                    take_matched=False))
        self.assertFalse(_take_miss(self._facts(has_take=False),
                                    has_queue=False, take_matched=False))

    def test_choose_cycle_mode_reports_the_take_miss_as_empty(self):
        from services.run.cycle_plan import choose_cycle_mode
        decision = choose_cycle_mode(self._facts(has_take=True),
                                     has_queue=False, take_matched=False)
        self.assertEqual((decision.mode, decision.reason),
                         ("empty", "no_take_match"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
