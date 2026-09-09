"""
core/ integration — Container + EventBus + Result + Protocols together.
Real assertions, no pass-through.
"""
import unittest
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from core.result import Ok, Err, ok, err
from core.events import EventBus, PeopleChanged
from core.di import Container
from core.interfaces import SettingsStoreProto


class FakeSettings:
    def __init__(self):
        self.data = {}
    def get(self, *keys, default=None):
        d = self.data
        for k in keys: d = d.get(k, default) if isinstance(d, dict) else default
        return d if d is not None else default
    def set(self, section, value, save=True): self.data[section] = value
    def section(self, name): return self.data.get(name, {})


class TestCoreIntegration(unittest.TestCase):
    def test_container_injects_event_bus_and_result_factory(self):
        c = Container()
        bus = EventBus()
        c.register_value("bus", bus)
        c.register("result_ok", lambda ct: ok(42))
        got_bus = c.get("bus")
        got_result = c.get("result_ok")
        self.assertIs(got_bus, bus)
        self.assertEqual(got_result.unwrap(), 42)

    def test_event_bus_emits_result_payload(self):
        bus = EventBus()
        got = []
        bus.subscribe(PeopleChanged, lambda e: got.append(e))
        result = ok("payload")
        # Emit an event that carries result data
        evt = PeopleChanged(reason=str(result.unwrap()))
        bus.emit(evt)
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0].reason, "payload")

    def test_di_cycle_detected_integration(self):
        c = Container()
        c.register("a", lambda ct: ct.get("b"))
        c.register("b", lambda ct: ct.get("a"))
        with self.assertRaises(ValueError) as ctx:
            c.get("a")
        self.assertIn("dependency cycle", str(ctx.exception))

    def test_protocol_fake_injected_via_container(self):
        c = Container()
        fake = FakeSettings()
        c.register_value("settings", fake)
        self.assertTrue(isinstance(c.get("settings"), SettingsStoreProto))
        c.get("settings").set("chrome", {"port": 9999})
        self.assertEqual(c.get("settings").get("chrome", "port"), 9999)

    def test_result_ok_and_err_cross_layer(self):
        # Domain error (Err) does not cross exception boundary; container can hold it
        c = Container()
        c.register_value("err", err("preset_not_found", "missing"))
        r = c.get("err")
        self.assertTrue(r.is_err)
        self.assertEqual(r.unwrap_or("default"), "default")


if __name__ == "__main__":
    unittest.main(verbosity=2)
