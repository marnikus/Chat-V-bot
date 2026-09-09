"""Tests for the core/ contracts: Result, EventBus, Protocols, Container.

Run:  python -m pytest tests/test_core_contracts.py
"""

import sys
import os
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.result import Ok, Err, Result, of, aof, err, ok
from core.events import (EventBus, PeopleChanged, PersonFound, LabelsChanged,
                         DbChanged, UndoHistoryChanged)
from core.di import Container
from core.interfaces import (SettingsStoreProto, PresetStoreProto,
                             BookmarkStoreProto, BlockStoreProto,
                             SessionStoreProto, UndoStoreProto)


class TestResult(unittest.TestCase):
    def test_ok_carries_value(self):
        r = Ok(42)
        self.assertTrue(r.is_ok)
        self.assertEqual(r.unwrap(), 42)
        self.assertIsNone(r.err())

    def test_err_carries_code_and_detail(self):
        r = Err("preset_not_found", "no preset named X")
        self.assertTrue(r.is_err)
        self.assertEqual(r.err().code, "preset_not_found")
        self.assertEqual(r.unwrap_or("fallback"), "fallback")
        with self.assertRaises(RuntimeError):
            r.unwrap()

    def test_map_only_maps_ok(self):
        self.assertEqual(Ok(2).map(lambda v: v * 10).value, 20)
        self.assertEqual(Err("x").map(lambda v: v * 10).code, "x")

    def test_of_catches_exceptions(self):
        r = of(lambda: 1 / 0, code="math")
        self.assertTrue(r.is_err)
        self.assertEqual(r.err().code, "math")
        self.assertIn("ZeroDivisionError", r.err().detail)
        self.assertEqual(of(lambda: 7).value, 7)

    def test_aof_catches_exceptions(self):
        async def boom():
            raise ValueError("nope")
        async def fine():
            return "yes"
        import asyncio
        self.assertEqual(asyncio.run(aof(fine)), Ok("yes"))
        r = asyncio.run(aof(boom, code="bad"))
        self.assertEqual(r.err().code, "bad")

    def test_constructors(self):
        self.assertEqual(ok(1), Ok(1))
        self.assertEqual(err("c", "d").code, "c")


class TestEventBus(unittest.TestCase):
    def test_subscribe_and_emit(self):
        bus = EventBus()
        got = []
        bus.subscribe(PeopleChanged, lambda e: got.append(e.reason))
        bus.emit(PeopleChanged(reason="deleted", nicks=("a",)))
        self.assertEqual(got, ["deleted"])

    def test_unsubscribe(self):
        bus = EventBus()
        got = []
        off = bus.subscribe(PeopleChanged, lambda e: got.append(1))
        off()
        bus.emit(PeopleChanged())
        self.assertEqual(got, [])

    def test_handler_exception_does_not_break_emit_or_other_handlers(self):
        bus = EventBus()
        got = []
        bus.subscribe(LabelsChanged, lambda e: 1 / 0)
        bus.subscribe(LabelsChanged, lambda e: got.append(e.payload))
        bus.emit(LabelsChanged(payload="{}"))       # must not raise
        self.assertEqual(got, ["{}"])

    def test_event_types_are_isolated(self):
        bus = EventBus()
        got = []
        bus.subscribe(PersonFound, lambda e: got.append("found"))
        bus.emit(PeopleChanged())                   # different type
        self.assertEqual(got, [])

    def test_same_handler_subscribed_once(self):
        bus = EventBus()
        seen = []
        h = lambda e: seen.append(1)               # noqa: E731
        bus.subscribe(DbChanged, h)
        bus.subscribe(DbChanged, h)
        bus.emit(DbChanged(action="load"))
        self.assertEqual(seen, [1])

    def test_during_emit_subscription_snapshot_is_stable(self):
        bus = EventBus()
        seen = []

        def handler(e):
            seen.append("a")
            bus.unsubscribe(UndoHistoryChanged, handler)
        bus.subscribe(UndoHistoryChanged, handler)
        bus.emit(UndoHistoryChanged())
        bus.emit(UndoHistoryChanged())
        self.assertEqual(seen, ["a"])


class FakeSettings:
    """Dict-backed fake proving the Protocol is implementable without I/O."""

    def __init__(self):
        self.data = {"chrome": {"port": 9333}}

    def get(self, *keys, default=None):
        node = self.data
        for k in keys:
            node = node.get(k, {}) if isinstance(node, dict) else {}
        return node or default

    def set(self, section, value, save=True):
        self.data[section] = value

    def section(self, name):
        return self.data.get(name, {})


class TestProtocols(unittest.TestCase):
    def test_dict_backed_fake_satisfies_protocol(self):
        fake = FakeSettings()
        self.assertIsInstance(fake, SettingsStoreProto)
        self.assertEqual(fake.get("chrome", "port", default=1), 9333)

    def test_every_config_protocol_is_runtime_checkable(self):
        for proto in (PresetStoreProto, BookmarkStoreProto, BlockStoreProto,
                      SessionStoreProto, UndoStoreProto):
            self.assertTrue(hasattr(proto, "__protocol_attrs__")
                            or proto.__mro__[1].__name__ == "Protocol")


class TestContainer(unittest.TestCase):
    def test_lazy_singleton(self):
        c = Container()
        calls = []

        def make(ct):
            calls.append(1)
            return {"v": 1}
        c.register("thing", make)
        self.assertEqual(calls, [])              # lazy
        self.assertEqual(c.get("thing"), {"v": 1})
        self.assertEqual(c.get("thing"), {"v": 1})
        self.assertEqual(len(calls), 1)          # cached

    def test_factory_receives_container(self):
        c = Container()
        c.register_value("port", 9222)
        c.register("client", lambda ct: {"port": ct.get("port")})
        self.assertEqual(c.get("client")["port"], 9222)

    def test_duplicate_registration_rejected(self):
        c = Container()
        c.register("a", lambda ct: 1)
        with self.assertRaises(ValueError):
            c.register("a", lambda ct: 2)
        c.register("a", lambda ct: 3, replace=True)   # explicit replace OK
        self.assertEqual(c.get("a"), 3)

    def test_unknown_key(self):
        c = Container()
        with self.assertRaises(KeyError):
            c.get("nope")

    def test_cycle_detected(self):
        c = Container()
        c.register("a", lambda ct: ct.get("b"))
        c.register("b", lambda ct: ct.get("a"))
        with self.assertRaises(ValueError):
            c.get("a")

    def test_contains(self):
        c = Container()
        c.register("x", lambda ct: 1)
        self.assertIn("x", c)
        self.assertNotIn("y", c)


if __name__ == "__main__":
    unittest.main()
