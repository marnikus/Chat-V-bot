"""RULE 16 §5 is a machine-checked format, not a comment you can hand-wave.

`docs/AGENT_RULES_CODE_QUALITY.md` §5 promises an override marker that CI
parses; this repo has no CI, so the format is enforced here instead:

  * every ``# quality-override:`` marker parses (metric=value + a real reason);
  * every marker covers a violation the gate actually measures today — a
    marker that no longer matches is stale and has to go, one that hides a
    worse number is drift and does not count;
  * the open debt (violations with no marker) may only shrink.

Markers belong on `def`/`class` lines, so the frozen stores modules
(``stores/migration.py``, ``stores/jsonio.py``, ``stores/history_models.py``,
pinned byte-for-byte by tests/unit/stores/test_stores_public_api.py) can not
carry one and their violations stay counted as debt here: a freeze is a
decision, not a clean bill of health.
"""

from __future__ import annotations

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools", "metrics"))

import gate_check  # noqa: E402

# The production scope, same list coverage uses (setup.cfg [coverage:run]).
SCOPE = ("main.py", "core", "actions", "backend", "bridge", "services",
         "stores", "app")
# Measured 2026-09-11 with gate_check's frozen counting. Lower it when a
# violation is fixed or accepted with a reason; never raise it.
OPEN_DEBT = 241

needs_tools = pytest.mark.skipif(
    not (gate_check.cc_visit and gate_check.get_cognitive_complexity),
    reason="radon and cognitive-complexity are needed to measure every gate")


def production_files():
    return gate_check.py_paths(list(SCOPE))


def measured_symbols(path, limits=None):
    """[(row, verdict)] for every def/class in a file, at the given gates."""
    rows, src = gate_check.rows_for(path, None, True)
    lines = src.splitlines()
    out = []
    for row in rows:
        cap = limits or (gate_check.CLASS_LIMITS if row["kind"] == "class"
                         else gate_check.LIMITS)
        out.append((row, gate_check.judge(row, lines, cap)))
    return out


def marker_of(row, lines):
    return gate_check.parse_override(
        gate_check.header_comment(lines, row["line"], row["header_end"]))


def owned_tokens(marker):
    """Marker tokens gate_check can measure itself (not coverage/vulture)."""
    mine = set(gate_check.MINE["function"]) | set(gate_check.MINE["class"])
    return sorted(t for t in marker["pairs"] if t in mine)


@needs_tools
def test_production_scope_is_found() -> None:
    """A wrong SCOPE would make every check below pass while measuring 0."""
    files = production_files()
    assert len(files) >= 140, (f"only {len(files)} production files found in "
                               f"{SCOPE} — the scope no longer points at the "
                               f"packages, so every check here is vacuous")


@needs_tools
def test_every_override_marker_parses() -> None:
    bad = []
    for path in production_files():
        rows, src = gate_check.rows_for(path, None, True)
        lines = src.splitlines()
        for row in rows:
            marker = marker_of(row, lines)
            if marker and "error" in marker:
                bad.append(f"{os.path.relpath(path, ROOT)}:{row['line']} "
                           f"{row['name']}: {marker['error']}")
    assert not bad, "markers that §5 would reject:\n" + "\n".join(bad)


@needs_tools
def test_every_override_covers_a_measured_violation() -> None:
    stale = []
    for path in production_files():
        for row, (_open, _accepted, notes, _reason) in measured_symbols(path):
            for note in notes:
                stale.append(f"{os.path.relpath(path, ROOT)}:{row['line']} "
                             f"{row['name']}: {note}")
    assert not stale, ("overrides that do not match a real violation "
                       "(fix the code or delete the marker):\n"
                       + "\n".join(stale))


@needs_tools
def test_open_debt_does_not_grow() -> None:
    unexplained = accepted = 0
    for path in production_files():
        for _row, (open_items, covers, _notes, _reason) in measured_symbols(path):
            unexplained += len(open_items)
            accepted += len(covers)
    assert unexplained <= OPEN_DEBT, (
        f"{unexplained} unaccepted violations, the pin allows {OPEN_DEBT}. "
        f"Fix one, or accept it with a `# quality-override:` marker that names "
        f"a constraint (docs/AGENT_RULES_CODE_QUALITY.md §5); {accepted} are "
        f"already accepted.")


# ── the parser itself: §5's own example, then each way it can be broken ──

DOC_EXAMPLE = ("def wide_legacy_adapter(self, a, b, c, d, e):  # "
               "quality-override: params=5 reason=CDP wire matches Chrome "
               "DevTools payload; do not invent a wrapper type this PR\n"
               "    return a\n")


def one_marker(body):
    return gate_check.parse_override(
        body.split("#", 1)[1].strip()) if "#" in body else None


def test_the_rulebooks_own_example_parses() -> None:
    marker = one_marker(DOC_EXAMPLE.splitlines()[0])
    assert marker == {"pairs": {"params": 5},
                      "reason": "CDP wire matches Chrome DevTools payload; "
                                "do not invent a wrapper type this PR"}


@pytest.mark.parametrize("body", [
    "def f(a, b, c, d, e):  # quality-override: params=5",
    "def f(a, b, c, d, e):  # quality-override: params=5 reason=too short",
    "def f(a, b, c, d, e):  # quality-override: params=5,5 reason=listed twice",
    "def f(a, b, c, d, e):  # quality-override: arguments=5 reason=not a token",
    "def f(a, b, c, d, e):  # quality-override: params=many reason=not a digit",
    "def f(a, b, c, d, e):  # quality-override: reason=metric and value first",
])
def test_a_marker_the_rule_rejects_never_suppresses(body: str) -> None:
    assert "error" in one_marker(body)


def _verdict(tmp_path, source, name, limits=None):
    path = tmp_path / "demo.py"
    path.write_text(source, encoding="utf-8")
    for row, verdict in measured_symbols(str(path), limits):
        if row["name"] == name:
            return verdict
    raise AssertionError(f"{name} was not measured in the demo source")


def test_a_matching_marker_covers_only_what_it_names(tmp_path) -> None:
    src = ("def f(a, b, c, d, e):  # quality-override: params=5 "
           "reason=the wire format names five arguments\n    return a\n")
    open_items, accepted, notes, _reason = _verdict(tmp_path, src, "f")
    assert (accepted, notes) == (["params=5"], [])
    assert open_items == []


def test_a_smaller_number_than_measured_stays_unexplained(tmp_path) -> None:
    src = ("def f(a, b, c, d, e, g):  # quality-override: params=5 "
           "reason=accepted at five, six is a new problem\n    return a\n")
    open_items, accepted, notes, _reason = _verdict(tmp_path, src, "f")
    assert accepted == [] and open_items == [("params", 6, 4)]
    assert notes == ["params: measured 6 > accepted 5"]


def test_a_marker_for_a_gate_that_no_longer_breaks_is_reported(tmp_path) -> None:
    src = ("def f(a, b, c, d, e):  # quality-override: loc=99 "
           "reason=the body shrank since this was written\n    return a\n")
    _open, accepted, notes, _reason = _verdict(tmp_path, src, "f")
    assert accepted == []
    assert notes == ["loc: gate is not broken, override can go"]


def test_class_loc_is_named_class_loc_not_loc(tmp_path) -> None:
    src = ("class Big:  # quality-override: class-loc=3 "
           "reason=one attribute per line, the reader wants them together\n"
           "    a = 1\n    b = 2\n")
    _open, accepted, notes, _r = _verdict(tmp_path, src, "Big", {"loc": 1})
    assert (accepted, notes) == (["class-loc=3"], [])


def test_another_stages_metric_is_left_alone(tmp_path) -> None:
    src = ("def f(a, b, c, d, e):  # quality-override: coverage=40 "
           "reason=a real browser is needed to cover this path properly\n"
           "    return a\n")
    _open, accepted, notes, _reason = _verdict(tmp_path, src, "f")
    assert (accepted, notes) == ([], [])          # params stays open, not here
    assert gate_check.MINE["function"].get("coverage") is None
