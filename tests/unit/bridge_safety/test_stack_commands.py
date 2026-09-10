"""StackBridge run control, signal forwarding and scheduling boundaries.

Proves the B3 matrix rows: Stack start, Stop/pause/resume slots, Engine
signal forwarding, and Scheduling. The wrong-shape-JSON cases are the
reproducer for the run_stack boundary fix.
"""

from __future__ import annotations

import asyncio
import inspect
import json
from unittest import mock

import pytest

from bridge.stack_bridge import StackBridge
from bridge.context import BridgeContext
from core.events import (PresetsChanged, StackLoaded, UndoHistoryChanged)
from stores.preset_store import PresetStore

from tests.unit.bridge_safety.helpers import (FakeEngine, LogCapture, drain,
                                              run)


def make_ctx(tmp_path, engine=None):
    from backend.config_manager import ConfigManager
    from backend.criteria_engine import CriteriaEngine
    cfg = ConfigManager(str(tmp_path / "config.json"))
    ctx = BridgeContext(config=cfg, engine=engine,
                        presets=PresetStore(config=cfg),
                        criteria=CriteriaEngine())
    return ctx, cfg


class TestRunStack:
    def test_valid_stack_is_normalized_persisted_and_scheduled_once(self,
                                                                    tmp_path):
        engine = FakeEngine()
        ctx, cfg = make_ctx(tmp_path, engine=engine)
        bridge = StackBridge(ctx)
        logs = LogCapture(ctx.bus)

        async def scenario():
            bridge.run_stack('[{"block_id":"PAUSE"}]')
            assert engine.loaded == [{"block_id": "PAUSE",
                                      "enabled": True}]
            await drain()

        run(scenario)
        assert engine.executions == 1
        assert cfg.get_state("last_stack") == [
            {"block_id": "PAUSE", "enabled": True}]
        assert cfg.get_state("last_stack_preset") == ""
        assert not logs.any("error", level="error")

    def test_retired_and_private_keys_are_stripped(self, tmp_path):
        engine = FakeEngine()
        ctx, _cfg = make_ctx(tmp_path, engine=engine)
        bridge = StackBridge(ctx)

        async def scenario():
            bridge.run_stack(json.dumps([
                {"block_id": "SCROLL_PARSE", "use_panel_filters": True,
                 "_secret": 1, "enabled": False}]))
            await drain()

        run(scenario)
        assert engine.loaded == [{"block_id": "SCROLL_PARSE",
                                  "enabled": False}]

    def test_malformed_json_has_no_execution_or_config_change(self, tmp_path):
        engine = FakeEngine()
        ctx, cfg = make_ctx(tmp_path, engine=engine)
        bridge = StackBridge(ctx)
        logs = LogCapture(ctx.bus)

        async def scenario():
            bridge.run_stack("{not json")
            await drain()

        run(scenario)
        assert engine.loaded is None
        assert engine.executions == 0
        assert cfg.get_state("last_stack") is None
        assert logs.any("Bad JSON", level="error")

    @pytest.mark.parametrize("payload", ['"just a string"', "{}", "42",
                                         "null", "true"])
    def test_wrong_json_shape_has_no_execution_or_config_change(
            self, tmp_path, payload):
        engine = FakeEngine()
        ctx, cfg = make_ctx(tmp_path, engine=engine)
        bridge = StackBridge(ctx)
        logs = LogCapture(ctx.bus)

        async def scenario():
            bridge.run_stack(payload)
            await drain()

        run(scenario)  # must not raise (regression: '42' used to raise)
        assert engine.loaded is None
        assert engine.executions == 0
        assert cfg.get_state("last_stack") is None
        assert logs.any("not a list of blocks", level="error")

    def test_list_of_non_dict_entries_follows_shared_normalization(
            self, tmp_path):
        # A list is the wire type; element filtering is normalize_blocks'
        # frozen job (same as save_stack_preset / snapshot_stack). Non-dict
        # entries normalize away, leaving an empty-but-valid stack.
        engine = FakeEngine()
        ctx, cfg = make_ctx(tmp_path, engine=engine)
        bridge = StackBridge(ctx)

        async def scenario():
            bridge.run_stack("[1, 2, 3]")
            await drain()

        run(scenario)
        assert engine.loaded == []
        assert engine.executions == 1
        assert cfg.get_state("last_stack") == []

    def test_already_running_is_refused_without_side_effects(self, tmp_path):
        engine = FakeEngine()
        engine.is_running = True
        ctx, cfg = make_ctx(tmp_path, engine=engine)
        bridge = StackBridge(ctx)
        logs = LogCapture(ctx.bus)

        async def scenario():
            bridge.run_stack('[{"block_id":"PAUSE"}]')
            await drain()

        run(scenario)
        assert engine.loaded is None
        assert engine.executions == 0
        assert cfg.get_state("last_stack") is None
        assert logs.any("Already running", level="warn")


class TestRunControlSlots:
    def test_stop_pause_resume_call_engine_exactly_once(self, tmp_path):
        engine = FakeEngine()
        ctx, _cfg = make_ctx(tmp_path, engine=engine)
        bridge = StackBridge(ctx)
        bridge.stop_stack()
        bridge.pause_stack()
        bridge.resume_stack()
        assert (engine.stop_calls, engine.pause_calls, engine.resume_calls) \
            == (1, 1, 1)
        # stop must not do anything else — the bridge has no extra work
        assert engine.loaded is None
        assert engine.executions == 0


class TestEngineSignalForwarding:
    def test_run_signals_are_relayed_verbatim(self, tmp_path):
        engine = FakeEngine()
        ctx, _cfg = make_ctx(tmp_path, engine=engine)
        bridge = StackBridge(ctx)
        got = []
        bridge.step_complete.connect(lambda status, nick: got.append(
            ("step_complete", status, nick)))
        bridge.step_started.connect(lambda i, bid, nick: got.append(
            ("step_started", i, bid, nick)))
        bridge.stack_complete.connect(lambda: got.append(("stack_complete",)))

        engine.step_complete.emit("ok", "Nick")
        engine.step_started.emit(2, "PAUSE", "Nick")
        engine.stack_complete.emit()
        assert got == [
            ("step_complete", "ok", "Nick"),
            ("step_started", 2, "PAUSE", "Nick"),
            ("stack_complete",),
        ]

    def test_log_and_debug_messages_reach_the_bus(self, tmp_path):
        engine = FakeEngine()
        ctx, _cfg = make_ctx(tmp_path, engine=engine)
        StackBridge(ctx)
        logs = LogCapture(ctx.bus)
        engine.log_msg.emit("hello log")
        engine.debug_msg.emit("hello debug", "warn")
        assert ("hello log", "info") in logs.messages
        assert ("hello debug", "warn") in logs.messages

    def test_presets_and_stack_loaded_events_are_forwarded(self, tmp_path):
        ctx, _cfg = make_ctx(tmp_path)
        bridge = StackBridge(ctx)
        got = []
        bridge.preset_list_updated.connect(got.append)
        bridge.template_list_updated.connect(lambda p: got.append(
            ("template", p)))
        bridge.custom_blocks_updated.connect(lambda p: got.append(
            ("blocks", p)))
        bridge.stack_loaded.connect(lambda n, p: got.append(
            ("stack_loaded", n, p)))

        ctx.bus.emit(PresetsChanged(kind="stacks", payload='[{"name":"x"}]'))
        ctx.bus.emit(PresetsChanged(kind="templates", payload="[]"))
        ctx.bus.emit(PresetsChanged(kind="custom_blocks", payload="[]"))
        ctx.bus.emit(StackLoaded(name="p", payload='[{"block_id":"PAUSE"}]'))
        # an unknown kind (e.g. urls, owned by CdpBridge) is ignored here
        ctx.bus.emit(PresetsChanged(kind="urls", payload="[]"))
        assert got == [
            '[{"name":"x"}]',
            ("template", "[]"),
            ("blocks", "[]"),
            ("stack_loaded", "p", '[{"block_id":"PAUSE"}]'),
        ]

    def test_duck_typed_engine_without_signals_does_not_crash(self, tmp_path):
        ctx, _cfg = make_ctx(tmp_path, engine=object())
        bridge = StackBridge(ctx)  # must construct cleanly
        assert isinstance(bridge, StackBridge)


class TestMessageCriteriaAndSnapshot:
    def test_composer_round_trip_and_engine_side_effect(self, tmp_path):
        engine = FakeEngine()
        ctx, _cfg = make_ctx(tmp_path, engine=engine)
        bridge = StackBridge(ctx)
        assert bridge.get_message() == ""
        bridge.save_message("hello {{nick}}")
        assert bridge.get_message() == "hello {{nick}}"
        assert engine.composer_text == "hello {{nick}}"

    def test_criteria_round_trip(self, tmp_path):
        ctx, _cfg = make_ctx(tmp_path)
        bridge = StackBridge(ctx)
        payload = '[{"label":"x","enabled":true,"selector":"s",' \
                  '"class_name":"c","check_type":"MUST_HAVE_CLASS"}]'
        logs = LogCapture(ctx.bus)
        bridge.save_criteria(payload)
        assert json.loads(bridge.get_criteria())[0]["label"] == "x"
        assert logs.any("Criteria saved")

    def test_snapshot_persists_cleaned_stack_without_undo_entry(self,
                                                                tmp_path):
        ctx, cfg = make_ctx(tmp_path)
        bridge = StackBridge(ctx)
        undo_events = []
        ctx.bus.subscribe(UndoHistoryChanged, lambda e: undo_events.append(e))
        bridge.snapshot_stack('[{"block_id":"PAUSE","use_panel_filters":1}]')
        assert cfg.get_state("last_stack") == [
            {"block_id": "PAUSE", "enabled": True}]
        assert cfg.get_state("last_stack_preset") == ""
        # snapshot is NOT a timeline edit (App.recordGlobal already recorded)
        assert undo_events == []

    def test_snapshot_ignores_bad_json_and_wrong_shape(self, tmp_path):
        ctx, cfg = make_ctx(tmp_path)
        bridge = StackBridge(ctx)
        bridge.snapshot_stack("{bad json")
        assert cfg.get_state("last_stack") is None
        bridge.snapshot_stack('"not a list"')
        assert cfg.get_state("last_stack") is None

    def test_save_message_survives_a_readonly_composer(self, tmp_path):
        engine = FakeEngine()
        readonly = property(lambda self: "fixed")
        ctx, _cfg = make_ctx(tmp_path, engine=engine)
        bridge = StackBridge(ctx)
        with mock.patch.object(type(engine), "composer_text", readonly,
                               create=True):
            bridge.save_message("hello")   # setter raises AttributeError
        assert bridge.get_message() == "hello"

    def test_get_stack_json_reads_engine(self, tmp_path):
        engine = FakeEngine()
        engine._stack = [{"block_id": "PAUSE"}]
        ctx, _cfg = make_ctx(tmp_path, engine=engine)
        bridge = StackBridge(ctx)
        assert json.loads(bridge.get_stack_json()) == [{"block_id": "PAUSE"}]


class TestScheduling:
    def test_schedule_runs_the_coroutine_when_a_loop_is_running(self):
        ran = []

        async def work():
            ran.append(1)

        async def scenario():
            StackBridge._schedule(work())
            await drain()

        run(scenario)
        assert ran == [1]

    def test_schedule_closes_the_coroutine_when_no_loop_can_take_it(self):
        async def work():
            return 1

        coro = work()
        with mock.patch.object(asyncio, "ensure_future",
                               side_effect=RuntimeError("no running loop")):
            StackBridge._schedule(coro)
        assert inspect.getcoroutinestate(coro) == "CORO_CLOSED"

    def test_scheduled_task_can_be_cancelled_without_leaking(self, tmp_path):
        engine = FakeEngine()
        ctx, _cfg = make_ctx(tmp_path, engine=engine)
        bridge = StackBridge(ctx)
        hold = asyncio.Event()

        async def scenario():
            async def blocked():
                await hold.wait()

            # patch execute to block so the scheduled task stays pending
            with mock.patch.object(engine, "execute", side_effect=blocked):
                bridge.run_stack('[{"block_id":"PAUSE"}]')
                await drain(4)
                tasks = [t for t in asyncio.all_tasks()
                         if t is not asyncio.current_task()]
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
            assert engine.executions == 0  # blocked before marking

        run(scenario)
        # no exception escaped the controlled cancel/drain
