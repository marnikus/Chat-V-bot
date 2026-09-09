"""Tests for the Router: the JS wire API parity and legacy compatibility.

The Router is the single QWebChannel object; if a slot or signal name is
missing (or its signature changed), the corresponding JS feature dies
silently. These tests pin the contract.

Run:  python -m pytest tests/test_bridge_router.py
"""

import os
import sys
import tempfile
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QMetaMethod, QObject

from backend.bridge import Bridge
from backend.config_manager import ConfigManager
from bridge.router import BRIDGE_CLASSES, BRIDGE_SPECS
from bridge.people_bridge import PeopleBridge
from bridge.layout_bridge import LayoutBridge
from services.undo_service import UndoService


class TestWireParity(unittest.TestCase):
    def _members(self, instance):
        mo = instance.metaObject()
        names = {}
        for i in range(mo.methodOffset(), mo.methodCount()):
            m = mo.method(i)
            name = bytes(m.name()).decode()
            names[name] = m.methodType()
        return names

    def test_every_domain_signal_is_published(self):
        inst = Bridge.__new__(Bridge)
        QObject.__init__(inst)
        published = self._members(inst)
        for cls in BRIDGE_CLASSES:
            signals, _slots = BRIDGE_SPECS[cls.__name__]
            for name, _types in signals:
                self.assertIn(name, published,
                              f"{cls.__name__}.{name} missing on Router")
                self.assertEqual(
                    published[name], QMetaMethod.MethodType.Signal,
                    f"{name} must be a Signal on the Router")

    def test_every_domain_slot_is_published(self):
        inst = Bridge.__new__(Bridge)
        QObject.__init__(inst)
        published = self._members(inst)
        for cls in BRIDGE_CLASSES:
            _signals, slots = BRIDGE_SPECS[cls.__name__]
            for name, _types, _ret in slots:
                self.assertIn(name, published,
                              f"{cls.__name__}.{name} missing on Router")
                self.assertEqual(
                    published[name], QMetaMethod.MethodType.Slot,
                    f"{name} must be a Slot on the Router")

    def test_log_message_signal_exists(self):
        inst = Bridge.__new__(Bridge)
        QObject.__init__(inst)
        published = self._members(inst)
        self.assertEqual(published["log_message"],
                         QMetaMethod.MethodType.Signal)

    def test_slot_forwards_to_the_domain_bridge(self):
        cfg = ConfigManager(os.path.join(tempfile.mkdtemp(), "config.json"))
        engine = types.SimpleNamespace(
            get_stack=lambda: [{"block_id": "PAUSE"}])
        br = Bridge(config=cfg, engine=engine)
        # get_stack_json forwards to StackBridge through the router
        payload = br.get_stack_json()
        self.assertEqual(payload, '[{"block_id": "PAUSE"}]')

    def test_signal_re_emission_reaches_router(self):
        cfg = ConfigManager(os.path.join(tempfile.mkdtemp(), "config.json"))
        br = Bridge(config=cfg)
        pb = br._bridge(PeopleBridge)
        got = []
        br.users_updated.connect(lambda v: got.append(v))
        pb.users_updated.emit("hello")
        self.assertEqual(got, ["hello"])

    def test_subclassing_the_router_still_works(self):
        class FakeBridge(Bridge):
            """Bridge with a throwaway config."""

        cfg = ConfigManager(os.path.join(tempfile.mkdtemp(), "config.json"))
        br = FakeBridge.__new__(FakeBridge)
        QObject.__init__(br)
        br._config = cfg
        br._engine = types.SimpleNamespace(load_stack=lambda _b: None)
        self.assertIsInstance(br, QObject)


class TestLegacyAttributeSurface(unittest.TestCase):
    def test_attribute_injection_flows_into_the_context(self):
        br = Bridge.__new__(Bridge)
        QObject.__init__(br)
        cfg = ConfigManager(os.path.join(tempfile.mkdtemp(), "config.json"))
        engine = types.SimpleNamespace(load_stack=lambda _b: None)
        br._config = cfg
        br._engine = engine
        br._memory = None
        br._presets = None
        self.assertIs(br._config, cfg)
        self.assertIs(br._ctx.config, cfg)
        self.assertIs(br._ctx.engine, engine)

    def test_grid_spec_constants_and_classmethods(self):
        self.assertEqual(Bridge.GRID_VERSION, 3)
        self.assertEqual(Bridge.MIN_GRID_SIZE, 4)
        self.assertEqual(sorted(Bridge.WINDOW_IDS),
                         sorted(Bridge._leaf_ids(Bridge._default_grid_tree())))
        self.assertIsNone(
            Bridge._validate_grid_tree(Bridge._default_grid_tree()))
        self.assertEqual(
            sorted(LayoutService_window_ids := LayoutBridge.WINDOW_IDS),
            sorted(Bridge.WINDOW_IDS))

    def test_undo_constants(self):
        self.assertEqual(UndoService.COMMAND_KINDS,
                         ("people", "labels", "archive", "dbconn"))
        self.assertEqual(Bridge.COMMAND_KINDS, UndoService.COMMAND_KINDS)
        self.assertEqual(Bridge.HISTORY_KINDS,
                         ("stack", "grid", "people", "labels", "archive",
                          "dbconn"))


if __name__ == "__main__":
    unittest.main()
