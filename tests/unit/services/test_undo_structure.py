"""Round F step F3 exit gates — the `UndoService` decomposition must not rot.

Design ref: docs/archive/2026-09-12-round-f-size-tail/
            ROUND_F2_F3_GOD_CLASS_DESIGN_2026-09-12.md §4

`services/undo_service.py::UndoService` was 418 class LOC / 28 methods / LCOM*
0.92 in a 573-line file. F3 moved the behaviour into four collaborators using
the convention `tests/unit/stores/test_stores_structure.py` pins for `stores/`
and step F2 used for `Collector`: a part is built from the aggregate and
nothing else, and the state stays on the aggregate.

Three things are load-bearing here, so each gets a gate rather than a comment:

  * `tests/test_world_write_gate.py` monkeypatches **`undo_service.
    MAX_STACK_HISTORY`** — a module-level name. Only `push` reads it, so `push`
    must stay a real body in this module. Moving it would leave that patch
    silently vacuous and the test still green (the trap step F1 hit, and the
    same shape as F2's `_sync`).
  * `bridge/router.py` imports `_values_equal` from here, `bridge/db_bridge.py`
    imports `emit_db_change` and `restart_world`, and
    `tests/integration/safety_deletion/test_bridge_results.py` patches
    `restart_world` on the db_bridge namespace. All three names moved, so the
    facade must keep re-exporting the SAME objects — a copy would silently
    divorce the patch target from the implementation.
  * no collaborator may import the facade: the parts are leaves, and a cycle
    would make the import order load-bearing again.

Run with:  python3 tests/unit/services/test_undo_structure.py
"""

import ast
import importlib
import inspect
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)

FACADE = "services.undo_service"

# attr on the facade -> module holding the behaviour
COLLABORATORS = {
    "_history": "services.undo_history",
    "_apply": "services.undo_apply",
    "_db_commands": "services.undo_db",
    "_world": "services.undo_world",
}

# the behaviour F3 moved out; each must be a thin delegator on the facade and a
# real body in its collaborator
MOVED = {
    "_history": ["history", "set_history", "migrate_global_history",
                 "_migrated_entry", "_next_seq", "stack_projection",
                 "set_stack_projection", "kind_projection", "push_stack"],
    "_apply": ["apply_command", "_apply_archive_command", "_apply_entry",
               "undo", "redo", "rewind_after_failure"],
    "_db_commands": ["_db_delete_op", "_db_op_forward", "_db_switch_op",
                     "_apply_db_command"],
    "_world": ["sync_world_state", "_schedule_world_undo_save"],
}

# names that moved to a part module but must still resolve from the facade
REEXPORTS = {
    "_values_equal": "services.undo_apply",
    "emit_db_change": "services.undo_world",
    "restart_world": "services.undo_world",
}


def _classes(module):
    return [v for v in vars(module).values()
            if isinstance(v, type) and v.__module__ == module.__name__
            and not v.__name__.startswith("_")]


def _facade_class():
    path = os.path.join(ROOT, "services", "undo_service.py")
    with open(path, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    return next(n for n in tree.body
                if isinstance(n, ast.ClassDef) and n.name == "UndoService")


def _statements(method):
    """A method's body without its docstring."""
    return [s for s in method.body
            if not (isinstance(s, ast.Expr) and isinstance(s.value,
                                                          ast.Constant))]


class TestUndoDecomposition(unittest.TestCase):

    def test_every_collaborator_module_exists(self):
        for target in COLLABORATORS.values():
            with self.subTest(module=target):
                self.assertTrue(_classes(importlib.import_module(target)),
                                f"{target} defines no public class")

    def test_the_facade_builds_each_collaborator_from_itself(self):
        """`__init__` composes the parts, passing `self` (design §2.1)."""
        klass = getattr(importlib.import_module(FACADE), "UndoService")
        src = inspect.getsource(klass.__init__)
        for attr, target in COLLABORATORS.items():
            part = importlib.import_module(target)
            pattern = "|".join(f"{c.__name__}\\(self" for c in _classes(part))
            with self.subTest(part=attr):
                self.assertRegex(
                    src, pattern,
                    f"UndoService.__init__ must build {attr} from one of "
                    f"{[c.__name__ for c in _classes(part)]}")

    def test_a_collaborator_takes_the_aggregate_and_nothing_else(self):
        for target in COLLABORATORS.values():
            part = importlib.import_module(target)
            for value in _classes(part):
                params = list(inspect.signature(value.__init__).parameters)
                with self.subTest(cls=f"{target}.{value.__name__}"):
                    self.assertEqual(
                        params[:2], ["self", "owner"],
                        "a collaborator is built from the aggregate only — "
                        "state stays on the aggregate")

    def test_the_bodies_live_in_the_collaborators_not_the_facade(self):
        """A moved name is a bare `return self.<part>.<name>(...)` here, and
        real code over there.

        This is what stops the split being undone method by method: logic
        re-inlined into the facade stops being a single return.
        """
        klass = _facade_class()
        on_facade = {m.name: m for m in klass.body
                     if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))}
        for attr, names in MOVED.items():
            part = importlib.import_module(COLLABORATORS[attr])
            owner = _classes(part)[0]
            for name in names:
                with self.subTest(name=name):
                    self.assertTrue(hasattr(owner, name),
                                    f"{owner.__name__} lost {name}")
                    self.assertIn(name, on_facade,
                                  f"UndoService no longer exposes {name}")
                    body = _statements(on_facade[name])
                    self.assertEqual(
                        len(body), 1,
                        f"UndoService.{name} should be a one-line delegator to "
                        f"{owner.__name__}, not a place to grow logic back")
                    self.assertIsInstance(body[0], ast.Return)
                    told = ast.unparse(body[0])
                    self.assertIn(
                        f"self.{attr}.", told,
                        f"UndoService.{name} must delegate to {attr}, got: "
                        f"{told}")
                    # an async body must stay async through the delegator, or
                    # the caller awaits a coroutine that was never created
                    part_fn = getattr(owner, name)
                    self.assertEqual(
                        isinstance(on_facade[name], ast.AsyncFunctionDef),
                        inspect.iscoroutinefunction(part_fn),
                        f"{name}: delegator and body disagree about async")

    def test_push_stays_a_real_body_reading_the_module_level_cap(self):
        """`push` must keep resolving MAX_STACK_HISTORY in THIS module.

        tests/test_world_write_gate.py sets `undo_service.MAX_STACK_HISTORY = 2`
        to shrink the cap. A patch only bites if the code under test looks the
        name up in that module, so the body cannot move.
        """
        mod = importlib.import_module(FACADE)
        self.assertTrue(hasattr(mod, "MAX_STACK_HISTORY"),
                        "the patch target name is gone from the module")
        klass = getattr(mod, "UndoService")
        src = inspect.getsource(klass.push)
        self.assertIn("MAX_STACK_HISTORY", src,
                      "push must still read the module-level cap the test "
                      "monkeypatches")
        for attr in COLLABORATORS:
            self.assertNotIn(f"self.{attr}.", src,
                             "push must stay a real body on the facade, not a "
                             "delegator — see the patch-target note above")

    def test_the_moved_module_functions_stay_reexported(self):
        """The facade must hand back the SAME objects, not copies.

        bridge/router.py imports `_values_equal` from here and
        bridge/db_bridge.py imports `emit_db_change` / `restart_world`;
        test_bridge_results.py patches `restart_world` on the db_bridge
        namespace. A re-definition would divorce the patch target from the
        implementation and every one of those callers would silently drift.
        """
        facade = importlib.import_module(FACADE)
        for name, home in REEXPORTS.items():
            with self.subTest(name=name):
                self.assertTrue(hasattr(facade, name),
                                f"{name} no longer resolves from {FACADE}")
                self.assertIs(getattr(facade, name),
                              getattr(importlib.import_module(home), name),
                              f"{name} must be the object defined in {home}, "
                              "not a copy")

    def test_no_collaborator_imports_the_facade(self):
        """The parts are leaves; a cycle would make import order load-bearing."""
        for target in COLLABORATORS.values():
            path = os.path.join(ROOT, target.replace(".", os.sep) + ".py")
            with open(path, encoding="utf-8") as fh:
                tree = ast.parse(fh.read())
            imported = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module:
                    imported.add(node.module)
                    # `from services import undo_service` names the facade in
                    # the alias, not in node.module — both forms are a cycle
                    imported.update(f"{node.module}.{a.name}"
                                    for a in node.names)
                elif isinstance(node, ast.Import):
                    imported.update(a.name for a in node.names)
            with self.subTest(module=target):
                self.assertNotIn(FACADE, imported,
                                 f"{target} imports the facade — the split "
                                 "would be a cycle")

    def test_the_facade_stays_inside_the_size_band(self):
        """May shrink, may not grow (RULE 18.2 band, ratcheted at F3)."""
        path = os.path.join(ROOT, "services", "undo_service.py")
        with open(path, encoding="utf-8") as fh:
            src = fh.read()
        lines = src.split("\n")
        self.assertLessEqual(
            len(lines), 300,
            "RULE 18.2 puts a module in the 150-300 line band; over 300 means "
            "a second responsibility crept back in")
        cls = _facade_class()
        self.assertLessEqual(
            cls.end_lineno - cls.lineno + 1, 179,
            "UndoService was 418 class LOC before F3 and 179 after; the house "
            "facades in stores/ sit at 202-232. Docstrings inside the class "
            "count against this, deliberately: F3 had to move a note out of "
            "`push` for exactly that reason.")


if __name__ == "__main__":
    unittest.main()
