"""UndoBridge wire contract: the one global timeline, aliases, signals.

Proves the B3 matrix rows for Undo input, Undo/redo output and Undo
signals/state, using the real UndoService against a real ConfigManager.
"""

from __future__ import annotations

import json

from bridge.undo_bridge import UndoBridge
from bridge.context import BridgeContext
from core.events import (LogMessage, PeopleChanged, UndoHistoryChanged)
from services.layout_service import LayoutService

from tests.unit.bridge_safety.helpers import LogCapture


def make_ctx(tmp_path):
    from backend.config_manager import ConfigManager
    cfg = ConfigManager(str(tmp_path / "config.json"))
    ctx = BridgeContext(config=cfg)
    return ctx, cfg


def collect(ctx, *event_types):
    seen = []
    for event_type in event_types:
        ctx.bus.subscribe(event_type, lambda e: seen.append(e))
    return seen


def stack_history(bridge):
    return json.loads(bridge.get_undo_history())


class TestUndoInput:
    def test_push_stack_accepts_list_and_persists_canonically(self, tmp_path):
        ctx, cfg = make_ctx(tmp_path)
        bridge = UndoBridge(ctx)
        history_events = collect(ctx, UndoHistoryChanged)
        people_events = collect(ctx, PeopleChanged)
        assert bridge.push_global_history(
            "stack", '[{"block_id":"PAUSE","use_panel_filters":1}]') is True
        # canonical payload: retired keys stripped, enabled defaulted
        hist = stack_history(bridge)
        assert hist["index"] == 0
        assert hist["history"][0]["value"] == [
            {"block_id": "PAUSE", "enabled": True}]
        # the session snapshot records the committed stack; the timeline
        # holds the canonical payload
        assert cfg.get_state("last_stack")[0]["block_id"] == "PAUSE"
        assert cfg.get_state("last_stack_preset") == ""
        assert [e.reason for e in people_events] == ["stack"]
        assert len(history_events) == 1

    def test_push_stack_rejects_bad_json_and_wrong_type(self, tmp_path):
        ctx, cfg = make_ctx(tmp_path)
        bridge = UndoBridge(ctx)
        assert bridge.push_global_history("stack", "{oops") is False
        assert bridge.push_global_history("stack", '{"not":"list"}') is False
        assert bridge.push_global_history("stack", '"str"') is False
        assert stack_history(bridge)["index"] == -1
        assert cfg.get_state("last_stack") is None

    def test_push_grid_accepts_valid_and_rejects_invalid(self, tmp_path):
        ctx, cfg = make_ctx(tmp_path)
        bridge = UndoBridge(ctx)
        valid = LayoutService.default_payload()
        assert bridge.push_global_history("grid", valid) is True
        stored = json.loads(cfg.get_state("grid_layout"))
        assert stored["v"] == LayoutService.GRID_VERSION
        # a rejected payload leaves the stored layout untouched
        assert bridge.push_global_history("grid", "{oops") is False
        assert json.loads(cfg.get_state("grid_layout"))["v"] == \
            LayoutService.GRID_VERSION
        assert bridge.push_global_history(
            "grid", json.dumps({"v": 99, "tree": None})) is False

    def test_unknown_kind_is_rejected_without_mutation(self, tmp_path):
        ctx, cfg = make_ctx(tmp_path)
        bridge = UndoBridge(ctx)
        assert bridge.push_global_history("bogus", "{}") is False
        assert bridge.push_global_history("people", "{}") is False
        assert stack_history(bridge)["index"] == -1
        assert cfg.get_state("last_stack") is None
        assert cfg.get_state("grid_layout") is None


class TestUndoRedoOutput:
    def test_empty_timeline_returns_null_and_logs(self, tmp_path):
        ctx, _cfg = make_ctx(tmp_path)
        bridge = UndoBridge(ctx)
        logs = LogCapture(ctx.bus)
        assert bridge.undo() == "null"
        assert bridge.redo() == "null"
        assert logs.any("Nothing to undo", level="warn")
        assert logs.any("Nothing to redo", level="warn")

    def test_undo_redo_walk_the_stack_snapshots(self, tmp_path):
        ctx, cfg = make_ctx(tmp_path)
        bridge = UndoBridge(ctx)
        a = [{"block_id": "PAUSE"}]
        b = [{"block_id": "PAUSE"}, {"block_id": "WAIT_PAGE_LOAD"}]
        assert bridge.push_global_history("stack", json.dumps(a)) is True
        assert bridge.push_global_history("stack", json.dumps(b)) is True

        undone = json.loads(bridge.undo())
        assert undone["kind"] == "stack"
        assert undone["value"] == [{"block_id": "PAUSE", "enabled": True}]
        assert cfg.get_state("last_stack") == [
            {"block_id": "PAUSE", "enabled": True}]

        redone = json.loads(bridge.redo())
        assert redone["value"] == [{"block_id": "PAUSE", "enabled": True},
                                   {"block_id": "WAIT_PAGE_LOAD",
                                    "enabled": True}]
        assert cfg.get_state("last_stack") == redone["value"]

    @staticmethod
    def _grid_payload(sizes):
        """A distinct, valid current-version grid with the given people/log
        split — so two pushes never deduplicate into one entry."""
        import copy
        tree = copy.deepcopy(LayoutService.default_grid_tree())
        tree["children"][2]["sizes"] = list(sizes)
        return json.dumps({"v": LayoutService.GRID_VERSION, "tree": tree})

    def test_legacy_stack_alias_uses_the_global_timeline_once(self, tmp_path):
        ctx, cfg = make_ctx(tmp_path)
        bridge = UndoBridge(ctx)
        a = [{"block_id": "PAUSE"}]
        b = [{"block_id": "PAUSE"}, {"block_id": "CLICK_SEND"}]
        bridge.push_global_history("stack", json.dumps(a))
        bridge.push_global_history("stack", json.dumps(b))

        before = stack_history(bridge)["index"]
        value = bridge.undo_stack()
        after = stack_history(bridge)["index"]
        assert json.loads(value) == [{"block_id": "PAUSE", "enabled": True}]
        assert after == before - 1          # one global step, not a new list
        assert json.loads(bridge.redo_stack()) == [
            {"block_id": "PAUSE", "enabled": True},
            {"block_id": "CLICK_SEND", "enabled": True}]

    def test_legacy_alias_returns_null_for_non_stack_entry(self, tmp_path):
        ctx, _cfg = make_ctx(tmp_path)
        bridge = UndoBridge(ctx)
        # two distinct grid entries: walking one back applies a grid entry,
        # which the stack alias cannot project → "null", timeline still moved
        bridge.push_global_history("grid", self._grid_payload([70, 30]))
        bridge.push_global_history("grid", self._grid_payload([30, 70]))
        before = stack_history(bridge)["index"]
        assert bridge.undo_stack() == "null"
        assert stack_history(bridge)["index"] == before - 1

    def test_legacy_grid_alias_renders_legacy_payload(self, tmp_path):
        ctx, _cfg = make_ctx(tmp_path)
        bridge = UndoBridge(ctx)
        bridge.push_global_history("grid", self._grid_payload([70, 30]))
        bridge.push_global_history("grid", self._grid_payload([30, 70]))
        result = bridge.undo_grid_layout()
        assert json.loads(result)["v"] == LayoutService.GRID_VERSION
        # nothing before the first entry → null
        assert bridge.undo_grid_layout() == "null"

    def test_legacy_grid_alias_redo_renders_legacy_payload(self, tmp_path):
        ctx, _cfg = make_ctx(tmp_path)
        bridge = UndoBridge(ctx)
        bridge.push_global_history("grid", self._grid_payload([70, 30]))
        bridge.push_global_history("grid", self._grid_payload([30, 70]))
        bridge.undo_grid_layout()   # back to the first grid entry
        result = bridge.redo_grid_layout()
        assert json.loads(result)["v"] == LayoutService.GRID_VERSION


class TestUndoSignalsAndState:
    def test_history_changed_signal_fires_on_push(self, tmp_path):
        ctx, _cfg = make_ctx(tmp_path)
        bridge = UndoBridge(ctx)
        fired = []
        bridge.history_changed.connect(lambda: fired.append(1))
        bridge.push_global_history("stack", '[{"block_id":"PAUSE"}]')
        assert fired == [1]

    def test_people_changed_only_for_stack_pushes(self, tmp_path):
        ctx, _cfg = make_ctx(tmp_path)
        bridge = UndoBridge(ctx)
        people = collect(ctx, PeopleChanged)
        bridge.push_global_history("grid", LayoutService.default_payload())
        bridge.push_global_history("stack", '[{"block_id":"PAUSE"}]')
        bridge.push_global_history("grid", LayoutService.default_payload())
        assert [e.reason for e in people] == ["stack"]


class TestLegacyStackHistorySlots:
    def test_stack_history_projection_and_bulk_save_round_trip(self, tmp_path):
        ctx, cfg = make_ctx(tmp_path)
        bridge = UndoBridge(ctx)
        bridge.push_global_history("stack", '[{"block_id":"PAUSE"}]')
        bridge.push_global_history("stack",
                                   '[{"block_id":"PAUSE"},{"block_id":"CLICK_SEND"}]')
        hist, index = json.loads(bridge.get_stack_history()).values()
        assert index == 1
        assert len(hist) == 2

        # bulk save replaces the projection
        bridge.save_stack_history(json.dumps(hist), 0)
        assert json.loads(bridge.get_stack_history())["index"] == 0
        # bulk save never rewrites the session stack snapshot
        assert cfg.get_state("last_stack") == [
            {"block_id": "PAUSE"}, {"block_id": "CLICK_SEND"}]

    def test_push_stack_history_ignores_bad_input(self, tmp_path):
        ctx, _cfg = make_ctx(tmp_path)
        bridge = UndoBridge(ctx)
        bridge.push_stack_history("{oops")
        bridge.push_stack_history('"not a list"')
        assert json.loads(bridge.get_stack_history())["history"] == []

    def test_push_stack_history_accepts_valid_stack(self, tmp_path):
        ctx, _cfg = make_ctx(tmp_path)
        bridge = UndoBridge(ctx)
        bridge.push_stack_history('[{"block_id":"PAUSE"}]')
        hist = json.loads(bridge.get_stack_history())
        assert hist["history"] == [[{"block_id": "PAUSE", "enabled": True}]]

    def test_save_stack_history_guards(self, tmp_path):
        from backend.config_manager import MAX_STACK_HISTORY
        ctx, _cfg = make_ctx(tmp_path)
        bridge = UndoBridge(ctx)

        bridge.save_stack_history("{bad", 0)          # JSON error → no-op
        assert json.loads(bridge.get_stack_history())["history"] == []
        bridge.save_stack_history('"not a list"', 0)  # wrong type → no-op
        assert json.loads(bridge.get_stack_history())["history"] == []

        # non-int index is coerced to -1
        bridge.save_stack_history(
            json.dumps([[{"block_id": "PAUSE"}]]), "not-an-int")
        assert json.loads(bridge.get_stack_history())["index"] == -1

        # overflow is truncated to MAX_STACK_HISTORY and index clamped
        many = [[{"block_id": "PAUSE"}] for _ in
                range(MAX_STACK_HISTORY + 1)]
        bridge.save_stack_history(json.dumps(many), MAX_STACK_HISTORY + 1)
        saved = json.loads(bridge.get_stack_history())
        assert len(saved["history"]) == MAX_STACK_HISTORY
        assert saved["index"] == MAX_STACK_HISTORY - 1


class TestUndoServiceErr:
    def test_push_rejection_on_service_error_does_not_mutate(self, tmp_path):
        import unittest.mock as mock
        from core.result import Err
        from services.undo_service import UndoService
        ctx, cfg = make_ctx(tmp_path)
        bridge = UndoBridge(ctx)
        with mock.patch.object(UndoService, "push",
                               return_value=Err("save failed", "disk")):
            assert bridge.push_global_history(
                "stack", '[{"block_id":"PAUSE"}]') is False
        # rejection prevented any timeline/config mutation
        assert stack_history(bridge)["index"] == -1
        assert cfg.get_state("last_stack") is None


class TestAliasDefensiveGuards:
    """The legacy aliases must survive a broken undo/redo result."""

    def _patched(self, bridge, method, value):
        import unittest.mock as mock
        return mock.patch.object(bridge, method, return_value=value)

    def test_stack_aliases_return_null_on_malformed_result(self, tmp_path):
        ctx, _cfg = make_ctx(tmp_path)
        bridge = UndoBridge(ctx)
        with self._patched(bridge, "undo", "not json"):
            assert bridge.undo_stack() == "null"
        with self._patched(bridge, "redo", "not json"):
            assert bridge.redo_stack() == "null"
        # a dict result without a "value" key raises KeyError inside the alias
        with self._patched(bridge, "undo", json.dumps({"kind": "stack"})):
            assert bridge.undo_stack() == "null"
        with self._patched(bridge, "redo", json.dumps({"kind": "stack"})):
            assert bridge.redo_stack() == "null"

    def test_grid_aliases_return_null_on_malformed_result(self, tmp_path):
        ctx, _cfg = make_ctx(tmp_path)
        bridge = UndoBridge(ctx)
        with self._patched(bridge, "undo", 42):   # TypeError from json.loads
            assert bridge.undo_grid_layout() == "null"
        with self._patched(bridge, "redo", 42):
            assert bridge.redo_grid_layout() == "null"
