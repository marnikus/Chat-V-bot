"""Real differential smell checks, tool failures and coverage provenance."""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from tools.metrics import changed_code_gate
from tools.metrics.changed_code import inspections, snapshots, symbols, testing


def pair(before, after):
    return snapshots.Pair("base", "WORKTREE", before, after)


def test_real_unused_import_is_detected_outside_old_feature_scope():
    result = inspections.unused(pair({}, {"core/fresh.py": "import os\n\ndef value():\n    return 1\n"}))
    assert any("core/fresh.py" in item and ("W0611" in item or "vulture" in item) for item in result)


def test_existing_unused_import_is_not_new_when_line_numbers_move():
    source = "import os\n\ndef value():\n    return 1\n"
    assert inspections.unused(pair({"core/x.py": source}, {"core/x.py": "\n" + source})) == []
    # Scope changes are not line drift: an unrelated new function cannot spend
    # a removed function's smell budget in the same file.
    old = "def old(arg):\n    return 1\n"
    new = "def new(arg):\n    return 1\n"
    assert inspections.unused(pair({"core/x.py": old}, {"core/x.py": new}))
    imports = "def new():\n    import os\n    return 1\n"
    assert inspections.unused(pair({"core/x.py": source}, {"core/x.py": imports}))


def test_removed_findings_are_allowed():
    assert inspections.unused(pair({"core/x.py": "import os\n"}, {"core/x.py": ""})) == []


@pytest.mark.parametrize("result", [
    SimpleNamespace(returncode=32, stdout="", stderr="tool broke"),
    SimpleNamespace(returncode=0, stdout="not json", stderr=""),
    SimpleNamespace(returncode=0, stdout='{"wrong": "shape"}', stderr=""),
])
def test_broken_pylint_is_an_error_not_a_clean_run(tmp_path, result):
    with patch.object(inspections.subprocess, "run", return_value=result):
        with pytest.raises(ValueError, match="Pylint"):
            inspections.pylint_findings(tmp_path, {"core/x.py": "pass\n"})


def test_missing_tool_becomes_nonzero_machine_readable_error(capsys):
    with patch.object(changed_code_gate, "evaluate", side_effect=ImportError("no radon")):
        assert changed_code_gate.main(["--json"]) == 2
    result = json.loads(capsys.readouterr().out)
    assert "no radon" in result["errors"][0]
    assert result["not_checked"]


def test_missing_smell_tool_is_not_a_skip_even_on_empty_diff():
    with patch.object(inspections.importlib, "import_module", side_effect=ImportError("no vulture")):
        with pytest.raises(ImportError):
            inspections.unused(pair({}, {}))


def block(prefix):
    return "\n".join(f"{prefix}{i} = {i}" for i in range(6)) + "\n"


def test_new_clone_in_existing_file_pair_is_detected():
    before = {"core/a.py": block("old"), "core/b.py": block("old")}
    after = {path: source + block("new") for path, source in before.items()}
    breaches = inspections.clones(pair(before, after))
    assert any("0 -> 2" in b and "core/a.py" in b and "core/b.py" in b for b in breaches)
    assert inspections.clones(pair(before, before)) == []


def test_extra_occurrence_of_an_existing_clone_is_detected():
    before = {"core/a.py": block("old"), "core/b.py": block("old")}
    after = {**before, "core/c.py": block("old")}
    assert any("2 -> 3" in b for b in inspections.clones(pair(before, after)))
    assert inspections.clones(pair(before, {"core/a.py": before["core/a.py"]})) == []


def report(hits, covered=2, branches=2):
    return {"meta": {"branch_coverage": True}, "totals": {"covered_lines": covered, "num_statements": 2,
                        "covered_branches": branches, "num_branches": 2},
            "files": {"core/x.py": {"executed_lines": hits}}}


BASELINE = {"line": {"covered": 2, "total": 2}, "branch": {"covered": 2, "total": 2}}


def test_line_and_branch_regressions_are_checked_separately():
    errors, _ = testing.coverage_breaches(report([1, 2], 1, 1), BASELINE, {"core/x.py": ""}, [])
    assert any("line coverage decreased" in e for e in errors)
    assert any("branch coverage decreased" in e for e in errors)


def test_def_line_hit_does_not_count_as_new_function_execution():
    source = "def new():\n    return 1\n"
    function = next(iter(symbols.collect({"core/x.py": source}).values()))
    assert testing.coverage_breaches(report([1]), BASELINE, {"core/x.py": source}, [function])[0]
    assert testing.coverage_breaches(report([1, 2]), BASELINE, {"core/x.py": source}, [function])[0] == []


def test_one_line_function_requires_unambiguous_execution_evidence():
    source = "def new(): return 1\n"
    function = next(iter(symbols.collect({"core/x.py": source}).values()))
    errors, _ = testing.coverage_breaches(report([1]), BASELINE, {"core/x.py": source}, [function])
    assert any("ambiguous" in e for e in errors)


def test_missing_source_in_coverage_is_not_a_pass():
    errors, _ = testing.coverage_breaches(report([1, 2]), BASELINE, {"core/missing.py": "pass"}, [])
    assert any("core/missing.py" in e for e in errors)


def test_coverage_cannot_be_attached_to_index_or_commit():
    for target in ("INDEX", "abc123"):
        with pytest.raises(ValueError, match="working-tree"):
            testing.run_tests(Path.cwd(), snapshots.Pair("base", target, {}, {}), [])


def test_production_changes_during_tests_invalidate_coverage(tmp_path):
    result = SimpleNamespace(returncode=0, stdout="passed", stderr="")
    with patch.object(testing.subprocess, "run", return_value=result), \
            patch.object(testing.snapshots, "worktree", return_value={"main.py": "changed"}):
        with pytest.raises(ValueError, match="changed during tests"):
            testing.run_tests(tmp_path, pair({}, {"main.py": "original"}), [])


def test_failed_suite_is_never_accepted_as_coverage(tmp_path):
    result = SimpleNamespace(returncode=1, stdout="one failed", stderr="")
    with patch.object(testing.subprocess, "run", return_value=result), \
            patch.object(testing.snapshots, "worktree", return_value={}):
        data = testing.run_tests(tmp_path, pair({}, {}), [])
    assert data["breaches"] == ["pytest failed (exit 1)"]
    assert "one failed" in data["summary"]


def test_multiline_signature_inline_body_is_also_ambiguous():
    source = "def new(\n    arg=None\n): return arg\n"
    function = next(iter(symbols.collect({"core/x.py": source}).values()))
    errors, _ = testing.coverage_breaches(report([1, 2, 3]), BASELINE, {"core/x.py": source}, [function])
    assert any("ambiguous" in e for e in errors)


def test_non_utf8_encoding_cookie_survives_materialization(tmp_path):
    source = '# coding: latin-1\nlabel = "café"\n'
    inspections.materialize(tmp_path, {"core/x.py": source})
    assert snapshots.decode("core/x.py", (tmp_path / "core/x.py").read_bytes()) == source


def test_pylint_warning_status_with_no_findings_is_invalid(tmp_path):
    result = SimpleNamespace(returncode=4, stdout="[]", stderr="")
    with patch.object(inspections.subprocess, "run", return_value=result):
        with pytest.raises(ValueError, match="disagrees"):
            inspections.pylint_findings(tmp_path, {"core/x.py": "pass\n"})
