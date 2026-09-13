# Round 4 — steps 6 and 7 completed (2026-09-13)

**Completed:** session lifecycle decomposition and the final compatibility-only
`backend/chat_sync.py` facade. **Still queued:** step 8 (general changed-code
gate / CI work) and step 9 (fresh prioritization). No new stop or failure-cleanup
policy was bundled into this extraction.

Design: `docs/archive/2026-09-13-refactor-round4/STEPS_6_7_DESIGN.md`.
Master queue: `docs/archive/2026-09-12-refactor-round4/ROUND4_DESIGN.md`.
Previous slice: `reports/REFACTOR_ROUND4_STEPS_4_5_2026-09-12.md`.
Branch: `arena/01a093f4-chat-v-bot` (existing working-tree changes retained).

## 1. Implemented ownership

| Module | Responsibility | Physical lines |
|---|---|---:|
| `backend/chat_sync.py` | Explicit imports and `__all__` only; no runtime definitions | **337 → 33** |
| `backend/sync/session.py` | Frozen dataclass state/API, composition and `run_sync` | 144 |
| `backend/sync/lifecycle.py` | Admission and final cursor/result bookkeeping | 111 |
| `backend/sync/viewport.py` | Settling, emptied-pane recovery, restore and window clamping | 110 |
| `backend/sync/planning.py` | Pure options/read decisions, unchanged | 221 |
| `backend/sync/persistence.py` | Archive write policy, unchanged | 173 |
| `backend/sync/reading.py` | Retry/pacing/alignment, unchanged | 149 |

With its seven-line initializer, `backend/sync/` now has **seven cohesive
files**, within the planned 5–7. No file in the family exceeds 300 lines.
This is a responsibility split, not a claim that total source volume fell:
composition, explicit compatibility adapters and documentation add overhead.

`SyncSession` still exposes its original dataclass fields, constructor, result
identity and public methods. The public hooks are explicit adapters where their
policy moved, not generated methods or mixins. Lifecycle and viewport borrow
only public session state/collaborators and use `sync_state()` for signature
refresh; they never reach into each other's private implementation.

The facade exports the **same implementation objects**. `SyncResult` remains
accessible and is now explicitly included in `__all__`; no golden API snapshot
was rewritten. Removed only the unused private `_MAX_QUIET_RETRIES` constant,
which controlled no behavior. The real `SLICE_RETRIES` export is unchanged.

## 2. Behavior-preservation evidence

Added characterization before production edits and ran it with existing sync
and API suites: **95 passed, six subtests**. After the collaborator extraction
(step 6), a wider focused selection passed **114 tests, six subtests**. Only
then was orchestration moved (step 7).

`run_sync` is **AST-identical** to the saved pre-step entry point. The lifecycle
and viewport methods necessarily change receiver/ownership references; their
behavior is checked by execution, not claimed to be textually identical.

Pinned contracts include:

* broken-agent versus empty/refused outcomes, with no scroll, archive access or
  write after private admission is refused;
* exact successful backfill order: probe/gate → scroll/settle → archive reads →
  chunk write/recovery → restoration → tail-media repair → marker/cursor/totals;
* settle-error reprobe, non-dict fallback, emptied-pane recovery and count/
  signature updates that re-clamp a retried window;
* zero original scroll position and unchanged fast-path behavior, without
  introducing an additional restoration or cursor write;
* best-effort restoration errors versus propagated external cancellation;
* supplied result identity/reason, pending/stopped backfill markers and partial
  cursor tail clearing;
* no shared mutable defaults or collaborators across independent sessions.

Fresh-process import guards prove lifecycle/viewport do not import their session
owner, facade, parser, Qt, services or the action registry at module load.
Session also imports without facade/parser/Qt/service/registry cycles. The
existing parser gate stays a deliberate **lazy runtime import**.

## 3. RULE 16 and RULE 18 final review

| Class | Previous LOC / methods | Current LOC / methods |
|---|---:|---:|
| `SyncSession` | 248 / 24 | **91 / 12** |
| `SyncLifecycle` | — | **92 / 10** |
| `SyncViewport` | — | **95 / 10** |

| New module scope | Max function LOC | Max params | Max CC | Max cognitive | Max nesting |
|---|---:|---:|---:|---:|---:|
| Session + orchestration | 25 | 5 (frozen entry point) | 5 | 4 | 1 |
| Lifecycle | 18 | 1 | 7 | 7 | 2 |
| Viewport | 17 | 1 | 9 | 8 | 1 |

`tests/test_sync_session_quality.py` automatically enumerates the 34 new/moved
functions and all three classes, rejects missing measurement tools, and checks
all hard limits. One additional class/inventory check makes **35 quality tests**.

The only hard-limit exception is the **existing** five-parameter `run_sync`
signature (`parser`, `repo`, `nick`, `options`, `**legacy`). Its new definition
has an explicit `quality-override: params=5` constraint; the test permits only
that exact violation and checks every other metric normally. No signature was
broadened. No class needs a hard-limit override.

RULE 18: all new classes are below 120 lines. Session's 12 methods exceed the
10-method preference because the 11 existing public/hooks must stay callable,
plus the explicit shared-state refresh seam; the constraint is documented
inline. The 25-line entry point has an ideal-size explanation for the unchanged
ordered phases/early-result contract. Small files/initializers are cohesive
leaves and are not padded to meet the 150-line preference.

RULE 19: the old session had no nesting/CC violation to simplify first; it was
the long-and-flat, multiple-responsibility case. No decisions were hidden in
lambdas, inherited mixins or dynamic dispatch to reduce measured complexity.
Project-wide CC > 10 and nesting > 4 remain zero; one legacy cognitive offender
(the Qt router factory) remains outside this scope.

## 4. Final validation

| Check | Result |
|---|---|
| Full Python suite | **2837 passed**, 3 skipped, 1 deselected, 1 xfailed; 774 subtests |
| Tests added this slice | **85** (30 characterization, 20 boundary, 35 quality) |
| Standalone RULE 16 suite | **23 passed**, measurement tools installed |
| Node harnesses | **25 files passed**, zero failures |
| Existing backend/stores API snapshots | pass unchanged |
| Existing test files edited in this slice | **none**; prior step-4–5 import-count adjustment retained |
| Store import-count baseline | still **39**, no new adjustment needed |
| Exact-AST clone gate | zero new groups, zero stale baseline entries |
| Vulture >= 90% | same seven pre-existing findings, none added |
| Pylint unused imports on sync scope | zero findings |
| `git diff --check` | clean |

### Coverage: separate line and branch ratios

| Metric | Before (steps 4–5) | After (steps 6–7) |
|---|---:|---:|
| Overall line | 13481 / 14792 = **91.13710%** | 13534 / 14838 = **91.21175%** |
| Overall branch | 3122 / 3634 = **85.91084%** | 3125 / 3634 = **85.99340%** |
| New session module | — | **100% lines / 100% branches** |
| New lifecycle module | — | **100% lines / 100% branches** |
| New viewport module | — | **98.75% lines / 87.50% branches** |
| Legacy facade | — | **100% lines**, no branches |

Every extracted/new production function executes under behavioral assertions;
there are no zero-hit functions in the three new modules. Overall coverage
increased relative to both the previous slice and frozen RULE 16 floors.
Combined coverage.py percentage is not used as the gate.

### Limits kept explicit

Real WebEngine rendering remains deselected in the headless environment; Qt
imports use the repository's `/tmp/stublibs`. This is not a live Chrome smoke
test. The one pre-existing unawaited collector-push warning remains. Mutation
testing is configured only for untouched `backend/history_query.py`; no mutation
score is claimed here. Scoped quality tests do not solve step 8's general gate.

In-flight CDP requests still complete at their existing cooperative-stop await
boundary. Existing restoration/finalization short-circuits and cancellation
propagation are preserved, not redesigned with an unrequested `finally` block.
Any expansion of cleanup or stop supervision needs its own behavioral design.

## 5. Reproduction

Install `requirements-dev.txt` into `.venv`. If Qt system libraries are absent,
run `.venv/bin/python tools/build_stubs.py .venv /tmp/stublibs` first. Keep
coverage/audit/log artifacts outside Git.

```bash
.venv/bin/radon cc -s backend/sync/session.py backend/sync/lifecycle.py backend/sync/viewport.py
.venv/bin/python tests/test_rule16_new_code.py
.venv/bin/python tools/metrics/rule16_gate.py --with-clones
QT_QPA_PLATFORM=offscreen LD_LIBRARY_PATH=/tmp/stublibs \
  .venv/bin/python -m coverage run --branch \
  --source=core,actions,backend,bridge,services,stores,app,main \
  -m pytest tests -q \
  --deselect=tests/test_sash_webengine.py::TestSashWebEngine::test_grid_in_real_webengine
.venv/bin/python -m coverage json -o /home/user/round4-step67-coverage.json
.venv/bin/python tools/metrics/current_audit.py > /home/user/round4-step67-audit.json
for f in tests/test_*.js; do node "$f" || exit 1; done
```
