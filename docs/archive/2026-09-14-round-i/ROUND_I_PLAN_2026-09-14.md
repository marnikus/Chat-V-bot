# Round I — plan (the 300-band and the inventory)

**Baseline:** [`reports/CODE_QUALITY_METRICS_2026-09-14-roundI.md`](../../../reports/CODE_QUALITY_METRICS_2026-09-14-roundI.md)
**Branch:** `arena/01a09e20-chat-v-bot` · **From:** `c0e18a2` · **Date:** 2026-09-14

## The thesis

Round H closed files ≥ 400 LOC. Complexity, coupling, dead code (gated)
and tests are all closed and re-verified. What remains is **one band
down and one kind wider**:

1. **Eighteen files at 300–399 lines** — eight with real seams, four
   research-gated, six correctly left alone (§1.2 of the audit);
2. **An inventory audit, not a gate, found**: a 52-line same-file
   duplication, a scanner-dodging import, two logic duplications outside
   the gate's scope, one dead import, stale exemption headers;
3. **Coverage gaps in Round H's own products** (`send_button` 21%,
   `history_media` 38%);
4. **Verdicts that need data, not splits**: `RunCoordinator`'s 73
   reachable methods (a §16.5 landmine — measure, then judge),
   `_DeleteState`'s 21 fields, and eight in-band files whose MI<45 is
   density, where splitting would be metric-gaming.

**RULE 19 still governs every step**: nesting → cyclomatic → cognitive
→ size. Complexity is already clean, so — as in H — size genuinely is
the cause for once; each step still re-checks the first three before
touching length, and each step states which of H's three shapes
applies: **(a)** family split on a semantic boundary, **(b)** depth
extraction / mixin split keeping class identity, **(c)** artefact with
a written, measured argument.

## Rules every step obeys

- From §18.2: **when size and LCOM disagree, LCOM wins.** A cohesive
  class is made *shorter*, never *scattered*. The audit's component
  analysis (§3) is the input: single-component classes stay whole.
- One commit per step, self-contained. The full verification set is
  green before the next begins: suite, coverage non-decrease,
  `rule16_gate.py --with-clones`, `dump_public_api.py --diff`, and
  `radon cc -s` before/after on every function touched.
- Growth budget: **≤ 2% SLOC growth for the whole round** (H's lesson:
  stated against SLOC, not total lines — step I14 writes that into the
  rules; the round already honours it). Per-step hard cap: no step may
  grow tree SLOC by more than 0.5% without saying so in its commit.
- No step may add a module whose only content is re-exports, and no
  step may game a metric (§16.2): no `foo_part1`, no span-shrinking,
  no comment-padding for MI.
- Order is load-bearing: hygiene and duplication (I1–I2) before splits
  (known-bad lines go before anyone measures against them); wire
  guards before Qt-contract splits (guards first inside I3, then I4);
  verdict/artefact steps (I12–I13) late so they argue final numbers;
  the rules edit (I14) last.

Total: 15 steps, each sized ~8–16 h, ~150–180 h for the round.

---

### I0 — Verification baseline [DONE by the audit]

**Effort: ~8 h. Shape: measurement, no production change.**

Rebuilt the full environment headless (system PySide6 6.11 +
`tools/build_stubs.py` against system site-packages — note for the
next runner: the script defaults to `.venv/...`; pass an explicit
prefix), ran the whole suite with branch coverage, re-ran the `[mutmut]`
job, ran the gate with tools present, all 26 JS suites, and the audit
walker. Closed H-backlog #5 (mutation re-run: 90.0%, reproduced
exactly) and produced the baseline this plan builds on.

**Exit:** the audit report. No commit of its own — it lands with this plan.

---

### I1 — Hygiene and the missing guard [~8 h]

Closes every F-item that is deletion or documentation, and adds the one
guard whose absence F2 proves:

1. Delete the second `ElementMatch`/`Overlay` copies in
   `backend/dom_highlight.py` (~52 lines). Behaviour-neutral by
   construction (byte-identical) — the suite proves it.
2. Add `tests/unit/test_no_duplicate_definitions.py`: AST walk over
   production files failing on any duplicate top-level name.
   **Prove non-vacuous** by reintroducing one copy and watching it fail
   (the H discipline for every new guard).
3. Delete the dead `Iterator` import in `actions/registry.py`.
4. Hoist the function-local `import os` in
   `services/history/export.py::_ensure_media_dir`. If a new header
   clone group appears, argue it in `CLONE_BASELINE` like the other
   eleven (F3) — do not re-dodge.
5. Verdict on `services/run/coordinator.py::execute(scroll_parser=None)`
   (vulture-unused): keep as public engine API with a one-line reason
   at the signature, or remove and migrate callers — measured, not
   assumed. The other five vulture findings (`__aexit__` dunder pair,
   three hook-protocol `coordinator` params) are rule-allowed (§16.4);
   record them as inventory in the step commit, no code change.
6. Add the headless skip marker to
   `test_grid_in_real_webengine` (H-backlog #1) so the suite runs clean
   in one command; prove the marker triggers headless and the test
   still runs where a GPU exists (or document why that half is
   unprovable here).
7. Re-derive the two `# ideal-size` headers from measurement
   (router 508→527 / MI 44.9→46.8; schema_repair 440→460) — numbers
   only, arguments stand (F5).
8. Fix `docs/README.md` "165 Python test files" → 186 (F8).

**Exit:** suite green; `dom_highlight.py` 360→~308 with zero behaviour
delta; vulture tree-wide inventory documented (1 fixed, 1 verdict, 5
allowed); gate still green; one-command suite run.

### I2 — The two logic duplications [~8–12 h]

Pylint R0801's two pairs (F4) — real copied logic, outside the gate's
owned-file scope:

1. **JS candidate-label idiom** (6 lines): `_LABEL_JS` in
   `backend/dom_highlight_js.py` vs inline in `backend/dom_probe.py`.
   Decide the owning probe (research: which probe owns "candidate
   labelling"), single-source the fragment there, import at the other
   site. Constraint: §16.1.5 — the fragment move must not split
   `build_probe`'s literal to chase LOC; behaviour must be
   byte-identical, pinned by `tests/js_harness.js` runs before/after.
2. **Fail-open-predicate + wrapped-callback guard** (~10 lines):
   `backend/chat_sync/options.py` (`stopping`/`progress`) vs
   `backend/scroll_parser/parser.py` (`_stop_requested`/
   `_notify_collected`). Extract to the owning layer —
   `actions/cancellation.py` owns the stop protocol (RULE 7) and the
   wrap rule is RULE 5 — as named helpers, and call them from both
   sites. The explanatory docstrings move with the code, not deleted.
3. Re-run pylint R0801 on `backend/ bridge/`: both pairs gone, no new
   pair introduced. Record the tree-wide R0801 count in the commit so
   the next audit has a baseline (the gate still scopes to owned
   files — widening is I14's decision, not this step's).

**Exit:** 0 R0801 pairs tree-wide (from 2); JS harness suites green;
pipeline stop/callback tests green (RULE 7 paths re-proven, not
assumed).

### I3 — `bridge/file_bridge.py`: the preset applier [~12–16 h]

332 LOC / MI 37.5. **Shape: (a)** — but a Qt-contract file, so the
guard comes first:

1. **Guard first (TDD, RULE 16.6):** extend H1's `staticMetaObject`
   comparison pattern to `FileBridge` (and `StackBridge` — I4 needs
   it): a test that fails if a slot/signal disappears from the wire
   surface. Prove non-vacuous by removing a slot in a scratch edit.
2. Research the seam: the 8 module-level orchestration functions all
   take `bridge` and use only `bridge.ctx` + `bridge._log` (the file
   says so itself — feature envy, bounded and documented). Extract a
   `PresetApplier` collaborator owning `(config, log)` explicitly;
   slots keep their names/signatures; the router diff is empty.
3. `dump_public_api.py --diff` byte-identical; `bridge_safety` suite
   green; radon before/after on every touched function.

**Exit:** no part over 300 LOC; every part MI ≥ 45 *or* argued with
measurement; wire surface byte-identical; two wire guards exist where
one did.

### I4 — `bridge/stack_bridge.py`: preset-family mixins [~12–16 h]

330 LOC / MI 39.4; `StackBridge` 308 LOC / 31 slots, **one LCOM
component** — cohesive, so **shape: (b)**, H1-pattern, class identity
kept for Qt:

1. Split the file into preset-family mixins (run-controls +
   message/criteria core; stack presets; template presets; custom
   blocks) following H1's `HistoryBridge` shape. The shared
   `_remember_stack`/`_emit_*` stay with the core the families call
   into — no back-references.
2. The I3 `StackBridge` wire guard holds the slot contract; extend it
   if the split exposes names the guard does not pin (H's gate-vacuity
   lesson: the split and its guard update in the same edit).
3. Behavioural suites (`test_stack_commands`, `test_stack_presets`,
   router contract) green; public API diff empty.

**Exit:** no part over 300 LOC; class identity and wire surface
unchanged; LCOM no worse than one component.

### I5 — `services/history/mutate.py`: legacy and world-undo mixins [~12 h]

308 LOC / MI 36.2 (lowest MI in the tree). **Shape: (b)** — the class
is one component, but the *module functions* already separate by
prefix (`_legacy_*`, `_undo_*`, `_gaze_*`, `_config_*`):

1. Research the three clusters against callers: settings/gaze core vs
   legacy-import (`_legacy_user_rows`, `_insert_legacy_users`,
   `_merge_legacy_queue`, `_import_config_labels` — called from
   `migrate.py`'s flow via host) vs world-undo (`_backfill_seqs`,
   `_insert_world_entries`, `_rehome_undo_entries`, `save_world_undo`
   + module `_undo_rows`/`_write_world_undo`).
2. Extract `LegacyImportMixin` → `mutate_legacy.py` and
   `WorldUndoMixin` → `mutate_world_undo.py`; `HistoryService` MRO
   unchanged; `migrate.py` calls the same names on the same host.
3. Migration/undo suites green (legacy paths are RULE 8 territory: a
   test that passes with the migration deleted is not a test).

**Exit:** no part over 300 LOC; MI ≥ 45 per part or argued; install
migration, legacy import, and world-undo flows green.

### I6 — `backend/cdp_client.py`: the lease moves out [~8–12 h]

331 LOC / MI 36.7. **Shape: (a)** — `CdpLease` (~70 LOC with
`_LeaseCtx`/`TabInfo`) is a standalone priority mutex the client
*holds*, not client logic:

1. Move `CdpLease` (+ `_LeaseCtx`) to `backend/cdp_lease.py`;
   `CDPClient` (21 methods, one component — cohesive, LCOM wins)
   stays whole and imports it.
2. Harden coverage while here: `cdp_client.py` sits at 63.1% (§1.4).
   Tests for lease priority/waiting semantics that fail if deleted —
   a lease bug is a deadlock bug, fail-open tests only.
3. CDP/event suites green; vulture re-check on the moved
   `__aexit__` dunder pair (stays — protocol).

**Exit:** `cdp_client.py` ≤ ~260 LOC; lease module tested ≥ 80%;
no behaviour delta on the wire.

### I7 — `stores/history_repo_identity.py`: row-shaping vs identity [~8–12 h]

373 LOC / MI 44.8. **Shape: (a)** — `ConversationIdentity` (224/15,
person rows + rename) vs seven pure module functions (`align_batch`,
`resolve_days`, `_as_record`, `_record_fields`, `_ui_media_payload`,
`_reattributed_params`, `_minutes`) that shape rows for the *writer*:

1. Research callers: confirm the pure functions serve the append path
   and answer "this line → this row", while the class answers "this
   nick → this person". The file's own docstring argues they belong
   together — re-derive, don't quote; if the call graph agrees with
   the docstring, this step ends as a (c) with the graph as evidence.
2. If the seam holds, move row-shaping to the writer's side
   (`history_row_shaping.py` or into `history_models.py` — whichever
   the import graph (stores layering test) allows without a new
   upward edge).
3. History/append suites green; stores layering + file-count +
   import-baseline gates updated in the same edit (H's vacuity
   lesson — they count files by family).

**Exit:** no part over 300 LOC; stores gates green; either a split or
a call-graph-backed artefact argument — both are valid exits, gaming
is not.

### I8 — `backend/message_injector.py`: message vs search typing [~8–12 h]

380 LOC / MI 49.1 (MI fine — length only). **Shape: (a)** — two entry
points, two callers, one shared ladder:

1. `type_message` ← `actions/type_message.py` only;
   `type_search` ← `actions/search_users.py` only. Both share
   `_find_field` + `_run_type_strategies` + field helpers.
2. Split on the caller boundary: search path (`type_search` + focus
   dance) → `message_search_typing.py` (name TBD by domain);
   message path + shared ladder stay. Shared-primitives discipline
   (H-shape-(a)): the halves must not import each other.
3. Per RULE 19 §19.5 the 70-line `_run_type_strategies` ladder
   extracts per attempt, not per branch — out of scope here unless
   the split touches it, in which case attempts, not branches.

**Exit:** no part over 300 LOC; both action-block suites green;
verified typing behaviour unchanged (read-back assertions, not log
assertions).

### I9 — `backend/dom_highlight.py`: builders vs interpreters [~12 h]

360 LOC → ~308 after I1's dup deletion / MI 56.4. **Shape: (a)** —
`build_*_probe` (generate JS) vs `interpret_*` (parse results) share
only the diagnostic shape:

1. Research the import graph: `visual_click.py` and
   `scroll_parser/viewport.py` consume both halves. Decide whether
   the seam is build/interpret or find/click (RULE 1's two phases);
   the phase boundary is the domain concept — prefer it if the
   functions cluster that way.
2. Split; `ElementMatch`/`Overlay` (post-I1 single copies) live with
   the builders. JS-harness suites pin byte-identical probes.
3. RULE 1 re-verified end to end: FIND red → CLICK orange, stash
   reuse, `pointer-events:none` — the runner tests, not eyeballing.

**Exit:** no part over 300 LOC; all visual-click suites + JS harness
green; RULE 1 behaviour pinned.

### I10 — Small seams: registry, undo, lifecycle [~12 h]

Three research-gated (a)/(b)-lites in one step — each may validly exit
as (c):

1. `services/db_registry.py` (310/MI 44.5): the deletion-inventory
   cluster (`deletion_inventory_sources` + 4 `registry`-taking module
   helpers) vs path/active/remember registry. Extract if the cluster
   is caller-coherent (deletion flow only); else argue.
2. `services/undo_support.py` (292/MI 44.4): `UndoWorldStore`
   (save scheduling) vs `UndoProjection` (migration/projection) — two
   classes, two jobs, one file. Move `UndoWorldStore` if coupling
   allows (it takes `host` — check what of host it touches).
3. `services/db_lifecycle.py` (349/MI 41.8): `DbLifecycle` is 24
   methods / one component — cohesive. Only exit available is
   (b)-lite: the 8 small private helpers to module scope *if* they
   take explicit args and barely touch `self`; otherwise (c) with the
   component graph as evidence. Do not manufacture a split to move a
   number.
4. `services/preset_io.py` (312/MI 41.1) verdict: pure format library
   (lean (c) — libraries read by function; the design doc owns the
   unity) unless export/import halves prove caller-separable.

**Exit:** each of the four carries either a split or a measured
argument; stores/services gates green; no SLOC growth beyond the
per-step cap.

### I11 — Coverage hardening for Round-H products [~12–16 h]

Test-only step (RULE 8 + §16.3). No production change except what a
failing-then-passing test forces:

1. `stores/send_button.py` 21.1% → ≥ 80%, `bridge/history_media.py`
   37.6% → ≥ 80%: the two H extractions that are barely executed.
   Every new test must fail if its function is deleted or its boolean
   inverted; JS probes through `tests/js_harness.js`.
2. `bridge/history_bridge.py` 76.8%, `stores/media_download.py`
   72.2%, `bridge/history_delete.py` 72.6% → ≥ 80% combined.
3. Empty-vs-broken distinguished (RULE 4) and stop paths honoured
   (RULE 7) in every new test that loops.
4. Overall line ≥ 80% and not below 91.15%; branch ≥ 75% and not
   below 87.12%. (Floors ratchet to the new measurements at closing.)

**Exit:** five files ≥ 80%; overall coverage not decreased; mutation
job still 90.0% (re-run — the H6 tool changes and new guards have
never been mutation-tested, H-backlog residue).

### I12 — Reachable-surface and state verdicts [~8 h]

Measurement spikes, not refactors. Each ends in a verdict + a guard
or a follow-up design doc — never a drive-by conversion:

1. **`RunCoordinator`, 73 reachable (§16.5 landmine).** Build the
   mixin shared-attribute coupling graph (which of the 6 mixins
   touches which of the ~15 shared attributes). Verdict:
   coordinator-by-design (phase-separated mixins, composition root
   like `router`) vs grab bag. Expected: design + a guard test
   pinning each mixin's responsibility vocabulary (the H6 lesson:
   pin the decomposition so it can't silently re-tangle). A
   mixin→collaborator conversion is explicitly out of scope without
   a separate design doc.
2. **`_DeleteState`, 21 fields.** Per-phase field-usage clusters
   across the 8 `db_deletion_*` phase modules. Verdict: accumulator
   pattern (document) vs embedded dataclasses for coherent clusters
   (plan/remove/outcome). Small, only if the clusters are clean.
3. **`HistoryService`, 57 reachable.** Expected (c): service
   composition root, the router argument verbatim. One paragraph,
   measured.
4. **`ScrollParse` (306), `AppendPlanner` (338), `SyncSession`
   (252/23).** Expected (c) each, argued from the component graphs
   (§3 of the audit): block+schema unity; one append algorithm at
   LCOM\* 0.17; one session lifecycle. If any graph disagrees on
   re-measurement, it becomes a scoped follow-up, not a same-step
   split.

**Exit:** four written verdicts with graphs; ≥ 1 new guard test
(coordinator mixin responsibilities); zero production refactors.

### I13 — The density-MI artefact record [~8 h]

The anti-gaming step: eight in-band files with MI<45 (§1.6), argued
per file from measurement, H-(c)-style. For each: MI, LOC, SLOC,
max/mean CC, longest function, the LCOM/component verdict, and the
one sentence saying why splitting loses information. Files:
`label_assignments`, `layout_service`, `run/coordinator` (with the
`;`-chaining style verdict: leave — readability-neutral either way,
churn either way), `chat_sync/session`, `window_preset_bridge`,
`history/runtime`, `window_preset_store`, `undo_support`.

Two honest micro-moves ride along (statics to module scope — they
touch no instance state, so this deletes nothing and scatters
nothing): `UndoService._clean_blocks/_clean_history`,
`UndoProjection.clean/stack_projection/kind_projection`.

**Exit:** `# ideal-size`-style arguments recorded where the convention
puts them; suite green; MI moved only as a side effect (and the step
says which direction it moved and why that number is not the goal).

### I14 — Rules, budget, closing [~8 h]

1. **The budgeted rules edit.** `AGENT_RULES.md` is 781 lines vs its
   ~730 budget and §18.4 requires extract-before-add: move §18.2's
   per-file history to the Round I archive folder (leaving the norm
   + one link), *then* write the two rule changes: (a) growth budget
   re-expressed against SLOC (H-backlog #2 — ≤ 2% SLOC/round, per-step
   cap); (b) exempt files freeze-or-re-argue (F5: an `# ideal-size`
   header whose numbers drifted is stale documentation — re-derive or
   retire on touch). Net line change ≤ 0. Also record the
   widen-or-allowlist decision for tree-wide vulture/pylint (F7)
   rather than silently widening.
2. Doc updates in the same change (RULE 17): `docs/README.md` counts,
   archive index entry for this round, `SYSTEM_OF_RECORD.md` only if
   behaviour moved (it should not have).
3. **Full re-measurement + Round I closing** (§16.7 + RULE 18
   re-check): suite, coverage floors ratcheted, mutmut, gate with
   tools, JS suites, radon before/after ledger, SLOC growth vs
   budget, public-API diff empty. Every claim re-tested, none quoted —
   including this plan's own (c) verdicts.

**Exit:** rules file at or under budget with the two new constraints;
closing report written; all six families re-measured; round green.

---

## Appendix: what this round deliberately does not do

- No complexity work: CC/cognitive/nesting are closed; the CC-10
  quintet is a watch list, and touching a function at exactly 10 to
  "give headroom" is churn without a reader benefit.
- No `RunCoordinator` mixin→collaborator conversion (I12 measures;
  conversion needs its own design doc — §16.5 landmine).
- No `window_preset_service` re-litigation (G8 artefact; I0 re-verified
  the numbers, I10 does not reopen it).
- No tree-wide vulture/pylint widening without the allowlist mechanism
  (I1 documents inventory; I14 decides).
- No mutation-scope widening beyond re-running the configured job
  (I11) — widening is a round of its own (G5's cost analysis stands).
- No churn/bug-density metrics: unmeasurable on a 1-commit history
  (needs full history, not code).

## Appendix: RULE 16 §16.7 / RULE 18 re-check of this plan

(Rechecked at plan time per the request; rechecked again for real at
I14 against the changed tree.)

- [ ] No new function > 30 LOC except documented JS-literal builders —
  holds by construction: I1–I2 delete or single-source; I3–I10 split
  on semantic boundaries with per-unit budgets in each exit clause.
- [ ] No new class > 150 LOC or > 15 methods — collaborators
  (`PresetApplier`, lease, mixins) are scoped small in their steps;
  mixin splits keep reachable surfaces identical by design.
- [ ] No new function with > 4 params — no wide signatures introduced;
  I7/I10 move, not widen.
- [ ] CC ≤ 10, cognitive ≤ 15, nesting ≤ 4 on every touched function —
  verified per step via `radon cc -s` before/after (rule, not hope).
- [ ] Coverage not below baseline; branch ≥ 75% — I11 raises the thin
  files; every step re-runs the suite.
- [ ] Every new/extracted function tested as if new (RULE 8) — I3's
  guards-first order and I11's fail-if-deleted standard.
- [ ] No new vulture/pylint findings; no new clone groups — I1–I2
  reduce both; gate runs with tools present from I0's environment
  note onward.
- [ ] Overrides only with real constraints — expected count: zero new.
- [ ] No metric gaming — I12–I13 are explicitly verdict/artefact steps;
  I10/I7 may validly exit as (c); the plan names gaming-shaped exits
  and forbids them per step.
- [ ] RULE 18 ideals aimed at with `ideal-size:` reasons for deviation
  — file band 150–300 drives I3–I10; I13/I5-artefacts carry written
  reasons; I14 keeps the rules file itself inside budget.
- [ ] RULE 19 order followed — complexity re-checked before size in
  every split step; size-last with the H justification recorded once
  (thesis) rather than per step.
- [ ] Docs updated with behaviour — I14; plan + audit already placed
  per RULE 17 (dated archive folder + `reports/`).
