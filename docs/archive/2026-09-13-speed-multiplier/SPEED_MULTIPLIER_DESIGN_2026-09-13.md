# Global Wait Speed Multiplier — design (2026-09-13)

Feature request: a `SPEED_MULTIPLIER` action block carrying one float
coefficient (1.0 = normal, 0.5 = 2× faster, 2.0 = 2× slower) that scales
**all** wait/pause timers of the action stack at once, so a run can be
sped up or slowed down without editing every block. UI: coefficient
input, live preview ("All waits ×0.5 (2× faster)"), quick presets
[0.5×] [1×] [2×] [3×], faster/slower indicator.

## 1. Semantics decision: GLOBAL, not "blocks below it"

The request lists two options: the multiplier affects blocks below it in
the stack, or all blocks globally. **Global wins**, for one structural
reason:

*Scroll & Parse runs at cycle level, before the per-user loop*
(`services/run/collect_phase.py`: `block.run_pipeline(self._cdp, self,
…)`). Positional semantics ("below the SPEED block") could therefore
never scale the scroll/load pauses — the longest waits of the whole run
(800 ms × up to 50 scrolls) — no matter where the SPEED block sits.
Global semantics scales the entire execution uniformly, which is what
the feature title promises.

Consequences, all documented on the block:

* The run's rate is resolved once at run start
  (`RunLifecycleMixin._begin_run`): the **last enabled**
  `SPEED_MULTIPLIER` block in stack order wins (top→bottom, last wins —
  the same overriding sequential application would produce). No SPEED
  block, or all disabled → ×1.0.
* A SPEED block's own `execute()` re-asserts its value on the engine
  (idempotent) and reports it, so standalone/direct/test paths behave
  identically.
* The rate resets to ×1.0 at every run start — no leakage between runs.

## 2. What scales and what does not

| Wait site | Scales? | How |
|---|---|---|
| `BaseAction.pre_delay()` (every block's pre-delay) | yes | `pre_delay(engine)` → `scale_ms` |
| `PAUSE.duration_ms` | yes | `scale_ms` in `execute` |
| `WAIT_PAGE_LOAD.timeout_ms` + pre-delay + 300 ms poll gap | yes | `scale_ms` at the three uses |
| visual-click `confirm_pause_ms` hold | yes | `scale_ms` in `run_click` |
| visual-click `CLICK_PAUSE_MS` 250 ms outline→click beat | yes | `scale_ms` in `click_phase` |
| `CLICK_USER.tab_pause_ms` | yes | `scale_ms` in `_wait_for_new_tab` |
| `SCROLL_PARSE` pause/load-timeout/confirm-pause | yes | `dataclasses.replace` on the built `ScrollOptions` in `_collect` |
| `ATTACH_IMAGE` verify-timeout/confirm-pause | yes | `scale_ms` before calling `media_handler` |
| `COLLECT_HISTORY` chunk pause | yes | `scale_ms` in `_CollectRun.collect` |
| stop-check slices (`slice_s`, `sleep_with_stop` internals) | **no** | RULE 7 responsiveness must not stretch |
| retry backoff (`RetryPolicy.base_delay`) | **no** | reliability timing, not pacing |
| CDP protocol gaps (0.1/0.2 s in `message_injector`, search focus) | **no** | correctness delays, not user waits |
| `typing_speed_ms` | n/a | log wording only — the verified ladder performs no per-char wait |
| `highlight_ms` outline durations, `poll_ms`, collector pacing | **no** | cosmetic cadence / background service, not stack pacing |

Reporting convention: a scaled wait reports the **actual (scaled)**
duration; the run-start line and the SPEED block's own line state the
active rate, so no per-site suffix is needed. At ×1.0 every report line
is byte-identical to before (all pinned-string tests stay green).

## 3. New code

* `actions/speed.py` — leaf module (stdlib only, like
  `actions/cancellation.py`): `SPEED_BLOCK_ID`, `coerce_multiplier`
  ([0.1, 10.0], garbage → 1.0 fail-open), `read_multiplier(engine)`
  (getattr fail-open), `scale_ms`, `describe` ("×0.5 (2× faster)"),
  `resolve_stack_multiplier` (last enabled SPEED block wins).
* `actions/speed_multiplier.py` — `SpeedMultiplier(MarkerBlock)`:
  no pre-delay of its own (marker), one `multiplier` field cleaned by
  `coerce_multiplier`, `execute` sets `engine.speed_multiplier`,
  reports, returns OK (SKIP would abort the user in the per-user loop —
  same override as `Pause`).
* Engine: `RunCoordinator.speed_multiplier = 1.0` default,
  `_begin_run` resolves via `_resolve_run_speed` (lazy import, same
  reason as `error_recovery`'s: `import actions.…` scans every block
  module), silent at ×1.0; `ActionContext.speed_multiplier` field for
  the typed seam.
* UI (`ui/js/stack-dnd.js`): `BUILTIN_BLOCKS` entry (RULE 3 mirror),
  `_speedDesc`/`_speedValue` preview helpers, `_summary` case
  ("All waits ×0.5 (2× faster)"), custom config row (stepped number
  input + [0.5×][1×][2×][3×] presets + live 🐇/➖/🐢 preview) following
  the TYPE_MESSAGE/TAKE_PERSON custom-row precedent.

## 4. Rejected alternatives

* **Positional ("blocks below it") semantics** — cannot scale the
  cycle-level collect phase (see §1). Rejected.
* **`speed_multiplier` field on `ScrollOptions`** — `from_options`
  forwards *every* dataclass field to `ScrollParser.__init__`, so the
  19-param legacy constructor would need a 20th parameter (RULE 16.5:
  must not grow a legacy offender; a `params` override would cite an
  internal choice, not a constraint). Rejected in favour of
  `dataclasses.replace` on the already-built options in
  `ScrollParse._collect` — zero `scroll_parser.py` changes (it is a
  RULE 16.5 landmine), following the `CollectHistory` precedent of a
  block stamping run-time values onto the parser it built.
* **Mutating `ScrollOptions` in place** — it is
  `@dataclass(frozen=True, slots=True)`, pinned by
  `tests/unit/backend/test_scroll_parser_options.py`. Rejected.
* **A `scale_seconds` twin of `scale_ms`** — one scaler, one tested
  function; the single seconds-denominated site (WaitPage poll gap)
  reads naturally as 300 ms. Rejected (YAGNI).
* **New AGENT_RULE ("all waits scale")** — considered; not added. The
  convention is documented here instead. A future change that adds a
  hand-rolled `asyncio.sleep` to a block should route it through
  `actions.speed` (flagged for the RULE 16 reviewer, not gated).

## 5. Measurements (RULE 16.6 step 2/4)

Before (radon 6.0.1, `radon cc -s`): all touched functions ≤ CC 8
(`WaitPageLoad._wait_loop` is the max at B (8)); the change adds **zero
branches** to existing functions (one-line expressions / one assigned
local each). New functions: 7 in `actions/speed.py` (CC ≤ 5),
`SpeedMultiplier.execute` (CC 3), `ScrollParse._with_run_speed` (CC 2),
`RunLifecycleMixin._resolve_run_speed` (CC 2) — all ≤ 11 physical LOC,
≤ 2 params. No signature grows on any legacy offender (scroll
threading deliberately avoids `to_scroll_options`/`build_parser`/
`run_pipeline`, all already over the params line).

Dishonest reductions rejected: none needed — no function required
splitting (RULE 19 order never triggered; every new unit was born
under the line).

## 6. Tests (RULE 8, RULE 16.3)

`tests/unit/actions/test_speed_multiplier.py` (unittest-style, runs
under pytest and `python3 file.py`): coerce/read/scale/describe units;
resolve (empty / absent / single / last-wins / disabled / garbage);
block registration, defaults, preset round-trip, schema, execute with
and without engine; `pre_delay`/`Pause`/visual-hold/WaitPage-report/
tab-wait scaling with a patched sleep; scroll options stamping through
real `to_scroll_options`+`from_options` with only `collect` faked;
attach/history scaling with the backend boundary faked (the
`click_runner` docstring's blessed pattern); a real `RunCoordinator`
end-to-end (`SPEED 0.5` + `PAUSE 1000` → sleeps 0.5 s).
`tests/test_speed_multiplier.js`: the real `ui/js/stack-dnd.js` in
Node — registry entry, defaults, preview strings, summary, and the
preset/preview config rows. Existing lists updated:
`ALL_SHIPPED_BLOCKS` / `SHIPPED_BLOCKS` (+`SPEED_MULTIPLIER`).
