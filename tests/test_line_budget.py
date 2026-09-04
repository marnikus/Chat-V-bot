"""Guard: every Python module file stays under the 150-line hard cap."""
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
BUDGET = 150


def test_all_python_files_under_budget():
    offenders = []
    for p in sorted(ROOT.rglob("*.py")):
        if any(part.startswith(".") for part in p.parts):  # .git, .venv*, .idea…
            continue
        n = len(p.read_text(encoding="utf-8").splitlines())
        if n >= BUDGET:
            offenders.append(f"{p.relative_to(ROOT)}: {n} lines")
    assert not offenders, "over budget:\n" + "\n".join(offenders)


def test_no_empty_modules():
    for p in sorted((ROOT / "chatflow").rglob("*.py")):
        content = p.read_text(encoding="utf-8").strip()
        assert content, f"{p} is empty"
