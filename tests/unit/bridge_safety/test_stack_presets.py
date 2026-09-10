"""StackBridge preset surfaces: stack presets, templates, custom blocks.

Proves the B3 matrix row for Stack/template/custom presets: real round
trips through PresetStore / BlockStore, expected notifications, and no
false success or overwrite on failed operations.
"""

from __future__ import annotations

import json
from unittest import mock

from bridge.stack_bridge import StackBridge
from bridge.context import BridgeContext
from core.events import PresetsChanged
from stores.preset_store import PresetStore

from tests.unit.bridge_safety.helpers import FakeEngine, LogCapture


def make_ctx(tmp_path, engine=None):
    from backend.config_manager import ConfigManager
    cfg = ConfigManager(str(tmp_path / "config.json"))
    ctx = BridgeContext(config=cfg, engine=engine,
                        presets=PresetStore(config=cfg))
    return ctx, cfg


def collect(ctx, *event_types):
    seen = []
    for event_type in event_types:
        ctx.bus.subscribe(event_type, lambda e: seen.append(e))
    return seen


class TestStackPresets:
    def test_save_list_load_delete_round_trip(self, tmp_path):
        engine = FakeEngine()
        ctx, cfg = make_ctx(tmp_path, engine=engine)
        bridge = StackBridge(ctx)
        logs = LogCapture(ctx.bus)
        emitted = []
        bridge.preset_list_updated.connect(emitted.append)

        bridge.save_stack_preset("morning", '[{"block_id":"PAUSE"}]')
        assert logs.any("saved", level="success")
        assert emitted and json.loads(emitted[-1])[0]["name"] == "morning"

        assert json.loads(bridge.list_stack_presets())[0]["name"] == "morning"
        payload = bridge.load_stack_preset("morning")
        assert json.loads(payload) == [{"block_id": "PAUSE",
                                        "enabled": True}]
        assert engine.loaded == [{"block_id": "PAUSE", "enabled": True}]
        assert cfg.get_state("last_stack_preset") == "morning"

        bridge.delete_stack_preset("morning")
        assert bridge.list_stack_presets() == "[]"
        assert logs.any("deleted", level="warn")

    def test_persistence_survives_a_reopen(self, tmp_path):
        from backend.config_manager import ConfigManager
        ctx, cfg = make_ctx(tmp_path)
        bridge = StackBridge(ctx)
        bridge.save_stack_preset("kept", '[{"block_id":"PAUSE"}]')
        reopened = ConfigManager(cfg._path)
        assert reopened.presets.load_stack("kept") == [
            {"block_id": "PAUSE", "enabled": True}]

    def test_empty_name_is_refused_without_overwrite(self, tmp_path):
        ctx, _cfg = make_ctx(tmp_path)
        bridge = StackBridge(ctx)
        logs = LogCapture(ctx.bus)
        bridge.save_stack_preset("   ", '[{"block_id":"PAUSE"}]')
        assert logs.any("Preset name cannot be empty", level="error")
        assert bridge.list_stack_presets() == "[]"

    def test_malformed_and_wrong_shape_payloads_are_refused(self, tmp_path):
        ctx, _cfg = make_ctx(tmp_path)
        bridge = StackBridge(ctx)
        logs = LogCapture(ctx.bus)
        bridge.save_stack_preset("bad", "{oops")
        assert logs.any("not valid JSON", level="error")
        bridge.save_stack_preset("bad2", '{"not": "a list"}')
        assert logs.any("bad stack payload", level="error")
        assert bridge.list_stack_presets() == "[]"

    def test_load_missing_preset_returns_null_and_logs(self, tmp_path):
        ctx, _cfg = make_ctx(tmp_path)
        bridge = StackBridge(ctx)
        logs = LogCapture(ctx.bus)
        assert bridge.load_stack_preset("ghost") == "null"
        assert logs.any("not found", level="error")

    def test_delete_missing_preset_logs_warn_without_emit(self, tmp_path):
        ctx, _cfg = make_ctx(tmp_path)
        bridge = StackBridge(ctx)
        logs = LogCapture(ctx.bus)
        emitted = []
        bridge.preset_list_updated.connect(emitted.append)
        bridge.delete_stack_preset("ghost")
        assert logs.any("not found", level="warn")
        assert emitted == []

    def test_save_emits_presets_changed_bus_event(self, tmp_path):
        ctx, _cfg = make_ctx(tmp_path)
        bridge = StackBridge(ctx)
        events = collect(ctx, PresetsChanged)
        bridge.save_stack_preset("x", '[{"block_id":"PAUSE"}]')
        assert [e.kind for e in events] == ["stacks"]


class TestTemplatePresets:
    def test_save_list_load_delete_round_trip(self, tmp_path):
        ctx, cfg = make_ctx(tmp_path)
        bridge = StackBridge(ctx)
        logs = LogCapture(ctx.bus)
        emitted = []
        bridge.template_list_updated.connect(emitted.append)

        bridge.save_template_preset("greet", "hi {{nick}}")
        assert logs.any("saved", level="success")
        assert emitted
        listed = json.loads(bridge.list_template_presets())
        assert listed[0]["name"] == "greet"
        assert bridge.load_template_preset("greet") == "hi {{nick}}"
        # persisted
        assert cfg.presets.load_template("greet") == "hi {{nick}}"

        bridge.delete_template_preset("greet")
        assert bridge.list_template_presets() == "[]"
        assert logs.any("deleted", level="warn")

    def test_empty_name_is_refused(self, tmp_path):
        ctx, _cfg = make_ctx(tmp_path)
        bridge = StackBridge(ctx)
        logs = LogCapture(ctx.bus)
        bridge.save_template_preset("", "body")
        assert logs.any("Template name cannot be empty", level="error")
        assert bridge.list_template_presets() == "[]"

    def test_load_missing_template_returns_empty_string(self, tmp_path):
        ctx, _cfg = make_ctx(tmp_path)
        bridge = StackBridge(ctx)
        logs = LogCapture(ctx.bus)
        assert bridge.load_template_preset("ghost") == ""
        assert logs.any("not found", level="error")

    def test_delete_missing_template_is_silent_no_false_success(self,
                                                                tmp_path):
        # Characterized (not a boundary defect): a missing template delete
        # emits neither a success log nor a list refresh; it also never
        # overwrites or removes existing data.
        ctx, cfg = make_ctx(tmp_path)
        bridge = StackBridge(ctx)
        bridge.save_template_preset("real", "body")
        logs = LogCapture(ctx.bus)
        emitted = []
        bridge.template_list_updated.connect(emitted.append)
        bridge.delete_template_preset("ghost")
        assert emitted == []
        assert not logs.any("deleted")
        # existing data untouched
        assert cfg.presets.load_template("real") == "body"


class TestCustomBlocks:
    def test_save_list_delete_round_trip(self, tmp_path):
        ctx, cfg = make_ctx(tmp_path)
        bridge = StackBridge(ctx)
        logs = LogCapture(ctx.bus)
        emitted = []
        bridge.custom_blocks_updated.connect(emitted.append)

        bridge.save_custom_block("cb", '{"selector":"#chat"}')
        assert logs.any("saved", level="success")
        assert emitted
        listed = json.loads(bridge.list_custom_blocks())
        assert listed[0]["name"] == "cb"
        assert listed[0]["block"] == {"selector": "#chat"}
        # persisted
        assert cfg.blocks.all()[0]["name"] == "cb"

        bridge.delete_custom_block("cb")
        assert bridge.list_custom_blocks() == "[]"
        assert logs.any("removed", level="warn")

    def test_missing_name_or_bad_json_is_refused(self, tmp_path):
        ctx, _cfg = make_ctx(tmp_path)
        bridge = StackBridge(ctx)
        logs = LogCapture(ctx.bus)
        bridge.save_custom_block("  ", '{"selector":"#x"}')
        assert logs.any("name and block config", level="error")
        bridge.save_custom_block("x", "{bad")
        assert logs.any("bad JSON", level="error")
        bridge.save_custom_block("x", "[1,2]")
        assert logs.any("name and block config", level="error")
        assert bridge.list_custom_blocks() == "[]"

    def test_delete_missing_block_logs_warn(self, tmp_path):
        ctx, _cfg = make_ctx(tmp_path)
        bridge = StackBridge(ctx)
        logs = LogCapture(ctx.bus)
        bridge.delete_custom_block("ghost")
        assert logs.any("not found", level="warn")


class TestPresetErrorHandling:
    """Store-level failures must never surface as a false success."""

    def test_save_preset_reports_store_error(self, tmp_path):
        ctx, _cfg = make_ctx(tmp_path)
        bridge = StackBridge(ctx)
        logs = LogCapture(ctx.bus)
        with mock.patch.object(ctx.presets, "save_stack",
                               side_effect=RuntimeError("disk full")):
            bridge.save_stack_preset("x", '[{"block_id":"PAUSE"}]')
        assert logs.any("Preset save failed", level="error")

    def test_save_preset_flush_error_is_swallowed(self, tmp_path):
        ctx, _cfg = make_ctx(tmp_path)
        bridge = StackBridge(ctx)
        with mock.patch.object(ctx.presets, "save",
                               side_effect=RuntimeError("flush")):
            bridge.save_stack_preset("x", '[{"block_id":"PAUSE"}]')
        # the preset itself still landed; the flush failure is tolerated
        assert ctx.presets.load_stack("x") == [
            {"block_id": "PAUSE", "enabled": True}]

    def test_list_presets_survives_store_error(self, tmp_path):
        ctx, _cfg = make_ctx(tmp_path)
        bridge = StackBridge(ctx)
        with mock.patch.object(ctx.presets, "list_stacks",
                               side_effect=RuntimeError("boom")):
            assert bridge.list_stack_presets() == "[]"

    def test_delete_preset_survives_store_error(self, tmp_path):
        ctx, _cfg = make_ctx(tmp_path)
        bridge = StackBridge(ctx)
        logs = LogCapture(ctx.bus)
        with mock.patch.object(ctx.presets, "delete_stack",
                               side_effect=RuntimeError("boom")):
            bridge.delete_stack_preset("x")
        assert logs.any("Preset delete failed", level="error")

    def test_list_templates_survives_store_error(self, tmp_path):
        ctx, _cfg = make_ctx(tmp_path)
        bridge = StackBridge(ctx)
        with mock.patch.object(ctx.presets, "list_templates",
                               side_effect=RuntimeError("boom")):
            assert bridge.list_template_presets() == "[]"

    def test_delete_template_survives_store_error(self, tmp_path):
        ctx, _cfg = make_ctx(tmp_path)
        bridge = StackBridge(ctx)
        logs = LogCapture(ctx.bus)
        with mock.patch.object(ctx.presets, "delete_template",
                               side_effect=RuntimeError("boom")):
            bridge.delete_template_preset("x")
        assert logs.any("Template delete failed", level="error")

    def test_save_custom_block_reports_store_error(self, tmp_path):
        from core.result import Err
        ctx, _cfg = make_ctx(tmp_path)
        bridge = StackBridge(ctx)
        logs = LogCapture(ctx.bus)
        with mock.patch.object(ctx.config.blocks, "save_custom_block",
                               return_value=Err("save failed", "disk full")):
            bridge.save_custom_block("x", '{"a": 1}')
        assert logs.any("Block preset save failed", level="error")


class TestLoadPreservesHistory:
    def test_load_with_no_current_stack_skips_preserve(self, tmp_path):
        engine = FakeEngine()
        ctx, cfg = make_ctx(tmp_path, engine=engine)
        bridge = StackBridge(ctx)
        bridge.save_stack_preset("one", '[{"block_id":"PAUSE"}]')
        cfg.set_state(last_stack=None)   # nothing to preserve
        payload = bridge.load_stack_preset("one")
        assert json.loads(payload) == [{"block_id": "PAUSE",
                                        "enabled": True}]

    def test_load_preserves_different_current_stack_once(self, tmp_path):
        engine = FakeEngine()
        ctx, cfg = make_ctx(tmp_path, engine=engine)
        bridge = StackBridge(ctx)
        bridge.save_stack_preset("one", '[{"block_id":"PAUSE"}]')
        bridge.save_stack_preset("two",
                                 '[{"block_id":"PAUSE"},{"block_id":"CLICK_SEND"}]')
        svc = ctx.undo
        with mock.patch.object(svc, "push_stack",
                               wraps=svc.push_stack) as patched:
            bridge.load_stack_preset("one")   # differs from current ("two")
        pushed = [list(c.args[0]) for c in patched.call_args_list]
        # first the preserved current stack, then the loaded one
        assert pushed[0] == [{"block_id": "PAUSE", "enabled": True},
                             {"block_id": "CLICK_SEND", "enabled": True}]
        assert pushed[1] == [{"block_id": "PAUSE", "enabled": True}]

    def test_load_equal_current_stack_does_not_duplicate(self, tmp_path):
        engine = FakeEngine()
        ctx, cfg = make_ctx(tmp_path, engine=engine)
        bridge = StackBridge(ctx)
        bridge.save_stack_preset("one", '[{"block_id":"PAUSE"}]')
        svc = ctx.undo
        with mock.patch.object(svc, "push_stack",
                               wraps=svc.push_stack) as patched:
            bridge.load_stack_preset("one")   # equals current
        # only the loaded stack is pushed (the preserve step is skipped)
        assert [list(c.args[0]) for c in patched.call_args_list] == \
            [[{"block_id": "PAUSE", "enabled": True}]]

    def test_load_survives_a_failed_history_preserve(self, tmp_path):
        engine = FakeEngine()
        ctx, cfg = make_ctx(tmp_path, engine=engine)
        bridge = StackBridge(ctx)
        bridge.save_stack_preset("one", '[{"block_id":"PAUSE"}]')
        cfg.set_state(last_stack=[{"block_id": "CLICK_SEND",
                                   "enabled": True}])
        svc = ctx.undo
        real = svc.push_stack
        calls = {"n": 0}

        def flaky_push(blocks):
            calls["n"] += 1
            if calls["n"] == 1:            # the preserve step fails
                raise RuntimeError("undo unavailable")
            return real(blocks)

        with mock.patch.object(svc, "push_stack", side_effect=flaky_push):
            payload = bridge.load_stack_preset("one")   # must not raise
        assert json.loads(payload) == [{"block_id": "PAUSE",
                                        "enabled": True}]
        assert engine.loaded == [{"block_id": "PAUSE", "enabled": True}]
        assert cfg.get_state("last_stack_preset") == "one"
