"""Differential smells on the selected snapshots, never on unstaged substitutes."""

from collections import Counter
import importlib
import json
import io
import tokenize
from pathlib import Path
import subprocess
import sys
import tempfile

from tools.metrics import clone_scan
from .symbols import collect


def materialize(root, sources):
    for relative, source in sources.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        encoding, _ = tokenize.detect_encoding(io.BytesIO(source.encode("utf-8")).readline)
        path.write_bytes(source.encode(encoding))


class ScopeResolver:
    """Keep finding identity stable across line drift, not across lexical scopes."""
    def __init__(self, sources):
        self.sources, self.rows = sources, {}

    def at(self, path, line):
        if type(line) is not int or not 1 <= line <= len(self.sources[path].splitlines()):
            raise ValueError(f"{path}: invalid diagnostic line {line!r}")
        if path not in self.rows:
            self.rows[path] = list(collect({path: self.sources[path]}).values())
        candidates = [s for s in self.rows[path] if s.node.lineno <= line <= s.node.end_lineno]
        if not candidates:
            return "<module>"
        return min(candidates, key=lambda s: s.node.end_lineno - s.node.lineno).qualname


def vulture_findings(sources):
    from vulture import Vulture

    scanner = Vulture()
    for path, source in sorted(sources.items()):
        scanner.scan(source, filename=path)
    if scanner.exit_code:
        raise ValueError(f"Vulture failed with exit code {scanner.exit_code}")
    scopes = ScopeResolver(sources)
    return Counter((str(item.filename), "vulture",
                    scopes.at(str(item.filename), item.first_lineno), item.message)
                   for item in scanner.get_unused_code(min_confidence=90))


def pylint_findings(root, sources):
    if not sources:
        return Counter()
    config = root / "empty-pylintrc"
    config.write_text("")
    command = [sys.executable, "-m", "pylint", "--disable=all", "--enable=unused-import",
               "--output-format=json", "--score=n", "--persistent=n", f"--rcfile={config}"]
    result = subprocess.run(command + sorted(sources), cwd=root, capture_output=True, text=True, timeout=180)
    if result.returncode not in (0, 4):
        raise ValueError(f"Pylint failed ({result.returncode}): {result.stderr or result.stdout}")
    try:
        messages = json.loads(result.stdout)
        if not isinstance(messages, list):
            raise ValueError("expected a JSON list")
        findings, scopes = Counter(), ScopeResolver(sources)
        for message in messages:
            path = Path(message["path"])
            relative = (path.relative_to(root) if path.is_absolute() else path).as_posix()
            if relative not in sources or message["message-id"] != "W0611" or not isinstance(message["message"], str):
                raise ValueError("unknown source/message in unused-import output")
            scope = scopes.at(relative, message["line"])
            findings[(relative, message["message-id"], scope, message["message"])] += 1
        if bool(findings) != bool(result.returncode):
            raise ValueError("exit status disagrees with unused-import findings")
        return findings
    except (ValueError, KeyError, TypeError) as exc:
        raise ValueError(f"Pylint returned invalid findings: {exc}") from exc


def unused(pair):
    # Required even if a no-change invocation has nothing to compare.
    importlib.import_module("vulture")
    importlib.import_module("pylint")
    if not pair.changed_files:
        return []
    findings = []
    with tempfile.TemporaryDirectory(prefix="rule16-unused-") as temporary:
        for name, sources in (("base", pair.before), ("target", pair.after)):
            root = Path(temporary) / name
            root.mkdir()
            materialize(root, sources)
            findings.append(vulture_findings(sources) + pylint_findings(root, sources))
    return [f"{path}::{scope}: new {tool}: {message} ({count} occurrence(s))"
            for (path, tool, scope, message), count in sorted((findings[1] - findings[0]).items())]


def clone_budgets(root):
    budgets = {}
    for signature, locations in clone_scan.collect(str(root)).items():
        occurrences = {(str(Path(path).relative_to(root)), start, end)
                       for path, start, end, _ in locations}
        if len({p for p, _, _ in occurrences}) >= 2:
            budgets[signature] = occurrences
    return budgets


def clones(pair):
    """Same scanner/counting rules; compare AST occurrence counts, not file-pair labels."""
    with tempfile.TemporaryDirectory(prefix="rule16-clones-") as temporary:
        inventories = []
        for name, sources in (("base", pair.before), ("target", pair.after)):
            root = Path(temporary) / name
            root.mkdir()
            materialize(root, sources)
            inventories.append(clone_budgets(root))
        before, after = inventories
    breaches = []
    for signature, occurrences in after.items():
        previous = len(before.get(signature, ()))
        if len(occurrences) > previous:
            locations = " | ".join(f"{p}:{a}-{b}" for p, a, b in sorted(occurrences))
            breaches.append(f"new/grown exact-AST clone ({previous} -> {len(occurrences)}): {locations}")
    return sorted(breaches)
