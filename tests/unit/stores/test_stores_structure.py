"""AREA B exit gates — file size, class size and the `stores/` layering rule.

Design ref: docs/archive/2026-09-09-four-area-refactor/REFACTOR_2026-09-09_AREA_B_DESIGN.md §2, §5 (criteria 2–4).

These are the numbers the plan asked for, written as tests so they cannot rot:

  * no file in `stores/` over **400 SLOC** (plan §6.2 exit criterion 2);
  * `HistoryRepo` under **30 public methods** (it had 44 in total);
  * a store never imports a service, a bridge or `app` — and the single
    documented `stores → backend` edge (`media_store → backend.chat_agent_js`,
    the layering inversion the plan defers in §9) stays the ONLY one;
  * every god class is composed of the collaborators B2 extracts, and each
    collaborator reads the aggregate's state (the split must move behaviour,
    not hide it behind a second copy of the data).

Run with:  python3 tests/unit/stores/test_stores_structure.py
"""

import ast
import importlib
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)
HERE = os.path.dirname(os.path.abspath(__file__))

STORES = os.path.join(ROOT, "stores")
SLOC_CEILING = 400
#: the one `stores → backend` import the plan knows about and defers (§3.5).
#: B2 moved it with the downloader, so `media_fetch.py` owns the JS expression
#: now and `stores/media_store.py` no longer imports `backend` at all — still
#: exactly ONE inversion, just one file deeper (design §2.2, §3.5).
ALLOWED_UPWARD_EDGES = {"media_fetch.py": "backend.chat_agent_js"}


def py_files():
    return sorted(name for name in os.listdir(STORES) if name.endswith(".py"))


def sloc(path):
    """Non-blank, non-comment source lines (the metrics.py rule)."""
    out = 0
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            out += 1
    return out


def imports_of(path):
    tree = ast.parse(open(path, encoding="utf-8").read())
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            out.append(node.module)
    return out


class TestFileSize(unittest.TestCase):
    def test_no_stores_file_is_bigger_than_the_ceiling(self):
        for name in py_files():
            with self.subTest(file=f"stores/{name}"):
                size = sloc(os.path.join(STORES, name))
                self.assertLessEqual(
                    size, SLOC_CEILING,
                    f"stores/{name} is {size} SLOC (ceiling {SLOC_CEILING})")

    def test_the_package_keeps_a_reasonable_file_count(self):
        # B2 splits must stay cohesive: 17 modules before, and a decomposition
        # that quietly exploded into 40 tiny files is just as unreadable.
        # 2026-09-11: 36 → 37 — the undo-restore fix added world_lock.py
        # (one write gate per world file), a leaf module other areas import.
        # window_preset_store.py came with the f82007c merge on this line.
        self.assertLessEqual(len(py_files()), 37)
        self.assertGreaterEqual(len(py_files()), 17)


class TestClassSize(unittest.TestCase):
    #: measured on the pre-split code (design §0.2) — the split must not ADD
    #: public surface to a facade, and `HistoryRepo` stays under the plan's
    #: 30-method gate
    MAX_PUBLIC = {
        "stores.history_repo": ("HistoryRepo", 22),
        "stores.media_store": ("MediaStore", 15),
        "stores.label_store": ("LabelStore", 25),
        "stores.history_db": ("HistoryDB", 14),
        "stores.user_memory": ("UserMemory", 17),
        "stores.preset_store": ("PresetStore", 15),
    }

    #: the ONE exception: B1 gave every store the same lifecycle verbs
    #: (design §1.1), which are new names on classes that used to persist
    #: implicitly. Anything else that shows up is growth the split must not
    #: have produced.
    LIFECYCLE = frozenset({"data", "dirty", "flush", "load", "path", "reload",
                           "save"})

    def test_public_method_counts(self):
        with open(os.path.join(HERE, "api_baseline_pre_b1.json"),
                  encoding="utf-8") as handle:
            before = json.load(handle)
        for module, (name, ceiling) in self.MAX_PUBLIC.items():
            klass = getattr(importlib.import_module(module), name)
            public = {attr for attr in dir(klass)
                      if not attr.startswith("_")
                      and callable(getattr(klass, attr, None))}
            known = {attr for attr in before[module]["classes"][name]
                     if not attr.startswith("_")}
            grew = public - known
            with self.subTest(cls=f"{module}.{name}"):
                self.assertEqual(
                    grew - self.LIFECYCLE, set(),
                    f"{name} gained {sorted(grew - self.LIFECYCLE)} — a "
                    "collaborator belongs behind the facade, not on it")
                self.assertLessEqual(
                    len(public), ceiling + len(grew & self.LIFECYCLE),
                    f"{name} grew from {ceiling} to {len(public)} public "
                    "methods — the collaborators belong behind the facade")
                self.assertLess(len(public), 30,
                                "a facade above 30 public methods is the "
                                "god class the plan asked to split")

    #: only the classes B2 takes apart — `stores/migration.py` (frozen for
    #: every area) keeps its own 79-line `migrate_legacy_config`
    SPLIT_FILES = ("history_repo", "history_repo_append",
                   "history_repo_identity", "history_repo_media",
                   "history_repo_lifecycle", "media_store", "media_layout",
                   "media_fetch", "media_cache", "history_db",
                   "history_schema", "history_schema_repair", "label_store",
                   "label_state", "label_world", "label_assignments",
                   "label_filter", "label_rules",
                   "user_memory", "user_query", "preset_store",
                   "preset_migration")
    CEILING = 60

    def test_no_single_method_body_beyond_the_ceiling(self):
        """The three worst functions (CC 34 / 33 / 32) must be decomposed.

        The plan's gates for B are structural (SLOC, method count), but the
        reason those gates exist is the unreadable bodies, so this pins the
        longest *method* of every class B2 splits.
        """
        ceiling = self.CEILING
        worst = []
        for name in [n for n in py_files() if n[:-3] in self.SPLIT_FILES]:
            tree = ast.parse(open(os.path.join(STORES, name),
                                  encoding="utf-8").read())
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    length = (node.end_lineno or node.lineno) - node.lineno + 1
                    if length > ceiling:
                        worst.append(f"stores/{name}:{node.lineno} "
                                     f"{node.name} ({length} lines)")
        self.assertEqual(worst, [], "longest method bodies over the ceiling")


class TestLayering(unittest.TestCase):
    def test_a_store_never_imports_a_service_bridge_or_app(self):
        for name in py_files():
            with self.subTest(file=f"stores/{name}"):
                for module in imports_of(os.path.join(STORES, name)):
                    top = module.split(".")[0]
                    self.assertNotIn(
                        top, ("services", "bridge", "app", "actions"),
                        f"stores/{name} imports {module} — the dependency "
                        "rule (stores/ docstring) is one-way")

    def test_backend_is_reached_only_through_the_documented_edge(self):
        for name in py_files():
            reached = {module.split(".")[0] for module in
                       imports_of(os.path.join(STORES, name))
                       if module.split(".")[0] == "backend"}
            with self.subTest(file=f"stores/{name}"):
                allowed = ALLOWED_UPWARD_EDGES.get(name, "")
                self.assertEqual(sorted(reached),
                                 sorted([allowed.split(".")[0]])
                                 if allowed else [],
                                 "a new stores → backend edge is a layering "
                                 "regression (plan §3.5 defers the existing "
                                 "one to the cleanup PR)")


class TestComposition(unittest.TestCase):
    """The collaborators B2 extracts, and the rule they obey.

    Each collaborator is constructed with the aggregate and must read the
    aggregate's state at call time — that is what keeps
    `store.paused = True` / `store.now = …` / `db._repair_tables = …` (used by
    production, the bridges and the other areas' tests) working through the
    split.
    """

    COLLABORATORS = {
        "stores.history_repo": ("HistoryRepo", {
            "identity": "stores.history_repo_identity",
            "planner": "stores.history_repo_append",
            "media": "stores.history_repo_media",
            "lifecycle": "stores.history_repo_lifecycle",
        }),
        "stores.media_store": ("MediaStore", {
            "layout": "stores.media_layout",
            "fetcher": "stores.media_fetch",
            "policy": "stores.media_cache",
        }),
        "stores.history_db": ("HistoryDB", {
            "migrator": "stores.history_schema_repair",
        }),
        # the four part-objects live on PRIVATE names: `LabelStore` already
        # owns public `state()` / `assignments()` / `filter()` methods, and a
        # public attribute would shadow them
        "stores.label_store": ("LabelStore", {
            "_state": "stores.label_state",
            "_world": "stores.label_world",
            "_assignments": "stores.label_assignments",
            "_filter": "stores.label_filter",
        }),
        "stores.user_memory": ("UserMemory", {
            "query": "stores.user_query",
        }),
        "stores.preset_store": ("PresetStore", {
            "migration": "stores.preset_migration",
        }),
    }

    def test_the_new_modules_exist(self):
        for module, (name, parts) in self.COLLABORATORS.items():
            with self.subTest(module=module):
                for attr, target in parts.items():
                    importlib.import_module(target)

    def test_the_facade_builds_each_collaborator_from_itself(self):
        """`__init__` composes the parts, passing `self` (design §2.1)."""
        import inspect
        import re
        for module, (name, parts) in self.COLLABORATORS.items():
            klass = getattr(importlib.import_module(module), name)
            src = inspect.getsource(klass.__init__)
            for attr, target in parts.items():
                with self.subTest(cls=name, part=attr):
                    part = importlib.import_module(target)
                    classes = [value for value in vars(part).values()
                               if isinstance(value, type)
                               and value.__module__ == target
                               and not value.__name__.startswith("_")]
                    self.assertTrue(
                        classes, f"{target} defines no public class")
                    pattern = "|".join(f"{c.__name__}\(self" for c in classes)
                    self.assertRegex(
                        src, pattern,
                        f"{name}.__init__ must build {attr} from one of "
                        f"{[c.__name__ for c in classes]}")

    def test_a_collaborator_takes_the_aggregate_and_nothing_else(self):
        import inspect
        for module, (name, parts) in self.COLLABORATORS.items():
            for attr, target in parts.items():
                part = importlib.import_module(target)
                for value in vars(part).values():
                    if not (isinstance(value, type)
                            and value.__module__ == target
                            and not value.__name__.startswith("_")):
                        continue
                    params = list(
                        inspect.signature(value.__init__).parameters)
                    with self.subTest(cls=f"{target}.{value.__name__}"):
                        self.assertEqual(
                            params[:2], ["self", "owner"],
                            "a collaborator is built from the aggregate only "
                            "— state stays on the aggregate")


if __name__ == "__main__":
    unittest.main()
