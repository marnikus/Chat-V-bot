# AREA C — Stop Correctness + Cycle Orchestration: New-Structure Design (implementation blueprint)

Date: 2026-09-10 · Branch: `arena/01a08bb6-chat-v-bot` · Baseline: `8f9c708` (AREA A landed)
Parent: `docs/archive/2026-09-10-safety-refactor/SAFETY_REFACTOR_2026-09-10_PLAN.md` + `docs/archive/2026-09-10-safety-refactor/SAFETY_REFACTOR_AREA_C_2026-09-10.md`
Status: **Design — tests to be written before any production change.**
Owner: AREA C only. No A/B files. Frozen files per master plan §2 are untouched.

> Process followed here: (1) understand fully, (2) design new structure doc
> first, (3) full test coverage before refactoring, (4) implement + run tests.

---

## 1. Problem restated (measured, not assumed)

Current flow (`RunCoordinator.execute` → `_execute_cycle` → `_execute_for_user`):

```
execute: mark_running → pre_run → for cycle: [stop? → wait_if_paused → _execute_cycle]
_execute_cycle: scroll lookup → collect/get_queue → label filter → order-by-column
                → take phase → stack inspection (mem_click/needs_user/take_present)
                → mode branch (single-target / empty / empty_stack / standalone / queued)
                → for user: [stop? → wait_if_paused → _execute_for_user → mark? → user_complete]
_execute_for_user: for block: [stop? → wait_if_paused → expand {{nick}} → retry(block.execute)
                              → restore → handle result → hook → next or return]
WaitPageLoad.execute: pre_delay → probe loop (cdp.evaluate + sleep 0.3) until deadline
```

Proved defects (temp-dir probes on this checkout, no user data touched):

1. **Wait ignores already-requested stop.** `WaitPageLoad.execute` with
   `_stop_requested=True`, fake CDP not-found, 30 ms timeout, no pre-delay
   made **2 probes** and returned **`fail`** (master plan §1 reproduced).
   No pre-delay/probe skip, no cooperative stopped outcome.
2. **Stop during final OK still marks.** Single-user run where the only block
   calls `engine.stop()` then returns `OK`: coordinator marks the user
   (`marked=['solo']`), trace ends `run_end/completed`, outcome `worked`.
   Stop requested before the automatic-mark boundary is not observed.
3. **Two-user stop strands STOPPING.** First block stops during user `a`
   (marks `a` — bug 2), second-user loop sees stop and returns `stopped`,
   `done` stays False, no `mark_done`, state stays **`STOPPING`**.
   A second `execute()` raises
   `ValueError: invalid transition: stopping -> running`. Reproduced.
4. **Stop during pause starts another block.** Pause between B1/B2, stop
   while paused: `_wait_if_paused` exits on stop, caller does **not**
   recheck, B2 runs (`calls=['b1','b2']`), run ends `DONE/worked`.
   Same gap exists in `execute` (next cycle starts) and `_execute_cycle`
   (next user starts via `_execute_for_user` returning `stop` only after
   progress/user_complete accounting).
5. **Single-target masks stop.** `_run_single_target_cycle` calls
   `_execute_for_user` (returns `stop` when the second block sees the flag),
   then unconditionally returns **`worked`**; progress `note_status(stop)`
   is a no-op; no next-cycle suppression beyond the wrong outcome.
   Reproduced: outcome `worked`, should be `stopped`.
6. **Stopped collect misclassified as empty.** `_run_collect_phase` returns
   `[]` on `result.stopped or _stop_requested`; `_execute_cycle` then
   follows the empty-queue branch (`empty` + `DONE/completed`), never
   `stopped`. No downstream standalone run in the probed stack (because
   `SCROLL_PARSE` is user-scoped), but the outcome/trace/state are wrong
   (`DONE`, not `STOPPING→DONE` with `stopped`).
7. **Progress accounting inconsistent.** `RunProgress.note_status("stop")`
   increments nothing (only `ok/skip/fail`); queued path maps
   `stop→fail` explicitly, single-target passes `stop` through (ignored).
   Wire `RunProgressChanged` has no `stopped` counter by design.
8. **External cancel strands RUNNING.** `task.cancel()` during a slow block:
   `CancelledError` propagates (good), `finally` awaits trivial `post_run`,
   closes tracer, resets `_running`, emits `stack_complete` — but state stays
   **`RUNNING`** (no terminal mark), `{{nick}}` expansion and `_ctx` are not
   restored via `finally` (the `except Exception` does not catch
   `CancelledError` on py3.11 where it is `BaseException`).
9. **Post-run failure can skip mandatory cleanup.** `finally: await post_run;
   tracer.close; _running=False; stack_complete.emit` — if `post_run`
   raises/cancels, the later lines are skipped. Not yet reproduced with a
   failing hook; risk-based, must be demonstrated by test.
10. **Retry is stop-blind.** `RetryPolicy.retry_with_backoff` sleeps the full
    backoff and retries transient errors without consulting any stop
    predicate; a `RunStopped`-style cooperative signal would be retried or
    sent to `fallback` as a transient error. Baseline has no cooperative
    exception at all.

Contracts to preserve (master plan §3.1 + §3.3):

- Same `RunCoordinator`/`ActionEngine` public API, Qt signals/slots, payload
  keys/types; same `execute/load_stack/stop/pause/resume` semantics except
  demonstrated bug fixes.
- Same `ActionResult.OK/FAIL/SKIP`, block IDs, retired-key handling, preset
  formats; **no new public STOP result**; `BaseAction.to_dict()` output
  unchanged (no new serialized settings).
- Same cycle outcomes `worked/empty/empty_stack/stopped`; same per-user
  statuses `ok/skip/fail/stop`.
- Automatic post-run marking only for successfully completed real-user work,
  never standalone/skipped/stopped; explicit `MARK_MESSAGED` already
  completed before stop is not rolled back.
- `RunHooksMixin.is_stopping()` + `ActionContext.is_stopping()` remain the
  duck-compatible stop query; `engine=None` means no predicate.
- `services/undo_service.py`, `services/history/*`, `stores/*`, `core/*`,
  `backend/*`, `bridge/*`, `actions/base*.py`, `services/run/hooks.py`,
  `services/run/__init__.py`, `tests/conftest.py` are **frozen** (not edited).

Audit baseline to preserve: `_execute_cycle` Radon CC 31 / cognitive 25;
`actions/wait_page.py:execute` Radon CC 18 / cognitive 28 (highest cognitive
in repo); coordinator module previously 100% branch — count/CC alone prove
nothing, interaction/side-effect tests are required.

---

## 2. Target structure

### 2.1 File map (C-owned only)

```
actions/cancellation.py          NEW — private RunStopped + stop-aware helpers (no services/Qt)
actions/wait_page.py             EDIT — cooperative cancellation, monotonic deadline, sliced probe
services/run/cycle_plan.py       NEW — private StackFacts + inspect_stack + choose_cycle_mode (no Qt/DB/CDP)
services/run/coordinator.py      EDIT — stop gates, RunStopped translation, terminal-state + cleanup guarantees
services/run/error_recovery.py   EDIT — stop-aware retry, per-action RunStopped/finally, collect-phase stop
services/run/progress.py         EDIT — pause-barrier recheck helper, single-target stop fix, take/order stop gates
services/run/state_machine.py    EDIT — restartable terminal handling (STOPPING-tolerant mark_running)
tests/unit/actions/test_wait_page_cancellation.py   NEW — C1a wait matrix
tests/integration/run_safety/    NEW — stop/cleanup/cycle suites (see §5)
docs/archive/2026-09-10-safety-refactor/SAFETY_REFACTOR_AREA_C_2026-09-10.md           EDIT — append implementation journal only
docs/archive/2026-09-10-safety-refactor/SAFETY_REFACTOR_AREA_C_DESIGN_2026-09-10.md    NEW — this file
```

No other production file is touched. In particular `services/run/hooks.py`
(`is_stopping`, `RunTracer`, `normalize_blocks`, nick expansion primitives)
stays frozen; C calls it but does not change it. `backend/cdp_client.py`
stays frozen; C tests its cancellation contract but does not patch it.

### 2.2 New module: `actions/cancellation.py`

Private, lightweight, no `services`/`Qt` imports. Actions may import it;
`to_dict()` never sees it (helpers are locals, never public attributes).

```python
class RunStopped(Exception):
    """Private cooperative-stop signal. Caught only at run-execution boundaries
    and translated to existing 'stop'/'stopped' statuses. Never serialized,
    never added to ActionResult, never confused with asyncio.CancelledError."""

def is_stop_requested(engine) -> bool:
    # engine None → False
    # callable engine.is_stopping() → bool(it) (duck-compatible; exceptions → False? NO:
    #   exceptions propagate? Decision: fail-open False + no log here (no logger dependency?
    #   actually logging is stdlib, allowed; but keep silent False to avoid log spam in tight loops.
    #   Rationale: a broken predicate must not crash a wait; engine-level tests pin fail-open.)
    # else getattr(engine, "_stop_requested", False) compat fallback for old duck-typed callers
    # non-callable is_stopping attribute → bool(it)? No: only callable counts; else fallback.

def check_stopped(engine) -> None:
    # raise RunStopped if is_stop_requested(engine)

async def sleep_with_stop(delay_s: float, engine, *, slice_s: float = 0.02) -> None:
    # Bounded cooperative sleep: checks before/after, sleeps in slices, raises RunStopped
    # promptly on stop. delay<=0 returns immediately after a stop check.
    # slice_s clamped to (0, delay]; default 20ms for pre-delays, caller may pass 0.05-0.1.

async def await_with_stop(awaitable_factory, engine, *, slice_s: float = 0.05,
                          deadline_monotonic: float | None = None) -> Any:
    # Run a read-only awaitable (factory returns coroutine/future) with stop/deadline
    # supervision. Creates ONE task, polls in slices, cancels+awaits it on stop/deadline.
    # Raises RunStopped on stop, TimeoutError on deadline? Decision: return a sentinel?
    # For WaitPageLoad the deadline is NOT an error — it is the normal timeout path
    # returning FAIL. So this helper raises RunStopped on stop, and returns the result
    # otherwise; deadline expiry cancels the probe task and raises TimeoutError, which
    # the caller (WaitPageLoad) translates to its existing timeout/FAIL path.
    # Guarantees: no orphaned task (cancelled task is always awaited); CancelledError
    # from EXTERNAL cancellation propagates after cancelling+awaiting the inner task.
```

Why a factory, not a coroutine: so external cancellation during setup cannot
orphan a created-but-unawaited coroutine (unawaited-coroutine warning gate).

Polling slices ≤100 ms per area doc; defaults 20–50 ms keep the <500 ms
integration stop gate with margin while avoiding busy-spin.

### 2.3 `actions/wait_page.py` — cooperative wait

Preserved: block_id/settings/schema, `ActionResult.OK/FAIL` returns for
found/timeout, probe-error/not-present throttling cadence, `interpret_wait`
diagnostics, `engine=None` usability.

New behavior (all pinned by `test_wait_page_cancellation.py`):

```
execute:
  check_stopped(engine) BEFORE pre-delay          # already-stopped → no delay/probe
  await sleep_with_stop(pre_delay_ms/1000, engine) # interruptible pre-delay
  report "Waiting for ..." (existing text)
  deadline = monotonic() + timeout_ms/1000
  loop attempt 1..:
    check_stopped(engine)                          # before probe
    try:
      raw = await await_with_stop(lambda: cdp.evaluate(probe), engine,
                                  slice_s=0.05, deadline_monotonic=deadline)
      res = json.loads(raw) if raw else None; last_res = res
    except RunStopped:                             # stop during probe await
      report stopped (see below); raise
    except TimeoutError:                           # probe overran deadline
      break                                        # → existing timeout/FAIL path
    except Exception as exc:                       # probe error (incl. malformed JSON)
      throttled error report (attempt%5==1); res = None
    check_stopped(engine)                          # after probe, before interpreting
    if res and res.get("found"):
      report interpret_wait(res); return OK
    if monotonic() >= deadline: break
    throttled not-present report (attempt%7==1)
    try:
      await sleep_with_stop(0.3, engine, slice_s=0.05)  # interruptible poll gap
    except RunStopped:
      report stopped; raise
  # timeout path (existing text/counts)
  report timeout FAIL; return FAIL
```

Stopped report text (new, pinned): `⏹ Wait stopped on request — no longer
waiting for {label}` at `warn` level. Found/timeout/error texts stay
byte-identical. `RunStopped` propagates to the engine (never converted to
FAIL here).

Deadline uses `time.monotonic()` (not `asyncio.get_event_loop().time()`).
`timeout_ms<=0` means “probe once, then timeout path” (existing loop polls at
least once; preserved).

CDP cancellation note: only this read-only `evaluate` await is ever
task-cancelled by C; no write-path await (`click/type/send/collect`) is
cancelled — those rely on flag checks between steps. Cancelling the local
await does not undo a remote side effect; the area journal lists the exact
boundaries (§8).

### 2.4 `services/run/error_recovery.py` — retry + execution boundaries

#### RetryPolicy (additive, backwards compatible)

```python
def should_retry(self, exc, attempt) -> bool:
    if isinstance(exc, RunStopped): return False   # cooperative stop never retries
    if isinstance(exc, asyncio.CancelledError): return False  # (defensive; BaseException anyway)
    ... existing transient check ...

async def retry_with_backoff(self, op, *, fallback=None, stop=None):
    # stop: None | callable[[], bool] | engine with is_stopping/_stop_requested
    #   Normalised via cancellation.is_stop_requested semantics (local import to avoid cycle?
    #   actions.cancellation imports nothing from services, so services→actions import is safe
    #   and NOT a new backend import. Alternatively duplicate the 5-line check to keep
    #   services→actions edge at zero. Decision: import from actions.cancellation — it is a
    #   leaf module (stdlib only), the edge is one-way, and the predicate stays single-sourced.
    #   The "zero new backend imports" gate counts backend.*, not actions.*.
    attempt = 0
    while True:
        if _stop_predicate(stop): raise RunStopped
        try:
            return await op()
        except RunStopped:
            raise                                   # before should_retry/fallback, always
        except asyncio.CancelledError:
            raise                                   # never retry, never fallback
        except Exception as exc:
            if isinstance(exc, RunStopped): raise   # (unreachable, defensive)
            if not self.should_retry(exc, attempt):
                return await fallback(exc) if fallback else (_raise(exc))
            # stop-aware backoff (sliced, no fallback on stop):
            try:
                await sleep_with_stop(self.base_delay * (2**attempt), stop, slice_s=0.02)
            except RunStopped:
                raise
            attempt += 1
```

Permissive-subclass test: a subclass overriding `should_retry→True` still
cannot retry `RunStopped` because the `except RunStopped: raise` precedes the
`should_retry` call. Pinned.

`fallback` is never invoked for stop/cancel. Backoff sleep for the normal
path keeps exact timing (`base_delay * 2**attempt`, `attempt` increments
after sleeping).

#### `_run_collect_phase` — stop-aware collect

```python
async def _run_collect_phase(self, block):
    ... existing preamble (log/tracer/ctx/step_started) ...
    check stop BEFORE pipeline? The pipeline itself is stop-aware via should_stop
    predicate (ScrollParser honours engine.is_stopping). Still pass stop=engine to retry.
    try:
        result = await self._retry.retry_with_backoff(
            lambda: block.run_pipeline(...), fallback=..., stop=self)
    except RunStopped:
        self._ctx = {}
        self.debug_msg.emit("      ⏹ Collection stopped by user …", "warn")
        self._tracer.note({"type": "run_end", "reason": "stopped"})
        raise                                    # → cycle boundary translates to "stopped"
    except asyncio.CancelledError:
        self._ctx = {}; raise
    except Exception:
        self._ctx = {}; return []
    ... existing upsert/report/tracer/step_complete ...
    self._ctx = {}
    if result.stopped or is_stop_requested(self):
        self.debug_msg.emit("      ⏹ Collection stopped …", "warn")
        # NEW: raise instead of returning [] — [] misclassifies as empty.
        raise RunStopped
    return [p for p in result.collected if not p.messaged]
```

Callers (`_execute_cycle`) catch `RunStopped` from the collect phase and
return `"stopped"` without further preparation/mode work. The `step_complete`
for the collect block is still emitted (it ran); no queue is fabricated.

#### `_execute_for_user` — per-action boundaries + finally restoration

```python
async def _execute_for_user(self, user, has_skip) -> str:
    if user.messaged and has_skip: ... return "skip"   # unchanged
    if not enabled: ... return "skip"                   # unchanged (B5 guard)
    for idx, block in enumerate(self._stack, start=1):
        if is_stop_requested(self):                     # before pause
            ... stopped debug+tracer ...; return "stop"
        await self._wait_if_paused()
        if is_stop_requested(self):                     # AFTER pause (NEW)
            ... stopped debug+tracer ...; return "stop"
        if disabled: ... continue                       # unchanged
        if CONDITIONAL_SKIP: ...                        # unchanged
        if block in {SCROLL_PARSE, REPEAT_LOOP, TAKE_PERSON}: continue  # unchanged
        self._ctx = {...}; step_started.emit(...); debug; tracer step_start
        originals = self._expand_nick_on_block(block, self.selected_nick or user.nick)
        try:
            try:
                result = await self._retry.retry_with_backoff(
                    lambda: block.execute(user.nick, self._cdp, self), fallback=..., stop=self)
            except RunStopped:
                self._tracer.note({"type": "step_end", "status": "stop", **self._ctx})
                self.debug_msg.emit(f"      ⏹ {block.display_name} stopped on request", "warn")
                self.step_complete.emit(block.display_name, user.nick)
                return "stop"
            status = self._handle_step_result(block, user.nick, idx, started, result)
            await self._call_action_hook(block, user.nick, status)
            if status != "ok":
                return status
        except asyncio.CancelledError:
            # mandatory restoration, then propagate (no hook, no status mapping)
            raise
        except Exception:
            # _step_failed already reported via fallback; map to fail
            return "fail"
        finally:
            self._restore_block_attrs(block, originals)  # ALWAYS, incl. cancel/stop/hook-raise
            self._ctx = {}
        # NOTE: _ctx cleared in finally (was cleared at each return); hook exceptions from
        # _call_action_hook propagate to the coordinator's outer handler (existing behavior:
        # hook raise currently propagates out of _execute_for_user → _execute_cycle →
        # execute's except Exception → ERROR). Preserved, but restoration now guaranteed.
    self.debug_msg.emit(f"      ✅ All steps done for {user.nick}", "success")
    return "ok"
```

Key points:

- `RunStopped` from `block.execute` (e.g. WaitPageLoad) or from the retry
  backoff is translated to `"stop"` here; the retry `fallback`
  (`_step_failed`) is never invoked for it.
- `CancelledError` propagates after `finally` restoration (no `step_end`
  fraud, no hook, no `user_complete` here — the coordinator's cancel path
  handles run-level accounting).
- `_step_failed` keeps its exact reporting for ordinary exceptions; it is
  unreachable for stop/cancel by construction (tested via hook spies).
- Hook raising: restoration still happens (finally); the exception
  propagates as today (pinned by cleanup-contract tests).

### 2.5 `services/run/progress.py` — pause + single-target + take/order gates

```python
async def _wait_if_paused(self) -> None:
    # UNCHANGED body: while self._paused and not stop: sleep(0.2)
    # Callers now recheck stop immediately after it returns (C1c). The helper
    # itself stays a pure barrier (no RunStopped) so existing pause/resume
    # timing tests keep passing unchanged.

async def _order_queue_by_column(self, queue):
    if is_stop_requested(self): raise RunStopped   # NEW pre-gate
    ... existing respect_order logic ...
    if is_stop_requested(self): raise RunStopped   # NEW post-gate (memory read is an await)
    return ...

async def _run_take_phase(self) -> bool:
    if is_stop_requested(self): raise RunStopped   # NEW pre-gate
    try: rows = await self._memory.get_all()
    except ...: return False                        # unchanged fail-open
    if is_stop_requested(self): raise RunStopped   # NEW post-read gate
    ... existing per-block choose loop (sync; check stop each iteration) ...
    for block in ...:
        if is_stop_requested(self): raise RunStopped
        ...
    return matched

async def _run_single_target_cycle(self, has_skip, take_matched) -> str:
    # take_present/no-match and no-nick early outs UNCHANGED (return "empty")
    if is_stop_requested(self):                      # NEW: stopped before target work
        self.debug_msg.emit("⏹ Stack stopped by user", "warn")
        self._tracer.note({"type": "run_end", "reason": "stopped"})
        return "stopped"
    target = self.selected_nick
    self.progress.extend_total(1); ... existing mode logs/tracer ...
    try:
        status = await self._execute_for_user(UserRecord(nick=target), has_skip)
    except RunStopped:                               # (defensive; _execute_for_user maps)
        status = "stop"
    if status == "stop" or is_stop_requested(self):  # NEW: stop translation + pre-mark gate
        self.progress.note_status("fail")            # unify with queued stop→fail mapping
        self._tracer.note({"type": "run_end", "reason": "stopped"})
        self.user_complete.emit(target, False)
        return "stopped"
    self.progress.note_status(status)                # ok/skip/fail as before
    if status == "ok":
        await self._memory.mark_messaged(target); self.person_marked.emit(target)
    self.user_complete.emit(target, status == "ok")
    return "worked"
```

Progress decision (§3.2): `RunProgress.note_status` keeps its exact
`ok/done, skip/skipped, fail/failed` mapping and ignores unknown statuses
(characterized, not changed). Both cycle paths map cooperative `stop` to the
existing `failed` counter explicitly (`note_status("fail")`); stop identity
is preserved in the cycle outcome (`stopped`), per-user `user_complete(nick,
False)`, debug/tracer `run_end/stopped` — never in a new wire counter.

### 2.6 `services/run/coordinator.py` — cycle orchestration + run lifecycle

`_execute_cycle` keeps the exact phase order; C1 adds stop gates, C2 extracts
pure decisions (same gates, smaller function):

```
C1 _execute_cycle (behavioral, before extraction):
  scroll = first enabled SCROLL_PARSE (unchanged lookup point: BEFORE collection)
  try:
    queue = await _run_collect_phase(scroll) if scroll else await memory.get_queue()
  except RunStopped: return "stopped"
  if is_stop_requested: return stopped                       # post-collect gate
  queue = filter_by_labels(queue, announce=True)
  if is_stop_requested: return stopped                       # post-filter gate
  try: queue = await _order_queue_by_column(queue)
  except RunStopped: return stopped
  try: take_matched = await _run_take_phase()
  except RunStopped: return stopped
  if is_stop_requested: return stopped                       # pre-mode gate
  ... existing inspection + mode branch, with these changes:
    single-target: return await _run_single_target_cycle(...)  # now stop-correct
    take-miss / empty_stack / needs_user-empty / standalone-total as today
  for user in queue:
    if is_stop_requested: stopped-trace; return "stopped"    # pre-user gate
    await _wait_if_paused()
    if is_stop_requested: stopped-trace; return "stopped"    # post-pause gate (NEW)
    try: status = await _execute_for_user(user, has_skip)
    except RunStopped: status = "stop"                        # defensive
    except CancelledError: raise
    if status == "stop" or is_stop_requested(self):           # pre-mark gate (NEW)
      # stop observed before the automatic-mark boundary → NO mark
      progress.note_status("fail"); user_complete(nick, False) [if not standalone]
      tracer run_end/stopped; return "stopped"
    progress.note_status(status)
    if status == "ok" and not standalone: mark; person_marked.emit
    if not standalone: user_complete.emit(nick, status=="ok")
    if status == "stop": (unreachable now; kept defensive) return "stopped"
  return "worked"
```

Pre-mark gate detail: when `_execute_for_user` returned `"ok"` but stop was
requested during the final block, the user is reported `user_complete(nick,
False)`, counted `failed` (stop→fail), **not** marked, and the cycle returns
`stopped`. An explicit `MARK_MESSAGED` block that already ran inside
`_execute_for_user` keeps its write (no rollback — pinned).

`execute` lifecycle (C1):

```
async def execute(self, scroll_parser=None) -> None:
  if self._running: log Already running; return              # unchanged
  self._running, self._stop_requested, self._paused = True, False, False
  self._state.mark_running()                                 # now STOPPING-tolerant (§2.7)
  progress.reset/emit; _run_seq+=1; tracer=RunTracer(...); selected_nick=""
  ... existing start logs/tracer ...
  cycles, done, outcome = self._repeat_cycles(), False, "worked"
  run_error = None  # BaseException capture for precedence
  try:
    await maybe_await(self._hooks.pre_run(self))
    ... existing repeat announcement ...
    for cycle in 1..cycles:
      if is_stop_requested: debug stopped; tracer run_end/stopped; outcome="stopped"; break
      await self._wait_if_paused()
      if is_stop_requested: debug stopped; tracer run_end/stopped; outcome="stopped"; break  # NEW
      ... existing cycle_start logs ...
      try:
        outcome = await self._execute_cycle()
      except RunStopped:
        outcome = "stopped"; debug stopped; tracer run_end/stopped; break
      if outcome in {"stopped","empty_stack"}: done = (outcome=="empty_stack"); break
      if outcome == "empty": ... done=True; break
      if cycle >= cycles: done=True
    if done:
      self._state.mark_done(); tracer run_end/completed
    elif outcome == "stopped" or is_stop_requested(self):
      self._state.mark_done()                                # STOPPING→DONE (NEW)
      # tracer run_end/stopped already noted at the boundary that observed it
  except asyncio.CancelledError as exc:
    run_error = exc
    self._state.mark_error()                                 # RUNNING/PAUSED/STOPPING→ERROR
    self.debug_msg.emit("⏹ Run cancelled — cleaning up…", "warn")
    self._tracer.note({"type": "run_end", "reason": "cancelled"})
    raise                                                    # after mandatory cleanup in finally
  except Exception as exc:
    run_error = exc
    self._state.mark_error(); ... existing error logs/tracer ...
  finally:
    # Mandatory cleanup runs even if post_run raises/cancels; original error wins.
    post_error = None
    try:
      await maybe_await(self._hooks.post_run(self, outcome))
    except asyncio.CancelledError as exc:
      post_error = exc
      self.debug_msg.emit(f"⚠ post_run cancelled: {exc}", "warn")
      try: self._tracer.note({"type": "hook_error", "hook": "post_run", "error": str(exc)})
      except Exception: pass
    except Exception as exc:
      post_error = exc
      self.debug_msg.emit(f"⚠ post_run failed: {exc}", "warn")
      try: self._tracer.note({"type": "hook_error", "hook": "post_run", "error": str(exc)})
      except Exception: pass
    try:
      if self._tracer is not None: self._tracer.close(); self._tracer = None
    finally:
      self._running = False; self._ctx = {}
      try: self.stack_complete.emit()
      finally: self.log_msg.emit("✅ Stack execution complete")
    # precedence: original run error/cancel propagates; else post_run error propagates
    if run_error is not None and post_error is not None:
      log.warning("post_run failed during %r cleanup: %r", run_error, post_error)
      # run_error already propagating (cancel) or already handled (Exception path logs it);
      # for the Exception path the method returns normally (existing contract: execute()
      # never raises for run-body Exceptions — verified by existing tests). So:
      # - CancelledError path: `raise` above already scheduled; post_error only reported.
      # - Exception path: post_error only reported (never masks the run error already logged).
      # - Success path with post_error: raise post_error? NO — existing contract is that
      #   execute() returns normally; post_run raising currently WOULD propagate (finally-raise).
      #   Decision: preserve propagation ONLY for the success path (raise post_error),
      #   after mandatory cleanup. Pinned by cleanup-contract tests.
      pass
    if run_error is None and post_error is not None:
      # success path, post_run failed → mark ERROR (was DONE) and propagate
      try: self._state.mark_error()
      except ValueError: pass
      raise post_error
```

Notes:

- `execute()` still never raises for ordinary run-body failures (existing
  tests `await engine.execute()` without `assertRaises`); only external
  cancellation and success-path `post_run` failure propagate.
- `stack_complete` emits exactly once on every path (success/stop/error/
  cancel/post-failure). `_running` reset, tracer close, `_ctx` clear are
  unconditional.
- Stopped runs end `DONE` (terminal, restartable); cancelled/error runs end
  `ERROR` (terminal, restartable via `mark_running` reset). No path strands
  `STOPPING`/`RUNNING`/`PAUSED`.

### 2.7 `services/run/state_machine.py` — restartable terminals

Minimal fix, public values and `_ALLOWED` matrix otherwise frozen:

```python
def mark_running(self) -> RunState:
    if self.state in (RunState.ERROR, RunState.DONE, RunState.STOPPING):
        self.reset()                       # NEW: tolerate stranded STOPPING
    return self.transition(RunState.RUNNING)
```

Rationale: with §2.6 every run ends terminal, `STOPPING` at `mark_running`
time means an older/interrupted path (or a direct `stop()` between runs
followed by an inconsistent manual state poke in tests). Resetting to `IDLE`
first preserves the public transition vocabulary while making
stop→start robust even if a future caller strands the machine. Existing
`mark_stopping`/`mark_done`/`mark_error` bodies unchanged; the full
transition-matrix test keeps passing (only `mark_running`-from-`STOPPING`
changes from `ValueError` to `RUNNING`, pinned as the intended fix).

Repeated `stop()` stays a safe no-op (`mark_stopping` from `STOPPING`
returns the state). Pause/resume vocabulary unchanged.

### 2.8 `services/run/cycle_plan.py` (C2, after C1 green)

Private, no Qt/DB/CDP imports. Pure decisions; the coordinator keeps all
signals/side effects.

```python
@dataclass(frozen=True)
class StackFacts:
    scroll_block: Any | None        # first enabled SCROLL_PARSE ref (identity, for collect)
    has_mem_click: bool             # enabled CLICK_USER with use_person_from_memory
    has_take: bool                  # enabled TAKE_PERSON present
    has_conditional_skip: bool      # enabled CONDITIONAL_SKIP present
    user_scoped_ids: tuple[str, ...]  # sorted unique enabled USER_SCOPED_BLOCKS ids
    stack_empty: bool               # len(blocks)==0 (actual stack, not enabled subset)
    all_disabled: bool              # stack non-empty but zero enabled

def inspect_stack(blocks) -> StackFacts   # single scan, central enabled-block rules
@dataclass(frozen=True)
class CycleDecision:
    mode: str   # "single_target" | "queued" | "standalone" | "empty" | "empty_stack" | "stopped"
    reason: str # "mem_click" | "queue" | "standalone" | "no_take_match" | "no_stack" |
                # "empty_queue" | "stopped" (see precedence table)
def choose_cycle_mode(facts, *, has_queue: bool, take_matched: bool, stopped: bool) -> CycleDecision
    # precedence (area doc §C2 table + stopped-first):
    # 1. stopped → stopped
    # 2. has_mem_click → single_target (TAKE/no-selection checks stay inside that path)
    # 3. has_take and not take_matched and not user_scoped_ids and not has_queue → empty/no_take_match
    # 4. has_queue → queued (even when stack empty — characterized, not changed)
    # 5. stack_empty → empty_stack
    # 6. user_scoped_ids → empty/empty_queue
    # 7. else → standalone
```

Snapshot semantics (no silent change): the coordinator keeps **two**
inspection points exactly as today — (a) the scroll lookup **before**
collection (it selects the collect block), (b) the full facts inspection
**after** collection/filter/order/take (it drives the mode branch). `C2`
does not hoist (b) before the awaits; a hook/action that legally mutates
`engine._stack` mid-preparation sees the same behavior as baseline. The only
change is that (b) is computed by one `inspect_stack` call instead of five
inline scans. A dedicated test mutates the stack from a `pre_run`/collect
hook and pins identical mode selection before/after extraction.

C1 and C2 stay in separate commits; C2 is a pure refactor behind the green
C1 gates (behavioral parity proven by the unchanged C1 + C2 suites).

---

## 3. Policies & decisions

- **Supported stop boundaries (cooperative, <500 ms with a cooperative fake
  CDP):** before/after every pause barrier; before each block; inside
  WaitPageLoad pre-delay/probe/poll-gap; inside retry backoff; after
  collect/filter/order/take preparation; before each user; before the
  automatic-mark write; at cycle/repeat boundaries. Excluded: a blocked event
  loop, an uninterruptible external await (real CDP write, real SQLite write),
  process kill (no cleanup claim).
- **Remote side effects are never rolled back:** cancelling the local await
  of a click/type/send/collect does not undo the browser/DB write. Only the
  read-only WaitPageLoad probe await is task-cancelled; everything else uses
  flag checks between steps. Already-completed explicit writes (including
  `MARK_MESSAGED`) stay completed.
- **Progress:** wire unchanged (`done/total/skipped/failed`); `stop` is
  accounted as `failed` at both cycle call sites; `note_status("stop")`
  itself stays a no-op emit (characterized). Stop identity lives in
  `outcome=stopped`, `user_complete(nick, False)`, `run_end/stopped` tracer
  + `⏹` debug lines.
- **State:** stopped→`DONE`, cancelled/error→`ERROR`; `mark_running` resets
  from `STOPPING` defensively. Repeated stop/pause/resume calls are safe.
- **Retry:** `RunStopped`/`CancelledError` bypass `should_retry` and
  `fallback` unconditionally (even for permissive subclasses).
- **Hooks:** `pre_run` failure → existing ERROR path (post_run still runs);
  `on_action_complete` failure → propagates after `finally` restoration
  (existing ERROR path); `post_run` failure → mandatory cleanup still runs,
  reported via `⚠` debug + `hook_error` tracer, propagates only on the
  success path; original run error/cancel always wins over `post_run` noise.
- **Presets:** no new public block attributes; `to_dict()`/schema outputs
  byte-identical (pinned by round-trip tests on WaitPageLoad).
- **No snapshot semantic change:** two inspection points preserved (§2.8);
  queue-nonempty still wins over empty-stack (characterized quirk, not a
  product change in this task).

---

## 4. What is NOT done (scope limits)

- No bridge/DB/history/collector/tab/normalization changes; no public API,
  signal, preset, schema, or dependency changes.
- No new wire progress category; no `ActionResult.STOP`; no `STOPPING`
  removal/rename; no cross-process lock; no crash-atomicity; no rollback of
  sent messages/DB writes; no force-unblock of stuck external IO.
- No `hooks.py`/`__init__.py`/shim edits; no shared-fixture edits; no
  existing-test rewrites (failing-before/passing-after is demonstrated with
  NEW tests; old tests must stay green as-is).
- No C2 extraction until C1 gates are green; no metric-gaming one-line
  helpers (CC≤10/cog≤15/nest≤4 are aims for new/rewritten cycle helpers,
  readability first).

---

## 5. Test plan (written BEFORE implementation)

New directories (C-owned): `tests/integration/run_safety/` (+ `__init__.py`
+ local `_helpers.py` with temp-CWD engine harness, fake CDP/memory/blocks,
deterministic fake clock — no `tests/conftest.py` edits, no global Qt fakes)
and `tests/unit/actions/test_wait_page_cancellation.py`.

| File | Group | Must assert (side effects, not only return codes) |
|---|---|---|
| `tests/unit/actions/test_wait_page_cancellation.py` | wait matrix (14 cases) | already-stopped: 0 probes, 0 pre-delay sleep, `RunStopped`; stop in pre-delay/poll-gap: prompt (<100 ms fake clock), `RunStopped`, no further probe; hanging probe + stop: task cancelled+awaited, no orphaned task, `RunStopped`; hanging probe + deadline: bounded, `FAIL`; engine None: OK/timeout as today; found/not-found/error/malformed: existing texts/levels + OK/FAIL; `to_dict`/schema round-trip unchanged |
| `tests/integration/run_safety/test_stop_contract.py` | C1a stop gates | stop-while-paused (between blocks/users/cycles): no new block/user/cycle starts; stop during collect/take/order/filter: outcome `stopped`, no mode work, no marks; stop during retry backoff: no next attempt, no fallback; final-OK + stop: no auto-mark, `user_complete(False)`, `failed+1`, outcome `stopped`; single-target stop: `stopped` not `worked`, no next repeat cycle; stop→start: terminal + restartable; repeated stop safe; explicit `MARK_MESSAGED` before stop not rolled back; stop latency <500 ms (fake CDP) |
| `tests/integration/run_safety/test_cleanup_contract.py` | C1c lifecycle | external `task.cancel()`: `CancelledError` propagates, no mark, no success trace, `_running` False, tracer closed+`None`, `stack_complete` once, state `ERROR`, restartable; `{{nick}}` + `_ctx` restored on cancel/stop/hook-raise; `pre_run` raise: ERROR path + post_run still runs + once-signal; `on_action_complete` raise: restoration + ERROR; `post_run` raise: cleanup still runs + once-signal + success-path propagates + error-path precedence (original wins, hook reported); permissive-retry + `RunStopped`: no retry, no fallback |
| `tests/integration/run_safety/test_cycle_plan_unit.py` | C2 pure table | `inspect_stack` rules (enabled/disabled/retired) + full `choose_cycle_mode` precedence matrix incl. `stopped`-first, `has_queue`-over-`empty_stack` quirk, take-miss, standalone; no Qt/DB/CDP imports (import-graph test) |
| `tests/integration/run_safety/test_cycle_modes.py` | C2 modes | real engine + fake CDP/memory/blocks/hooks: multi-user, zero-user, disabled, no-stack, standalone (no sentinel mark), take-miss, memory missing/present, order-column, label filter, conditional skip, one-fail-then-next, repeat termination; assert effect traces (collect/filter/order/take, block calls, marks, user signals, progress counters, outcomes) |
| `tests/integration/run_safety/test_cycle_event_order.py` | C2 order | signal/trace ordering: load/collect/filter/order/take, step_started/complete, marks, user_complete, progress increments, final outcome; volatile timestamps/run-ids normalized; stack-mutating hook parity (no snapshot change); stop-after-first-user, paused-stop, external-cancel event tails |

Baseline demonstration: at least the wait-already-stopped, stranded-`STOPPING`,
pause-starts-block, final-OK-marks, single-target-`worked`, and collect-`empty`
cases must FAIL on baseline; all must PASS after. Fault tests use
`IsolatedAsyncioTestCase`, temp CWD (tracer files out of repo), real
`RunCoordinator`/`RetryPolicy`/`RunProgress`/`RunStateMachine`, fake CDP with a
cooperative `evaluate`, and effect-trace assertions. No long sleeps; fake-clock
waits where timing matters.

Coverage targets (master plan §5): modified execution/cycle/cancellation code
≥90% line / ≥85% branch; global never below 80%/75% (baseline 88.44%/81.32%
explained if reduced); new/rewritten cycle helpers CC≤10/cog≤15/nest≤4.

---

## 6. Implementation steps (after green-red baseline)

1. Land tests (red) + record failing baseline outcomes in journal.
2. Add `actions/cancellation.py` (pure, unit-probed via new wait tests).
3. Make `RetryPolicy` stop-aware + `RunStopped` passthrough (no caller yet).
4. Rewire `WaitPageLoad` to cooperative cancellation (wait suite green).
5. Rewire execution boundaries (`error_recovery` + `progress` gates +
   `coordinator` cycle/run lifecycle + `state_machine` tolerance) — C1 green.
6. Extract `services/run/cycle_plan.py` + slim `_execute_cycle` behind green
   C1 gates — C2 green, parity proven (no C1 test changes).
7. Run targeted → full Python → JS entrypoints → coverage → `git diff --check`.
8. Fill journal: branch/head, changed files, repros, commands/results,
   coverage, API compat, deferred risks.

Commit boundaries: (1) design doc, (2) failing tests, (3) `cancellation` +
`wait_page` fix, (4) execution/cycle/state fix (C1), (5) `cycle_plan`
extraction (C2), (6) journal+coverage. No standalone red commit released.
C1 and C2 stay in separate reviewable commits.

---

## 7. Acceptance & gates

```bash
.venv/bin/python tools/build_stubs.py .venv /tmp/stublibs
export QT_QPA_PLATFORM=offscreen LD_LIBRARY_PATH=/tmp/stublibs
.venv/bin/python -m pytest tests --collect-only -q
.venv/bin/python -m pytest tests/integration/run_safety tests/unit/actions/test_wait_page_cancellation.py -q
COVERAGE_FILE=/home/user/analysis/.coverage .venv/bin/python -m coverage run --branch \
  --source=core,actions,backend,bridge,services,stores,app,main -m pytest tests -q \
  --deselect=tests/test_sash_webengine.py::TestSashWebEngine::test_grid_in_real_webengine
COVERAGE_FILE=/home/user/analysis/.coverage .venv/bin/python -m coverage json -o /home/user/analysis/coverage.json
status=0; for f in tests/test_*.js; do node "$f" || status=1; done; test "$status" -eq 0
.venv/bin/python tools/metrics/current_audit.py > /home/user/analysis/current.json
git diff --check
```

- New safety tests pass; key tests demonstrated failing on baseline.
- Existing suite still passes; no new skip/xfail/exclusion.
- Coverage per §5; new helpers CC≤10/cog≤15/nest≤4 (no one-line scatter).
- JS 20/20 (baseline stale `test_bridge_router.js` failure remains until B;
  no new JS failures).
- No unawaited coroutines / leaked handles / Qt contamination.
- Desktop smoke (manual, before release): disposable worlds; switch/delete/
  cancel a wait; people/labels/undo refresh; real-WebEngine on display/GL.

---

## 8. Risks & explicit non-promises

- External processes / process kill mid-write can leave partial work;
  reported truthfully where observed, never rolled back (no resurrection of
  sent messages or DB rows).
- A blocked event loop or an uninterruptible external await (real CDP write,
  real SQLite write, real network) cannot be interrupted in <500 ms; the
  latency gate covers cooperative fake-CDP paths only.
- Direct `HistoryService`/`UserMemory` writers bypass run stop; the run
  refuses/ignores post-stop marks but cannot exclude external writers.
- `services/run/hooks.py` stays frozen: nick-expansion primitives are reused
  as-is; only the `finally` discipline in the owned caller changes.

---

## 9. Journal placeholder (filled after implementation)

- Actual branch/head, changed files, baseline repros, test commands/results,
  coverage (line+branch separately), API compat diff, deferred risks.
  (Full journal lives in `docs/archive/2026-09-10-safety-refactor/SAFETY_REFACTOR_AREA_C_2026-09-10.md`.)
