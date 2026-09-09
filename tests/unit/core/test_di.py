"""
core/di — Dependency Injection (Real Path Tests)
Every assertion verifies a real path: lazy build, cache, cycle, missing, clear.
No pass-through.
"""
import unittest
import sys
sys.path.insert(0, "/home/user/Chat-V-bot")
from core.di import Container


class TestContainerPaths(unittest.TestCase):
    def setUp(self):
        self.c = Container()

    def tearDown(self):
        self.c.clear()

    # Path: register -> get lazy build -> cached identity
    def test_register_lazy_build_and_cache_identity(self):
        call_order = []
        def factory(ct):
            call_order.append("factory")
            return {"built": True}
        self.c.register("svc", factory)
        first = self.c.get("svc")
        second = self.c.get("svc")
        self.assertIs(first, second)
        self.assertEqual(call_order, ["factory"])  # built once
        self.assertTrue(first["built"])

    # Path: replace=False raises
    def test_register_duplicate_no_replace_raises(self):
        self.c.register("x", lambda ct: 1)
        with self.assertRaises(ValueError) as ctx:
            self.c.register("x", lambda ct: 2)
        self.assertIn("already has 'x'", str(ctx.exception))

    # Path: replace=True allows overwrite + clears instance cache
    def test_register_replace_true_overwrites_and_clears_cache(self):
        self.c.register("x", lambda ct: 1)
        old = self.c.get("x")
        self.c.register("x", lambda ct: 2, replace=True)
        new = self.c.get("x")
        self.assertIsNot(old, new)
        self.assertEqual(new, 2)

    # Path: register_value bypasses factory
    def test_register_value_bypasses_factory(self):
        self.c.register_value("val", "hello")
        self.assertTrue(self.c.has("val"))
        self.assertEqual(self.c.get("val"), "hello")
        # factory should be removed
        self.assertNotIn("val", self.c._factories)

    # Path: missing key raises KeyError with name in message
    def test_get_missing_raises_key_error_with_name(self):
        with self.assertRaises(KeyError) as ctx:
            self.c.get("missing")
        msg = str(ctx.exception)
        self.assertIn("missing", msg)
        self.assertIn("main.py wires", msg)

    # Path: dependency cycle detected with chain
    def test_cycle_detection_raises_value_error_with_chain(self):
        def a(ct):
            return ct.get("b")
        def b(ct):
            return ct.get("c")
        def c(ct):
            return ct.get("a")
        self.c.register("a", a)
        self.c.register("b", b)
        self.c.register("c", c)
        with self.assertRaises(ValueError) as ctx:
            self.c.get("a")
        msg = str(ctx.exception)
        self.assertIn("dependency cycle", msg)
        self.assertIn("a", msg)
        self.assertIn("b", msg)

    # Path: clear empties everything
    def test_clear_removes_all(self):
        self.c.register("v", lambda ct: 1)
        self.c.get("v")
        self.c.clear()
        self.assertFalse(self.c.has("v"))
        with self.assertRaises(KeyError):
            self.c.get("v")

    # Path: __contains__ true/false
    def test_contains_true_false(self):
        self.c.register("yes", lambda ct: 1)
        self.assertIn("yes", self.c)
        self.assertNotIn("no", self.c)

    # Path: get builds with container passed to factory
    def test_factory_receives_container(self):
        received = []
        def factory(ct):
            received.append(ct)
            return ct
        self.c.register("self", factory)
        result = self.c.get("self")
        self.assertIs(result, self.c)
        self.assertEqual(len(received), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
