# Area C — Implementation design (new structure)

Parent: [Safety master plan](SAFETY_REFACTOR_2026-09-10_PLAN.md) · [Area C task list](SAFETY_REFACTOR_AREA_C_2026-09-10.md)
Date: 2026-09-10 · Branch: `arena/01a08b7b-chat-v-bot` · Baseline: `3820136`
Status: **Design — no production changes yet.** Tests are written next, before any refactor.
Ownership: Area C files only (`services/run/coordinator.py`, `error_recovery.py`, `progress.py`,
`state_machine.py`, `actions/wait_page.py`, new `actions/cancellation.py`, new `services/run/cycle_plan.py`,
new `tests/integration/run_safety/`, new `tests/unit/actions/test_wait_page_cancellation.py`).
Frozen files (master plan §2) are not touched. `services/run/hooks.py` is deliberately **not**
owned/edited: nickname expansion stays where it is, the `finally` fix lands at its
call-site in `error_recovery.py`.

Process followed here: (1) understand fully → (2) this structure doc → (3) full test
coverage before refactoring → (4) smallest safety fix, then structure extraction.

---

## 1. Current behaviour (characterised from code + existing contracts)

### 1.1 Entry and loop (`services/run/coordinator.py::execute`)

```
execute():
  refuse if already running ("Already running")
  reset _running/_stop_requested/_paused, mark_running, progress.reset+emit, new tracer
  pre_run hook (awaitable-tolerant)
  for cycle in 1..repeat_cycles:
    if _stop_requested: emit stopped + tracer run_end(stopped); break   # (B1) outcome NOT set to "stopped"
    await _wait_if_paused()                                              # (B2) no re-check after barrier here
    outcome = _execute_cycle()
    stopped/empty_stack -> break (done only for empty_stack)
    empty -> done, break (repeat-aware log)
    last cycle -> done
  if done: mark_done + tracer run_end(completed)
  except Exception: mark_error + logs + tracer run_end(exception)
  finally:
    await post_run(outcome)      # (B3) cleanup below is skipped if post_run raises/cancels
    tracer.close; _running=False; _ctx={}; stack_complete.emit; "Stack execution complete"
```

Observations pinned by existing tests and kept:

- `execute` resets stale pause/stop at start (`test_a_new_run_clears_a_stale_*`).
- `Already running` guard (`test_already_running_is_refused`).
- Repeat N cycles; stop ends it; empty queue with user blocks ends repeats after one cycle.
- All-disabled stack reports user not-completed and marks nobody (B5).
- Tracer vocabulary: `run_start / repeat / cycle_start / run_end / run_skip / run_mode /
  phase / phase_end / step_start / step_end / step_skip / user_skip / detail /
  person_collected / person_purged / nick_selected / queue_mode`.

Defects / risks (code inspection + one reproduced probe; each gets a failing-before test):

| ID | Location | Behaviour today | Required |
|----|----------|-----------------|----------|
| B1 | `execute` pre-cycle stop | `break` leaves `outcome="worked"` and `done=False`; `post_run` sees wrong outcome; state stays `STOPPING` (not terminal) | set `outcome="stopped"`, emit existing stopped diagnostics, leave `done=False` but transition state to terminal `DONE` (stopped is a completed run, not an error); `post_run` receives `"stopped"` |
| B2 | pause barriers | `execute` checks stop before `_wait_if_paused` but not after; `_execute_cycle` queue loop same; `_execute_for_user` block loop same | re-check stop immediately after every `_wait_if_paused` and before starting the next block/user/automatic mark |
| B3 | `finally` cleanup | `post_run` awaited before mandatory cleanup; raising/cancelling `post_run` skips tracer close, `_running` reset, `stack_complete` | mandatory cleanup in inner `finally`; preserve original outcome/exception, report `post_run` failure separately (log + tracer), never mask cancellation |
| B4 | external `task.cancel()` | `CancelledError` (BaseException) propagates through `except Exception` untouched — good — but `finally` still awaits `post_run` first (B3) and per-action `_restore_block_attrs` is skipped (B5); no test pins "no success result / no automatic marking" | `finally`-safe restoration; `CancelledError` propagates after cleanup; no mark, no `user_complete(ok=True)`, no `mark_done`; state → `ERROR`? No — cancellation is not a run error: state → `DONE`? See §3.4. Decision: cancellation leaves state via `mark_error` only when an `Exception` caused it; pure external cancel transitions to `DONE` is wrong too. Keep `ERROR` for exceptions, and for external cancel reset to `IDLE` via `STOPPING→IDLE` is not right either. Chosen: external cancel is reported as `run_end(cancelled)` and state goes `ERROR`→restartable? No. Final: external cancel is **not** mapped to DONE/ERROR silently; the `finally` always emits `stack_complete` and resets `_running`; state machine uses existing `mark_error` only for `Exception`, and for `CancelledError` transitions `RUNNING/STOPPING→DONE`? Rejected. Instead: introduce no new state; on external cancel, call `mark_error` is misleading. So: on `CancelledError`, do **not** call `mark_error`/`mark_done`; explicitly `reset()` to `IDLE` (existing public transition) after cleanup and re-raise. `IDLE` is restartable and truthful ("no terminal outcome was produced"). Tested. |
| B5 | `_execute_for_user` restoration | `_restore_block_attrs` only on `except Exception` success path; `CancelledError`/`RunStopped`/hook-raise paths skip it; `_ctx` reset also skipped | `try/finally` around expansion; `_ctx` cleared in `finally`; hook failures contained (see §3.3) |
| B6 | `_run_single_target_cycle` masks stop | always returns `"worked"` even when `_execute_for_user` returned `"stop"`; progress notes raw `"stop"` (ignored) while queued path maps `stop→fail` | return `"stopped"` when status is `"stop"` (+ existing stopped tracer note); map progress `stop→fail` exactly like the queued path (legacy counter preserved, stop identity in outcome/trace) |
| B7 | `_stop_requested` stranded state | stop before any cycle leaves state `STOPPING`; next `execute` calls `mark_running` which raises `ValueError` from `STOPPING` (only `ERROR/DONE` reset first) | `execute` marks terminal `DONE` for stopped outcomes (B1); `state_machine.mark_running` additionally resets from `STOPPING` (defensive, restartable even if a caller stopped while idle then ran) — both covered |
| B8 | `WaitPageLoad.execute` ignores stop | no stop check at all; `pre_delay` + `cdp.evaluate` + `sleep(0.3)` uninterruptible; already-stopped run still probes (reproduced: 2 probes, `fail`) | cooperative `RunStopped` checks before delay/probe, after probe, during bounded sleeps; read-only probe awaited in ≤100 ms slices, cancelled+awaited on stop; timeout path preserved |
| B9 | `RetryPolicy` retries stop | `retry_with_backoff` catches `Exception` (would catch `RunStopped`) and sleeps `base_delay*2**attempt` without stop checks | `RunStopped` passes through (never retried, never fallback); backoff sleep is stop-aware (raises `RunStopped`); optional `is_stopping` predicate, no signature break (keyword-only, default `None`) |
| B10 | collect/take/queue stop gaps | `_run_collect_phase` swallows `Exception` → `[]` (empty-success misclassification if stop raised inside); `_run_take_phase` has no stop check; `_memory.get_queue` failure modes untested with stop | `RunStopped` propagates from collect (cycle maps to `"stopped"`); take phase checks stop before/after each `choose`; `get_queue` stop is observed at the next boundary (no claim of interrupting the memory await itself) |
| B11 | automatic-mark boundary | `_execute_cycle` marks `ok and not standalone` without a final stop re-check; a stop landing between the final block returning `OK` and the mark would still mark | re-check stop after `_execute_for_user` returns `ok` and before `mark_messaged`; stopped → `"stopped"`, no mark, no `user_complete(ok=True)` |
| B12 | `_wait_if_paused` granularity | `sleep(0.2)` slices; stop latency ≤200 ms + scheduling (acceptable) but pause+stop ordering untested at every site | keep 200 ms slices (no churn), add post-barrier re-checks (B2); unit test pins prompt exit without long sleeps (event-driven, not wall-clock) |

Accounting (characterised, frozen): `RunProgress.note_status` counts only `ok/skip/fail`
and ignores any other string (including `"stop"`). The queued path therefore maps
`stop→fail` before noting; the single-target path does not (B6). There is **no**
`stopped` progress counter on the wire and none is added. Stop identity lives in the
cycle outcome (`"stopped"`), per-user status (`"stop"`), tracer `run_end(stopped)` and
the `⏹` debug line. `failed` incrementing on stop is the preserved legacy mapping,
documented in tests, not a new semantic.

State machine (characterised, `services/run/state_machine.py`):

- Values frozen: `idle/running/paused/stopping/error/done`.
- Allowed edges frozen except the `mark_running` entry fix (B7): `STOPPING` is added
  to the reset-first set (`ERROR/DONE/STOPPING → IDLE → RUNNING`). No `_ALLOWED`
  edge is added or removed; `STOPPING→IDLE→RUNNING` already exists as two legal
  steps, the fix just performs them.
- `stop()` (`mark_stopping`) is a no-op outside `RUNNING/PAUSED` (repeated stops safe).
- `mark_done` only from `RUNNING/STOPPING`; `mark_error` direct from `IDLE`.

### 1.2 Cycle (`_execute_cycle`, CC 31 — the extraction target)

Current order (must be preserved):

```
1. scroll = first enabled SCROLL_PARSE (before any await)
2. queue = collect_phase(scroll) if scroll else memory.get_queue()
3. queue = filter_by_labels(queue, announce=True)
4. queue = _order_queue_by_column(queue)   # only when a CLICK_USER respect_order is on
5. take_matched = _run_take_phase()
6. has_skip / mem_click / needs_user / take_present  (second stack scan, after awaits)
7. mem_click present -> single-target path (TAKE/no-selection checks inside that path)
8. take_present and not matched and not needs_user and empty queue -> "empty" (no_take_match)
9. queue nonempty -> queued mode (extend_total, loop users)
   stack empty -> "empty_stack"
   needs_user -> "empty" (empty_queue)
   else -> standalone (synthetic UserRecord("—"), extend_total(1))
10. per-user loop: stop-check, pause barrier, _execute_for_user, progress map,
    auto-mark (ok, non-standalone), user_complete (non-standalone), stop -> "stopped"
11. return "worked"
```

Stack-mutation hazard: steps 1 and 6 sit on opposite sides of awaits (collect, order,
take). A hook (`pre_run`/`on_action_complete`) or a block could legally mutate
`engine._stack` between them. Therefore **no blind pre-collection snapshot**.
The extraction keeps two inspection points: scroll lookup before collection (step 1)
and full facts after take (step 6). `cycle_plan.inspect_stack` is a pure function of
the passed list; the coordinator decides *when* to call it. No frozen-stack semantic
change.

Single-target path (`RunQueueMixin._run_single_target_cycle`):

```
take_present and not matched -> "empty" (no_take_match)
no selected_nick -> "empty" (no_memory_nick)
extend_total(1); _execute_for_user(UserRecord(target)); note_status(raw); mark if ok;
user_complete(target, ok==True); return "worked"   # B6: stop masked
```

Take phase (`_run_take_phase`): iterates enabled `TAKE_PERSON` blocks, sync `choose(rows, engine)`;
keeps previous selection on no-match; announces each pick. No stop awareness (B10).

Collect phase (`RunExecutionMixin._run_collect_phase`): emits phase, reads known-messaged
(fail-open), `retry_with_backoff(block.run_pipeline)`, upserts collected (warn-contained),
announces seek/hit/miss/counts, notes `phase_end`, and returns `[]` when
`result.stopped or _stop_requested` ("not queueing anyone"). Crash → `[]` via
`_collect_failed` re-raise contained by the caller's `except Exception`. (B10: `RunStopped`
must not take the crash/empty path.)

Per-user execution (`_execute_for_user`): messaged+has_skip fast-path `"skip"`;
all-disabled guard `"skip"` (B5 is about restoration, not this guard — guard stays);
per-block: stop-check, pause barrier, disabled skip, `CONDITIONAL_SKIP` handling,
marker skip (`SCROLL_PARSE/REPEAT_LOOP/TAKE_PERSON` silently skipped in the user loop),
`_expand_nick_on_block`, `retry_with_backoff(block.execute, fallback=_step_failed)`,
restore, `_handle_step_result` (OK/SKIP/FAIL → ok/skip/fail), `_call_action_hook`,
non-ok short-circuits the user. (B2/B5/B9/B11 apply here.)

### 1.3 Wait (`actions/wait_page.py::execute`, cognitive 28 — the cancellation target)

```
await pre_delay()                       # uninterruptible (B8)
deadline = loop.time() + timeout_ms/1000  # loop.time, not monotonic
loop:
  raw = await cdp.evaluate(build_probe(selector))   # uninterruptible (B8)
  res = json.loads(raw) if raw else None            # malformed -> res=None via except? No: json error inside try -> probe-error path
  except Exception: report every 5th, res=None
  found -> interpret_wait -> OK
  now >= deadline -> break
  every 7th attempt (from 1st): throttled "not present yet" warn
  await sleep(0.3)                                  # uninterruptible (B8)
report timeout with last total -> FAIL
```

Preserved: found/timeout/error/malformed diagnostics, throttling cadence (5/7),
`interpret_wait` messages, `timeout_ms=0` meaning "single probe then timeout",
`TEXTAREA_SEL` default, `config_schema`/`to_dict` round-trip, no-engine usability.

---

## 2. New structure

### 2.1 `actions/cancellation.py` (new, private, dependency-free)

Constraints: no `services`, no `Qt`, no `actions.base*` imports (avoid cycles);
only stdlib (`asyncio`, `time`, `typing`). Actions and `services/run/*` may import it.

```python
"""Private cooperative-stop helpers. Not part of the action wire contract."""

class RunStopped(Exception):
    """Cooperative stop requested. Distinct from asyncio.CancelledError (external task
    cancellation). Raised by stop-aware waits; translated to "stop"/"stopped" only at
    run-execution boundaries. Never retried, never mapped to ActionResult."""

def is_stop_requested(engine) -> bool:
    """True when engine asks to stop. engine=None -> False.
    Prefers callable engine.is_stopping(); falls back to truthy engine._stop_requested
    for old duck-typed callers; any error/absence -> False (fail-open, never crash a block)."""

def raise_if_stopped(engine) -> None:
    """Raise RunStopped when is_stop_requested(engine)."""

async def sleep_or_stop(delay_s: float, engine=None, *, slice_s: float = 0.05) -> None:
    """Bounded sleep in short slices; raises RunStopped promptly when stopped.
    delay<=0 returns immediately (after one stop check). slice_s clamped to (0, delay]."""

async def await_or_stop(awaitable, engine=None, *, slice_s: float = 0.05):
    """Await a read-only awaitable (CDP probe) in short slices.
    Wraps it in a Task, polls for stop/completion, and on stop cancels + awaits the task
    (suppressing its CancelledError) before raising RunStopped. On completion returns the
    result (or raises the awaitable's own exception unchanged). Caller must only use this
    for read-only probes — cancelling the local await never undoes a remote side effect."""
```

Semantics pinned by tests:

- `is_stop_requested(None)` is `False`; `is_stopping` non-callable ignored; `_stop_requested`
  fallback honoured; raising `is_stopping` fails open to `False`.
- `sleep_or_stop` with `engine=None` behaves like `asyncio.sleep` (bounded); with a
  pre-stopped engine raises immediately without sleeping; stop mid-sleep raises within
  ~`slice_s` (event-driven test, no wall-clock flakiness: the test stops the engine from
  a timer callback after 20 ms and asserts prompt raise and no further work).
- `await_or_stop` returns the probe value on success; propagates probe exceptions
  unchanged (no `RunStopped` confusion); on pre-stop cancels the probe task and raises;
  on stop-during-probe cancels+awaits (no orphaned task warnings) and raises; never
  touches `ActionResult`.
- `RunStopped` is an `Exception` subclass (so existing `except Exception` sites must
  explicitly re-raise it — the fix is audited at every such site in §3).

Why an exception, not a return code: stop must unwind through arbitrary block depths
(`block.execute` → retry → user loop → cycle → run) without every intermediate layer
inventing a new `None`/`SKIP` meaning (master plan §3.3 forbids overloading `SKIP` and
adding a public `STOP` result). The exception is caught exactly at the three execution
boundaries (`_execute_for_user` → `"stop"`, `_run_collect_phase`/`_execute_cycle`/
`execute` → `"stopped"`) and nowhere else.

### 2.2 `services/run/cycle_plan.py` (new, private, pure)

Constraints: no `Qt`, no `DB`, no `CDP`, no signals, no side effects. Imports only
`dataclasses`, `typing`, and `USER_SCOPED_BLOCKS` from `.hooks` (a constant, not a mixin —
accepted; alternatively duplicated frozenset — decision: import the constant to avoid
drift, it creates no runtime coupling).

```python
@dataclass(frozen=True, slots=True)
class StackFacts:
    scroll_block: Any | None          # first enabled SCROLL_PARSE reference (identity kept for the collect call)
    has_memory_click: bool            # enabled CLICK_USER with use_person_from_memory
    has_take: bool                    # any enabled TAKE_PERSON
    has_conditional_skip: bool        # any enabled CONDITIONAL_SKIP
    user_scoped_ids: tuple[str, ...]  # sorted enabled block_ids ∩ USER_SCOPED_BLOCKS (for diagnostics)
    is_empty: bool                    # len(blocks) == 0  (actual stack empty, before enabled filtering)
    enabled_count: int                # number of enabled blocks (all-disabled detection stays in _execute_for_user)

def inspect_stack(blocks) -> StackFacts: ...
    # single pass; getattr(block,"enabled",True); getattr(block,"block_id","");
    # memory-click requires getattr(block,"use_person_from_memory",False) truthy.

@dataclass(frozen=True, slots=True)
class CycleDecision:
    mode: str        # "single_target" | "queued" | "standalone" | "empty" | "empty_stack"
    reason: str      # "memory_click" | "queue" | "standalone" | "no_take_match" |
                     # "no_memory_nick" (single-target inner) | "empty_queue" | "empty_stack"

def choose_cycle_mode(facts: StackFacts, *, has_queue: bool, take_matched: bool) -> CycleDecision: ...
    # precedence (after preparation — collect/filter/order/take have run):
    # 1. has_memory_click            -> single_target (TAKE/no-selection checks stay inside the path)
    # 2. has_take and not take_matched and not user_scoped_ids and not has_queue -> empty/no_take_match
    # 3. has_queue                   -> queued   (even when is_empty — preserved ordering, see note)
    # 4. is_empty                    -> empty_stack
    # 5. user_scoped_ids             -> empty/empty_queue
    # 6. else                       -> standalone
```

Notes:

- Queued-before-empty-stack ordering is today's behaviour (`if queue:` precedes
  `elif not self._stack:`). A queue with an empty stack can only arise from
  `memory.get_queue()` (no scroll block) or a hook-injected queue; the standalone fallback
  for truly empty stacks stays unreachable in that corner until a product decision says
  otherwise. The decision table pins it; the doc calls it out so no "cleanup" silently
  flips it.
- `enabled_count==0` with a non-empty stack is **not** a cycle mode: today's code falls
  through to queued/standalone and relies on `_execute_for_user`'s all-disabled `"skip"`
  guard. That guard stays the single owner (B5 regression); `cycle_plan` does not duplicate it.
- Stop is not a `CycleDecision`: stop pre-empts at the C1 boundaries and maps to
  `"stopped"` outside the pure planner (planner has no engine access by construction).
- The coordinator keeps the orchestration narrative (§1.2 steps 1–11) verbatim; only the
  branching in steps 7–9 delegates to `inspect_stack`/`choose_cycle_mode`, and the per-user
  loop in step 10 delegates its body to small private helpers (`_run_queued_users`,
  `_run_standalone_user`) so `_execute_cycle` drops to CC ≤10 without scattering conditions
  into meaningless one-liners. Each helper keeps a visible, scenario-matrix-covered job.

### 2.3 Call-graph after C2 (private helpers, same public API)

```
RunCoordinator.execute                       (public, signals unchanged)
 └─ _execute_cycle                           (private, same outcome vocabulary)
     ├─ scroll lookup (inline, pre-collect — step 1, NOT snapshotted)
     ├─ _run_collect_phase / memory.get_queue
     ├─ filter_by_labels / _order_queue_by_column   (unchanged)
     ├─ _run_take_phase                          (stop-aware, §3)
     ├─ cycle_plan.inspect_stack(self._stack)    (post-take facts — step 6)
     ├─ cycle_plan.choose_cycle_mode(facts, has_queue, take_matched)
     ├─ _emit_mode_diagnostics(decision, ...)    (existing log/debug/tracer lines, moved verbatim)
     ├─ _run_single_target_cycle  (existing boundary, B6 fix)
     ├─ _run_queued_users(queue, standalone)     (extracted loop body: stop/pause/execute/mark/emit)
     └─ _run_standalone_user(...)                (one synthetic user via the same body)
RunExecutionMixin._execute_for_user           (stop-aware, finally-safe, §3)
RetryPolicy.retry_with_backoff               (RunStopped passthrough + stop-aware backoff, §3)
RunQueueMixin._wait_if_paused                (unchanged granularity + documented contract)
WaitPageLoad.execute                         (stop-aware, §3)
```

No service locator, no context object carrying the engine, no new public symbols on
`RunCoordinator`/`ActionEngine`/`RetryPolicy` beyond a keyword-only optional predicate.

---

## 3. C1 fixes (behaviour; each lands behind a failing-before test)

### 3.1 `actions/wait_page.py`

Rewrite `execute` around `cancellation.py` (helpers stay local/private; no new public
action settings, so `to_dict()` is unchanged):

```
raise_if_stopped(engine)                                   # already-stopped: no delay, no probe
await sleep_or_stop(pre_delay_ms/1000, engine)             # stop during pre-delay
report "Waiting for ..." (existing wording)
deadline = monotonic() + timeout_ms/1000                   # monotonic, not loop.time
attempt loop:
  raise_if_stopped(engine)                                 # before each probe
  probe_task = await_or_stop(cdp.evaluate(build_probe(selector)), engine)  # ≤100 ms slices
  parse (existing: json.loads if raw else None; exceptions -> throttled probe-error path)
  found -> interpret_wait -> OK (existing messages)
  raise_if_stopped(engine)                                 # after probe, before deadline check
  monotonic() >= deadline -> break
  throttled "not present yet" warn (attempt%7==1, existing)
  await sleep_or_stop(0.3 slice? No: 0.3 in ≤100 ms slices)  # stop during polling delay
timeout report (existing wording, last total) -> FAIL
```

Cooperative-stop outcome: `RunStopped` propagates to the caller (the engine maps it to
`"stop"`/`"stopped"`; a bare `block.execute` caller sees the exception — documented, and
unit tests assert it rather than a fake `ActionResult`). No `SKIP`-as-`STOP`, no new
result constant. `engine=None` preserves today's success/timeout behaviour exactly.
Malformed probe payloads keep today's diagnostics (probe-error throttling every 5th from
attempt 1; not-present throttling every 7th from attempt 1).

CDP cancellation note: `await_or_stop` cancels only the local `evaluate` awaitable for
this read-only probe. `backend/cdp_client.py` is frozen; its `send()` has no cancellation
entrypoint and `evaluate` holds no lease, so the worst case is a late-arriving probe
response being dropped — no remote side effect exists for a read probe. Verified by a
test with a controllable fake CDP (event-gated `evaluate`); a note is filed that a real
`CDPClient.evaluate` cancellation contract (lease-aware abort) is out of scope for Area C.

### 3.2 `services/run/error_recovery.py`

`RetryPolicy`:

```python
def should_retry(self, exc, attempt) -> bool:
    if isinstance(exc, RunStopped): return False        # never retried, even by permissive subclasses
    ... (existing transient check unchanged)

async def retry_with_backoff(self, op, *, fallback=None, is_stopping=None):
    # is_stopping: optional ()->bool, keyword-only, default None (back-compat).
    attempt = 0
    while True:
        if callable(is_stopping) and is_stopping(): raise RunStopped()
        try:
            return await op()
        except RunStopped:
            raise                                            # passthrough: no fallback, no counter
        except asyncio.CancelledError:
            raise                                            # passthrough: external cancellation, no fallback
        except Exception as exc:
            if not self.should_retry(exc, attempt):
                return await fallback(exc) if fallback else (_raise(exc))
            await _sleep_stop_aware(self.base_delay * (2**attempt), is_stopping)
            attempt += 1
```

`_sleep_stop_aware` uses ≤50 ms slices and raises `RunStopped` when the predicate fires;
`is_stopping=None` degrades to plain `asyncio.sleep` (existing timing preserved).
A permissive-subclass test (`should_retry` always `True`) proves `RunStopped` still
propagates without retry/fallback.

`_run_collect_phase(self, block)`:

- `except RunStopped: self._ctx = {}; raise` before the generic `except Exception → []`.
- `except asyncio.CancelledError: self._ctx = {}; raise` (no silent empty queue on external cancel).
- Pass `is_stopping=self.is_stopping` into `retry_with_backoff` so stop during
  collect-retry backoff aborts without fallback.
- Keep the existing `result.stopped or _stop_requested → []` ("not queueing anyone")
  path — it is the graceful post-collection stop, distinct from mid-collection
  `RunStopped` (which now propagates to `"stopped"` instead of masquerading as empty).

`_execute_for_user(self, user, has_skip)`:

```
if _stop_requested: announce + tracer + return "stop"          # existing, kept
...
for idx, block in enumerate(stack, 1):
  if _stop_requested: ... return "stop"                        # existing, kept
  await _wait_if_paused()
  raise_if_stopped(self) -> caught below as "stop"             # NEW: post-barrier re-check (B2)
  ... disabled / CONDITIONAL_SKIP / marker handling (unchanged)
  originals = _expand_nick_on_block(...)
  try:
    try:
      result = await retry(..., is_stopping=self.is_stopping)
    except RunStopped:
      tracer run_end(stopped) + debug "⏹" ; return "stop"      # cooperative stop, no fallback
    except asyncio.CancelledError:
      raise                                                    # finally restores, then propagates
    except Exception:
      return "fail"                                            # _step_failed already ran via fallback
    status = _handle_step_result(...)
    try:
      await _call_action_hook(...)
    except (RunStopped, asyncio.CancelledError):
      raise
    except Exception as hook_exc:
      log.warning("on_action_complete failed: %s", hook_exc)   # NEW: hook containment (was unhandled)
  finally:
    _restore_block_attrs(block, originals); self._ctx = {}     # NEW: always restores (B5)
  if status != "ok": return status
return "ok"
```

`_collect_failed`/`_step_failed` gain an explicit `RunStopped`/`CancelledError` guard
(never invoked for those — defence in depth if a future caller forgets the passthrough).

### 3.3 `services/run/progress.py`

- `_wait_if_paused`: unchanged body (`while _paused and not _stop_requested: sleep(0.2)`),
  documented contract: exits promptly on stop (≤200 ms + scheduling); external
  cancellation propagates (the sleep is cancellable); every caller re-checks stop after it.
- `_run_single_target_cycle`: after `_execute_for_user`, `if status == "stop": tracer
  run_end(stopped); return "stopped"` (B6); progress mapping becomes
  `note_status("fail" if status == "stop" else status)` (queued parity, legacy counter).
  `user_complete(target, status == "ok")` unchanged (stop reports not-done).
- `_run_take_phase`: `raise_if_stopped(self)` before reading memory and inside the block
  loop before each `choose` (B10); `RunStopped`/`CancelledError` propagate (no `"no match"`
  misclassification); existing choose-exception containment unchanged.
- `_order_queue_by_column` / `filter_by_labels` / `queue_order` / `RunProgress`: unchanged
  (accounting frozen). `RunProgress.note_status("stop")` remains a documented no-op at the
  unit level; the engine never passes raw `"stop"` to it after B6.

### 3.4 `services/run/coordinator.py`

`execute` (same signals, same tracer vocabulary, same public behaviour except the listed fixes):

```
cycles, done, outcome = ..., False, "worked"
run_exc = None
try:
  await maybe_await(pre_run)                      # hook raise -> except Exception path (existing)
  ... repeat announce ...
  for cycle ...:
    if _stop_requested:
      outcome = "stopped"                         # FIX B1 (was left as "worked")
      debug "⏹" + tracer run_end(stopped); break
    await _wait_if_paused()
    if _stop_requested:                           # FIX B2 (post-barrier re-check)
      outcome = "stopped"; debug + tracer; break
    ... cycle_start announce ...
    try:
      outcome = await _execute_cycle()
    except RunStopped:                            # cooperative stop from collect/take
      outcome = "stopped"; debug + tracer; break
    # CancelledError is NOT caught here — it unwinds to the outer finally, then re-raises.
    if outcome in {"stopped","empty_stack"}: done = (outcome == "empty_stack"); break
    ... (empty/last-cycle handling unchanged)
  if done or outcome == "stopped":                # FIX B1/B7: stopped runs terminate
    self._state.mark_done(); tracer run_end(completed if done else stopped)
    # note: the loop already noted run_end(stopped); the terminal note here is
    # run_end(completed) only for done; for stopped the loop note stands and no
    # duplicate is emitted (decision: single run_end(stopped) from the break site).
except asyncio.CancelledError:
  run_exc = ... ; raise                           # flagged for finally precedence, then re-raised
except Exception as exc:
  self._state.mark_error(); ... existing logs + tracer run_end(exception)
finally:
  post_exc = None
  try:
    await maybe_await(post_run(outcome))          # outcome is always meaningful now
  except asyncio.CancelledError as exc:
    post_exc = exc                                # cleanup still runs below
  except Exception as exc:
    post_exc = exc; log + debug + tracer note (type run_hook_error, hook post_run)
  try:
    if tracer: close; tracer=None
    _running=False; _ctx={}
    stack_complete.emit(); log "Stack execution complete"
  finally:
    if run_exc is not None: raise run_exc         # original cancellation/error wins
    if post_exc is not None and isinstance(post_exc, asyncio.CancelledError): raise post_exc
    # ordinary post_run Exception is reported, not raised (execute() stays non-raising
    # for hook failures, as today — only cancellation propagates).
```

External-cancel state (B4 decision): when the run unwinds via `CancelledError`, the
`finally` above resets `_running`, closes the tracer and emits `stack_complete`, then
re-raises; the state machine is explicitly `reset()` to `IDLE` in that path (existing
public transition, no new value). Rationale: cancellation produced no terminal run
outcome, so neither `DONE` nor `ERROR` is truthful; `IDLE` is restartable and matches
"the run did not complete". A tracer `run_end(cancelled)` note is emitted before close.
Tested: cancel mid-block → `CancelledError` propagates, no mark, no `user_complete(ok)`,
`is_running` False, `stack_complete` once, next `execute` starts cleanly.

`_execute_cycle` (C1 shape — C2 delegates the branching, §2.3):

- After `queue = await collect/get_queue`: `if _stop_requested: tracer run_end(stopped);
  return "stopped"` (covers stop during `get_queue` — B10, no claim of interrupting the await).
- After take phase: same check (take raises `RunStopped` itself, but an external stop
  landing between take and mode selection must also pre-empt).
- Mode branches emit today's diagnostics verbatim (moved to `_emit_mode_diagnostics` in C2).
- Per-user loop:

```
for user in queue:
  if _stop_requested: ... return "stopped"
  await _wait_if_paused()
  if _stop_requested: ... return "stopped"      # NEW post-barrier re-check (B2)
  try:
    status = await _execute_for_user(user, has_skip)
  except RunStopped:                             # defence in depth (user-level already maps it)
    ... return "stopped"
  progress.note_status("fail" if status == "stop" else status)   # unchanged mapping
  if status == "ok":
    if _stop_requested: ... return "stopped"    # NEW mark boundary (B11), no mark
    if not standalone: mark + person_marked
  if not standalone: user_complete(nick, status == "ok")
  if status == "stop": tracer run_end(stopped); return "stopped"
return "worked"
```

- `_run_single_target_cycle` `RunStopped` from take propagates through the same path
  (its inner `RunStopped` is caught in `execute`'s cycle `try`, or directly if the
  single-target call itself is wrapped — decision: wrap the single-target call in
  `_execute_cycle` with the same `except RunStopped → "stopped"`).

### 3.5 `services/run/state_machine.py`

Single fix (B7): `mark_running` resets from `STOPPING` as well as `ERROR`/`DONE`:

```python
def mark_running(self):
    if self.state in (RunState.ERROR, RunState.DONE, RunState.STOPPING):
        self.reset()
    return self.transition(RunState.RUNNING)
```

No `_ALLOWED` change, no new value, no signature change. Repeated `stop()` stays a
no-op outside `RUNNING/PAUSED`; stopping a paused/running run then starting again is
tested, including stop-while-idle-then-run.

---

## 4. C2 extraction (structure; no behaviour change beyond C1)

Precondition: all C1 tests green, plus the existing regression gates
(`test_run_engine_p0_pins`, `test_run_service_paths`, `test_run_state_machine_contract`,
`test_services_run`, `test_action_engine_sequence`, `test_engine_standalone_run`,
`test_repeat_loop`, `test_click_user_memory`, `test_click_user_order`, `test_take_person`,
`test_scroll_only_seek`, `test_scroll_parse_pipeline`, `test_nick_placeholder`, full suite).

Steps (each keeps the suite green):

1. Add `services/run/cycle_plan.py` (pure, §2.2) + its decision-table unit test. No
   coordinator change yet.
2. Add `_emit_mode_diagnostics` + `_run_queued_users`/`_run_standalone_user` private
   helpers to the coordinator; move the existing diagnostic lines and loop body verbatim
   (mechanical move, no logic edits). `_execute_cycle` calls them; suite stays green.
3. Replace the inline stack scans + `if/elif` chain with
   `facts = inspect_stack(self._stack)` + `choose_cycle_mode(...)` + dispatch on
   `decision.mode`. Keep the pre-collect scroll lookup inline (step 1) and the post-take
   facts (step 6) — two call sites, documented.
4. Re-measure: `_execute_cycle` and helpers target CC ≤10, cognitive ≤15, nesting ≤4
   (Radon + cognitive-complexity, same definitions as the audit). Readability beats metric
   tricks: no one-line helper scattering; the scenario matrix (§5) still visibly covers
   every decision.

Behaviour parity proof: `tests/integration/run_safety/test_cycle_modes.py` (effect traces
per mode) + `test_cycle_event_order.py` (signal/tracer/progress ordering) run identically
before and after step 3 (added in the test-first phase against current code, then kept
unchanged through the extraction).

---

## 5. Test plan (written before the refactor; failing-before demonstrated)

New files (Area C owned):

| File | Covers | Key assertions |
|------|--------|----------------|
| `tests/unit/actions/test_wait_page_cancellation.py` | wait §3.1 + `cancellation.py` unit contract | pre-stopped → `RunStopped`, 0 probes, 0 delay; stop in pre-delay/polling/probe → prompt `RunStopped`, no further probes; hanging probe bounded by deadline, cancellable, no orphaned task; `engine=None` success/timeout preserved; found/not-found/error/malformed diagnostics preserved; throttling cadence preserved; `to_dict` has no cancellation state; `RunStopped` ≠ `CancelledError`; `sleep_or_stop`/`await_or_stop` unit matrix; fake-clock/event-driven (no long sleeps) |
| `tests/integration/run_safety/test_stop_contract.py` | B1/B2/B6/B7/B8/B9/B10/B11 + decision precedence | stop-while-paused never starts another block; stop during collect/take/queue-prep → `"stopped"`, no downstream action, no auto-mark; stop during retry backoff → no next attempt, no fallback, no fail-counter as transient; stop on final-OK before mark → no mark, `"stopped"`; single-target stop → `"stopped"`, no next repeat; stop-then-new-run restartable (incl. repeated stops, stop-while-idle); permissive-retry `RunStopped` passthrough; progress `stop→fail` parity queued vs single-target; `<500 ms` stop gate with cooperative fake CDP (excludes blocked loops/uninterruptible IO, documented) |
| `tests/integration/run_safety/test_cleanup_contract.py` | B3/B4/B5 + hook precedence | `post_run` raising → cleanup still runs (tracer closed, `_running` False, `stack_complete` once), original outcome preserved, hook error separately reported; `post_run` cancelling → cleanup runs, `CancelledError` propagates; external `task.cancel()` mid-block/mid-collect/mid-pause → propagates after cleanup, no mark, no success signals, state `IDLE`, restartable; `pre_run`/`on_action_complete` raising → contained, `_ctx` cleared, expansion restored, run continues/ends per existing contract; `{{nick}}` expansion restored under `RunStopped` and `CancelledError`; `stack_complete` emitted exactly once in every path |
| `tests/integration/run_safety/test_cycle_modes.py` | §2.2 precedence + §1.2 parity | one test per decision row (memory-click precedence, take-miss-no-user-blocks, queued incl. empty-stack-with-queue, empty-stack, empty-queue-with-user-blocks, standalone, all-disabled, stop-pre-empts); standalone never marks `—`; fail/skip never auto-mark; single-target runs selected nick once per cycle; memory-click/TAKE interaction; repeat termination; label-filter-then-order preserved; retired keys ignored |
| `tests/integration/run_safety/test_cycle_event_order.py` | observable ordering | effect traces (load/collect/filter/order/take, block executions, marks, `user_complete`/`person_marked`/`step_*` signals, progress increments, tracer `type` sequence with volatile `ts`/`run_id` normalised); multi-user, zero-user, disabled, no-stack, standalone, take-miss, memory missing/present, repeat end, fail-then-next-user, conditional skip, stop-after-first-user, paused-stop, external cancel |
| `tests/integration/run_safety/test_cycle_plan_unit.py` | pure planner | exhaustive `choose_cycle_mode` truth table (no Qt/signals); `inspect_stack` single-pass rules (enabled filtering, memory-click detection, scroll identity, user-scoped sorting, empty/enabled counts) |

Harness rules (frozen `tests/conftest.py` respected — real PySide6, no global fakes):

- Real `RunCoordinator` (QObject) with fake CDP/memory/blocks/hooks; `ActionRegistry`
  snapshot/restore around modules that define fake blocks (same pattern as the existing
  `test_services_run.py`).
- `RunTracer` writes to per-test temp CWD (`logs/` under temp dir).
- Deterministic timing: `asyncio.Event`/call-count gates, never `sleep(>0.5)`; the only
  wall-clock assertion is the `<500 ms` cooperative-stop gate, measured with `monotonic`
  around an already-gated scenario.
- No stubbing of `_execute_cycle` in tests that validate it; no relaxation of existing
  regression tests.

Coverage targets (master plan §5): modified execution/cycle/cancellation code ≥90% line /
≥85% branch; new `cycle_plan`/`cancellation` modules ≥90% / ≥85% with every destructive
or stop invariant tested regardless of percentage.

---

## 6. What is explicitly NOT changing

- No new `ActionResult` constant; no `None`-as-stop; no `SKIP`-as-`STOP`.
- No new progress wire category; `RunProgress.note_status` untouched.
- No new state value; no `_ALLOWED` edge change; no signal/slot signature change.
- No `bridge/*`, no `backend/*` (incl. `cdp_client`), no `stores/*`, no `core/*`,
  no `services/undo_service.py`, no `services/history/*`, no `services/db_*`,
  no `app/*`, no `main.py`, no `requirements.txt`/`pytest.ini`, no `tests/conftest.py`,
  no existing snapshot files.
- No claim that stop rolls back already-started writes (sent messages, DB marks before
  the boundary) or interrupts truly uninterruptible external IO / a blocked event loop.
- No product change to queued-before-empty-stack ordering, standalone semantics, label
  filter order, order-column semantics, retired-key handling, preset formats, or the
  history-push coroutine warning (separately owned).

---

## 7. Implementation journal (filled as work lands)

- [ ] Test-first commit: new `tests/integration/run_safety/*` + `test_wait_page_cancellation.py`
      failing against baseline (record which fail and why).
- [ ] C1 commit: `actions/cancellation.py` + `actions/wait_page.py` + `services/run/*`
      safety fixes; failing→passing; full suite + JS gate + coverage attached.
- [ ] C2 commit: `services/run/cycle_plan.py` + coordinator extraction; parity via
      `test_cycle_modes`/`test_cycle_event_order` unchanged; before/after CC/cognitive/LOC.
- [ ] Handoff: owned-file diff, failing-before/passing-after evidence, suite results,
      line/branch coverage separately, limitations (remote side effects, blocked loops),
      remaining risks.

Branch/head, metrics and gate outputs are recorded in
[Area C task list](SAFETY_REFACTOR_AREA_C_2026-09-10.md) §Implementation journal on landing.
