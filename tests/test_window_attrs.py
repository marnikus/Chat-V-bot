"""Static guard: private self.<attr> used anywhere in MainWindow must be
assigned somewhere in the class (catches the 'no attribute _tray_icon' bug
class without needing a Qt GUI in the test environment)."""
import ast
import pathlib

SRC = (pathlib.Path(__file__).resolve().parents[1]
       / "chatflow" / "app" / "window.py")


def test_private_attrs_are_assigned():
    tree = ast.parse(SRC.read_text(encoding="utf-8"))
    cls = next(n for n in ast.walk(tree)
               if isinstance(n, ast.ClassDef) and n.name == "MainWindow")
    assigned: set[str] = set()
    used: set[str] = set()
    for node in ast.walk(cls):
        if (isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id == "self"
                and node.attr.startswith("_")
                and not node.attr.startswith("__")):
            if isinstance(node.ctx, ast.Store):
                assigned.add(node.attr)
            elif isinstance(node.ctx, ast.Load):
                # ignore method calls (self._method()) — only data attrs
                in_call = any(isinstance(p, ast.Call) and p.func is node
                              for p in ast.walk(cls))
                if not in_call:
                    used.add(node.attr)
    missing = used - assigned
    assert not missing, (
        f"private attrs used but never assigned in MainWindow: {sorted(missing)}")
