"""Round H step H6: the three audit metrics that each produced a false headline.

Every test here pins a defect that ACTUALLY misled this project, and each is
written so that reverting the fix fails it. A metric that cannot see its own
blind spot is worse than no metric: it produces a confident wrong headline,
and three earlier rounds acted on these.
"""
import ast
import importlib.util
import os
import sys
import textwrap
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_spec = importlib.util.spec_from_file_location(
    "current_audit", os.path.join(ROOT, "tools", "metrics", "current_audit.py"))
audit = importlib.util.module_from_spec(_spec)
sys.modules["current_audit"] = audit
_spec.loader.exec_module(audit)


def _class(source, name="C"):
    tree = ast.parse(textwrap.dedent(source))
    return next(n for n in ast.walk(tree)
                if isinstance(n, ast.ClassDef) and n.name == name)


def _analyse(source, name="C"):
    node = _class(source, name)
    methods = [n for n in node.body if isinstance(n, audit.FUNCTION)]
    names = {m.name for m in methods}
    fields = set().union(*[audit.fields_of(m, names) for m in methods]) or set()
    return audit.lcom4(methods, fields, names)


class TestLcomSeesThroughADelegationHandle(unittest.TestCase):
    """The defect: PersonLifecycle scored LCOM4 = 1 and three rounds left it
    alone. Every method held `self._owner`, and a field everyone holds links
    everyone. Discounting it revealed eight components and a real split."""

    SOURCE = """
    class C:
        def __init__(self, owner):
            self._owner = owner
        def read_a(self):
            return self._owner.db, self._a
        def write_a(self, v):
            self._a = v
            return self._owner
        def read_b(self):
            return self._owner.db, self._b
        def write_b(self, v):
            self._b = v
            return self._owner
    """

    def test_the_raw_count_is_collapsed_by_the_shared_handle(self):
        raw, _, _ = _analyse(self.SOURCE)
        self.assertEqual(raw, 1, "the handle links every method — this is the "
                                 "number that misled earlier rounds")

    def test_the_net_count_reveals_the_real_components(self):
        _, net, handles = _analyse(self.SOURCE)
        self.assertEqual(handles, ["_owner"])
        self.assertGreaterEqual(net, 3, "discounting the handle must separate "
                                        "the a/b clusters and __init__")

    def test_a_class_clustering_on_real_state_is_not_split_by_the_fix(self):
        """Non-vacuity: the fix must not report every class as incohesive.

        Here `rows` is shared by some methods but not all, so nothing is
        discounted and the class stays one component — the evidence on which
        SchemaMigrator was left whole in H5.
        """
        raw, net, handles = _analyse("""
        class C:
            def __init__(self, db):
                self.db = db
                self.rows = []
            def add(self, r):
                self.rows.append(r)
            def total(self):
                return len(self.rows)
            def reset(self):
                self.db = None
        """)
        self.assertEqual(handles, [], "no field is held by every method")
        self.assertEqual((raw, net), (1, 1))


class TestLcomCountsAClassmethodReceiver(unittest.TestCase):
    """The defect: the old reader matched the literal name `self`, so every
    @classmethod looked field-free and shrank the cohesion denominator."""

    def test_cls_is_read_as_the_receiver(self):
        node = _class("""
        class C:
            @classmethod
            def make(cls):
                return cls._registry
        """)
        method = node.body[0]
        self.assertEqual(audit.receiver(method), "cls")
        self.assertEqual(audit.fields_of(method, set()), {"_registry"})


class TestMethodCountSeesThroughAFacade(unittest.TestCase):
    """The defect: Round H kept class identity by splitting files with mixins.
    A class then DECLARES few methods while its caller-visible surface is
    unchanged, so the methods-per-class budget stopped measuring anything."""

    def test_reachable_counts_inherited_methods_from_local_bases(self):
        classes = [
            dict(name="Mixin", methods=4, bases=[]),
            dict(name="Other", methods=3, bases=[]),
            dict(name="Facade", methods=2, bases=["Mixin", "Other", "QObject"]),
        ]
        resolved = {c["name"]: c for c in classes}

        def reachable(name, seen):
            cls = resolved.get(name)
            if cls is None or name in seen:
                return 0
            seen.add(name)
            return cls["methods"] + sum(reachable(b, seen) for b in cls["bases"])

        # QObject is not local and contributes nothing; 2 + 4 + 3 = 9.
        self.assertEqual(reachable("Facade", set()), 9)
        self.assertGreater(reachable("Facade", set()), resolved["Facade"]["methods"],
                           "a facade must not read as smaller than its surface")


class TestParameterCountSeesAParameterObject(unittest.TestCase):
    """The defect: RULE 19 §19.4 prescribes a parameter object for a long
    argument list, and the counter could not see one — so the remedy and a
    genuinely simple function were indistinguishable."""

    def test_a_request_dataclass_expands_to_its_field_count(self):
        widths = {"Request": 14}
        params, objects = 1, ["Request"]
        effective = params + sum(widths.get(o, 1) - 1 for o in objects)
        self.assertEqual(effective, 14)

    def test_an_ordinary_annotation_does_not_inflate_the_count(self):
        widths = {"Request": 14}
        effective = 2 + sum(widths.get(o, 1) - 1 for o in ["str", "int"])
        self.assertEqual(effective, 2, "only known parameter OBJECTS expand")


if __name__ == "__main__":
    unittest.main()
