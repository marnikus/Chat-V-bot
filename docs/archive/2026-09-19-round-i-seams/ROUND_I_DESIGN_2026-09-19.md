# Round I — seams and testability hardening

Date: 2026-09-19. Source: user-supplied **Chat-V-bot — Seams & Testability
Improvement Plan** (six areas), reviewed against checkout `f8f1d880`.
This is the repository-adapted analysis and roadmap, not a verbatim transcript
or a declaration that the proposed architecture already exists.

**Authorization: implement Area A only. Areas B–F remain proposals.**
Area A is **partially implemented**, not complete: its first transport slice is
recorded in [the implementation record](AREA_A_IMPLEMENTATION_2026-09-19.md).
This round follows the Round H plan and its already-landed work; it does not
replace RULE 1–19 or refresh frozen snapshots to make tests pass.

## 1. Verdict and evidence corrections

Keep the audit's central verdict: hardening, not a legacy rescue. Preserve the
pure cycle planner, private archive gate, deletion protections, existing
characterization tests and small, behavior-preserving extractions.

The supplied audit used the older System of Record figures (91.83% line,
87.02% branch, 2,829 Python tests, 27 JS harness files). Those are historical
claims, not fresh measurements of this checkout. Inventory before scheduling.

| Supplied claim | Checkout evidence / adopted correction |
|---|---|
| Mutation never measured | `reports/MUTATION_REPORT_2026-09-14.md`, `setup.cfg`, `tools/metrics/mutation_platform.py` already exist. The report records 49.34% for the widened history-query job and 94.4% for the bot family. Expand existing scope; do not install a second platform blindly. Scores are dated reports, not rerun here. |
| JS coverage measured nowhere | `reports/JS_COVERAGE_BASELINE_2026-09-13.md`, `tools/metrics/js_coverage.py` and `js_gate.py` already exist. V8 line measurement is not an Istanbul branch baseline. Audit attribution and uncovered files before changing runners. |
| CDP reconnect/lifecycle deterministically testable for the first time | `tests/unit/backend/test_cdp_client_transport.py` already characterizes the real lifecycle using patched acquisition. New value is object injection, not inventing missing tests. |
| Parsers consume raw Runtime.evaluate envelopes | `cdp_client_transport.evaluate` already unwraps the wire envelope. Parser state is still a dict; typed **application probe values**, not another wire decoder, are the candidate seam. |
| Six disjoint branches; any merge order works | A and C overlap in `backend/`; B/C/D reach into `services/`; B/E share wire artifacts; F owns shared gates/docs. Package ownership alone does not eliminate coordination. |
| Delete shims while keeping API snapshot unchanged | Contradictory. Preserve shims and snapshot now. Retirement requires importer inventory and separately approved compatibility change, not this behavior-preserving slice. |
| Frozen DOM fixtures detect live site drift | They detect regressions against recorded markup only. Actual site drift needs a fresh, authorized capture or opt-in live comparison. Never run a live authenticated canary by default. |
| Four-port BlockContext but ≤3 fakes | Measure actual per-block dependencies first; four ports may require four doubles. Do not enforce inconsistent targets. |
| Qt only legal in bridge/app | Current CDP facade is a QObject, and other existing imports need inventory. Contracts start from the actual graph with explicit exceptions. |
| F effort ≈1 in overview | Treat as the detailed estimate of 1.5–2 weeks, not a delivery promise. |

Other absolutes (no memory-backed store tests, zero migration fixtures, no
architecture checks, all tests sleep) remain **hypotheses to inventory**, not
verified defects. Named invariants and their actual tests take precedence over
the audit's paraphrases. The external reference prompt itself is not a repo
artifact; its coverage map below describes the supplied audit's categories.

## 2. Method, contracts and execution rules

Seams → characterize → introduce injection → cover → refactor → ratchet.
Object injection first, narrow parameters second, external adapters third.
Do not split for line counts or add interfaces without demonstrated consumers.

- P0: inventory files, imports, mutable state, existing seams and tests.
- P1: freeze outputs/order/refusals on **untouched** behavior; sanitize fixtures.
- P2: introduce the smallest seam with production defaults unchanged.
- P3: failure/cancellation/empty-path tests and measured coverage.
- P4: refactor only behind that safety net, one independently reviewable step.
- P5–6: assess mutants, document contracts, then enable regression checks.

RULE 8 requires executing real production paths; RULE 16 gates every new
production function; RULE 17 keeps dated designs here and current facts in
`docs/current/SYSTEM_OF_RECORD.md`. No feature/UI/schema redesign. Preserve
backend API, QWebChannel wire, deletion result shape, collector statuses,
private-gate refusal ordering and cancellation semantics.

All work in this session stays on `arena/01a0bac1-chat-v-bot`. The six branch
names in the submitted audit are conceptual workstream labels, **not** an
instruction to create/switch branches. Future parallel implementation requires
reviewed file ownership and shared-contract coordination. Baseline failures
must be reported, not hidden or fixed opportunistically in another area.

## 3. Six workstreams and coordination

| Area | Scope / seams in priority order | Dependencies and intended exit evidence | Estimate |
|---|---|---|---|
| **A — CDP & browser boundary** | Transport + fake; typed probe values; selector registry; sanitized DOM/frame corpus; shim inventory | Existing API unchanged; replay and gate characterizations; selector parity; parser mutation target ≥60% after baseline. Only area authorized now. | 2–3 weeks |
| B — Qt bridge & app shell | Pure wire/orchestration helpers; scheduler; verified-result announcer; shared wire schema; minimal Qt smoke set | Freeze each bridge's calls/signals, boot event order and announcement truth table first. Aim ≥85% branch on pure modules and ≥95% Qt-free bridge tests after census. | 2 weeks |
| C — World store & persistence ports | Consumer-sized repo protocols; parity-tested memory fake; clock; explicit FTS/LIKE strategies; filesystem adapter and migration corpus | Canonical migration dumps, world-gate traces and explicit search divergences first. Aim ≥90% store branch coverage, ≥70% mutation on gate/repo/migration. No invented historical databases. | 2–3 weeks |
| D — Run engine & action blocks | Access-audited BlockContext; Waiter; registry conformance; TraceSink; collector throttle contract | Preserve cycle/report sequences and speed-scaling table. Registry covers every actual block; no real unit delays; ≥70% mutation on plan/stop/cancel. | 2 weeks |
| E — JS measurement & humble views | Evaluate Vitest/jsdom coexistence; presenters; contract-faithful FakeBridge; wire usage inventory; Stryker on pure models | Reuse existing V8 baseline. Freeze real render/event scenarios; ≥75% branch on models/presenters and ≥60% mutation as proposed targets. Qt WebEngine remains the browser authority. | 3 weeks |
| F — Metrics & architecture | Extend existing mutation platform; import contracts; churn×complexity hotspots; Ca/Ce/I trends; test taxonomy/isolation | Inventory existing tooling before additions. Report-only first; graph exceptions reviewed; reproducible baselines; unit isolation goal ≥90%, not an unmeasured claim. | 1.5–2 weeks |

Targets are proposed acceptance criteria, not achieved measurements or a
reason to weaken stronger RULE 16 requirements. Mutation denominators must
separate killed, survived, timeout, invalid and unreachable mutants. Coupling
is a trend: no dependency-count target may override a legitimate boundary.

### File ownership / integration points

- A: CDP/probe/parser/agent files in `backend/`, corresponding backend tests.
  C owns `backend/history_query*`; neither owns all of `backend/`.
- B: `bridge/`, `app/`, `main.py`; coordinate `services/world_events.py` changes.
- C: `stores/`, history-query family; coordinate `services/history/trash.py`.
- D: `services/run/`, `actions/`; explicitly reserve collector files if touched.
- E: `ui/js/`, JS harness/tooling; backend agent tests coordinate with A.
- F: shared tools/reports/CI and architectural tests; reads production packages.
- Shared schemas, rules, dependencies and System of Record edits require one
  integration owner; current docs must be corrected, not blindly append-only.

Suggested future sequence: F **baseline reuse** → A/C/D → B → E, with parallel
characterization where files do not overlap. Only A runs now; do not implement
F merely because the original audit calls it an enabler.

## 4. Area A — detailed accepted roadmap

### A0/P0 — Orient

Inventory socket/HTTP acquisition and existing patch seams; parser state
consumers; selector definition sites; compatibility importers. Existing
`cdp_client`, `cdp_client_transport`, `cdp_client_commands`, `cdp_client_events`
are already separated. Preserve `cdp.send`, `_ws` and `_connected` test seams.
Golden evidence must be synthetic or sanitized (no cookies, auth headers,
private messages or user identifiers). Real sessions require an available,
authorized Chrome instance; none is supplied for this implementation.

### A1/P1–P2 — Transport boundary (first implementation slice)

Define a connection frame-stream protocol and a browser-acquisition protocol.
Inject through an additive construction helper, keeping the frozen constructor
signature. Default adapter retains WebSocket size/timeouts and HTTP timeout.
Keep ID allocation, response framing, event dispatch and domain enable order
in the existing implementation. A scripted fake must feed that **real** code,
not reimplement the client's behavior in tests.

Evidence: run existing lifecycle/API tests before edits, then fake-backed
connect, evaluate, discovery, failure, reconnect, event and EOF tests. Preserve
existing timeout/disconnect behavior even if characterization exposes a bug;
correct it separately rather than quietly changing it in a seam extraction.

### A2/P1–P3 — Typed probe values (pending)

Enumerate state, scroll and author payloads, including missing/null/invalid
values. Characterize `verify_private` precedence: non-private → missing
partner → mismatched title/self-chat → unavailable authors/strangers. Include
emoji, quoted nicks, empty pane and a stale third author. Extend existing
private-gate suites rather than replace them.

Introduce frozen values **inside** the boundary with legacy dict adapters;
do not change snapshotted signatures. Preserve all reason strings and unknown
field behavior. Only migrate consumers after complete input/output parity.
Target ≥90% branch on touched gate paths, then a scoped mutation baseline.

### A3/P1–P4 — Selector data and golden DOMs (pending)

Inventory literal selectors in Python probes, `backend/js/chat_agent.js` and
`docs/current/DOM_SELECTORS.md`, separating arbitrary user-supplied selectors
from fixed site selectors. Choose JSON or generated injection only after
checking the current runtime loader and Node harness. One canonical registry
for **fixed** selectors; generated JS and doc tables checked for parity.

Execute the real agent against sanitized private/group/list/re-render DOM
fixtures; approve fingerprints, slices and gap markers before moving selector
strings. Keep recorded-DOM regression checks distinct from fresh-site drift
checks. Captured frames cover evaluation, discovery and disconnect mid-command;
synthetic traces must never be described as live captures.

### A4/P4–P6 — Cleanup and strengthening (pending)

Split parser responsibilities only where evidence supports it (gate/decode/
sync), preserving re-exports. Inventory shim importers; no warning side effects
or removal without separately reviewed compatibility approval. Run scoped
parser/command mutation testing (audit target ≥60%, subject to RULE 16),
report survivors, establish ratchets and record actual coupling changes.
No new CI subsystem or F work is authorized in this slice.

### Area A exit checklist

- [x] Existing lifecycle characterization and frozen API tests exercised.
- [x] Injectable browser acquisition, production adapter and scripted fake.
- [x] Real connect/command/event/discovery paths exercised without network patches.
- [ ] Complete typed probe migration and private-gate truth-table expansion.
- [ ] Fixed-selector inventory, registry and doc/JS parity checks.
- [ ] Sanitized captured DOM/CDP corpus and real-agent golden approvals.
- [ ] Shim importer inventory and separately approved retirement decision.
- [ ] Scoped mutation scores, coverage ratchet and final Area A exit review.

## 5. Deferred areas: characterization before implementation

**B:** Freeze service calls, emitted signals and payload shapes per bridge;
boot request → wait → world-open → one reply → announcements; announcement
truth table by undo kind. Extract domain-by-domain, not a universal router
rewrite. Fake clock preserves bounded waits; schema generation must represent
payload semantics as well as method names. Qt-free ratio needs a denominator.

**C:** Run one repository contract on SQLite and the proposed fake, retaining
real-SQLite tests for locking, transactions, FTS and migrations. Canonical
logical dumps, not byte-identical SQLite files. Pin FTS/LIKE allowed divergence,
time/identity edges and write-gate traces; a filesystem fake does not prove
symlink/atomic-move behavior, so retain real filesystem safety tests.

**D:** Freeze cycle ordering, every block's success/refusal report stream and
which waits scale. Discover the actual dependency shape rather than impose
four ports without memory/config access. Conformance requires per-block valid
inputs and expected outcomes; registry discovery alone cannot prove safety.
Instant waits must still model cancellation/yield points and stop-inside-wait.

**E:** Assess existing harness compatibility before runner replacement. Freeze
render states and capture-phase outside clicks, redraw races, Esc-drag cancel,
reorder and sort cycles. jsdom is not fully browser-faithful (layout/focus/Qt
integration especially); retain browser backstops. Shared wire unification is
a reviewed integration task, not an assumed one-line change.

**F:** Snapshot actual imports and current rule enforcement; grandfather only
reviewed violations. Measure test dependencies rather than infer isolation
from directory names. Reuse existing mutation/coverage commands. Add churn
window, formula and known limitations to hotspot reports. Start coupling and
cohesion measures as trends. Promote each reliable check independently after
baseline review; do not wait for all six areas or break concurrent work with
unreviewed thresholds.

## 6. Reference-concept coverage and non-goals

| Audit reference category | Planned evidence |
|---|---|
| Seam/dependency metrics | A transport/probes, B scheduler/wire, C repo ports, D block dependency audit |
| Size/complexity/isolation | Existing RULE 16/18/19; touched-function measurements and F taxonomy |
| Coupling/cohesion/mock surface | F graph trends/contracts; C consumer protocols; D access counts |
| Test readiness/strength | Existing baselines plus characterization in A–E; F scoped mutation and isolation |
| Barriers/side effects | A selectors/IO, B announcements, C time/files, D waits, E DOM-state separation |
| Risk/hotspots/blast radius | F churn×complexity with explicit methodology, invariant-first area ordering |
| Phases 0–6 | Inventory → characterize → seam → coverage → refactor → strengthen → prevent regression |

Seam density, LCOM, cognitive complexity, global state, setup cost, bug density,
debt ratio and maintainability index are not all made measured merely by adding
Ca/Ce or hotspots. F must record each as measured, deferred, or N/A with reason.
No claim of full reference-prompt metric coverage is made here.

No new product behavior, schema migration, UI redesign, weakened safety gate,
contract snapshot refresh or mandatory toolchain migration is approved by this
plan. Effort estimates assume one experienced developer per workstream and
are not commitments. Current facts always win over this dated roadmap.
