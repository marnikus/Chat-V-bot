"""`actions.base_action` — the block base-class contract (P0).

SPEC-FIRST (docs/ACTIONS_TEST_DESIGN_2026-09-09.md §2). The contract being
pinned here is the one the rest of the app relies on:

  * class docstring — "Every action block inherits this and implements
    execute()", i.e. an action without `execute` is a programming error;
  * `to_dict` docstring — "Serialize the block with ALL of its settings
    (**round-trip safe**)", and `bridge/stack_bridge.get_stack_json()`
    literally does `json.dumps(engine.get_stack())` on the live stack;
  * `__init__` comment — "'enabled' and 'pre_delay_ms' may arrive inside
    kwargs when built from dict (load_stack)";
  * `display_name` docstring — "custom block name if set";
  * `__init_subclass__` — a block registers itself under its own block id.

Run with:  python3 tests/test_base_action_contract.py
"""

import asyncio
import json
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from actions import base_action  # noqa: E402
from actions.base_action import ActionResult, BaseAction  # noqa: E402


def run(coro):
    return asyncio.run(coro)


class Concrete(BaseAction):
    """A minimal real block: own id, one extra setting."""
    block_id = "SPEC_CONCRETE"
    name = "Concrete"
    icon = "🧪"

    def __init__(self, speed: int = 7, pre_delay_ms: int = 500, **kw):
        super().__init__(pre_delay_ms=pre_delay_ms, **kw)
        self.speed = speed
        self.calls = []

    async def execute(self, user_nick, cdp, engine=None):
        self.calls.append((user_nick, cdp, engine))
        return ActionResult.OK


class RegistryIsolation(unittest.TestCase):
    def setUp(self):
        self._snapshot = dict(base_action._REGISTRY)

    def tearDown(self):
        base_action._REGISTRY.clear()
        base_action._REGISTRY.update(self._snapshot)


class TestAbstractContract(unittest.TestCase):
    """BASE-01, BASE-02, BASE-15 — the execute flow."""

    def test_base_action_cannot_be_instantiated(self):
        """BASE-01."""
        with self.assertRaises(TypeError):
            BaseAction()

    def test_a_block_without_execute_cannot_be_instantiated(self):
        """BASE-02: "every action block inherits this and implements execute()"."""
        class Incomplete(BaseAction):
            block_id = ""

        with self.assertRaises(TypeError):
            Incomplete()

    def test_execute_is_awaited_with_the_documented_arguments(self):
        """BASE-15."""
        block = Concrete(pre_delay_ms=0)
        cdp = object()
        engine = object()
        self.assertEqual(run(block.execute("Ann", cdp, engine)),
                         ActionResult.OK)
        self.assertEqual(block.calls, [("Ann", cdp, engine)])

    def test_result_constants_are_distinct(self):
        """BASE-14."""
        self.assertEqual(
            3, len({ActionResult.OK, ActionResult.FAIL, ActionResult.SKIP}))


class TestPreDelay(unittest.TestCase):
    """BASE-03, BASE-04."""

    def test_zero_pre_delay_does_not_sleep(self):
        block = Concrete(pre_delay_ms=0)
        start = time.monotonic()
        run(block.pre_delay())
        self.assertLess(time.monotonic() - start, 0.02)

    def test_positive_pre_delay_sleeps_that_long(self):
        block = Concrete(pre_delay_ms=120)
        start = time.monotonic()
        run(block.pre_delay())
        elapsed = time.monotonic() - start
        self.assertGreaterEqual(elapsed, 0.115)
        self.assertLess(elapsed, 1.0)


class TestConstructorKwargs(unittest.TestCase):
    """BASE-05, BASE-06 — the load_stack path."""

    def test_enabled_positional(self):
        self.assertFalse(Concrete(enabled=False).enabled)
        self.assertTrue(Concrete(enabled=True).enabled)

    def test_enabled_arriving_inside_kwargs(self):
        """BASE-05: documented load_stack shape — everything in one dict."""
        self.assertFalse(Concrete(speed=3, **{"enabled": False}).enabled)

    def test_pre_delay_arriving_inside_kwargs(self):
        block = Concrete(**{"pre_delay_ms": 12})
        self.assertEqual(block.pre_delay_ms, 12)

    def test_none_enabled_means_unset_and_defaults_to_on(self):
        self.assertTrue(Concrete(enabled=None).enabled)

    def test_unknown_kwargs_are_kept_as_config_for_legacy_presets(self):
        """BASE-06."""
        block = Concrete(some_future_option="x")
        self.assertEqual(block.config, {"some_future_option": "x"})
        self.assertEqual(block.to_dict()["some_future_option"], "x")


class TestToDict(unittest.TestCase):
    """BASE-07 .. BASE-09 — the round-trip and JSON guarantees."""

    def test_contains_every_setting_and_no_plumbing(self):
        """BASE-07."""
        block = Concrete(speed=9, pre_delay_ms=250, enabled=False)
        data = block.to_dict()
        self.assertEqual(data["block_id"], "SPEC_CONCRETE")
        self.assertEqual(data["speed"], 9)
        self.assertEqual(data["pre_delay_ms"], 250)
        self.assertIs(data["enabled"], False)
        self.assertNotIn("config", data)
        self.assertNotIn("calls", [k for k in data if k.startswith("_")])
        self.assertTrue(all(not k.startswith("_") for k in data))

    def test_round_trip_is_stable(self):
        """BASE-08: "round-trip safe"."""
        block = Concrete(speed=4, pre_delay_ms=10, enabled=False,
                         legacy_flag=True)
        data = block.to_dict()
        clone = Concrete(**{k: v for k, v in data.items() if k != "block_id"})
        self.assertEqual(clone.to_dict(), data)

    def test_serialises_to_json(self):
        """BASE-09: bridge/stack_bridge.get_stack_json() does exactly this."""
        block = Concrete(speed=4, pre_delay_ms=10)
        payload = json.dumps(block.to_dict(), ensure_ascii=False)
        self.assertIn("SPEC_CONCRETE", payload)

    def test_private_attributes_are_not_serialised(self):
        block = Concrete()
        block._runtime_state = object()
        self.assertNotIn("_runtime_state", block.to_dict())


class TestDisplayName(unittest.TestCase):
    """BASE-10."""

    def test_falls_back_to_the_block_name(self):
        self.assertEqual(Concrete().display_name, "Concrete")

    def test_uses_a_custom_name(self):
        block = Concrete()
        block.custom_name = "  My preset  "
        self.assertEqual(block.display_name, "My preset")

    def test_blank_custom_name_falls_back(self):
        block = Concrete()
        block.custom_name = "   "
        self.assertEqual(block.display_name, "Concrete")

    def test_non_string_custom_name_falls_back(self):
        block = Concrete()
        block.custom_name = 42
        self.assertEqual(block.display_name, "Concrete")


class TestConfigSchema(unittest.TestCase):
    """BASE-11."""

    def test_base_schema_describes_pre_delay(self):
        schema = Concrete().config_schema()
        self.assertIn("pre_delay_ms", schema)
        self.assertEqual(schema["pre_delay_ms"]["type"], "number")

    def test_subclass_schema_extends_rather_than_replaces(self):
        class Extended(Concrete):
            def config_schema(self):
                s = super().config_schema()
                s["extra"] = {"type": "text", "default": ""}
                return s

        schema = Extended().config_schema()
        self.assertIn("pre_delay_ms", schema)
        self.assertIn("extra", schema)


class TestAutoRegistration(RegistryIsolation):
    """BASE-12, BASE-13 — the __init_subclass__ hook."""

    def test_a_block_registers_itself_under_its_own_id(self):
        """BASE-12."""
        class Fresh(BaseAction):
            block_id = "SPEC_FRESH"

            async def execute(self, user_nick, cdp, engine=None):
                return ActionResult.OK

        self.assertIs(base_action.get_action_class("SPEC_FRESH"), Fresh)
        self.assertIn("SPEC_FRESH", base_action.all_action_ids())

    def test_a_block_without_an_id_is_not_registered(self):
        class Anonymous(BaseAction):
            async def execute(self, user_nick, cdp, engine=None):
                return ActionResult.OK

        self.assertNotIn(Anonymous, base_action._REGISTRY.values())

    def test_inheriting_a_block_id_does_not_replace_the_parent(self):
        """BASE-13: shadow — a subclass must not hijack its parent's id.

        Both the coverage plan (registry: "duplicate, shadow") and simple
        safety demand this: a variant/subclass of a block (a test double, a
        specialised preset class) silently swapping itself into the palette
        would change what every existing preset runs.
        """
        class Parent(BaseAction):
            block_id = "SPEC_PARENT"

            async def execute(self, user_nick, cdp, engine=None):
                return ActionResult.OK

        class Child(Parent):        # inherits block_id, declares none
            pass

        self.assertIs(base_action.get_action_class("SPEC_PARENT"), Parent)
        self.assertNotIn(Child, base_action._REGISTRY.values())

    def test_registry_and_base_action_share_one_registry(self):
        """The package palette API must not be a second, empty registry."""
        from actions import registry

        class Shared(BaseAction):
            block_id = "SPEC_SHARED"

            async def execute(self, user_nick, cdp, engine=None):
                return ActionResult.OK

        self.assertIs(registry.get_action_class("SPEC_SHARED"), Shared)
        self.assertIn("SPEC_SHARED", registry.all_action_ids())


if __name__ == "__main__":
    unittest.main(verbosity=2)
