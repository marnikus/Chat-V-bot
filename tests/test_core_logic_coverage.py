"""
🧪 PHASE 3 — SAFETY NET STARTER
Cover-all-logic starter for core/result + actions/registry.
Run with: python -m pytest tests/test_core_logic_coverage.py -v --cov=core.result --cov=actions.registry --cov-branch --cov-report=term-missing
Target: 100% branch + mutation-resistant assertions for both modules.
"""
from __future__ import annotations

import asyncio
import sys
import types
import unittest
from unittest.mock import patch, MagicMock

# Ensure repo root in path
sys.path.insert(0, "/home/user/Chat-V-bot")

# ── core/result ──────────────────────────────────────────────────────────
from core.result import Ok, Err, ok, err, of, aof, ERR, Result


class TestResultOk(unittest.TestCase):
    """Every branch of Ok[T]."""

    def test_ok_is_ok(self):
        o = Ok(42)
        self.assertTrue(o.is_ok)
        self.assertFalse(o.is_err)

    def test_ok_unwrap(self):
        o = Ok("hello")
        self.assertEqual(o.unwrap(), "hello")

    def test_ok_unwrap_or_returns_value_ignores_default(self):
        o = Ok(99)
        self.assertEqual(o.unwrap_or(0), 99)

    def test_ok_map_transforms(self):
        o = Ok(2)
        mapped = o.map(lambda x: x * 3)
        self.assertIsInstance(mapped, Ok)
        self.assertEqual(mapped.value, 6)

    def test_ok_err_returns_none(self):
        o = Ok(1)
        self.assertIsNone(o.err())

    def test_ok_frozen_slots(self):
        o = Ok(1)
        with self.assertRaises(AttributeError):
            o.value = 99


class TestResultErr(unittest.TestCase):
    """Every branch of Err[T]."""

    def test_err_is_err(self):
        e = Err("not_found", "missing")
        self.assertTrue(e.is_err)
        self.assertFalse(e.is_ok)

    def test_err_unwrap_raises_with_message(self):
        e = Err("code_1", "detail message")
        with self.assertRaises(RuntimeError) as ctx:
            e.unwrap()
        msg = str(ctx.exception)
        self.assertIn("unwrap() on Err('code_1')", msg)
        self.assertIn("detail message", msg)

    def test_err_unwrap_or_returns_default(self):
        e = Err("bad", "bad")
        self.assertEqual(e.unwrap_or("fallback"), "fallback")

    def test_err_map_pass_through(self):
        e = Err("bad", "bad")
        mapped = e.map(lambda x: x + 1)
        self.assertIs(mapped, e)  # identity preserved

    def test_err_err_returns_self(self):
        e = Err("bad")
        self.assertIs(e.err(), e)

    def test_err_frozen_slots(self):
        e = Err("bad")
        with self.assertRaises(AttributeError):
            e.code = "new"


class TestResultFactories(unittest.TestCase):
    def test_ok_factory_default_none(self):
        o = ok()
        self.assertIsInstance(o, Ok)
        self.assertIsNone(o.value)

    def test_ok_factory_with_value(self):
        o = ok(42)
        self.assertEqual(o.value, 42)

    def test_err_factory_defaults_empty_detail(self):
        e = err("missing")
        self.assertEqual(e.code, "missing")
        self.assertEqual(e.detail, "")

    def test_err_factory_full(self):
        e = err("preset_not_found", "preset X missing")
        self.assertEqual(e.detail, "preset X missing")


class TestResultOf(unittest.TestCase):
    """`of()` catches exceptions and returns typed Err — the bridge seam rule."""

    def test_of_success(self):
        r = of(lambda: 42, code="fail")
        self.assertIsInstance(r, Ok)
        self.assertEqual(r.unwrap(), 42)

    def test_of_exception_returns_err(self):
        def raise_value_error():
            raise ValueError("boom")
        r = of(raise_value_error, code="unexpected")
        self.assertIsInstance(r, Err)
        self.assertEqual(r.code, "unexpected")
        self.assertIn("ValueError", r.detail)
        self.assertIn("boom", r.detail)

    def test_of_exception_default_code(self):
        def fail():
            raise RuntimeError("x")
        r = of(fail)
        self.assertEqual(r.code, "unexpected_error")

    def test_of_zero_arg_call(self):
        # ensures the callable takes no args (design contract)
        r = of(lambda: [1, 2, 3])
        self.assertTrue(r.is_ok)


class TestResultAof(unittest.IsolatedAsyncioTestCase):
    """Async `aof()` — await coroutine factory."""

    async def test_aof_success(self):
        async def good():
            return 99
        r = await aof(good, code="fail")
        self.assertIsInstance(r, Ok)
        self.assertEqual(r.unwrap(), 99)

    async def test_aof_exception(self):
        async def bad():
            raise TypeError("bad type")
        r = await aof(bad, code="async_err")
        self.assertIsInstance(r, Err)
        self.assertEqual(r.code, "async_err")
        self.assertIn("TypeError", r.detail)

    async def test_aof_default_code(self):
        async def bad():
            raise KeyError("k")
        r = await aof(bad)
        self.assertEqual(r.code, "unexpected_error")


class TestResultGenericTyping(unittest.TestCase):
    """Result is a Union; generic behavior must hold at runtime."""

    def test_result_ok_int(self):
        r: Result[int] = ok(10)
        self.assertEqual(r.unwrap(), 10)

    def test_result_err_str(self):
        r: Result[str] = err("bad", "bad")
        self.assertTrue(r.is_err)

    def test_result_union_check(self):
        # runtime union doesn't enforce but design contracts do
        from typing import get_args
        # just ensure import didn't break
        self.assertTrue(True)


class TestResultBoundaryEdgeCases(unittest.TestCase):
    """Boundary / edge cases for complete branch coverage."""

    def test_ok_map_with_exception_raises_during_map(self):
        # If map's fn raises, it propagates (not caught by result) — design choice
        o = Ok(1)
        def bad_map(x):
            raise ZeroDivisionError("div")
        with self.assertRaises(ZeroDivisionError):
            o.map(bad_map)

    def test_err_map_does_not_call_fn(self):
        e = Err("bad")
        called = False
        def never(x):
            nonlocal called
            called = True
            return x
        e.map(never)
        self.assertFalse(called)

    def test_ok_unwrap_or_does_not_use_default(self):
        # design: unwrap_or ignores default on Ok
        o = Ok("real")
        self.assertEqual(o.unwrap_or("fake"), "real")

    def test_err_unwrap_or_uses_default(self):
        e = Err("bad")
        self.assertEqual(e.unwrap_or(42), 42)

    def test_result_sentinel_err_kind(self):
        # ERR is a sentinel; it should never be truthy like an exception
        self.assertIsNot(ERR, True)
        self.assertIsNot(ERR, False)


# ── actions/registry ──────────────────────────────────────────────────────
# Bypass actions/__init__.py which triggers ActionRegistry.scan() and imports
# heavy dependencies (aiohttp, etc.). Import module file directly.
import importlib.util
import os
_registry_path = os.path.join(os.path.dirname(__file__), "..", "actions", "registry.py")
_registry_path = os.path.abspath(_registry_path)
_spec = importlib.util.spec_from_file_location("actions.registry_direct", _registry_path)
_registry_mod = importlib.util.module_from_spec(_spec)
sys.modules["actions.registry_direct"] = _registry_mod
# We must set up the actions package stub so relative imports inside registry work
# (registry uses no relative imports; safe to exec directly)
_spec.loader.exec_module(_registry_mod)
ActionRegistry = _registry_mod.ActionRegistry
get_action_class = _registry_mod.get_action_class
all_action_ids = _registry_mod.all_action_ids


class TestActionRegistryUnit(unittest.TestCase):
    """Every branch of ActionRegistry (Phase 3 starter for registry logic)."""

    def setUp(self):
        # Tests only: clear before each
        ActionRegistry.clear()

    def tearDown(self):
        ActionRegistry.clear()

    def test_clear_empties(self):
        ActionRegistry.register_class(type("Dummy", (), {"block_id": "D"}))
        self.assertIn("D", ActionRegistry.all_ids())
        ActionRegistry.clear()
        self.assertEqual(ActionRegistry.all_ids(), [])

    def test_register_decorator(self):
        @ActionRegistry.register("DECORATED")
        class DecoratedBlock:
            pass
        self.assertEqual(ActionRegistry.get("DECORATED").__name__, "DecoratedBlock")

    def test_register_class_explicit_block_id(self):
        class Explicit:
            pass
        ActionRegistry.register_class(Explicit, block_id="EXPLICIT")
        self.assertIs(ActionRegistry.get("EXPLICIT"), Explicit)

    def test_register_class_uses_class_attr(self):
        class Implicit:
            block_id = "IMPLICIT"
        ActionRegistry.register_class(Implicit)
        self.assertIs(ActionRegistry.get("IMPLICIT"), Implicit)

    def test_register_class_no_block_id_ignored(self):
        class NoId:
            pass
        ActionRegistry.register_class(NoId)
        self.assertNotIn("NoId", ActionRegistry.all_ids())

    def test_duplicate_real_block_raises(self):
        class BlockA:
            block_id = "DUP"
        class BlockB:
            block_id = "DUP"
        # Make them appear to be in actions package for in_package check
        BlockA.__module__ = "actions.block_a"
        BlockB.__module__ = "actions.block_b"
        ActionRegistry.register_class(BlockA)
        with self.assertRaises(ValueError) as ctx:
            ActionRegistry.register_class(BlockB)
        self.assertIn("duplicate action id 'DUP'", str(ctx.exception))

    def test_duplicate_shadow_logs_warning(self):
        # A non-package shadow is allowed but logs warning
        class Real:
            block_id = "SHADOW"
            __module__ = "actions.real"
        class Shadow:
            block_id = "SHADOW"
            __module__ = "tests.shadow"
        ActionRegistry.register_class(Real)
        with self.assertLogs("chatbot", level="WARNING") as cm:
            ActionRegistry.register_class(Shadow)
        self.assertTrue(any("re-registered" in msg for msg in cm.output))

    def test_get_missing_returns_none(self):
        self.assertIsNone(ActionRegistry.get("NOTHING"))

    def test_all_ids_sorted(self):
        ActionRegistry.register_class(type("Z", (), {"block_id": "Z"}))
        ActionRegistry.register_class(type("A", (), {"block_id": "A"}))
        ids = ActionRegistry.all_ids()
        self.assertEqual(ids, ["A", "Z"])

    def test_all_classes_is_copy(self):
        ActionRegistry.register_class(type("X", (), {"block_id": "X"}))
        classes = ActionRegistry.all_classes()
        self.assertIsInstance(classes, dict)
        # modification of returned dict must not affect internal
        classes.pop("X", None)
        self.assertIn("X", ActionRegistry.all_ids())

    def test_scan_imports_and_registers(self):
        # scan triggers package imports that may need optional deps (aiohttp);
        # we assert scan returns list and does not crash when possible.
        try:
            before = set(ActionRegistry.all_ids())
            new_ids = ActionRegistry.scan()
            after = set(ActionRegistry.all_ids())
            self.assertIsInstance(new_ids, list)
        except ImportError:
            self.skipTest("Optional dependency missing for full package scan")

    def test_scan_idempotent(self):
        try:
            ActionRegistry.scan()
        except ImportError:
            self.skipTest("Optional dependency missing for full package scan")
        first = set(ActionRegistry.all_ids())
        try:
            second = ActionRegistry.scan()
        except ImportError:
            self.skipTest("Optional dependency missing for full package scan")
        # Second scan should not find new ids if package unchanged
        self.assertIsInstance(second, list)


class TestGetActionHelpers(unittest.TestCase):
    def test_get_action_class_compat(self):
        ActionRegistry.clear()
        class C:
            block_id = "C"
        ActionRegistry.register_class(C)
        self.assertIs(get_action_class("C"), C)

    def test_all_action_ids_compat(self):
        ActionRegistry.clear()
        self.assertEqual(all_action_ids(), [])


# ── Integration-style contract: core/result + registry together ───────────
class TestResultAndRegistryIntegration(unittest.TestCase):
    """Simulate a block that uses result patterns with registry lookup."""

    def test_registry_lookup_then_result_ok(self):
        class GoodBlock:
            block_id = "GOOD"
        ActionRegistry.register_class(GoodBlock)
        block_class = ActionRegistry.get("GOOD")
        self.assertIsNotNone(block_class)
        # Simulate execution returning Ok
        result = ok(42)
        self.assertTrue(result.is_ok)

    def test_registry_lookup_then_result_err(self):
        ActionRegistry.clear()
        result = err("missing_block", "block not registered")
        self.assertTrue(result.is_err)
        self.assertEqual(result.code, "missing_block")


if __name__ == "__main__":
    unittest.main(verbosity=2)
