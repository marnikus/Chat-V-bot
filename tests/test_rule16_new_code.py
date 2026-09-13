"""RULE 16 — size & complexity gate for the sortable-columns feature.

The thresholds are executable, so they cannot rot, and "does the new code
fit?" is answered by the project's own runner rather than by someone
re-reading a document.

The limits, the policy tables and the measurement live in
`tools/metrics/rule16_gate.py` — the same module the pre-commit hook and CI
call. This file deliberately holds *no* copy of them: a second copy of the
thresholds is how a gate starts disagreeing with itself.

Three kinds of check live here:

1. **Hard gate** — every function this feature owns fits all six limits.
2. **Ratchet** — a class that was already over the class limits before this
   feature and cannot be split here has its size frozen: it may shrink, it may
   not grow. `HistoryQuery` (362 LOC) left the ratchet in god-class step 5 and
   `HistoryBridge` (493 LOC) in step 6 — both are small facades over single-
   responsibility mixins now, so the ratchet dict is EMPTY and the
   "enforcement actually fires" proof below is anchored on a real oversized
   class elsewhere in the tree instead.
3. **The gate is not vacuous** — a known over-limit function must actually be
   reported, and every override must be justified and still needed.

Rule: docs/AGENT_RULES_CODE_QUALITY.md
Worked example: docs/RULE16_SIZE_COMPLEXITY_FIT_2026-09-10.md

Run with:  python3 tests/test_rule16_new_code.py
"""

import importlib.util
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _load_gate():
    """`tools/` is not a package, so load the gate module by path."""
    path = os.path.join(ROOT, "tools", "metrics", "rule16_gate.py")
    spec = importlib.util.spec_from_file_location("rule16_gate", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gate = _load_gate()
LIMITS, OWNED, RATCHET, OVERRIDES = (gate.LIMITS, gate.OWNED, gate.RATCHET,
                                     gate.OVERRIDES)

# A real function in this repo that is over the limit (53 LOC at the time of
# writing). Used to prove the measurement detects a breach, so a green gate
# cannot simply be a gate that measures nothing.
# (2026-09-12, god-class step 5: `page` moved from `HistoryQuery` to
# `PagingMixin` when `backend/history_query.py` became a package.)
CANARY = ("backend/history_query/paging.py", "PagingMixin", "page")


class TestTheGateIsNotVacuous(unittest.TestCase):
    """Guards against the failure mode where the gate passes because it found
    nothing to look at."""

    def test_the_canary_is_detected_as_over_limit(self):
        m = gate.measure_function(*CANARY)
        self.assertIsNotNone(m, "the canary function vanished")
        self.assertTrue(gate.violations(m),
                        f"{CANARY[2]} is {m['loc']} LOC and must be reported; "
                        "if it now genuinely fits, pick another canary")
        self.assertGreater(m["loc"], LIMITS["func_loc"])

    def test_the_canary_is_not_in_the_owned_set(self):
        """Otherwise it would have to be overridden, and the check above would
        be testing the override path instead of detection."""
        self.assertNotIn(CANARY, OWNED)

    def test_every_owned_function_exists(self):
        missing = [f"{rel}::{cls or ''}.{fn}"
                   for rel, cls, fn in OWNED
                   if gate.find(rel, cls, fn) is None]
        self.assertEqual(missing, [],
                         "these functions are gone — the gate is pointing at "
                         "nothing: " + ", ".join(missing))


class TestOwnedFunctionsFitEveryLimit(unittest.TestCase):
    """The hard gate: LOC / params / CC / cognitive / nesting."""

    def _over(self, axes):
        out = []
        for rel, cls, fn in OWNED:
            m = gate.measure_function(rel, cls, fn)
            if m is None:
                continue
            bad = [v for v in gate.violations(m) if v.split()[0] in axes]
            if bad and (rel, cls, fn) not in OVERRIDES:
                out.append(f"{rel}::{fn}: " + ", ".join(bad))
        return out

    def test_function_size_and_parameter_limits(self):
        over = self._over({"LOC", "params"})
        self.assertEqual(over, [], "\n".join(over))

    def test_nesting_depth(self):
        over = self._over({"nesting"})
        self.assertEqual(over, [], "\n".join(over))

    def test_cyclomatic_complexity(self):
        if not gate._tool("radon"):
            self.skipTest("radon not installed "
                          "(pip install -r requirements-dev.txt)")
        over = self._over({"CC"})
        self.assertEqual(over, [], "\n".join(over))

    def test_cognitive_complexity(self):
        probe = gate.measure_function(*OWNED[0])
        if probe is None or probe["cognitive"] is None:
            self.skipTest("cognitive_complexity not installed "
                          "(pip install -r requirements-dev.txt)")
        over = self._over({"cognitive"})
        self.assertEqual(over, [], "\n".join(over))

    def test_no_owned_function_is_silently_unmeasured(self):
        """A missing tool must surface as 'not checked', never as a pass."""
        unmeasured = []
        for rel, cls, fn in OWNED:
            m = gate.measure_function(rel, cls, fn)
            if m is not None and m["cc"] is None:
                unmeasured.append(f"{rel}::{fn}")
        if unmeasured:
            self.skipTest("radon not installed — CC unchecked for "
                          + ", ".join(unmeasured))


class TestRequestObjectIsSmall(unittest.TestCase):
    """The new class must itself be inside the class limits."""

    def test_person_page_request_fits(self):
        info = gate.classes("backend/history_query/request.py").get("PersonPageRequest")
        self.assertIsNotNone(info, "PersonPageRequest does not exist")
        self.assertLessEqual(info["loc"], gate.CLASS_LIMITS["loc"],
                             f"PersonPageRequest is {info['loc']} LOC")
        self.assertLessEqual(info["methods"], gate.CLASS_LIMITS["methods"],
                             f"PersonPageRequest has {info['methods']} methods")


class TestClassLimitsAreEnforced(unittest.TestCase):
    """`CLASS_LIMITS` used to be decoration: declared, echoed into the report,
    and never actually checked. These tests pin the enforcement."""

    def test_synthetic_over_cap_class_is_flagged_on_both_axes(self):
        v = gate.class_violations({"loc": 999, "methods": 99})
        self.assertEqual(len(v), 2, v)
        self.assertTrue(any("loc" in x for x in v), v)
        self.assertTrue(any("methods" in x for x in v), v)

    def test_synthetic_fitting_class_is_clean(self):
        self.assertEqual(
            gate.class_violations({"loc": gate.CLASS_LIMITS["loc"],
                                   "methods": gate.CLASS_LIMITS["methods"]}),
            [], "a class exactly at the cap must pass — the limit is 'fail if >'")

    def test_the_owned_request_object_is_reported_and_clean(self):
        rows = {r["target"]: r for r in gate.run()["class_rows"]}
        key = "backend/history_query/request.py::PersonPageRequest"
        self.assertIn(key, rows, "class enforcement did not scan the owned file")
        self.assertEqual(rows[key]["violations"], [])

    #: A real class in the tree that is over BOTH class caps today (225 LOC /
    #: 44 direct methods at the 2026-09-13 measurement): the archive's write
    #: facade. It is not owned by this feature, so the test lends it to the
    #: gate for one run to prove the enforcement loop measures real code.
    OVERSIZED = ("stores/history_repo.py", "HistoryRepo", "ensure_person")

    def test_enforcement_actually_fires_on_real_oversized_classes(self):
        """The strongest check: a genuinely oversized class must be reported.
        Proves the loop is wired to real measurement rather than passing
        because nothing was examined. (God-class steps 5 and 6 split
        `HistoryQuery` and `HistoryBridge` into mixins, so no class in an
        owned file is oversized any more — the proof is anchored on a real
        oversized class elsewhere in the tree instead of going vacuous.)"""
        saved_owned = list(gate.OWNED)
        saved_ratchet = dict(gate.RATCHET)
        gate.OWNED.append(self.OVERSIZED)
        gate.RATCHET.clear()
        try:
            breaches = gate.run()["breaches"]
        finally:
            gate.OWNED[:] = saved_owned
            gate.RATCHET.update(saved_ratchet)
        rel, name, _fn = self.OVERSIZED
        self.assertTrue(
            any(name in b and "loc" in b for b in breaches),
            f"{rel}::{name} is over the {gate.CLASS_LIMITS['loc']}-LOC cap and "
            f"must be reported; got: {breaches}")
        self.assertTrue(
            any(name in b and "methods" in b for b in breaches),
            f"{name} must breach the methods cap too; got: {breaches}")


class TestPreExistingDebtDoesNotGrow(unittest.TestCase):
    def test_class_ratchet(self):
        grew = []
        for (rel, name), cap in RATCHET.items():
            info = gate.classes(rel).get(name)
            self.assertIsNotNone(info, f"{name} disappeared from {rel}")
            for axis in ("loc", "methods"):
                if info[axis] > cap[axis]:
                    grew.append(f"{rel}::{name} {axis} {info[axis]} > "
                                f"frozen {cap[axis]}")
        self.assertEqual(grew, [], "\n".join(grew))

    def test_the_ratchet_still_bites_when_it_has_something_to_hold(self):
        """`RATCHET` is EMPTY since god-class step 6 split `HistoryBridge`
        (step 5 split `HistoryQuery`), so the loop above passes vacuously.
        This pins the mechanism itself: a cap below the real measurement of a
        real class must be reported as growth, on both axes."""
        rel, name = "stores/history_repo.py", "HistoryRepo"
        info = gate.classes(rel).get(name)
        self.assertIsNotNone(info, f"{name} disappeared from {rel}")
        saved = dict(gate.RATCHET)
        gate.RATCHET[(rel, name)] = {"loc": info["loc"] - 1,
                                     "methods": info["methods"] - 1}
        try:
            breaches = gate.run()["breaches"]
        finally:
            gate.RATCHET.clear()
            gate.RATCHET.update(saved)
        for axis in ("loc", "methods"):
            self.assertTrue(
                any(name in b and axis in b and "frozen" in b
                    for b in breaches),
                f"growth of {name}'s {axis} over a frozen cap must be "
                f"reported; got: {breaches}")


class TestOverridesAreHonest(unittest.TestCase):
    """An escape hatch that is not audited becomes a dumping ground.

    Nothing in OWNED needs an override today, so `OVERRIDES` is empty. These
    checks exist for the day someone adds one.
    """

    BOILERPLATE = ("todo", "noqa", "fixme", "later", "tbd", "xxx")

    def test_an_override_must_name_a_gated_function(self):
        stray = [str(k) for k in OVERRIDES if k not in OWNED]
        self.assertEqual(stray, [],
                         "overrides that gate nothing: " + ", ".join(stray))

    def test_an_override_must_carry_a_real_justification(self):
        weak = []
        for key, why in OVERRIDES.items():
            text = str(why).strip().lower()
            if len(text) < 40:
                weak.append(f"{key[2]}: justification is under 40 characters")
            elif any(text.startswith(b) for b in self.BOILERPLATE):
                weak.append(f"{key[2]}: '{why}' is a placeholder, not a reason")
        self.assertEqual(weak, [], "\n".join(weak))

    def test_an_override_that_is_no_longer_needed_must_be_deleted(self):
        stale = [f"{key[0]}::{key[2]} now fits inside every limit"
                 for key in OVERRIDES
                 if not gate.violations(gate.measure_function(*key))]
        self.assertEqual(stale, [], "stale overrides:\n" + "\n".join(stale))

    def test_the_whole_gate_run_is_clean(self):
        """End-to-end through the same entry point the hook and CI use."""
        result = gate.run()
        self.assertEqual(result["breaches"], [], "\n".join(result["breaches"]))


class TestNoNewSmells(unittest.TestCase):
    """Zero new duplication, zero dead code."""

    def test_no_duplication_or_dead_code_in_the_changed_files(self):
        findings, not_checked = gate.smells()
        self.assertEqual(findings, [], "smells in the changed files:\n"
                         + "\n".join(findings))
        if not_checked:
            self.skipTest("not checked, tool missing: " + ", ".join(not_checked)
                          + " — this is NOT a pass")


class TestCloneBaselineIsHonest(unittest.TestCase):
    """The AST duplication scan main's spec §4/§7.1 requires.

    The baseline is frozen pre-existing debt, so the two ways it can rot are:
    an entry that no longer exists (fiction that hides nothing but misleads the
    next reader), and a new group that was never added to it.
    """

    def test_baseline_is_not_empty_and_every_entry_is_sorted(self):
        """`clones()` compares against `tuple(sorted(...))`. An unsorted
        baseline entry could therefore never match, and its group would be
        reported as new forever — a permanently red gate nobody can explain."""
        self.assertTrue(gate.CLONE_BASELINE, "an empty baseline claims the repo "
                        "has no clones at all, which is not true")
        for sig in gate.CLONE_BASELINE:
            self.assertEqual(list(sig), sorted(sig), f"unsorted entry: {sig}")
            self.assertGreaterEqual(len(sig), 2, f"not a cross-file group: {sig}")

    def test_no_owned_file_is_excused_by_the_clone_baseline(self):
        """Documents the day the last owned file LEFT the baseline.

        Until god-class step 6 (2026-09-13) the baseline carried
        ('bridge/db_bridge.py', 'bridge/history_bridge.py') — the standard
        import header both modules had carried since the base commit.
        Splitting `bridge/history_bridge.py` into a package whose leaves
        import only what they use removed that group. Nothing this feature
        owns may be excused by the frozen baseline now: an owned file
        reappearing there is duplication the feature introduced, not
        pre-existing debt.
        """
        owned = {rel for rel, _cls, _fn in gate.OWNED}
        excused = sorted({rel for group in gate.CLONE_BASELINE for rel in group}
                         & owned)
        self.assertEqual(
            excused, [],
            "owned files excused by CLONE_BASELINE — new duplication frozen "
            "instead of fixed: " + ", ".join(excused))

    def test_no_new_clone_groups_and_no_stale_baseline_entries(self):
        result = gate.run(with_clones=True)
        self.assertTrue(result["clones_checked"])
        self.assertEqual(result["new_clones"], [],
                         "new duplication:\n" + "\n".join(result["new_clones"]))
        self.assertEqual(result["clone_stale"], [],
                         "baseline entries that no longer exist — delete them:\n"
                         + "\n".join(result["clone_stale"]))

    def test_a_skipped_scan_is_not_reported_as_a_pass(self):
        """The hook runs without --with-clones. That must stay visibly
        distinguishable from a scan that ran and found nothing."""
        result = gate.run()
        self.assertFalse(result["clones_checked"])
        self.assertEqual(result["new_clones"], [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
