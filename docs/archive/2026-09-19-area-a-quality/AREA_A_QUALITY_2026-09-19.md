# Area A report follow-up — safety evidence and gate maintenance

Base: `c74e14b`. Follow-up to `reports/AREA_A_TRANSFER_2026-09-19.md`.
Scope: prioritize the report, strengthen private-gate/decoder contracts,
simplify repeated identity comparisons, and repair two stale quality-test
locations without relaxing a threshold. Other workstreams remain deferred.

## Priority order and design

1. **Safety evidence:** cover unknown own-nick, renamed own-nick, flat author
   lists, refusal detail/order, default strict policy and decoder non-default
   values. The report lists 17 gate and 5 decoder mutation survivors; these
   are evidence gaps, not proof of bugs or equivalent mutants.
2. **Behavior-preserving cleanup:** normalize identity comparison values once
   per judgment; represent the three accepted outbound identities as a set.
   Keep original display nicks, author order and refusal strings. Remove the
   redundant equality branch in title matching (non-empty equality already
   implies substring membership). No added modes, signatures or acceptance
   rules. Baseline gate max CC=10; reduce repeated work, not just line count.
3. **Quality checker integrity:** its PersonPageRequest class moved to
   history_query_request.py, but two tests still inspect history_query.py.
   Correct the locations, preserving explicit existence and limit assertions.
4. **Verification/report:** rerun scoped mutation in isolated scratch copies,
   compare gate judgments with the parent implementation, run full tests and
   the measuring command; publish a priority-sorted follow-up rather than
   rewriting the historical transfer report.

Rejected: lowering coverage floors, excluding survivors from score without
proof, replacing early guards with eager evaluation, or expanding this pass
into unrelated Qt/UI/store repairs merely to get a green dashboard.

## Execution evidence

Results will be recorded in `reports/AREA_A_QUALITY_2026-09-19.md` after running
the tools. Current docs will link that report; the transfer snapshot remains
historical evidence.

## Results

- New characterization passed before the production cleanup (46 tests, 1,569
  subtests in the two focused files). Expanded backend selection afterwards:
  436 passes; full suite: 3,361 passes, 70 existing failures, no new failures.
- Private gate max CC 10 → 8, cognitive max unchanged at 4. `title_matches`
  CC 4 → 3; `_foreign_authors` 10 → 8. `_split_authors` CC remains 6, but
  comparison identity normalization is no longer repeated per author.
- 3,402 parent/new gate judgments match in every result field. Golden agent,
  historical API and targeted collector contracts remain green.
- Gate and decoder both have 100% measured line/branch coverage. Gate mutation
  191/195 (97.95%), decoder 153/153 (100%); four gate survivors remain visible.
- RULE 16 wrapper 23/23 passes; measuring command including clone scan has no
  breaches or missing tools. No threshold or snapshot changes.
- The priority-sorted report distinguishes completed changes from remaining
  release risks, preserves the historical baseline, and records commands and
  score denominators: `reports/AREA_A_QUALITY_2026-09-19.md`.
