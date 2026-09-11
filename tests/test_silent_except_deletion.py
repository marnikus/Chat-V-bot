"""The delete tool's `except Exception` handlers must stay explainable.

`services/db_deletion*.py` decides which files get unlinked. A handler there
that swallows an error and prints nothing is a decision nobody can review,
so the trio is held to a stricter bar than the rest of the repo (147 of 269
production handlers are silent today; these files may not add to that):

  * a handler is *silent* when its own source contains no `log.`, no
    `report(`/`emit(`, and no `raise`;
  * it counts as explained when the `# noqa: BLE001` marker carries a
    `-- reason` naming what the fallback decides, or it delegates to
    `raise_refusal`.

Both numbers are pinned so the debt can only shrink: fix a handler by logging
or by refusing, and lower the pin in the same change.
"""

from __future__ import annotations

import ast
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FILES = ("services/db_deletion.py", "services/db_deletion_flow.py",
         "services/db_deletion_scan.py")
# Measured 2026-09-11, after the fail-closed ladder made its guards explain
# themselves. Each number is a ceiling: it may only come down.
SILENT_MAX = {"services/db_deletion.py": 9, "services/db_deletion_flow.py": 11,
              "services/db_deletion_scan.py": 0}
LODGED = ("log.", "report(", "emit(", "raise", "logging")
REASON_MARK = "noqa: BLE001 --"


def handlers(source):
    """Yield (lineno, body-text) for every `except Exception`/BaseException."""
    tree = ast.parse(source)
    lines = source.splitlines()
    for node in ast.walk(tree):
        named = isinstance(node, ast.ExceptHandler) and isinstance(
            node.type, ast.Name)
        if named and node.type.id in ("Exception", "BaseException"):
            yield node.lineno, "\n".join(lines[node.lineno - 1:node.end_lineno])


def silent_handlers(rel_path):
    """Lines where a broad catch neither logs nor names its fallback."""
    source = open(os.path.join(ROOT, rel_path), encoding="utf-8").read()
    out = []
    for lineno, body in handlers(source):
        logged = any(word in body for word in LODGED)
        explained = REASON_MARK in body or "raise_refusal" in body
        if not logged and not explained:
            out.append(lineno)
    return out


def test_the_deletion_trio_stays_within_its_pinned_debt() -> None:
    over = {rel: len(silent_handlers(rel)) for rel in FILES
            if len(silent_handlers(rel)) > SILENT_MAX[rel]}
    assert not over, (
        f"{over} grew past the pinned ceiling {SILENT_MAX}. A handler in the "
        f"tool that deletes files must say what it decided: log it, refuse, "
        f"or name the fallback on its noqa marker.")
