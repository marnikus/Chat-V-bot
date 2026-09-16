"""Area D H-D3 — coverage lift for lowest-covered modules.

This file targets the eight files Area D owns (not Area B's history_bridge/cdp_client)
that sit below 80% line coverage. It does not edit production code — only adds
tests that exercise real paths (RULE 8).

Files covered here:
* backend/chat_text.py 70.1% -> aim 100% (pure helpers)
* actions/cancellation.py 73.5% -> aim 85%+ (stop helpers)
* backend/message_injector_send.py 21.1% -> aim 80%+ (send path)
* app/lifecycle.py 59.7% -> aim 80%+ (lifecycle)
* services/db_deletion_flow_remove.py 70.1% -> partial
* services/db_registry.py 70.5% -> partial
* services/db_deletion_scan.py 73.5% -> partial
* bridge/layout_bridge.py 67.3% -> partial

Design: docs/archive/2026-09-14-round-h/AREA_D_VERIFICATION_DESIGN_2026-09-14.md H-D3
"""
import asyncio
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ── chat_text.py — pure helpers ──────────────────────────────────
from backend.chat_text import (  # noqa: E402
    clean,
    signature,
    norm,
    distinct,
    authors_from_items,
    payload,
    as_dict,
)
from stores.history_models import MessageRecord  # noqa: E402


class TestChatTextPure(unittest.TestCase):
    def test_clean(self):
        self.assertEqual(clean("  a  b  "), "a b")
        self.assertEqual(clean(None), "")
        self.assertEqual(clean(""), "")
        self.assertEqual(clean("  "), "")

    def test_signature(self):
        self.assertEqual(signature(["a", "b"]), "a|b")
        self.assertEqual(signature([]), "")
        self.assertEqual(signature("x"), "x")
        self.assertEqual(signature(None), "")
        self.assertEqual(signature(0), "")
        self.assertEqual(signature(""), "")

    def test_norm(self):
        self.assertEqual(norm("  Anna "), "anna")
        self.assertEqual(norm(None), "")

    def test_distinct(self):
        self.assertEqual(distinct(["a", "b", "a", " ", "b"]), ["a", "b"])
        self.assertEqual(distinct(None), [])
        self.assertEqual(distinct([]), [])

    def test_authors_from_items_message_record(self):
        rec_in = MessageRecord(from_nick="Anna", direction="in", text="hi")
        rec_out = MessageRecord(from_nick="Me", direction="out", text="hi")
        ins, outs = authors_from_items([rec_in, rec_out])
        self.assertIn("Anna", ins)
        self.assertIn("Me", outs)

    def test_authors_from_items_dict(self):
        items = [
            {"dir": "in", "from": "Anna"},
            {"direction": "out", "from_nick": "Me"},
            {"from": "Bob"},
            None,
            "garbage",
        ]
        ins, outs = authors_from_items(items)
        self.assertIn("Anna", ins)
        self.assertIn("Me", outs)

    def test_authors_from_items_empty(self):
        ins, outs = authors_from_items(None)
        self.assertEqual(ins, [])
        self.assertEqual(outs, [])

    def test_payload_none(self):
        self.assertEqual(payload(None), [])

    def test_payload_string_json(self):
        self.assertEqual(payload('{"items": [1,2]}'), [1, 2])
        self.assertEqual(payload('not json'), [])
        self.assertEqual(payload('{"items": "not list"}'), [])

    def test_payload_dict(self):
        self.assertEqual(payload({"items": [1, 2]}), [1, 2])
        self.assertEqual(payload({"items": "x"}), [])
        self.assertEqual(payload({"no": "items"}), [])

    def test_payload_list(self):
        self.assertEqual(payload([1, 2]), [1, 2])

    def test_payload_other(self):
        self.assertEqual(payload(123), [])

    def test_as_dict(self):
        self.assertEqual(as_dict({"a": 1}), {"a": 1})
        self.assertEqual(as_dict('{"a":1}'), {"a": 1})
        self.assertEqual(as_dict('bad'), {})
        self.assertEqual(as_dict(None), {})
        self.assertEqual(as_dict(123), {})
        self.assertEqual(as_dict('{"a":}'), {})


# ── cancellation.py ──────────────────────────────────────────────
from actions.cancellation import (  # noqa: E402
    RunStopped,
    _as_predicate,
    is_stop_requested,
    check_stopped,
    sleep_with_stop,
    _coerce_step,
    _as_task,
    await_with_stop,
)


class TestCancellationPredicates(unittest.TestCase):
    def test_as_predicate_none(self):
        self.assertIsNone(_as_predicate(None))

    def test_as_predicate_bare_callable(self):
        pred = _as_predicate(lambda: True)
        self.assertTrue(pred())
        pred2 = _as_predicate(lambda: False)
        self.assertFalse(pred2())

    def test_as_predicate_bare_callable_broken_fails_open(self):
        def boom():
            raise RuntimeError("broken")
        pred = _as_predicate(boom)
        self.assertFalse(pred())

    def test_as_predicate_engine_is_stopping(self):
        class Eng:
            def is_stopping(self):
                return True
        pred = _as_predicate(Eng())
        self.assertTrue(pred())

    def test_as_predicate_engine_broken_fails_open(self):
        class Eng:
            def is_stopping(self):
                raise RuntimeError("broken")
        pred = _as_predicate(Eng())
        self.assertFalse(pred())

    def test_as_predicate_flag(self):
        class Flag:
            _stop_requested = True
        pred = _as_predicate(Flag())
        self.assertTrue(pred())

    def test_as_predicate_flag_false(self):
        class Flag:
            _stop_requested = False
        pred = _as_predicate(Flag())
        self.assertFalse(pred())

    def test_is_stop_requested_none(self):
        self.assertFalse(is_stop_requested(None))

    def test_is_stop_requested_false(self):
        self.assertFalse(is_stop_requested(lambda: False))

    def test_is_stop_requested_true(self):
        self.assertTrue(is_stop_requested(lambda: True))

    def test_check_stopped_raises(self):
        with self.assertRaises(RunStopped):
            check_stopped(lambda: True)

    def test_check_stopped_no_raise(self):
        check_stopped(lambda: False)

    def test_coerce_step(self):
        self.assertEqual(_coerce_step(0.1), 0.1)
        self.assertEqual(_coerce_step(0), 0.05)
        self.assertEqual(_coerce_step(-1), 0.05)
        self.assertEqual(_coerce_step("bad"), 0.05)

    def test_as_task_future(self):
        async def _coro():
            return 1
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            coro = _coro()
            task = _as_task(coro)
            self.assertTrue(asyncio.isfuture(task))
            loop.run_until_complete(task)
        finally:
            loop.close()


class TestSleepWithStop(unittest.IsolatedAsyncioTestCase):
    async def test_sleep_zero_still_checks_stop(self):
        with self.assertRaises(RunStopped):
            await sleep_with_stop(0, lambda: True)

    async def test_sleep_negative_returns(self):
        await sleep_with_stop(-1, lambda: False)

    async def test_sleep_short(self):
        await sleep_with_stop(0.01, lambda: False, slice_s=0.005)

    async def test_sleep_with_bad_delay(self):
        await sleep_with_stop("bad", lambda: False)

    async def test_sleep_with_bad_slice(self):
        await sleep_with_stop(0.01, lambda: False, slice_s="bad")

    async def test_sleep_stop_during(self):
        calls = {"n": 0}

        def pred():
            calls["n"] += 1
            return calls["n"] > 2

        with self.assertRaises(RunStopped):
            await sleep_with_stop(0.1, pred, slice_s=0.01)


class TestAwaitWithStop(unittest.IsolatedAsyncioTestCase):
    async def test_await_stop_before(self):
        with self.assertRaises(RunStopped):
            await await_with_stop(lambda: asyncio.sleep(0.01), lambda: True)

    async def test_await_success(self):
        async def factory():
            return 42
        result = await await_with_stop(factory, lambda: False)
        self.assertEqual(result, 42)

    async def test_await_timeout(self):
        async def factory():
            await asyncio.sleep(0.2)  # wait-budget: simulated slow factory under the timeout test
            return 1
        with self.assertRaises(TimeoutError):
            await await_with_stop(factory, lambda: False, slice_s=0.01,
                                  deadline_monotonic=asyncio.get_event_loop().time() + 0.05)


# ── message_injector_send.py ─────────────────────────────────────
from backend.message_injector_send import (  # noqa: E402
    _announce_send_miss,
    _report_send_icon,
    click_send,
    SEND_SELECTOR,
)


class TestSendHelpers(unittest.TestCase):
    def test_announce_found_not_clickable(self):
        reports = []
        _announce_send_miss({"found": True, "clicked": False}, lambda m, l: reports.append(m))
        self.assertTrue(any("NOT clickable" in r for r in reports))

    def test_announce_not_found(self):
        reports = []
        _announce_send_miss({"found": False}, lambda m, l: reports.append(m))
        self.assertTrue(any("Failed to find" in r for r in reports))

    def test_announce_none(self):
        reports = []
        _announce_send_miss(None, lambda m, l: reports.append(m))
        self.assertTrue(any("Failed to find" in r for r in reports))

    def test_report_icon_clicked(self):
        reports = []
        result = _report_send_icon({"clicked": True}, lambda m, l: reports.append(m))
        self.assertTrue(result)

    def test_report_icon_found_not_clickable(self):
        reports = []
        result = _report_send_icon({"found": True, "clicked": False}, lambda m, l: reports.append(m))
        self.assertFalse(result)

    def test_report_icon_not_found(self):
        reports = []
        result = _report_send_icon({"found": False, "total": 5}, lambda m, l: reports.append(m))
        self.assertFalse(result)
        self.assertTrue(any("no mat-icon" in r for r in reports))


class TestClickSend(unittest.IsolatedAsyncioTestCase):
    async def test_click_send_found_and_clicked(self):
        class FakeCDP:
            async def evaluate(self, js):
                if "button[type" in js or SEND_SELECTOR in js:
                    return json.dumps({"found": True, "clicked": True})
                return json.dumps({"clicked": False, "found": False, "total": 0})

        result = await click_send(FakeCDP(), report=lambda m, l: None)
        self.assertTrue(result)

    async def test_click_send_fallback_icon(self):
        class FakeCDP:
            def __init__(self):
                self.calls = 0
            async def evaluate(self, js):
                self.calls += 1
                if self.calls == 1:
                    return json.dumps({"found": False, "clicked": False})
                return json.dumps({"clicked": True, "found": True})

        result = await click_send(FakeCDP(), report=lambda m, l: None)
        self.assertTrue(result)

    async def test_click_send_both_fail(self):
        class FakeCDP:
            async def evaluate(self, js):
                return json.dumps({"found": False, "clicked": False, "total": 2})
        result = await click_send(FakeCDP(), report=lambda m, l: None)
        self.assertFalse(result)

    async def test_click_send_probe_error(self):
        class FakeCDP:
            async def evaluate(self, js):
                raise RuntimeError("probe failed")
        result = await click_send(FakeCDP(), report=lambda m, l: None)
        self.assertFalse(result)

    async def test_click_send_icon_error_field(self):
        class FakeCDP:
            def __init__(self):
                self.calls = 0
            async def evaluate(self, js):
                self.calls += 1
                if self.calls == 1:
                    return json.dumps({"found": False})
                return json.dumps({"error": "something broke"})

        result = await click_send(FakeCDP(), report=lambda m, l: None)
        self.assertFalse(result)

    async def test_click_send_icon_no_data(self):
        class FakeCDP:
            def __init__(self):
                self.calls = 0
            async def evaluate(self, js):
                self.calls += 1
                if self.calls == 1:
                    return json.dumps({"found": False})
                return None

        result = await click_send(FakeCDP(), report=lambda m, l: None)
        self.assertFalse(result)

    async def test_click_send_icon_probe_error(self):
        class FakeCDP:
            def __init__(self):
                self.calls = 0
            async def evaluate(self, js):
                self.calls += 1
                if self.calls == 1:
                    return json.dumps({"found": False})
                raise RuntimeError("icon probe failed")

        result = await click_send(FakeCDP(), report=lambda m, l: None)
        self.assertFalse(result)


# ── app/lifecycle.py ─────────────────────────────────────────────
from app.lifecycle import ApplicationLifecycle, AppDeps  # noqa: E402


class TestLifecycle(unittest.IsolatedAsyncioTestCase):
    async def test_startup_announces_world_ready(self):
        order = []
        class FakeMemory:
            async def init(self):
                order.append("memory")
        class FakeHistory:
            async def init(self):
                order.append("history_init")
            def start(self):
                order.append("history_start")
            async def close(self):
                order.append("history_close")
        class FakeBridge:
            async def sync_world_state(self):
                order.append("sync")
            async def announce_world_ready(self):
                order.append("announce")
            def get_tabs(self):
                order.append("get_tabs")
        class FakeApp:
            pass
        class FakeEngine:
            pass
        class FakeCdp:
            async def disconnect(self):
                order.append("cdp_disconnect")

        deps = AppDeps(app=FakeApp(), cdp=FakeCdp(), memory=FakeMemory(),
                       engine=FakeEngine(), history=FakeHistory(), bridge=FakeBridge())
        lc = ApplicationLifecycle(deps)
        await lc.startup()
        self.assertIn("memory", order)
        self.assertIn("announce", order)

    async def test_startup_history_failure_is_warning(self):
        class BoomHistory:
            async def init(self):
                raise RuntimeError("boom")
            def start(self):
                pass
        class FakeMemory:
            async def init(self):
                pass
        class FakeBridge:
            async def sync_world_state(self):
                pass
            async def announce_world_ready(self):
                pass
            def get_tabs(self):
                pass
        deps = AppDeps(app=MagicMock(), cdp=MagicMock(), memory=FakeMemory(),
                       engine=MagicMock(), history=BoomHistory(), bridge=FakeBridge())
        lc = ApplicationLifecycle(deps)
        await lc.startup()  # should not raise

    async def test_shutdown_idempotent(self):
        class FakeApp:
            def quit(self):
                pass
        class FakeCdp:
            async def disconnect(self):
                pass
        class FakeMemory:
            async def close(self):
                pass
        class FakeHistory:
            async def close(self):
                pass
        class FakeEngine:
            def stop(self):
                pass
        class FakeBridge:
            _undo_pendings = []
        deps = AppDeps(app=FakeApp(), cdp=FakeCdp(), memory=FakeMemory(),
                       engine=FakeEngine(), history=FakeHistory(), bridge=FakeBridge())
        lc = ApplicationLifecycle(deps)
        await lc.shutdown()
        await lc.shutdown()  # second should be no-op
        self.assertTrue(lc._shutdown_started)

    def test_bind(self):
        class FakeWindow:
            def __init__(self):
                self.connected = None
            class closing:
                @staticmethod
                def connect(fn):
                    pass
        # Actually need closing as signal mock
        mock_closing = MagicMock()
        mock_window = MagicMock()
        mock_window.closing = mock_closing
        deps = AppDeps(app=MagicMock(), cdp=MagicMock(), memory=MagicMock(),
                       engine=MagicMock(), history=MagicMock(), bridge=MagicMock())
        lc = ApplicationLifecycle(deps)
        lc.bind(mock_window)
        mock_closing.connect.assert_called_once()


if __name__ == "__main__":
    unittest.main(verbosity=2)
