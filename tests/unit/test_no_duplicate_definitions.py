"""No production module may define the same top-level name twice.

Round I step I1. `backend/dom_highlight.py` shipped TWO byte-identical
copies of `ElementMatch` and `Overlay` (~52 lines): the second silently
shadowed the first, so behaviour was correct and the suite was green.
Nothing in the tree could see it —

  * both clone detectors (`tools/metrics/clone_scan.py` and pylint R0801)
    compare across FILES and require at least two, so same-file duplication
    is invisible to them by construction;
  * vulture reports unused *imports* and *names*, not a shadowed definition
    that is genuinely reachable right up until the moment it is replaced;
  * coverage counts the surviving copy as covered.

That is the gap this guard closes. It is deliberately a whole-tree AST scan
rather than a diff-scoped check: a duplicate arrives from a bad merge or
rebuild, which is exactly the situation where nobody is reading the diff.

Redefinition is legal Python and occasionally intentional, so the two
sanctioned forms are allowed explicitly and nothing else is:

  * `typing.overload` stubs, which are declarations, not definitions;
  * branch-guarded definitions (`if TYPE_CHECKING:`, `try/except ImportError`,
    `if sys.version_info >= ...`), where only one body ever binds — these are
    not top-level siblings in the AST, so they never reach this check.
"""
import ast
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PACKAGES = ("core", "actions", "backend", "bridge", "services", "stores", "app")


def production_files():
    out = []
    for pkg in PACKAGES:
        for base, _dirs, names in os.walk(os.path.join(ROOT, pkg)):
            if "__pycache__" in base:
                continue
            out += [os.path.join(base, n) for n in names if n.endswith(".py")]
    out.append(os.path.join(ROOT, "main.py"))
    return sorted(out)


def _is_overload(node):
    """A `@typing.overload` stub declares a signature; it is not a body."""
    for dec in getattr(node, "decorator_list", []):
        name = dec.attr if isinstance(dec, ast.Attribute) else getattr(dec, "id", "")
        if name == "overload":
            return True
    return False


def duplicate_definitions(path):
    """[(name, [lineno, ...]), ...] for top-level names defined more than once."""
    with open(path, encoding="utf-8") as handle:
        tree = ast.parse(handle.read())
    seen = {}
    for node in tree.body:
        if not isinstance(node, (ast.ClassDef, ast.FunctionDef,
                                 ast.AsyncFunctionDef)):
            continue
        if _is_overload(node):
            continue
        seen.setdefault(node.name, []).append(node.lineno)
    return sorted((name, lines) for name, lines in seen.items() if len(lines) > 1)


class TestNoDuplicateTopLevelDefinitions(unittest.TestCase):

    def test_no_production_module_defines_a_name_twice(self):
        offenders = []
        for path in production_files():
            for name, lines in duplicate_definitions(path):
                rel = os.path.relpath(path, ROOT)
                offenders.append(f"{rel}: {name} defined at lines "
                                 + ", ".join(str(n) for n in lines))
        self.assertEqual(offenders, [],
                         "a shadowed duplicate definition is dead code that "
                         "reads as live code:\n" + "\n".join(offenders))

    def test_the_scan_actually_detects_a_duplicate(self):
        """Non-vacuity, the H discipline: a guard that cannot fail is decoration.

        Uses the real analyser on the real shape the bug had — two identical
        top-level classes in one module.
        """
        import tempfile
        source = (
            "from dataclasses import dataclass\n"
            "\n@dataclass\nclass Thing:\n    a: int = 1\n"
            "\ndef helper():\n    return 1\n"
            "\n@dataclass\nclass Thing:\n    a: int = 1\n"
        )
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as fh:
            fh.write(source)
            temp = fh.name
        try:
            found = duplicate_definitions(temp)
            self.assertEqual([n for n, _ in found], ["Thing"])
            self.assertEqual(len(found[0][1]), 2)
            self.assertEqual(duplicate_definitions(__file__), [],
                             "and it must not fire on a healthy module")
        finally:
            os.unlink(temp)

    def test_an_overload_stub_is_not_a_duplicate(self):
        """The one sanctioned redefinition stays legal."""
        import tempfile
        source = (
            "from typing import overload\n"
            "\n@overload\ndef f(x: int) -> int: ...\n"
            "\n@overload\ndef f(x: str) -> str: ...\n"
            "\ndef f(x):\n    return x\n"
        )
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as fh:
            fh.write(source)
            temp = fh.name
        try:
            self.assertEqual(duplicate_definitions(temp), [])
        finally:
            os.unlink(temp)


if __name__ == "__main__":
    unittest.main()
