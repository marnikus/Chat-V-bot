# Step 3 — split `ScrollParser` into `backend/scroll_parser/`

Done 2026-09-12. Target: the round plan's step 3 — `backend/scroll_parser.py`
(**674 LOC, MI 28.4**, one class `ScrollParser` with 34 methods / 507 LOC of
class body, LCOM* 0.87). The plan's success metric: *class 507/37 →
≤150/≤15*.

## Why it is one step

The file is a textbook god class: it reads the DOM (`_snapshot`, `_do_scroll`,
`_confirm_person`), *settles* lazy loading (`_settle`, `_new_people`), *judges*
each person against the filter (`_judge`, `_seek_hit`, `_collect_one`,
`_reject_one`), runs the *scroll loop* (`_scroll_loop`, `_advance`,
`_list_is_over`, `_target_reached`), and *reports* (`_say`, `_notify_collected`,
`_notify_rejected`). Those are five genuinely different jobs sharing one
`self`, which is exactly the cohesion smell RULE 18 §18.2 / RULE 19 §19.4
target. The file was never touched by the earlier complexity rounds (its
`collect` is already phased and its CC is green), so this is pure size/cohesion
debt — and it is a §16.5 landmine: the virtual-scroll parse is pinned
behaviour-by-behaviour by five test files (121 tests + 17 subtests at baseline).

## The seam to preserve (the one risk)

The public surface other areas and tests import must stay byte-identical:

* `actions/scroll_parse.py` — `from backend.scroll_parser import CollectResult, ScrollOptions, ScrollParser`.
* `services/run/coordinator.py` — `from backend.scroll_parser import ScrollParser` (lazy).
* `tests/…/test_scroll_parser_options.py` — `CollectResult, ScrollParser` + guarded `ScrollOptions`.
* `tests/test_collect_visual_and_live_refresh.py` — `from backend.scroll_parser import ScrollParser`, **and** `import backend.scroll_parser as sp; sp.asyncio.sleep = spy` (patches the module attribute `asyncio`).
* `tests/test_filter_purge.py`, `tests/test_scroll_only_seek.py`, `tests/test_scroll_parse_pipeline.py` — `from backend.scroll_parser import ScrollParser`.

The parser instance surface the tests read directly: `parser.known_nicks`
(a live `set`, mutated by `test_scroll_only_seek.py`), `parser._criteria`,
`parser._on_reject` (asserted `None`), `parser.set_log_cb(...)`. All of these
stay on the `ScrollParser` facade.

The `asyncio` patch is the subtle one: today the test rebinds
`backend.scroll_parser.asyncio.sleep`. After the promotion to a package,
`backend.scroll_parser` is the `__init__`, so **`__init__.py` re-exports the
`asyncio` module** and every leaf module imports `asyncio` from the top of the
package (`from backend.scroll_parser import asyncio`), so the one patch still
lands on every sleep the run takes.

## The split

One responsibility per module; the class is composed by single inheritance
per responsibility via mixins (each mixin is a phase, ≤8 methods, ≤150 LOC),
and `ScrollParser` is the thin facade that owns construction, configuration and
the callback/stop/log seams every phase reads.

| Module | Owns | Methods | LOC |
|---|---|---:|---:|
| `constants.py` | `_EXTRACT_JS` (the DOM probe), `STOPPED` (the halt sentinel) | — | ~50 |
| `result.py` | `CollectResult` (the run outcome) | 2 | ~30 |
| `options.py` | `ScrollOptions` (the frozen config) | 3 | ~75 |
| `runstate.py` | `_Pass` (the per-run mutable bag) | — | ~40 |
| `probe.py` | `ProbeMixin`: read/scroll/highlight/settle the page | 8 | ~145 |
| `judge.py` | `JudgeMixin`: filter each person, seek / collect / reject | 5 | ~110 |
| `loop.py` | `LoopMixin`: scroll iteration, target & end detection | 5 | ~120 |
| `pipeline.py` | `PipelineMixin`: open → snapshot → loop → finish, `parse` | 5 | ~90 |
| `notify.py` | `NotifyMixin`: log + on_collect/on_reject + stop check | 5 | ~70 |
| `parser.py` | `ScrollParser` facade: construction + callback/stop seams | 7 + 3 props | ~110 |
| `__init__.py` | the frozen seam re-exports (incl. `asyncio`) | — | ~25 |

Import order is a DAG, leaves first:

```
constants → (result, options, runstate)
    ├─→ probe → (judge, loop) ─┬─→ pipeline → parser → __init__
    └─→ notify ────────────────┘
```

`probe`, `judge`, `loop`, `pipeline`, `notify` are mixins: they read `self.*`
but own no state and never import `parser`, so the facade (`parser.py`) is the
only module that imports the mixins. `runstate._Pass` is imported by `pipeline`
and `judge`/`loop` (they mutate it); it imports nothing from this package.

## Rejected dishonest reductions

* **Merging probe + settle into one method** was rejected: `_settle`'s whole
  point is to distinguish "still lazy-loading" from "end of list" (module
  docstring); it stays its own method inside `ProbeMixin`.
* **Making the mixins plain module functions** was rejected: they share the
  parser's `_cdp`, `options`, `known_nicks`, `_say`, `_stop_requested` — free
  functions would need all of that threaded as arguments (the "12-argument"
  smell `_Pass` already removed). One merged class per phase keeps the `self`
  references honest without new plumbing.
* **Collapsing the four data/constant modules** was rejected: `CollectResult`,
  `ScrollOptions`, `_Pass` and the JS probe are four unrelated vocabularies;
  putting them in one `types.py` would recreate the mixed-responsibility file
  we are removing.
* **Leaving `flow`-style accepted debt** (one 400+ LOC file) was rejected here
  because `ScrollParser` genuinely has five jobs; the round plan's own metric
  for this step is *≤150/≤15*, which a single-file split would not meet.

## Gates

* `radon cc -s backend/scroll_parser/` — worst ≤ 9 (A).
* `tools/metrics/rule16_gate.py` — clean (and `--with-clones` on the new
  package only).
* The five scroll tests + `test_backend_api_snapshot.py` +
  `test_stores_public_api.py` green; the golden snapshot regenerated
  (`dump_public_api.py --write`) because the public types relocated into
  submodules, and the `test_snapshot_covers_both_packages` assertion updated
  to the package's leaf (the `backend.scroll_parser` key becomes a package,
  exactly as `backend.chat_sync` did in step 1).
