# Area A transfer and integration — 2026-09-19

Source: user-pasted delivery from
https://01a0bac5-301c-7f3c-b3dd-a98ec4725dec.arena.site/ (source design dated
2026-09-16); integrated onto `7aeafd4` on `arena/01a0bac1-chat-v-bot`.
This is a reconstructed code transfer, not a Git merge from an accessible
source branch. Only Area A is authorized. The supplied file bodies are the
reference; local compatibility and correctness fixes are recorded here.

## Design before integration

Adopt the supplied `CdpWire` connector/discovery split and deferred network
adapters; extract the existing private gate to a typed leaf; add the selector
registry/mirror, golden-page characterization and shim deprecation inventory.
Preserve the already-shipped `client_with_transport` helper and combined port
through an adapter instead of maintaining two live client implementations.
Keep the frozen constructor and snapshot. Do not overwrite the current System
of Record with the older supplied copy or erase Round I's validation caveats.

Existing source at transfer: `chat_parser.py` includes gate plus probes and
sync facade. Extract the gate's bodies first, preserving reason precedence
and output fields. Decoder rejects malformed author lists explicitly; this is
a fail-closed behavior change, not pure refactoring. Preserve valid-input
semantics and test malformed/non-finite numeric fields too. Do not allow
unrelated numeric metadata to crash the archive safety gate.

Source limitations to correct during integration:
- Network import exclusivity applies to `backend/`, not services/stores HTTP.
- Only the registered fixed selector subset is centralized; user-specified
  selectors and ratcheted legacy sites remain. Mirror parity is not live-site
  drift detection. Golden fixtures are synthetic DOM-stub scenarios, not
  authenticated captures or saved HTML recordings.
- Migration of old tests must not replace actual HTTP-adapter coverage with
  assertions only against pre-filtered fake responses. Add adapter tests.
- Typed state is used by the gate, not every sync/scroll consumer.
- Keep shim exports; warnings and importer inventory are not shim removal.
- P0–P6 completion, ≥90% branch and mutation targets require actual local
  measurement. The source document's reported results are not local evidence.

## Validation plan

Run existing backend/private-gate/CDP/scroll and real-agent tests before and
after; approve golden observations against the pre-transfer agent first.
Compare the typed gate with the old gate on a generated valid-input matrix.
Add malformed author/value regressions, adapter cancellation/error contracts,
full-machine API checks and an explicit CI canary job. Measure new/changed
Python with the existing RULE 16 tools; keep known baseline failures visible.
No threshold reductions or frozen snapshot refreshes are permitted.

## Results

**Integrated and tested; audit exit gates are not all complete.** Local source
adaptations and measured evidence are below; full commands and survivor lists:
[`reports/AREA_A_TRANSFER_2026-09-19.md`](../../../reports/AREA_A_TRANSFER_2026-09-19.md).
The supplied design is preserved as a reconstructed source record at
[`AREA_A_CDP_BOUNDARY_DESIGN_2026-09-16.md`](../2026-09-16-area-a-cdp-boundary/AREA_A_CDP_BOUNDARY_DESIGN_2026-09-16.md).

### Transferred implementation

1. CdpWire protocols, production adapters, `CDPClient.with_wire` and consumer
   test migration. The prior `client_with_transport` and `BrowserTransport`
   public helpers remain compatible; `cdp_ports.CdpConnection` now re-exports
   the single connection protocol. No network imports remain elsewhere in
   `backend/`; services/stores HTTP remains out of scope.
2. Frozen TabState/PaneAuthors/ScrollPos decoder and extracted private gate.
   Dict-facing signatures and public symbol identities remain unchanged.
3. All 39 agent query-selector literal sites replaced by the 20-entry mirror;
   scroll probe substitutions read the same registry. Exact doc-table parity
   and a legacy-site ratchet keep this subset coherent.
4. Eight supplied synthetic golden scenarios and approved observations, with
   every supplied fingerprint sequence verified against the untouched agent
   before migration. No live captures fabricated.
5. Twelve shim deprecations and importer inventory; original exports retained.
6. Source characterization suites reconstructed, plus independent production
   adapter tests and integration regressions. Registered new functions in the
   existing quality checker, and added a canary job to the staged CI template.

### Integration fixes (deviations from a blind file overwrite)

- The supplied moved `PrivateCheck`/`title_matches` aliases failed the real
  snapshot tool, which tracks module ownership. Their historical module
  identity is retained for serialization and API inspection; pickle and API
  regression tests pass. No frozen JSON snapshot or checker was relaxed.
- Decoder `_count` now catches OverflowError as well as malformed values, so
  infinite count metadata cannot crash an otherwise valid gate.
- Read-only mapping is checked against an explicit exact doc table, not just
  substring presence. Agent mirror format and unknown names are checked too.
- The fake wire parks on a queue and closes deterministically instead of
  repeatedly polling the event loop. EOF pending-request behavior remains
  unchanged; replay tests do not wait out the 30-second client timeout.
- Actual adapter tests cover timeout arguments, HTTP statuses, JSON failures,
  cancellation/resource cleanup and library-specific closure. Consumer-fake
  tests alone would not have provided this evidence.
- Shim inventory uses AST imports, warnings cover all twelve modules, and a
  mismatched replacement target is rejected rather than emitting wrong advice.
- Current docs were merged, not overwritten with the source's older baseline.

### Measured results

- Targeted: **424 passed, 1 xfailed, 1,637 subtests passed**.
- Full Python: **3,347 passed, 72 failed**, with the exact existing 72 failure
  identifiers; 2 skipped, 1 deselected, 1 xfailed, 2,555 subtests passed.
- Backend API and block-wire snapshot: unchanged and passing.
- Golden: **8/8**; history-agent **43/43**; private scope **15/15**.
- Full Node harness: **22 passed / 14 failed**, same existing UI failures.
- RULE 16 measuring command with clone scan: **zero breaches**, no skipped
  tools. Test wrapper retains two pre-existing stale request-location failures.
- Coverage: **92.94% line / 88.46% branch**; improved over the local prior run
  but below the historical official baseline. No global acceptance claimed.
- Gate: **98.99% line / 96.43% branch**. New wire adapters, decoder, selector
  helpers, shim helper and combined-port adapter: **100% line/branch** where
  branch denominators exist.
- Mutation: private gate **183/200 = 91.50%**; decoder **148/153 = 96.73%**.
  Zero unreachable/timeouts/errors; 22 survivors explicitly retained, not
  marked equivalent. These are scoped measurements, not a repo-wide score.
- Valid-state differential: **5,760 judgments, zero differences**. Malformed
  list sample: twelve explicit refusal changes (including four prior errors).

### Remaining audit gates

No shim deletion, sync/scroll-wide typed migration, live capture/drift monitor,
full parser/command mutation run, coupling trend or active CI ratchet is
claimed. `tools/ci/quality-gate.yml` remains an inactive template awaiting the
workflow permissions/activation described in its header. Global baseline test
failures and the historical coverage-floor shortfall remain visible release
work; unrelated B–F production code was not changed.
