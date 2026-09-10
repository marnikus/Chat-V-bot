"""Direct run-helper contracts, independent of Area A's coordinator defects."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from services.run.state_machine import RunState, RunStateMachine
from services.run.error_recovery import RetryPolicy, RunExecutionMixin
from services.run.hooks import (
    RunHooks,
    RunHooksMixin,
    RunTracer,
    maybe_await,
    normalize_blocks,
    norm_level,
)


ALLOWED = {
    "idle": {"running", "paused"},
    "running": {"paused", "stopping", "error", "done"},
    "paused": {"running", "stopping", "error"},
    "stopping": {"done", "error", "idle"},
    "error": {"idle", "running"},
    "done": {"idle", "running"},
}


@pytest.mark.parametrize("source", list(RunState))
@pytest.mark.parametrize("target", list(RunState))
def test_transition_matrix(source, target):
    machine = RunStateMachine()
    machine.state = source
    if target == source or target.value in ALLOWED[source.value]:
        assert machine.transition(target.value) == target
        assert machine.state == target
    else:
        with pytest.raises(ValueError, match="invalid transition"):
            machine.transition(target)
        assert machine.state == source


@pytest.mark.parametrize("source", list(RunState))
def test_state_convenience_guards(source):
    machine = RunStateMachine()
    machine.state = source
    assert machine.mark_stopping() == (
        RunState.STOPPING if source in (RunState.RUNNING, RunState.PAUSED) else source
    )
    machine.state = source
    assert machine.mark_done() == (
        RunState.DONE if source in (RunState.RUNNING, RunState.STOPPING) else source
    )
    assert machine.reset() == RunState.IDLE
    assert machine.mark_error() == RunState.ERROR
    assert machine.mark_running() == RunState.RUNNING
    assert machine.mark_paused() == RunState.PAUSED
    assert machine.mark_resumed() == RunState.RUNNING


@pytest.mark.parametrize(
    "exc,attempt,expected",
    [
        (TimeoutError(), 0, True),
        (ConnectionError(), 1, True),
        (TimeoutError(), 2, False),
        (ValueError(), 0, False),
        (OSError(), 0, False),
    ],
)
def test_retry_classification(exc, attempt, expected):
    assert RetryPolicy(2).should_retry(exc, attempt) is expected
    assert RetryPolicy(-2, -0.5).max_retries == 0
    assert RetryPolicy(-2, -0.5).base_delay == 0


@pytest.mark.asyncio
async def test_retry_exponential_backoff_and_return(monkeypatch):
    sleep = AsyncMock()
    monkeypatch.setattr("services.run.error_recovery.asyncio.sleep", sleep)
    op = AsyncMock(side_effect=[TimeoutError(), ConnectionError(), "done"])
    assert await RetryPolicy(2, 0.5).retry_with_backoff(op) == "done"
    assert [c.args for c in sleep.await_args_list] == [(0.5,), (1.0,)]
    assert op.await_count == 3


@pytest.mark.asyncio
async def test_retry_exhaustion_and_fallback():
    exc = ValueError("permanent")
    op = AsyncMock(side_effect=exc)
    fallback = AsyncMock(return_value="fallback")
    assert await RetryPolicy(5).retry_with_backoff(op, fallback=fallback) == "fallback"
    fallback.assert_awaited_once_with(exc)
    with pytest.raises(ValueError, match="permanent"):
        await RetryPolicy().retry_with_backoff(op)
    with pytest.raises(ValueError, match="permanent"):
        await RetryPolicy().fallback(exc)


@pytest.mark.asyncio
async def test_cancellation_is_never_retried():
    op = AsyncMock(side_effect=asyncio.CancelledError())
    with pytest.raises(asyncio.CancelledError):
        await RetryPolicy(5).retry_with_backoff(op)
    assert op.await_count == 1


def test_normalization_filters_only_retired_and_private_keys():
    original = [
        {
            "block_id": "PAUSE",
            "enabled": None,
            "_hidden": 1,
            "skip_if_backlog": True,
            "use_panel_filters": True,
            "backlog_threshold": 9,
            "custom": 7,
        },
        {"enabled": False},
        None,
        "bad",
    ]
    assert normalize_blocks(original) == [
        {"block_id": "PAUSE", "enabled": True, "custom": 7},
        {"enabled": False},
    ]
    assert original[0]["enabled"] is None
    assert normalize_blocks(None) == []


@pytest.mark.parametrize(
    "level,expected",
    [
        ("ok", "success"),
        ("DONE", "success"),
        ("debug", "info"),
        ("warning", "warn"),
        ("fail", "error"),
        ("???", "info"),
        (None, "info"),
        ("error", "error"),
        ("success", "success"),
        ("warn", "warn"),
    ],
)
def test_level_mapping(level, expected):
    assert norm_level(level) == expected


def test_trace_writes_identity_and_closes(tmp_path):
    tracer = RunTracer("c-test", str(tmp_path))
    tracer.note({"type": "detail", "message": "Ю"})
    tracer.close()
    row = json.loads((tmp_path / "run_trace_c-test.jsonl").read_text())
    assert row["run_id"] == "c-test" and row["message"] == "Ю"
    assert row["type"] == "detail" and row["ts"]
    assert tracer._fh.closed


def test_trace_io_errors_are_logged_not_raised(tmp_path, caplog):
    tracer = RunTracer("bad", str(tmp_path))
    tracer.close()
    tracer._fh = Mock()
    tracer._fh.write.side_effect = OSError("disk full")
    tracer._fh.close.side_effect = OSError("close")
    tracer.note({})
    tracer.close()
    assert "Trace write failed" in caplog.text


class Runner(RunHooksMixin, RunExecutionMixin):
    def __init__(self):
        self._memory = SimpleNamespace(
            get_all=AsyncMock(return_value=[]),
            upsert_user=AsyncMock(),
            delete_user=AsyncMock(return_value=True),
            mark_messaged=AsyncMock(),
        )
        self._tracer = SimpleNamespace(note=Mock())
        self.debug_msg = SimpleNamespace(emit=Mock())
        self.log_msg = SimpleNamespace(emit=Mock())
        self.person_found = SimpleNamespace(emit=Mock())
        self.person_removed = SimpleNamespace(emit=Mock())
        self.person_marked = SimpleNamespace(emit=Mock())
        self.step_complete = SimpleNamespace(emit=Mock())
        self.step_started = SimpleNamespace(emit=Mock())
        self._ctx = {}
        self._stop_requested = False
        self.selected_nick = ""
        self._hooks = RunHooks()
        self._retry = RetryPolicy()
        self._cdp = self._criteria = None
        self._wait_if_paused = AsyncMock()


@pytest.mark.asyncio
async def test_hook_events_and_memory_failures(caplog):
    runner = Runner()
    record = SimpleNamespace(
        nick="N",
        gender="unknown",
        registered=False,
        anonymous=True,
        guest=False,
        messaged=False,
    )
    runner._memory.upsert_user.side_effect = OSError("upsert")
    await runner.person_collected(record, [record])
    assert json.loads(runner.person_found.emit.call_args.args[0])["collected"] == 1
    runner._memory.get_all.return_value = [record]
    assert await runner.unmessaged_nicks() == {"N"}
    assert await runner.person_rejected(record, "filter")
    assert json.loads(runner.person_removed.emit.call_args.args[0]) == {
        "nick": "N",
        "reason": "filter",
    }
    runner._memory.delete_user.return_value = False
    assert not await runner.person_rejected(record, "filter")
    runner._memory.delete_user.side_effect = OSError("delete")
    assert not await runner.person_rejected(record, "filter")
    runner._memory.get_all.side_effect = OSError("read")
    assert await runner.unmessaged_nicks() == set()
    assert "Live upsert failed" in caplog.text


def test_reporting_selection_and_nick_expansion():
    runner = Runner()
    runner._ctx = {"step": 2}
    runner.report("hello", "ok")
    runner.debug_msg.emit.assert_called_once_with("      hello", "success")
    assert runner._tracer.note.call_args.args[0] == {
        "type": "detail",
        "level": "success",
        "message": "hello",
        "step": 2,
    }
    runner.note_selected("N")
    runner.note_selected("")
    assert runner.selected_nick == "N"
    block = SimpleNamespace(text="hi {{nick}}", _private="{{nick}}", count=4)
    original = runner._expand_nick_on_block(block, "N")
    assert block.text == "hi N" and block._private == "{{nick}}"
    runner._restore_block_attrs(block, original)
    assert block.text == "hi {{nick}}"
    runner._tracer = None
    runner.report("plain")
    runner.note_selected("Other")
    assert not runner.is_stopping()
    runner._stop_requested = True
    assert runner.is_stopping()


@pytest.mark.asyncio
async def test_maybe_await_supports_futures_and_sync():
    future = asyncio.get_running_loop().create_future()
    future.set_result(None)
    await maybe_await(future)
    await maybe_await(None)
    hook = AsyncMock()
    await maybe_await(hook())
    hook.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "state,expected", [(None, "missing"), (False, "ok"), (True, "already")]
)
async def test_mark_messaged_outcomes(state, expected):
    runner = Runner()
    if state is not None:
        runner._memory.get_all.return_value = [
            SimpleNamespace(nick="N", messaged=state)
        ]
    assert await runner.mark_person_messaged("N") == expected
    assert runner._memory.mark_messaged.await_count == int(expected == "ok")
    assert await runner.mark_person_messaged("") == "missing"
    runner._memory.get_all.side_effect = OSError()
    assert await runner.mark_person_messaged("N") == "error"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["OK", "SKIP", "FAIL"])
async def test_execute_restores_expanded_settings_and_emits_result(status):
    from actions.base_action import ActionResult

    runner = Runner()
    block = SimpleNamespace(
        block_id="CUSTOM", display_name="Custom", icon="x", text="{{nick}}"
    )
    block.execute = AsyncMock(return_value=getattr(ActionResult, status))
    runner._stack = [block]
    result = await runner._execute_for_user(
        SimpleNamespace(nick="N", messaged=False), False
    )
    assert result == status.lower()
    assert block.text == "{{nick}}"
    assert runner._ctx == {}
    runner.step_complete.emit.assert_called_once_with("Custom", "N")


@pytest.mark.asyncio
async def test_execute_exception_restores_settings():
    runner = Runner()
    block = SimpleNamespace(
        block_id="CUSTOM",
        display_name="Custom",
        icon="x",
        text="{{nick}}",
        execute=AsyncMock(side_effect=ValueError("failure")),
    )
    runner._stack = [block]
    assert (
        await runner._execute_for_user(SimpleNamespace(nick="N", messaged=False), False)
        == "fail"
    )
    assert block.text == "{{nick}}" and runner._ctx == {}


@pytest.mark.asyncio
async def test_all_disabled_is_skipped_not_completed():
    runner = Runner()
    block = SimpleNamespace(enabled=False)
    runner._stack = [block]
    assert (
        await runner._execute_for_user(SimpleNamespace(nick="N", messaged=False), False)
        == "skip"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [None, "read", "write", "pipeline"])
async def test_collection_failures_and_queue_filter(failure):
    runner = Runner()
    new = SimpleNamespace(nick="new", messaged=False)
    done = SimpleNamespace(nick="done", messaged=True)
    runner._memory.get_all.return_value = [new, done]
    if failure == "read":
        runner._memory.get_all.side_effect = OSError("read")
    if failure == "write":
        runner._memory.upsert_user.side_effect = OSError("write")
    result = SimpleNamespace(
        collected=[new, done],
        all_people=[new, done],
        seeking=False,
        found=None,
        purged=["rejected"],
        scrolls=2,
        reached_end=True,
        stopped_early=False,
        stopped=False,
    )
    block = SimpleNamespace(
        block_id="SCROLL_PARSE",
        display_name="Collect",
        run_pipeline=AsyncMock(return_value=result),
    )
    if failure == "pipeline":
        block.run_pipeline.side_effect = ValueError("pipeline")
    queue = await runner._run_collect_phase(block)
    assert queue == ([] if failure == "pipeline" else [new])
    assert runner._ctx == {}
    assert block.run_pipeline.await_args.kwargs["known_messaged"] == (
        set() if failure == "read" else {"done"}
    )
    if failure == "pipeline":
        assert runner._tracer.note.call_args.args[0]["status"] == "exception"
    else:
        runner.step_complete.emit.assert_called_once_with("Collect", "—")
        assert runner._tracer.note.call_args.args[0]["purged"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "stopped,requested", [(True, False), (False, True), (True, True)]
)
async def test_stopped_collection_never_queues(stopped, requested):
    runner = Runner()
    runner._stop_requested = requested
    result = SimpleNamespace(
        collected=[SimpleNamespace(nick="N", messaged=False)],
        all_people=[],
        seeking=False,
        found=None,
        purged=[],
        scrolls=0,
        reached_end=False,
        stopped_early=False,
        stopped=stopped,
    )
    block = SimpleNamespace(
        block_id="SCROLL_PARSE",
        display_name="Collect",
        run_pipeline=AsyncMock(return_value=result),
    )
    assert await runner._run_collect_phase(block) == []
    assert "stopped" in runner.debug_msg.emit.call_args.args[0]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "block_id,messaged,has_skip,expected",
    [
        ("CUSTOM", True, True, "skip"),
        ("CONDITIONAL_SKIP", True, False, "skip"),
        ("CONDITIONAL_SKIP", False, False, "ok"),
        ("SCROLL_PARSE", False, False, "ok"),
        ("REPEAT_LOOP", False, False, "ok"),
        ("TAKE_PERSON", False, False, "ok"),
    ],
)
async def test_non_execution_block_paths(block_id, messaged, has_skip, expected):
    runner = Runner()
    block = SimpleNamespace(
        block_id=block_id, display_name="B", icon="x", execute=AsyncMock()
    )
    runner._stack = [block]
    assert (
        await runner._execute_for_user(
            SimpleNamespace(nick="N", messaged=messaged), has_skip
        )
        == expected
    )
    block.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_stop_before_step_and_disabled_step():
    from actions.base_action import ActionResult

    runner = Runner()
    block = SimpleNamespace(
        block_id="CUSTOM",
        display_name="B",
        icon="x",
        execute=AsyncMock(return_value=ActionResult.OK),
    )
    runner._stack = [block]
    runner._stop_requested = True
    assert (
        await runner._execute_for_user(SimpleNamespace(nick="N", messaged=False), False)
        == "stop"
    )
    block.execute.assert_not_awaited()
    runner._stop_requested = False
    disabled = SimpleNamespace(block_id="CUSTOM", display_name="Off", enabled=False)
    runner._stack.insert(0, disabled)
    assert (
        await runner._execute_for_user(SimpleNamespace(nick="N", messaged=False), False)
        == "ok"
    )
    block.execute.assert_awaited_once()
    assert any(
        call.args[0].get("reason") == "disabled"
        for call in runner._tracer.note.call_args_list
    )


@pytest.mark.asyncio
async def test_action_hooks_support_sync_async_and_missing():
    runner = Runner()
    for hook in (Mock(), AsyncMock()):
        runner._hooks = SimpleNamespace(on_action_complete=hook)
        await runner._call_action_hook("block", "N", "ok")
        hook.assert_called_once_with(runner, "block", "N", "ok")
        if isinstance(hook, AsyncMock):
            hook.assert_awaited_once()
    runner._hooks = None
    await runner._call_action_hook("block", "N", "ok")
    hooks = RunHooks()
    assert hooks.pre_run(runner) is None
    assert hooks.post_run(runner, "worked") is None
    assert hooks.on_action_complete(runner, "block", "N", "ok") is None
