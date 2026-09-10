"""AREA C — local harness for run-safety tests (no global fixtures).

Real RunCoordinator/RetryPolicy/RunProgress/RunStateMachine, temp CWD for
tracer files, cooperative fake CDP/memory/blocks. No edits to
tests/conftest.py, no global Qt fakes, no registry pollution (snapshot +
restore around shadowing fakes).
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile

from actions.base_action import ActionResult, ActionRegistry, BaseAction
from services.run import RunCoordinator
from stores.user_memory import UserRecord

try:
    from actions.cancellation import RunStopped  # type: ignore
except ImportError:  # red phase: placeholder so tests fail as assertions
    class RunStopped(Exception):  # type: ignore
        pass


# ── registry guard ──────────────────────────────────────────────
class RegistryGuard:
    """Snapshot the global ActionRegistry; restore on demand.

    Test blocks with shipped block_ids (SCROLL_PARSE/CLICK_USER/...) shadow
    the real actions at class-definition time. Use unique TEST_* ids where
    possible; when a shipped id is required, wrap the test case with this.
    """

    def __init__(self):
        self._saved = None

    def __enter__(self):
        self._saved = dict(ActionRegistry._classes)
        return self

    def __exit__(self, *exc):
        ActionRegistry._classes.clear()
        ActionRegistry._classes.update(self._saved)
        return False


# ── fake memory ─────────────────────────────────────────────────
class FakeMemory:
    """Minimal async UserMemory stand-in with effect traces."""

    def __init__(self, users=None):
        self._users = list(users or [])
        self.marked = []
        self.upserts = []
        self.deleted = []

    async def get_queue(self):
        return [u for u in self._users if not getattr(u, "messaged", False)]

    async def get_all(self):
        return list(self._users)

    async def upsert_user(self, user):
        self.upserts.append(user.nick)
        self._users.append(user)

    async def mark_messaged(self, nick):
        self.marked.append(nick)
        for u in self._users:
            if u.nick == nick:
                try:
                    u.messaged = True
                except Exception:
                    pass

    async def delete_user(self, nick):
        self.deleted.append(nick)
        for u in list(self._users):
            if u.nick == nick:
                self._users.remove(u)
                return True
        return False


class ScriptedMemory(FakeMemory):
    """Memory whose get_queue/get_all can run a hook (e.g. request stop)."""

    def __init__(self, users=None, on_get_queue=None, on_get_all=None):
        super().__init__(users)
        self._on_get_queue = on_get_queue
        self._on_get_all = on_get_all

    async def get_queue(self):
        if self._on_get_queue is not None:
            res = self._on_get_queue()
            if asyncio.iscoroutine(res):
                await res
        return await super().get_queue()

    async def get_all(self):
        if self._on_get_all is not None:
            res = self._on_get_all()
            if asyncio.iscoroutine(res):
                await res
        return await super().get_all()


# ── fake CDP ────────────────────────────────────────────────────
class FakeCDP:
    """Cooperative fake CDP: scripted evaluate results, hang support."""

    def __init__(self, script=None):
        # script: list of dict|str|Exception|callable(attempt)->...; repeats last
        self._script = list(script or [])
        self.calls = 0
        self.exprs = []
        self.hang_event = None  # if set, evaluate waits on it (for hang tests)

    async def evaluate(self, expr):
        self.calls += 1
        self.exprs.append(expr)
        n = self.calls
        if self.hang_event is not None:
            await self.hang_event.wait()
        if not self._script:
            return json.dumps({"found": False, "total": 0})
        item = self._script[min(n - 1, len(self._script) - 1)]
        if callable(item):
            item = item(n)
            if asyncio.iscoroutine(item):
                item = await item
        if isinstance(item, BaseException):
            raise item
        if isinstance(item, Exception):
            raise item
        if isinstance(item, dict):
            return json.dumps(item)
        return item


# ── generic test blocks (unique ids, no registry shadowing) ─────
_next_id = [0]


def _unique_id(prefix="TEST_OK"):
    _next_id[0] += 1
    return f"{prefix}_{_next_id[0]}"


class OkBlock(BaseAction):
    block_id = "TEST_OK_GENERIC"
    name = "Test Ok"
    icon = "✓"

    def __init__(self, **kw):
        kw.pop("block_id", None)
        super().__init__(pre_delay_ms=0)
        self.calls = []
        self.on_run = kw.pop("on_run", None)

    async def execute(self, user_nick, cdp, engine=None):
        self.calls.append(user_nick)
        if self.on_run is not None:
            res = self.on_run(engine, user_nick)
            if asyncio.iscoroutine(res):
                await res
        return ActionResult.OK


def make_ok_block(on_run=None, block_id=None):
    """Build an OkBlock with an optional unique block_id (avoids collisions)."""
    if block_id is None:
        b = OkBlock()
    else:
        cls = type(f"Ok_{block_id}", (OkBlock,), {"block_id": block_id})
        b = cls()
    b.on_run = on_run
    return b


class FailBlock(BaseAction):
    block_id = "TEST_FAIL_GENERIC"
    name = "Test Fail"
    icon = "✗"

    def __init__(self, **kw):
        super().__init__(pre_delay_ms=0)
        self.calls = []

    async def execute(self, user_nick, cdp, engine=None):
        self.calls.append(user_nick)
        return ActionResult.FAIL


class SkipBlock(BaseAction):
    block_id = "TEST_SKIP_GENERIC"
    name = "Test Skip"
    icon = "⏭"

    def __init__(self, **kw):
        super().__init__(pre_delay_ms=0)
        self.calls = []

    async def execute(self, user_nick, cdp, engine=None):
        self.calls.append(user_nick)
        return ActionResult.SKIP


class StopRequestBlock(BaseAction):
    """Requests engine.stop() then returns OK (stop-during-block probe)."""

    block_id = "TEST_STOP_REQ"
    name = "Test StopReq"
    icon = "⏹"

    def __init__(self, **kw):
        super().__init__(pre_delay_ms=0)
        self.calls = []

    async def execute(self, user_nick, cdp, engine=None):
        self.calls.append(user_nick)
        if engine is not None and hasattr(engine, "stop"):
            engine.stop()
        return ActionResult.OK


class GateBlock(BaseAction):
    """Parks on an event so stop/pause/cancel can land mid-execution."""

    block_id = "TEST_GATE"
    name = "Test Gate"
    icon = "🚧"

    def __init__(self, gate=None, **kw):
        super().__init__(pre_delay_ms=0)
        self.calls = []
        self.gate = gate

    async def execute(self, user_nick, cdp, engine=None):
        self.calls.append(user_nick)
        if self.gate is not None:
            await self.gate.wait()
        return ActionResult.OK


class SlowBlock(BaseAction):
    block_id = "TEST_SLOW"
    name = "Test Slow"
    icon = "🐢"

    def __init__(self, delay=5.0, **kw):
        super().__init__(pre_delay_ms=0)
        self.calls = []
        self.delay = delay

    async def execute(self, user_nick, cdp, engine=None):
        self.calls.append(user_nick)
        await asyncio.sleep(self.delay)
        return ActionResult.OK


# ── engine harness ──────────────────────────────────────────────
class EngineHarness:
    """Temp-CWD engine with signal traces. Use as async context or manual."""

    def __init__(self, users=None, memory=None, hooks=None, retry_policy=None):
        self._tmp = None
        self._old = None
        self.memory = memory if memory is not None else FakeMemory(users)
        self._hooks = hooks
        self._retry = retry_policy
        self.engine = None
        self.logs = []
        self.debug = []
        self.user_done = []
        self.marked_live = []
        self.stack_complete = []
        self.step_started = []
        self.step_complete = []
        self._guard = RegistryGuard()

    def __enter__(self):
        self._guard.__enter__()
        self._old = os.getcwd()
        self._tmp = tempfile.TemporaryDirectory()
        os.chdir(self._tmp.name)
        kwargs = {}
        if self._hooks is not None:
            kwargs["hooks"] = self._hooks
        if self._retry is not None:
            kwargs["retry_policy"] = self._retry
        self.engine = RunCoordinator(
            cdp=None, memory=self.memory, criteria=None, **kwargs
        )
        self.engine.log_msg.connect(lambda m: self.logs.append(m))
        self.engine.debug_msg.connect(lambda m, l: self.debug.append((m, l)))
        self.engine.user_complete.connect(
            lambda n, ok: self.user_done.append((n, ok))
        )
        self.engine.person_marked.connect(lambda n: self.marked_live.append(n))
        self.engine.stack_complete.connect(
            lambda: self.stack_complete.append(True)
        )
        self.engine.step_started.connect(
            lambda i, b, u: self.step_started.append((i, b, u))
        )
        self.engine.step_complete.connect(
            lambda n, u: self.step_complete.append((n, u))
        )
        return self

    def __exit__(self, *exc):
        try:
            if self._tmp is not None:
                os.chdir(self._old)
                self._tmp.cleanup()
        finally:
            self._guard.__exit__(*exc)
        return False

    def debug_text(self):
        return " | ".join(m for m, _ in self.debug)

    def log_text(self):
        return " | ".join(self.logs)

    def trace_records(self):
        import glob

        files = sorted(glob.glob(os.path.join(os.getcwd(), "logs", "*.jsonl")))
        if not files:
            files = sorted(glob.glob(os.path.join(os.getcwd(), "*.jsonl")))
        records = []
        for path in files:
            with open(path, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if line:
                        records.append(json.loads(line))
        return records


def make_harness(*args, **kwargs):
    return EngineHarness(*args, **kwargs)
