"""Executor failure-policy tests (requeue / drop after max failures)."""
import asyncio

from .test_executor import b, make_ctx


class NoSend:
    """Mixin: clicking send never confirms (counter never resets)."""

    async def click(self, sel, timeout=None, retries=None):
        self.clicks.append(sel)
        if "container-item" in sel:
            self.person_tab = "Lizalo4ka"
        # never "type=submit" -> send never confirmed


def _patch(monkeypatch, max_failures):
    import chatflow.blocks.send_message as send_mod
    import chatflow.engine.executor as ex_mod
    monkeypatch.setattr(send_mod, "_CONFIRM_ATTEMPTS", 2)
    monkeypatch.setattr(send_mod, "_CONFIRM_SEC", 0.01)
    monkeypatch.setattr(ex_mod, "MAX_TARGET_FAILURES", max_failures)


def test_send_failure_drops_target_after_max_failures(monkeypatch):
    """A target that keeps failing must not loop the run forever: after
    MAX_TARGET_FAILURES consecutive failed passes it is dropped (SKIPPED)."""
    _patch(monkeypatch, 2)
    from .test_executor import FakeOps
    from chatflow.engine.executor import SequenceExecutor

    class Ops(NoSend, FakeOps):
        pass

    ops = Ops()
    events = []
    ctx = make_ctx(ops, events)
    ctx.queued = ["Lizalo4ka"]
    seq = [b("pick_target"), b("click_user"), b("type_message"), b("send_message")]
    ex = SequenceExecutor(lambda n, p: events.append((n, p)), lambda *a: None, ctx.s)
    summary = asyncio.run(ex.run_sequence(seq, ctx))
    assert summary["sent"] == 0
    assert ctx.queued == [], "dropped target must leave the queue"
    dropped = [p for n, p in events if n == "users_updated"]
    assert dropped and dropped[-1]["nickname"] == "Lizalo4ka" \
        and dropped[-1]["status"] == "SKIPPED"


def test_send_failure_requeues_then_drains(monkeypatch):
    """Run terminates (no infinite loop): every broken target is dropped
    after MAX_TARGET_FAILURES consecutive failed passes, queue drains."""
    _patch(monkeypatch, 3)
    from .test_executor import FakeOps
    from chatflow.engine.executor import SequenceExecutor

    class Ops(NoSend, FakeOps):
        pass

    ops = Ops()
    events = []
    ctx = make_ctx(ops, events)
    ctx.queued = ["Lizalo4ka", "Dr0che"]
    seq = [b("pick_target"), b("click_user"), b("type_message"), b("send_message")]
    ex = SequenceExecutor(lambda n, p: events.append((n, p)), lambda *a: None, ctx.s)
    summary = asyncio.run(ex.run_sequence(seq, ctx))
    assert summary["sent"] == 0
    assert ctx.queued == []
    dropped = {p["nickname"] for n, p in events if n == "users_updated"}
    assert dropped == {"Lizalo4ka", "Dr0che"}
