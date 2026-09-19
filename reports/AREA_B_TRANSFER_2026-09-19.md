# Area B reconstruction and verification — 2026-09-19

## Outcome

Reconstructed the supplied `seam/bridge-humble-shell` implementation on top
of Area A quality commit `7fed141`. This is an integration of the pasted
manifest, **not** a merge from a fetched upstream branch. Areas C–F remain
outside scope. Design was recorded before production changes:
[design](../docs/archive/2026-09-19-area-b-integration/DESIGN.md),
[port notes](../docs/archive/2026-09-19-area-b-integration/PORT_NOTES.md),
[file index](../docs/archive/2026-09-19-area-b-integration/FILES.md).

Implemented:
- Qt-free wire codec, database-result policy and undo projections, used by
  People/History/DB/Undo QObject adapters without losing existing slots.
- Scheduler protocol, real and manual clocks, injectable PeopleBridge clock,
  WorldGate and unchanged historical world-event facade signatures.
- Confirmed-result Announcer for DB success; shared labels-only intent policy
  imported by existing undo reporting. Other domain reporting is not migrated.
- Complete generated Router schema and opt-in JS diagnostics. **124 methods
  and 41 signals**, with arity, parameter types and return types. Pre/post
  generated schemas are byte-identical. No runtime interceptor was installed.
- Pure tests, independent transitive Qt import blocking, real-Qt smoke tests
  marked `needs_qt`, and complete generated-artifact parity tests.

## Independently measured results

| Check | Result |
|---|---|
| New Area B tests | **104 passed**: 101 selected without conftest/Qt smoke, 3 real Qt smoke tests |
| Pure selection | **101 passed, 3 deselected**, 0.19 s pytest test phase (not total interpreter startup) |
| Scoped bridge/world/undo/RULE16 selection | **360 passed, 6 preexisting failures** |
| Full Python coverage run | **3,465 passed, 70 failed, 2 skipped, 1 deselected, 1 xfailed, 2,559 subtests passed**; 482.22 s |
| Full failure-ID comparison with Area A quality | **No new failures; none of the existing 70 removed** |
| RULE16 standalone wrapper | **23/23 passed** |
| Clone-inclusive gate | **No breaches, no missing tools, no stale clone entries** |
| New schema Node harness | **4/4 passed**; whole Node suite not rerun |
| Complete Router artifact | Exact generator parity and byte-identical pre/post contract |
| Git whitespace | `git diff --check` clean |

The first full run found one additional source-spelling test failure after
extracting the delete guard. Replaced the text search with an execution of
**real DbBridge** for delete and load: delete must not push, load must push the
exact undo payload. The final full run returned to the original 70 failures.
No frozen public-API snapshot was refreshed.

### Coverage — no baseline promotion

Overall: **16,798 / 18,049 statements = 93.068868%**;
**3,558 / 4,016 branches = 88.595618%**. This improves on the prior
92.943795% / 88.488488%, but still misses the official **93.16% / 88.85%**
historical floors. The global coverage gate therefore remains **unmet**.

| Seam | Statements | Branches |
|---|---:|---:|
| `bridge/wire_codec.py` | 32/32 | 6/6 |
| `bridge/wire_db.py` | 12/12 | 2/2 |
| `bridge/wire_undo.py` | 36/36 | 12/12 |
| `core/announcer.py` | 18/18 | 4/4 |
| `core/scheduler.py` | 29/29 | 7/8 |
| `services/world_events.py` | 49/49 | 8/8 |

The remaining scheduler arc is the multiline Protocol `until` declaration's
exit arc. It remains in the denominator; no coverage configuration or new
exclusion was added. Pure import closure is checked in a fresh interpreter
that refuses PySide/PyQt/Shiboken imports, not inferred from filenames.
Root conftest still optionally seeds Qt for the old suite, so these results
**do not claim the existing bridge_safety suite is Qt-free**.

### Mutation — fresh isolated mutmut 3.7.0 run

| Module | Killed / generated | Survived | Kill rate |
|---|---:|---:|---:|
| Wire codec | 85/87 | 2 | 97.70% |
| DB policy | 72/72 | 0 | 100% |
| Undo wire | 63/65 | 2 | 96.92% |
| Announcer | 35/36 | 1 | 97.22% |
| Scheduler | 39/40 | 1 | 97.50% |
| World events | 87/100 | 13 | 87.00% |
| **Total** | **381/400** | **19** | **95.25%** |

All six meet the touched-pure 70% floor. Final run: clean-test and forced-fail
checks passed, **zero timeout, invalid/error, suspicious or unreachable results**,
zero traceback/bad-test-execution diagnostics; run and results commands exited 0.
Survivors remain included, not declared equivalent to improve the score.

Two initial measurement problems were corrected before this final run: bounded
async scenarios turn infinite-poll mutations into test failures rather than
process timeouts; materializing the parametrization product avoids iterator
exhaustion during mutmut's repeated in-process collection. Early runs are not
the reported evidence. Survivor inventory is in the port notes.

### Size and complexity

New seam functions: maximum **13 physical LOC, 4 parameters, CC 7, cognitive 6,
nesting 3**. All extracted production functions are added to RULE16 ownership.
The moved person-request function is measured at its new location.

| Existing adapter | Class LOC before → after | Direct methods before → after |
|---|---:|---:|
| DB | 142 → 135 | 12 → 12 |
| People | 133 → 123 | 20 → 20 |
| History | 180 → 169 | 27 → 26 |
| Undo | 165 → 107 | 15 → 14 |

These preserve legacy adapter surface; they do not claim every adapter now
meets new-class method limits. Removing People's unused JSON import shrank an
existing three-file import-only clone to its original remaining two-file pair;
the clone inventory was narrowed accordingly, not expanded to allow new logic.

## Reproduction

```bash
export QT_QPA_PLATFORM=offscreen LD_LIBRARY_PATH=/tmp/stublibs
.venv/bin/python -m pytest --noconftest tests/unit/bridge_wire -m 'not needs_qt' -q
.venv/bin/python -m pytest tests/unit/bridge_wire -q
.venv/bin/python tests/test_rule16_new_code.py
.venv/bin/python tools/metrics/rule16_gate.py --with-clones --json
.venv/bin/python tools/wire_schema.py --check
node tests/test_wire_schema_js.js
.venv/bin/python -m coverage run --branch \
  --source=core,actions,backend,bridge,services,stores,app,main \
  -m pytest tests -q \
  --deselect=tests/test_sash_webengine.py::TestSashWebEngine::test_grid_in_real_webengine
```

Mutation: copy the checkout without `.git`, virtualenvs or generated caches into
an isolated scratch directory; use the original virtualenv's Python. Configuration:

```ini
[mutmut]
source_paths=
    bridge/wire_codec.py
    bridge/wire_db.py
    bridge/wire_undo.py
    core/announcer.py
    core/scheduler.py
    services/world_events.py
also_copy=
    backend
    stores
    core
    actions
    services
    bridge
    app
    tools
    ui
    main.py
pytest_add_cli_args=
    --noconftest
pytest_add_cli_args_test_selection=
    tests/unit/bridge_wire/test_codec.py
    tests/unit/bridge_wire/test_policy.py
    tests/unit/bridge_wire/test_scheduler.py
```

Run `python -m mutmut run --max-children 4`, then
`python -m mutmut results --all True`. Check logs as well as aggregate status.
This session's raw evidence is under `/tmp/area-b-{final.log,final-coverage.json,
final-targeted.log,metrics.json,pure.log,node.log}` and `/tmp/area-b-mutation/`;
these scratch files are not tracked deliverables.

## Remaining work, priority order

1. **Release gate:** resolve the existing 70 suite failures and historical global
   coverage shortfall without lowering floors or blindly replacing snapshots.
   Six failures in the scoped selection are existing undo API/helper and preset
   export problems, not a green adapter-suite claim.
2. **Test quality:** review the 19 included mutation survivors, especially
   WorldGate cleanup/logging/default-argument paths. Strengthen meaningful
   assertions, not implementation-detail assertions for equivalent changes.
3. **Runtime/CI integration:** decide whether/where to activate schema diagnostics
   in UI boot and CI. The loader/guard is opt-in, parity checks method presence
   only, and the JS guard validates arity (allowing a result callback), not values.
4. **Further extraction:** old bridge tests still depend on Qt; no repository-wide
   ≥95% Qt-free claim. History retains its production facade runner, while
   deterministic scheduler injection is available on PeopleBridge and WorldGate.
   Domain-specific undo success emitters remain domain-specific.
