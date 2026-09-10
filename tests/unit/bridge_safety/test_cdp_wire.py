"""CdpBridge wire contract: connect, tab discovery/match, bookmarks,
and scheduling. Proves the B3 matrix rows for CDP connect, Tab
discovery/match, Bookmarks and Scheduling (service raises case).

The thrown-failure case is the reproducer for the `_do_connect` fix:
a raising service used to leave an unhandled task exception and no log.
"""

from __future__ import annotations

import asyncio
import gc
import inspect
import json
from unittest import mock

from bridge.cdp_bridge import CdpBridge
from bridge.context import BridgeContext
from core.events import (ConnectionChanged, LogMessage, PeopleChanged,
                         PresetsChanged, TabMatchResult, TabsReceived)
from core.result import Err, Ok

from tests.unit.bridge_safety.helpers import (FakeCdpService, LogCapture,
                                              drain, run)


def make_ctx(tmp_path, service=None):
    from backend.config_manager import ConfigManager
    cfg = ConfigManager(str(tmp_path / "config.json"))
    ctx = BridgeContext(config=cfg)
    if service is not None:
        ctx._cdp_svc = service
        service.bus = ctx.bus
    return ctx, cfg


def collect(ctx, *event_types):
    seen = []
    for event_type in event_types:
        ctx.bus.subscribe(event_type, lambda e: seen.append(e))
    return seen


class TestTabDiscoveryAndMatch:
    def test_get_tabs_returns_pending_and_schedules_fetch(self, tmp_path):
        service = FakeCdpService()
        ctx, _cfg = make_ctx(tmp_path, service=service)
        bridge = CdpBridge(ctx)

        async def scenario():
            assert bridge.get_tabs() == "pending"
            await drain()

        run(scenario)
        assert service.fetch_calls == 1

    def test_tabs_received_forwards_payload_to_signal(self, tmp_path):
        service = FakeCdpService()
        service.fetch_payload = '[{"id":1,"title":"t","url":"u","ws_url":"w"}]'
        ctx, _cfg = make_ctx(tmp_path, service=service)
        bridge = CdpBridge(ctx)
        got = []
        bridge.tabs_received.connect(got.append)
        ctx.bus.emit(TabsReceived(payload=service.fetch_payload))
        assert got == [service.fetch_payload]

    def test_find_tab_by_url_passes_query_and_forwards_result(self, tmp_path):
        service = FakeCdpService()
        service.find_matches = '[{"kind":"host"}]'
        ctx, _cfg = make_ctx(tmp_path, service=service)
        bridge = CdpBridge(ctx)
        got = []
        bridge.tab_match_result.connect(lambda q, m: got.append((q, m)))

        async def scenario():
            bridge.find_tab_by_url("virt-chat")
            await drain()

        run(scenario)
        assert service.find_calls == ["virt-chat"]
        assert got == [("virt-chat", '[{"kind":"host"}]')]

    def test_connection_status_forwards(self, tmp_path):
        ctx, _cfg = make_ctx(tmp_path)
        bridge = CdpBridge(ctx)
        got = []
        bridge.connection_status.connect(got.append)
        ctx.bus.emit(ConnectionChanged(status="connected"))
        ctx.bus.emit(ConnectionChanged(status="error"))
        assert got == ["connected", "error"]


class TestConnect:
    def test_successful_connect_emits_people_changed_once(self, tmp_path):
        service = FakeCdpService()
        service.connect_result = Ok(True)
        ctx, _cfg = make_ctx(tmp_path, service=service)
        bridge = CdpBridge(ctx)
        people = collect(ctx, PeopleChanged)

        async def scenario():
            bridge.connect_tab("ws://x")
            await drain()

        run(scenario)
        assert service.connect_calls == ["ws://x"]
        assert [e.reason for e in people] == ["connected"]

    def test_false_and_err_connects_do_not_emit_people_changed(self,
                                                               tmp_path):
        for result in (Ok(False), Err("connect_failed", "nope")):
            service = FakeCdpService()
            service.connect_result = result
            ctx, _cfg = make_ctx(tmp_path, service=service)
            bridge = CdpBridge(ctx)
            people = collect(ctx, PeopleChanged)

            async def scenario():
                bridge.connect_tab("ws://x")
                await drain()

            run(scenario)
            assert people == []

    def test_raising_service_is_observed_not_unhandled(self, tmp_path):
        service = FakeCdpService()
        service.connect_error = RuntimeError("boom")
        ctx, _cfg = make_ctx(tmp_path, service=service)
        bridge = CdpBridge(ctx)
        logs = LogCapture(ctx.bus)
        people = collect(ctx, PeopleChanged)

        loop = asyncio.new_event_loop()
        handler_events = []
        loop.set_exception_handler(lambda l, c: handler_events.append(c))

        async def scenario():
            bridge.connect_tab("ws://x")
            await drain(24)
            gc.collect()   # surface any "never retrieved" task exception

        loop.run_until_complete(scenario())
        loop.close()

        assert logs.any("Connect failed", level="error")
        assert people == []
        assert handler_events == []   # no unhandled task failure


class TestBookmarks:
    def test_empty_and_whitespace_add_is_refused(self, tmp_path):
        ctx, cfg = make_ctx(tmp_path)
        bridge = CdpBridge(ctx)
        logs = LogCapture(ctx.bus)
        before = list(cfg.bookmarks.all())
        bridge.add_url_preset("")
        bridge.add_url_preset("   ")
        assert logs.any("empty", level="warn")
        assert cfg.bookmarks.all() == before

    def test_add_duplicate_and_remove_round_trip(self, tmp_path):
        ctx, cfg = make_ctx(tmp_path)
        bridge = CdpBridge(ctx)
        logs = LogCapture(ctx.bus)
        updated = []
        bridge.url_presets_updated.connect(updated.append)

        bridge.add_url_preset("https://example.com/")
        assert logs.any("added", level="success")
        assert "https://example.com/" in cfg.bookmarks.all()
        assert updated and "https://example.com/" in updated[-1]

        bridge.add_url_preset("https://example.com/")   # duplicate
        added = [m for m, l in logs.messages
                 if l == "success" and "added" in m]
        assert len(added) == 1           # no false success on duplicate
        assert logs.any("already exists", level="info")

        bridge.remove_url_preset("https://example.com/")
        assert "https://example.com/" not in cfg.bookmarks.all()
        assert logs.any("removed", level="warn")

    def test_remove_missing_changes_nothing(self, tmp_path):
        ctx, cfg = make_ctx(tmp_path)
        bridge = CdpBridge(ctx)
        logs = LogCapture(ctx.bus)
        before = list(cfg.bookmarks.all())
        bridge.remove_url_preset("https://never-added.example/")
        assert cfg.bookmarks.all() == before
        assert not logs.any("removed", level="warn")

    def test_bookmarks_persist_across_reopen(self, tmp_path):
        from backend.config_manager import ConfigManager
        ctx, cfg = make_ctx(tmp_path)
        bridge = CdpBridge(ctx)
        bridge.add_url_preset("https://persist.example/")
        reopened = ConfigManager(cfg._path)
        assert "https://persist.example/" in reopened.bookmarks.all()

    def test_remember_last_url_preset(self, tmp_path):
        ctx, cfg = make_ctx(tmp_path)
        bridge = CdpBridge(ctx)
        logs = LogCapture(ctx.bus)
        bridge.set_last_url_preset("https://chat.example/")
        assert cfg.get_state("last_url_preset") == "https://chat.example/"
        assert logs.any("remembered", level="info")
        bridge.set_last_url_preset("   ")   # blank is a no-op
        assert cfg.get_state("last_url_preset") == "https://chat.example/"

    def test_get_url_presets_reads_store(self, tmp_path):
        ctx, cfg = make_ctx(tmp_path)
        bridge = CdpBridge(ctx)
        bridge.add_url_preset("https://one.example/")
        assert json.loads(bridge.get_url_presets()) == cfg.bookmarks.all()

    def test_non_urls_preset_change_is_ignored(self, tmp_path):
        ctx, _cfg = make_ctx(tmp_path)
        bridge = CdpBridge(ctx)
        updated = []
        bridge.url_presets_updated.connect(updated.append)
        # a stack/template/custom-block preset change must not fake a
        # bookmarks update through this bridge
        ctx.bus.emit(PresetsChanged(kind="stacks", payload="[]"))
        assert updated == []

    def test_schedule_closes_coroutine_without_running_loop(self):
        async def work():
            return 1

        coro = work()
        with mock.patch.object(asyncio, "ensure_future",
                               side_effect=RuntimeError("no running loop")):
            CdpBridge._schedule(coro)
        assert inspect.getcoroutinestate(coro) == "CORO_CLOSED"
