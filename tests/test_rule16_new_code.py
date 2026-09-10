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
2. **Ratchet** — `HistoryQuery` and `HistoryBridge` were already over the
   class limits before this feature (362 and 490 LOC) and cannot be split here
   (the AREA D API snapshot and the QWebChannel wire contract both pin them).
   So their size is frozen: it may shrink, it may not grow.
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
CANARY = ("backend/history_query.py", "HistoryQuery", "page")


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
        info = gate.classes("backend/history_query.py").get("PersonPageRequest")
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
        key = "backend/history_query.py::PersonPageRequest"
        self.assertIn(key, rows, "class enforcement did not scan the owned file")
        self.assertEqual(rows[key]["violations"], [])

    def test_enforcement_actually_fires_on_real_oversized_classes(self):
        """The strongest check: with the ratchet lifted, the two genuinely
        oversized legacy classes must be reported. Proves the loop is wired to
        real measurement rather than passing because nothing was examined."""
        saved = dict(gate.RATCHET)
        gate.RATCHET.clear()
        try:
            breaches = gate.run()["breaches"]
        finally:
            gate.RATCHET.update(saved)
        self.assertTrue(
            any("HistoryQuery" in b and "loc" in b for b in breaches),
            "with the ratchet lifted, HistoryQuery (340 LOC) must breach the "
            f"{gate.CLASS_LIMITS['loc']} cap; got: {breaches}")
        self.assertTrue(
            any("HistoryBridge" in b for b in breaches),
            f"HistoryBridge must breach too; got: {breaches}")


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

    def test_the_owned_file_group_is_the_pre_existing_import_header(self):
        """Documents why an owned file appears in the baseline at all."""
        self.assertIn(("bridge/db_bridge.py", "bridge/history_bridge.py"),
                      gate.CLONE_BASELINE)

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
