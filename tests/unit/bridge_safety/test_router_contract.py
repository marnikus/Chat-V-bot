"""Router contract: real Router delegation, lazy domain creation, context
rebinding, and Qt slot-name/arity stability.

Validated through the generated actual Router (bridge.router.Router) and
its Qt metaobject — a fake of the Router proves nothing (B2).
"""

from __future__ import annotations

import types

import pytest
from PySide6.QtCore import QMetaMethod, QObject, Signal, Slot

from backend.bridge import Bridge
from bridge.cdp_bridge import CdpBridge
from bridge.context import BridgeContext
from bridge.stack_bridge import StackBridge
from bridge.undo_bridge import UndoBridge

from tests.unit.bridge_safety.helpers import (FakeCdpService, FakeEngine,
                                              drain, run)


def make_bridge(tmp_path, engine=None):
    from backend.config_manager import ConfigManager
    cfg = ConfigManager(str(tmp_path / "config.json"))
    return Bridge(config=cfg, engine=engine), cfg


class TestDelegation:
    def test_run_stack_delegates_to_stack_bridge(self, tmp_path):
        engine = FakeEngine()
        bridge, cfg = make_bridge(tmp_path, engine=engine)

        async def scenario():
            bridge.run_stack('[{"block_id":"PAUSE"}]')
            await drain()

        run(scenario)
        assert engine.loaded == [{"block_id": "PAUSE", "enabled": True}]
        assert engine.executions == 1
        assert cfg.get_state("last_stack") == [
            {"block_id": "PAUSE", "enabled": True}]

    def test_stop_pause_resume_delegate_to_engine(self, tmp_path):
        engine = FakeEngine()
        bridge, _cfg = make_bridge(tmp_path, engine=engine)
        bridge.stop_stack()
        bridge.pause_stack()
        bridge.resume_stack()
        assert (engine.stop_calls, engine.pause_calls, engine.resume_calls) \
            == (1, 1, 1)

    def test_undo_delegates_to_undo_bridge(self, tmp_path):
        bridge, _cfg = make_bridge(tmp_path)
        assert bridge.undo() == "null"      # empty timeline → null

    def test_get_tabs_delegates_and_returns_pending(self, tmp_path):
        bridge, _cfg = make_bridge(tmp_path)
        service = FakeCdpService()
        bridge._ctx._cdp_svc = service

        async def scenario():
            assert bridge.get_tabs() == "pending"
            await drain()

        run(scenario)
        assert service.fetch_calls == 1


class TestDomainBridgesAndContext:
    def test_domain_bridge_is_built_once_and_shared(self, tmp_path):
        bridge, _cfg = make_bridge(tmp_path)
        assert bridge._bridge(StackBridge) is bridge._bridge(StackBridge)
        assert isinstance(bridge._bridge(CdpBridge), CdpBridge)
        assert isinstance(bridge._bridge(UndoBridge), UndoBridge)

    def test_domain_bridges_share_one_context(self, tmp_path):
        bridge, _cfg = make_bridge(tmp_path)
        assert bridge._bridge(StackBridge).ctx is bridge._ctx
        assert bridge._bridge(UndoBridge).ctx is bridge._ctx

    def test_context_rebinding_flows_to_existing_bridges(self, tmp_path):
        engine1 = FakeEngine()
        engine2 = FakeEngine()
        bridge, _cfg = make_bridge(tmp_path, engine=engine1)
        stack = bridge._bridge(StackBridge)
        assert stack.ctx.engine is engine1
        bridge._engine = engine2
        assert bridge._engine is engine2
        assert stack.ctx.engine is engine2


class TestQtMetaobjectContract:
    def _members(self, instance):
        mo = instance.metaObject()
        members = {}
        for i in range(mo.methodOffset(), mo.methodCount()):
            m = mo.method(i)
            members[bytes(m.name()).decode()] = m
        return members

    def test_representative_slots_have_stable_names_and_arity(self,
                                                              tmp_path):
        bridge, _cfg = make_bridge(tmp_path)
        members = self._members(bridge)
        for name in ("run_stack", "stop_stack", "pause_stack", "resume_stack",
                     "undo", "redo", "get_tabs", "connect_tab",
                     "find_tab_by_url"):
            assert name in members, f"{name} missing from Router"
            assert members[name].methodType() == QMetaMethod.MethodType.Slot
        assert members["run_stack"].parameterCount() == 1
        assert members["connect_tab"].parameterCount() == 1
        assert members["undo"].parameterCount() == 0
        assert members["get_tabs"].parameterCount() == 0

    def test_router_signals_are_stable_qobject_signals(self, tmp_path):
        bridge, _cfg = make_bridge(tmp_path)
        members = self._members(bridge)
        for name in ("tabs_received", "connection_status",
                     "tab_match_result", "stack_loaded", "step_complete",
                     "history_changed"):
            assert name in members, f"{name} missing from Router"
            assert members[name].methodType() == QMetaMethod.MethodType.Signal


class TestHandAssembledRouter:
    def test_new_assembled_router_lazily_builds_context_and_bridges(
            self, tmp_path):
        from backend.config_manager import ConfigManager
        cfg = ConfigManager(str(tmp_path / "config.json"))
        br = Bridge.__new__(Bridge)
        QObject.__init__(br)
        br._config = cfg
        br._engine = types.SimpleNamespace(
            load_stack=lambda _b: None, is_running=False)
        # first touch builds the context + the bridge table on demand
        ctx, bridges = br._ensure_ctx()
        assert isinstance(ctx, BridgeContext)
        assert bridges == {}
        stack = br._bridge(StackBridge)
        assert stack.ctx.engine is br._engine
        assert br._bridge(StackBridge) is stack


class TestLegacyCompatSurface:
    """The Router's hand-written legacy helpers still delegate correctly."""

    def test_legacy_stack_history_helpers(self, tmp_path):
        bridge, _cfg = make_bridge(tmp_path)
        bridge._push_history([{"block_id": "PAUSE"}])
        hist, idx = bridge._get_history()
        assert hist == [[{"block_id": "PAUSE", "enabled": True}]]
        assert idx == 0
        bridge._set_history([], 0)
        assert bridge._get_history()[0] == []

    def test_legacy_kind_projection_helpers(self, tmp_path):
        bridge, _cfg = make_bridge(tmp_path)
        projection, index = bridge._push_hist("stack",
                                              [{"block_id": "PAUSE"}])
        assert projection == [[{"block_id": "PAUSE", "enabled": True}]]
        assert index == 0
        assert bridge._get_hist("stack")[0] == [
            [{"block_id": "PAUSE", "enabled": True}]]
        bridge._set_hist("stack", [[{"block_id": "CLICK_SEND"}]], 0)
        assert bridge._get_hist("stack")[0] == [
            [{"block_id": "CLICK_SEND", "enabled": True}]]

    def test_legacy_global_history_helpers(self, tmp_path):
        bridge, _cfg = make_bridge(tmp_path)
        bridge._set_global_history([], -1)
        assert bridge._get_global_history() == ([], -1)

    def test_legacy_non_stack_kind_projection_helpers(self, tmp_path):
        bridge, _cfg = make_bridge(tmp_path)
        projection, index = bridge._push_hist("grid", {"cells": [[1]]})
        assert projection == [{"cells": [[1]]}]
        assert index == 0
        bridge._set_hist("grid", [{"cells": [[2]]}], 0)
        proj, idx = bridge._get_hist("grid")
        assert proj == [{"cells": [[2]]}]
        assert idx == 0

    def test_people_rows_delegates_to_people_service(self, tmp_path):
        bridge, _cfg = make_bridge(tmp_path)

        class FakeMemory:
            async def get_all(self):
                return []

        bridge._memory = FakeMemory()   # write-through rebinds people svc

        async def scenario():
            assert await bridge._people_rows() == []

        run(scenario)

    def test_people_entry_push(self, tmp_path):
        bridge, _cfg = make_bridge(tmp_path)
        assert bridge._push_people_entry([], []) is False   # no-op
        assert bridge._push_people_entry([], [{"nick": "x"}]) is True

    def test_attach_history_none_is_a_noop(self, tmp_path):
        bridge, _cfg = make_bridge(tmp_path)
        bridge.attach_history(None)   # must not raise

    def test_db_manager_property_with_and_without_archive(self, tmp_path):
        bridge, _cfg = make_bridge(tmp_path)
        assert bridge.db_manager is not None
        bridge._ctx.archive = object()   # attach() just stores the service
        assert bridge.db_manager.service is bridge._ctx.archive

    def test_sync_world_state_runs(self, tmp_path):
        bridge, _cfg = make_bridge(tmp_path)

        async def scenario():
            await bridge.sync_world_state()

        run(scenario)

    def test_refresh_users_is_a_safe_noop_without_memory(self, tmp_path):
        bridge, _cfg = make_bridge(tmp_path)

        async def scenario():
            await bridge._refresh_users()

        run(scenario)

    def test_undo_pendings_compat_property(self, tmp_path):
        bridge, _cfg = make_bridge(tmp_path)
        assert isinstance(bridge._undo_pendings, list)


class TestRouterBuildGuards:
    def test_router_method_named_decorator(self):
        from bridge.router import _ROUTER_METHODS, _router_method

        @_router_method("custom_helper")   # explicit-name spelling
        def helper(self):
            return 42

        assert _ROUTER_METHODS["custom_helper"] is helper

    def test_preset_import_failure_is_swallowed(self, tmp_path):
        from backend.config_manager import ConfigManager

        class BoomPresets:
            def import_legacy(self):
                raise RuntimeError("no sqlite")

        cfg = ConfigManager(str(tmp_path / "config.json"))
        br = Bridge(config=cfg, presets=BoomPresets())   # must not raise
        assert isinstance(br, Bridge)

    def test_constructor_without_config_or_presets(self):
        from bridge.router import Router
        br = Router()   # presets stays None → legacy import skipped
        assert isinstance(br, Router)

    def test_build_rejects_duplicate_signal_names(self, monkeypatch):
        import bridge.router as router_mod

        class DupSignalA(QObject):
            shared = Signal()

            def __init__(self, _ctx):
                super().__init__()

        class DupSignalB(QObject):
            shared = Signal()

            def __init__(self, _ctx):
                super().__init__()

        monkeypatch.setattr(router_mod, "BRIDGE_SPECS", {})
        monkeypatch.setattr(router_mod, "BRIDGE_CLASSES",
                            [DupSignalA, DupSignalB])
        with pytest.raises(ValueError, match="defined by both"):
            router_mod._build_router_class()

    def test_build_rejects_duplicate_slot_names(self, monkeypatch):
        import bridge.router as router_mod

        class DupSlotA(QObject):
            def __init__(self, _ctx):
                super().__init__()

            @Slot()
            def shared_slot(self):
                return None

        class DupSlotB(QObject):
            def __init__(self, _ctx):
                super().__init__()

            @Slot()
            def shared_slot(self):
                return None

        monkeypatch.setattr(router_mod, "BRIDGE_SPECS", {})
        monkeypatch.setattr(router_mod, "BRIDGE_CLASSES",
                            [DupSlotA, DupSlotB])
        with pytest.raises(ValueError, match="defined by both"):
            router_mod._build_router_class()


class TestAttachHistoryWiring:
    """attach_history wires the archive service through the whole stack."""

    def test_attach_history_wires_engine_and_label_store(self, tmp_path):
        engine = FakeEngine()
        bridge, _cfg = make_bridge(tmp_path, engine=engine)

        class FakeArchive:
            def __init__(self):
                self.bound_store = None

            def bind_labels(self, store):
                self.bound_store = store

        service = FakeArchive()
        bridge.attach_history(service)
        assert engine.history is service
        assert service.bound_store is not None
        assert bridge._ctx.archive is service

    def test_attach_history_bind_labels_failure_is_logged(self, tmp_path,
                                                          caplog):
        bridge, _cfg = make_bridge(tmp_path)   # engine=None

        class BoomArchive:
            def bind_labels(self, store):
                raise RuntimeError("no binding")

        with caplog.at_level("WARNING", logger="chatbot"):
            bridge.attach_history(BoomArchive())   # must not raise
        assert any("label store not bound" in r.message
                   for r in caplog.records)

    def test_attach_history_readonly_engine_history_is_ignored(self,
                                                               tmp_path):
        class ReadonlyHistoryEngine(FakeEngine):
            @property
            def history(self):
                return None

            @history.setter
            def history(self, value):
                raise RuntimeError("readonly")

        class FakeArchive:
            def bind_labels(self, store):
                pass

        bridge, _cfg = make_bridge(tmp_path,
                                   engine=ReadonlyHistoryEngine())
        bridge.attach_history(FakeArchive())   # must not raise

    def test_attach_history_attaches_active_db_manager(self, tmp_path):
        bridge, _cfg = make_bridge(tmp_path)
        manager = bridge.db_manager   # force ctx.dbs to be built

        class FakeArchive:
            def bind_labels(self, store):
                pass

        service = FakeArchive()
        bridge.attach_history(service)
        assert manager.service is service

    def test_init_with_cdp_builds_cdp_service(self, tmp_path):
        from backend.config_manager import ConfigManager

        class FakeClient(QObject):
            connected = Signal()
            disconnected = Signal()
            error = Signal(str)

        cfg = ConfigManager(str(tmp_path / "config.json"))
        br = Bridge(config=cfg, cdp=FakeClient())
        assert br._ctx._cdp_svc is not None
