"""Behavior tests for the general RULE 16 gate, outside the historical OWNED list."""

import json
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "tools/metrics/changed_code_gate.py"


def git(root, *args):
    result = subprocess.run(["git", "-c", "user.name=Gate Test", "-c",
                             "user.email=gate@example.invalid", *args], cwd=root,
                            capture_output=True, text=True, check=True)
    return result.stdout.strip()


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, "init", "-q")
    (tmp_path / "core").mkdir()
    (tmp_path / "core/sample.py").write_text("def value():\n    return 1\n")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-qm", "baseline")
    return tmp_path


def run_gate(repo, *args):
    result = subprocess.run([sys.executable, str(CLI), "--root", str(repo),
                             "--structure-only", "--json", *args],
                            capture_output=True, text=True)
    return result.returncode, json.loads(result.stdout)


def wide(name="wide"):
    return f"def {name}(a, b, c, d, e):\n    return a\n"


def test_untracked_production_is_checked_but_tests_and_docs_are_not(repo):
    (repo / "core/new.py").write_text(wide())
    (repo / "tests").mkdir()
    (repo / "tests/fixture.py").write_text("broken python !!!")
    code, result = run_gate(repo)
    assert code == 1
    assert any("core/new.py" in b and "params" in b for b in result["breaches"])


def test_staged_bad_code_cannot_be_hidden_by_an_unstaged_fix(repo):
    path = repo / "core/sample.py"
    path.write_text(wide())
    git(repo, "add", ".")
    path.write_text("def value():\n    return 2\n")
    assert run_gate(repo, "--staged")[0] == 1
    assert run_gate(repo)[0] == 0
    assert "wide" in git(repo, "show", ":core/sample.py")  # no index mutation


def test_unstaged_bad_code_does_not_contaminate_valid_staged_snapshot(repo):
    path = repo / "core/sample.py"
    path.write_text("def value():\n    return 2\n")
    git(repo, "add", ".")
    path.write_text(wide())
    assert run_gate(repo, "--staged")[0] == 0
    assert run_gate(repo)[0] == 1


def test_commit_comparison_does_not_read_dirty_working_tree(repo):
    base = git(repo, "rev-parse", "HEAD")
    (repo / "core/sample.py").write_text("def value():\n    return 2\n")
    git(repo, "commit", "-qam", "fitting")
    (repo / "core/sample.py").write_text(wide())
    assert run_gate(repo, "--base", base, "--head", "HEAD")[0] == 0


def test_deletions_are_reported_and_paths_with_spaces_work(repo):
    (repo / "core/sample.py").unlink()
    (repo / "core/new file.py").write_text(wide())
    code, result = run_gate(repo)
    assert code == 1
    assert result["deleted_files"] == ["core/sample.py"]
    assert result["deleted_symbols"] == ["core/sample.py::value"]
    assert any("core/new file.py" in b for b in result["breaches"])


@pytest.mark.parametrize("args", [("--base", "does-not-exist"), ("--head", "bad-revision")])
def test_invalid_revision_fails_closed(repo, args):
    code, result = run_gate(repo, *args)
    assert code == 2 and result["errors"]


def test_unborn_repository_has_explicit_empty_base(tmp_path):
    git(tmp_path, "init", "-q")
    (tmp_path / "main.py").write_text(wide())
    assert run_gate(tmp_path, "--base", "EMPTY")[0] == 1


def test_symlinked_production_is_rejected_without_reading_its_target(repo, tmp_path):
    target = tmp_path / "private.txt"
    target.write_text("not Python")
    (repo / "core/link.py").symlink_to(target)
    code, result = run_gate(repo)
    assert code == 2 and "symlink" in str(result["errors"]).lower()


def test_syntax_errors_are_not_silently_skipped(repo):
    (repo / "core/sample.py").write_text("def nope(:\n")
    code, result = run_gate(repo)
    assert code == 2 and "core/sample.py" in str(result["errors"])


def test_unmerged_index_is_rejected(repo):
    oid = git(repo, "hash-object", "-w", "core/sample.py")
    subprocess.run(["git", "update-index", "--index-info"], cwd=repo, input=(
        "0 0000000000000000000000000000000000000000\tcore/sample.py\n"
        f"100644 {oid} 1\tcore/sample.py\n100644 {oid} 2\tcore/sample.py\n"
        f"100644 {oid} 3\tcore/sample.py\n"), text=True, check=True)
    code, result = run_gate(repo, "--staged")
    assert code == 2 and "conflict" in str(result["errors"])
    assert run_gate(repo)[0] == 2


def test_real_git_rename_inherits_only_the_removed_definition(repo):
    (repo / "core/sample.py").write_text(wide())
    git(repo, "commit", "-qam", "legacy")
    git(repo, "mv", "core/sample.py", "core/renamed.py")
    code, result = run_gate(repo, "--staged")
    assert code == 0
    assert result["rows"][0]["status"] == "moved"


def test_ignored_untracked_files_are_excluded_but_tracked_files_are_not(repo):
    (repo / ".gitignore").write_text("core/sample.py\ncore/ignored.py\n")
    (repo / "core/ignored.py").write_text("not python !!!")
    assert run_gate(repo)[0] == 0
    (repo / "core/sample.py").write_text(wide())
    assert run_gate(repo)[0] == 1


@pytest.mark.parametrize("staged_unused", [False, True])
def test_default_smell_gate_reads_staged_imports_not_worktree(repo, staged_unused):
    path = repo / "core/sample.py"
    clean = "def value():\n    return 2\n"
    dirty = "import os\n" + clean
    path.write_text(dirty if staged_unused else clean)
    git(repo, "add", ".")
    path.write_text(clean if staged_unused else dirty)
    result = subprocess.run([sys.executable, str(CLI), "--root", str(repo), "--staged", "--json"],
                            capture_output=True, text=True)
    assert result.returncode == int(staged_unused), result.stdout


def test_missing_real_site_packages_fails_closed(repo):
    result = subprocess.run([sys.executable, "-S", str(CLI), "--root", str(repo), "--json"],
                            capture_output=True, text=True)
    assert result.returncode == 2
    assert json.loads(result.stdout)["errors"]


def test_ci_resolves_pr_push_and_new_branch_bases_in_real_repository(repo):
    from tools.metrics.changed_code.ci import resolve

    base = git(repo, "rev-parse", "HEAD")
    git(repo, "update-ref", "refs/remotes/origin/main", base)
    (repo / "core/sample.py").write_text("def value():\n    return 2\n")
    git(repo, "commit", "-qam", "target")
    head = git(repo, "rev-parse", "HEAD")
    event = {"HEAD_SHA": head, "GITHUB_EVENT_NAME": "pull_request", "PR_BASE_SHA": base}
    assert resolve(repo, event) == base
    event.update(GITHUB_EVENT_NAME="push", BEFORE_SHA=base)
    assert resolve(repo, event) == base
    event.update(BEFORE_SHA="0" * 40, DEFAULT_BRANCH="main", CURRENT_BRANCH="feature")
    assert resolve(repo, event) == base
    event["CURRENT_BRANCH"] = "main"
    assert resolve(repo, event) == "EMPTY"
    event.update(CURRENT_BRANCH="feature", DEFAULT_BRANCH="absent")
    assert resolve(repo, event) == "EMPTY"
    event.update(BEFORE_SHA="bad-ref")
    with pytest.raises(ValueError):
        resolve(repo, event)
    event.update(HEAD_SHA=base, BEFORE_SHA=base)
    with pytest.raises(ValueError, match="checkout HEAD"):
        resolve(repo, event)


def test_coverage_mode_runs_real_tests_and_exports_fresh_results(repo, monkeypatch):
    from tools.metrics.changed_code import snapshots, testing

    monkeypatch.setenv("PYTEST_ADDOPTS", "-k nonexistent_test_selection")
    (repo / "tests").mkdir()
    test_file = repo / "tests/test_value.py"
    test_file.write_text("from core.sample import value\n\ndef test_value():\n    assert value() == 1\n")
    import os
    original_stat = test_file.stat()
    selected = snapshots.load(repo)
    result = testing.run_tests(repo, selected, [])
    assert result["breaches"] == []
    assert result["ratios"]["line"] == {"covered": 2, "total": 2}
    assert "1 passed" in result["summary"]
    test_file.write_text("from core.sample import value\n\ndef test_value():\n    assert value() == 2\n")
    # Reproduce CPython/pytest timestamp+size cache collisions deterministically.
    os.utime(test_file, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
    assert testing.run_tests(repo, selected, [])["breaches"] == ["pytest failed (exit 1)"]

    # The same guarantee applies to production imports, not just pytest rewrites.
    test_file.write_text("from core.sample import value\n\ndef test_value():\n    assert value() == 1\n")
    os.utime(test_file, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
    production = repo / "core/sample.py"
    production_stat = production.stat()
    production.write_text("def value():\n    return 2\n")
    os.utime(production, ns=(production_stat.st_atime_ns, production_stat.st_mtime_ns))
    assert testing.run_tests(repo, snapshots.load(repo), [])["breaches"] == ["pytest failed (exit 1)"]
