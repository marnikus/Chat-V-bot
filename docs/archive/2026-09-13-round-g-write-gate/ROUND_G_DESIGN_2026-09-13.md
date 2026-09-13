# Round G design — the open tails after Round F, and step G1: the write-gate union fix

Date 2026-09-13 · branch `arena/01a09b73-chat-v-bot` · base `0ad07c9`
(the merge of `arena/01a09227-chat-v-bot` that closed Round F).
Required by RULE 16 §16.6 step 2 and RULE 17. Every number in §1–§2 was
re-measured from this tree, not quoted from a report; the commands are in
**Reproduction** at the end.

## 1. The tail inventory — every open item, with its evidence

Round F closed its eight steps (F1–F8) against the targets in
`docs/archive/2026-09-12-round-f-size-tail/ROUND_F_DESIGN_2026-09-12.md` §6 and
`ROUND_F2_F3_GOD_CLASS_DESIGN_2026-09-12.md`. What follows is the complete set
of items those documents (and the reports in `reports/`) explicitly left open,
plus what a fresh audit of this tree found that no report records. Sorted by
severity, not by size.

### 1a. NEW — the suite is red at HEAD, and no report knows it

`tests/test_engine_standalone_run.py::TestSavedTabMainConfig::test_saved_tab_main_preset_is_user_independent`
**fails deterministically** at `0ad07c9`: baseline run of this session measured
**1 failed, 2 800 passed, 2 skipped, 1 deselected, 1 xfailed, 897 subtests**
(5 m 55 s). Round F's last recorded run (§11.7 of the Round F design) was
2 800 passed / 0 failed / **3** skipped — the same collection, with this test
skipping. The difference is not the code; it is the checkout:

* `config/` is **gitignored** ("Runtime config (split stores …)") but seven
  `config/*.json` files are **tracked anyway** (tracked beats ignored) — among
  them `config/blocks.json` (550 B) and a 170 KB `config/undo.json`. They
  entered the repository with the squash-merge, so on every fresh clone of
  `0ad07c9` the test now runs instead of skipping.
* The test iterates the JSON root as a **list** (`for c in stored`); the
  production shape — written by `stores/block_store.py::BlockStore.save_custom_block`
  and present in the tracked file — is `{"custom_blocks": [ … ]}`. Iterating a
  dict yields keys, so `c.get("name")` raises `AttributeError: 'str' object has
  no attribute 'get'`.
* Even with the shape handled, the test hardcodes a block named **"Tab Main"**
  (one machine's data); the tracked file holds **"Custom Klicer win"** —
  `next(…)` would raise `StopIteration`.

Three distinct defects in one test: wrong reader (raw `json.load` instead of
the production store), wrong shape assumption, machine-specific data baked into
assertions. It violates RULE 8 in spirit — it reads a file instead of executing
the real store — and its skip-on-pristine-clone design meant CI-shaped
environments never saw it fail.

**Owner finding — RULED (2026-09-13):** the seven tracked `config/*.json`
files contradicted the `.gitignore` intent (runtime data). This round fixed
the test to be correct with the file **present or absent**; the tracking
question was put to the owner, who ruled **keep `config/` tracked** and drop
the contradicting ignore rule, so tracked state is intended state. Applied in
this round's follow-up commit: the `config/` line is removed from
`.gitignore` (the legacy `config.json*` rules stay — those files are not
tracked).

### 1b. F3c — the write-gate desync, a named residual risk and the only live bug class

`ROUND_F2_F3_GOD_CLASS_DESIGN_2026-09-12.md` §8.10 settled the world-switch
flake as a **product bug**: `WriteTurn.held` is ONE flag per connection, so two
overlapping write transactions desynced the flag from the `WorldGate` depth and
left the turn held by a closed connection — after which **every writer on that
world waits `WAIT_S` (15 s) and fails OPEN**, writing without the exclusion the
gate exists to provide. That is the exact bug class the gate was added for
(2026-09-11: a Ctrl+Z reported success while the person stayed deleted).
§8.10 removed the one *source* it could prove (overlapping undo saves, now
queued) and recorded the structural defect as **F3c**, deliberately not fixed:

> "Residual risk, deliberately not fixed here. `WriteTurn.held` is still one
> flag per connection, so *any* two concurrent writers on one `HistoryDB` — a
> gaze save against a collector append, say — can desynchronise it from the
> gate's depth the same way. … Fixing `WriteTurn` properly means a nesting
> count per task, which changes an 817-line pinned contract
> (`tests/test_world_write_gate.py` asserts `turn.held` as a boolean)."

Corroborating evidence since: Round F design §9.7 observed a one-off ordering
failure in
`tests/integration/services/test_services_people.py::TestSnapshots::test_payload_falls_back_to_queue_when_engine_raises`
under concurrent CPU load, diagnosed as "consistent with a dropped write under
contention and with nothing else observed … Not proven". F3c is the mechanism
that would produce exactly that.

Measured state of the target: `stores/world_lock.py` 241 LOC, MI 58.69, worst
CC 5 (`retry_locked`), `WriteTurn` at lines 134–158 (25 LOC, CC 2). Not a
§16.5 landmine, not in AREA B's frozen three (`history_db`, `history_models`,
`history_repo`), absent from `api_baseline.json`. The pinned surface is
`tests/test_world_write_gate.py` (826 lines), whose only `held` assertions are
two `assertFalse(…turn.held)` reads — a **property** returning `bool` satisfies
both. No production code reads `.held` at all (grep: zero hits outside
`world_lock.py` itself and the two test lines).

**This is step G1 (§3).** It is the biggest problem that is (i) a correctness
defect rather than structural mass, (ii) named and deferred by the previous
round with its remedy already designed in prose, and (iii) fixable without
spending any frozen guarantee.

### 1c. The frozen five and the F0 decision — the biggest structural mass

Re-measured on this tree: **7 files over 500 lines** (was 10 at the 2026-09-12
audit; F1–F3 removed three).

| Lines | MI | File | Status |
|---:|---:|---|---|
| 807 | **11.35** | `backend/chat_sync.py` | AREA D frozen; note says 800 (stale) |
| 706 | 28.58 | `backend/scroll_parser.py` | AREA D frozen; note says 699 (stale); `ScrollParser` 532 LOC / 39 m / LCOM\* 0.88 — the largest god class left, §16.5 landmine |
| 603 | 35.41 | `backend/history_query.py` | AREA D frozen; note says 596 (stale); ratcheted 362/14 |
| 544 | 24.95 | `bridge/history_bridge.py` | F4 §18.5 note (QWebChannel slots); ratcheted 467/44 |
| 534 | 55.91 | `backend/dom_highlight.py` | AREA D frozen; note says 527 (stale) |
| 509 | 40.96 | `backend/config_manager.py` | AREA D frozen; note says 502 (stale) |
| 509 | 31.50 | `services/db_deletion_flow.py` | **unfrozen**; "the F1 family's next candidate" (§18.2 measured bullet), no note |

`chat_sync.py` remains what the 2026-09-12 audit called it: MI 11.35, roughly
half the next-worst score — "a single file accounts for most of the
maintainability risk in the codebase". Round F §7 reserved the unblock to the
owner (**F0**): option (a) refresh the AREA D snapshot
(`tools/metrics/dump_public_api.py --write`) as a coordinated change and split;
option (b) keep the notes and do not split. (b) was applied.

New in this design, because §7 did not have it: the snapshot contract itself
admits **two split mechanisms that spend nothing**:

1. **Base-class extraction.** `tests/unit/backend/test_backend_api_snapshot.py`
   accepts a pinned method that is "moved into a shared base — same surface"
   (`have["inherited"][method] == sig`), and `dump_public_api.dump_class`
   deliberately records the inherited surface for exactly that. A pinned class
   may keep a shell in its module and inherit the bodies from sibling-module
   bases. Bases may be added ("may move up the MRO or gain parents, but must
   stay an ancestor").
2. **Private-helper extraction.** The dumper skips every `_`-prefixed name
   ("privates are this area's own business"), so private functions and methods
   may move to sibling modules freely; only the module qualname must stay a
   file (packages are skipped) and public symbols must stay owned.

Honest appraisal per file, recorded so nobody oversells either mechanism:
for `ScrollParser` (one class, 39 methods, low cohesion) base-class extraction
is a *genuine* decomposition — the same collaborator pattern F2/F3 used, with
the facade kept by contract instead of by taste. For `chat_sync.py` the mass is
**seven public phase classes**; extracting their bodies into bases leaves
hollow shells in the pinned file — legal, but the improvement is mostly
notional, so a real split of `chat_sync.py` still wants the F0(a) refresh.
The decision stays the owner's; step G2 carries both routes.

**F0 RULED (2026-09-13, owner, verbatim):** *"remove any restrictino to all
frozen solutions. redesign any code as needed"* — the AREA B / AREA D freezes
are lifted for Round G onward. Pinned surfaces may change, and the snapshot
tests (`test_stores_public_api.py`, `test_backend_api_snapshot.py`) are
refreshed **deliberately, inside the step that changes the surface**, with the
diff justified in that step's design doc (§16.2's anti-gaming discipline still
applies — lifting a freeze is not a licence to shrink assertions silently).
Consequences for the plan: G2 takes route (a) as its default (real
`chat_sync.py` split + `ScrollParser` decomposition); G4's formerly-frozen
wide signatures (`scroll_parse.__init__` 20 p, `chat_parser.sync_conversation`
14 p) become migration candidates rather than quality-override debt. G1
itself is unaffected: it landed contract-free and needed no spend.

### 1d. Structural tail, unfrozen — measured on this tree

| Item | Measured 2026-09-13 | Source of the obligation |
|---|---|---|
| Functions > 4 params | **51** (worst 20: `actions/scroll_parse.py::__init__`) | F5 floor for `stores/` (7, all contract-blocked); 44 outside: `actions/` 15 (RULE 3 legacy shape — decide per block), `backend/` 13 (mostly AREA D-pinned signatures: `sync_conversation` 14, `find_and_click` 12), `services/` 13, `bridge/` 2, `app/` 1 |
| Functions > 30 LOC | **42** | incl. `collector_service.py::__init__` 51 (F2's recorded §16.5 deviation), `scroll_parse.py::__init__` 49, `message_injector.py::_run_type_strategies` 70 (§19.5 names the remedy: extract per attempt) |
| Classes > 150 LOC | **38**; > 300 LOC: **9**; > 15 methods: **26** | facades (`HistoryRepo` 44 m, `LabelStore`, `MediaStore`) are the house shape and stay; genuine candidates: `StackBridge` 308/31 LCOM\* 0.89, `ScrollParse` 306/14 LCOM\* 0.92, `SchemaMigrator` 406/25 (cohesive, needs helper-module extraction) |
| Files 300–500 over the §18.2 ideal without a note | **20** | §12.8 of the Round F design: "clearing the other 20 is its own change and is not claimed here" |
| Cognitive > 15 (fail line) | **2**: `bridge/router.py::_build_router_class` 17, `stores/settings_store.py::get` 17 | legacy offenders under §16.0/§16.5 — and **undocumented**: the 2026-09-12 audit attributed the two cognitive outliers to `dom_probe::build_probe`, which measures ≤ 15 on this tree. The audit's attribution was wrong; the real two appear in no exemption record |
| `stores/` module count | 37 files → **15** §18.3 modules, ratcheted | F8's counting remedy; closed |

### 1e. Test-quality tail

| Item | Evidence |
|---|---|
| `undo_history._migrated_entry` — **no test at all** | §8.12.5: "the seq-preserving legacy rebuild is entirely unexercised, which is the function whose bug pushed every app entry ahead of the world entries and issued duplicate seqs" |
| `undo_world._schedule_world_undo_save` — no test calls it; `restart_world`'s three failure paths uncovered | §8.12.5 (`undo_world.py` 84.34%) |
| `undo_apply.py` eight attributed uncovered lines | §8.15.8 list (exception fallbacks, refusal returns, redo `Err`) |
| **F6b**: module-wide mutation of `history_query.py` | §9.6: 910 of 1 141 mutants reachable vs the configured job's 159; "its own step … not smuggled into a test-only commit" |
| No JavaScript coverage instrumentation | 2026-09-12 audit §3: 23 frontend JS files / 9 237 LOC plus embedded JS payloads sit outside every denominator |
| `dbconn` rewind asymmetry | §8.13.3 "Named, not done": a refused dbconn op does not `rewind_after_failure` the way `archive` does; needs the retryability decision for legacy delete entries |

### 1f. Hygiene and docs tail

| Item | Evidence |
|---|---|
| Five stale `ideal-size:` notes, each exactly 7 lines low (800/807, 502/509, 527/534, 596/603, 699/706) | Round F §12.8: "A note whose number is wrong is worse than no note"; parked because the files are AREA D-frozen — comment-only edits do not touch the snapshot, so the park was round policy, not contract |
| Four unused imports: `core/events.py` (`field`), `backend/criteria_engine.py` (`field`, `Optional`), `services/undo_support.py` (`copy`) | §10.4 named the first three; re-confirmed with pylint W0611 on this tree, which also surfaced the fourth — vulture misses all of them for §10.4's reason (the names are used elsewhere in the scanned set) |
| vulture ≥ 90 %: 7 findings | unchanged inventory (`actions/registry.py:18` + six protocol args) |
| `docs/README.md` map is stale | says "three current docs and 78 archived"; `docs/archive/README.md` said 83 in 16 groups while the tree holds 17 — the `2026-09-13-round-f/` group was never indexed — and the `docs/README.md` tree drawing missed `2026-09-12-round-f-size-tail/` and `2026-09-13-round-f/` while labelling `2026-09-12-db-undo-restore-port` "(newest)". **Partially paid by G1**: both index files gained the missing groups and true counts when this folder was registered (RULE 17); the `docs/README.md` "Current vs. historical" table rows for Rounds F/G stay owed to G6 |
| `docs/current/AGENT_RULES.md` at **763** lines against its stated ~730 budget | §11.8: "The budget overrun itself is pre-existing debt … paying it down is its own change" |
| One standing warning: `coroutine 'Collector.handle_push' was never awaited` in `test_services_history.py` | §11.7 recorded it as pre-existing |

## 2. Prioritisation — why G1 is what it is

Ranked by *severity class* first (a live defect beats structural mass), then by
what is spendable without an owner decision:

1. **The suite is red (§1a).** Everything else verifies against the suite
   (§16.6 step 3 makes the existing run the equivalence gate); a red baseline
   makes every later "still green" claim meaningless. Fixed inside G1 — it is
   one hour of the step, not its own step.
2. **F3c (§1b).** The only open item that is a live product-bug *class* with a
   proven instance (§8.10's journal), a named remedy, a plausible second
   sighting (§9.7), and no frozen guarantee in its way. Data integrity beats
   maintainability.
3. **The frozen five (§1c).** The largest mass, but gated on the owner's F0
   decision and — for `chat_sync.py` — genuinely blocked without it. G2, in the
   shape the owner picks.
4. Unfrozen structural tail (§1d) → G3/G4. Test-quality tail (§1e) → G5.
   Hygiene (§1f) → G6. JS coverage → G7 backlog.

## 3. Step plan — Round G (each step sized ≈ 8–16 h)

| # | Step | Content | Size driver |
|---|---|---|---|
| **G1** | **Green baseline + the write-gate union fix (F3c)** | §1a test fix; §1b `WriteTurn` redesign, tests with negative checks, doc updates | this document §4–§5 |
| G2 | The two worst files — **F0 ruled: freezes lifted (§1c)** | route (a): split `chat_sync.py` (807 · MI 11.35) into a prefix family with the AREA D snapshot refreshed in-step, and decompose `ScrollParser` (532/39) | design doc per §16.5 (landmine) |
| G3 | The unfrozen 500-line file + the named long-flat ladders | `services/db_deletion_flow.py` 509 → F1-family split; `message_injector._run_type_strategies` 70 → per-attempt extraction (§19.5); `collector_service.__init__` 51 and `scroll_parse.__init__` 49 reductions | 3 named targets |
| G4 | Wide-parameter continuation (F5, outside `stores/`) | `services/` 13, `bridge/` 2, `app/` 1 parameter objects; per-block RULE 3 ruling for `actions/` 15 (documented constraint or migration); formerly pinned signatures (`scroll_parse.__init__` 20 p, `sync_conversation` 14 p) migrate properly now that the freezes are lifted (§1c F0 ruling) | 44 → floor |
| G5 | Test-debt batch | `_migrated_entry`, `_schedule_world_undo_save`, `restart_world` failure paths, `undo_apply`'s eight lines; **F6b** module-wide mutation measurement of `history_query.py`; dbconn-rewind decision + implementation if the owner rules | coverage ≥ baseline |
| G6 | Hygiene + docs reconciliation | five stale notes corrected (comment-only, snapshot-neutral); three unused imports; `docs/README.md` map; AGENT_RULES.md budget paydown 763 → ≤ 730 by §18.4's "extract first"; the two cognitive-17 offenders reduced or recorded as exemptions; `config/` tracking **ruled** (owner: keep tracked — applied in the G1 follow-up commit) | one commit per family |
| G7 | Backlog (scheduled after G1–G6) | JS coverage instrumentation; `StackBridge`/`ScrollParse` cohesion passes; `HistoryExportService` 21-method pass | — |

**Implement 1st step only** — the owner's instruction for this session. G2–G7
are planned, not started.

## 4. G1a — the broken test, redesigned

### 4.1 What the test must prove

The 2026-09-09 config split moved custom blocks into `config/blocks.json`. The
invariants worth pinning, separated from the machine data that broke:

1. **Codebase fact (always runs):** a custom block is user-independent —
   `CUSTOM_FIND ∉ USER_SCOPED_BLOCKS`. The original test could only assert
   this through one machine's file; it is a property of the engine and runs
   everywhere.
2. **Real-store fact (runs where data exists):** whatever the local
   `blocks.json` holds must survive the production reader and be runnable —
   read through `BlockStore` (RULE 8: execute the real thing, not a raw
   `json.load`), every entry's `block` constructs into its registered block
   class, and every stored setting survives the RULE 3 round trip
   (`to_dict()` re-emits it unchanged).
3. **Skip semantics kept:** pristine clone (no file) or empty store → skip, as
   before — but the skip now triggers only on *absent data*, never on a shape
   the test failed to understand.

Rejected: keeping the "Tab Main" lookup with a shape fix — the name is one
machine's data and its absence raises `StopIteration`, the second latent
failure this session found. Rejected: asserting `highlight_enabled` /
`selector` truthiness on arbitrary stored blocks — both are user settings that
may legitimately be false/empty; the round-trip check subsumes what was honest
about those assertions (stored values arrive on the constructed block).

### 4.2 Shape

`TestSavedTabMainConfig` becomes `TestSavedCustomBlocks` with two test methods
(the invariant one + the data one, `subTest` per stored entry). Imports move to
module top per the file's existing convention (`BlockStore`, `CustomFind` — the
file's registry-snapshot dance is untouched: fake blocks shadow the registry at
import and are restored at module end; constructing `CustomFind` directly is
registry-independent, as it was). No production code changes in G1a.

## 5. G1b — `WriteTurn`: one flag → the union of its writers

### 5.1 Current code, and exactly how it desyncs

```python
class WriteTurn:                      # stores/world_lock.py:134-158
    def __init__(self, token, path=""):
        self._token = token
        self._gate = gate_for(path)
        self.held = False             # ONE flag for the whole connection

    async def begin(self) -> bool:
        if self.held: return True     # "idempotent per transaction"
        self.held = True
        return await self._gate.enter(self._token)

    def end(self) -> None:
        if not self.held: return
        self.held = False
        self._gate.leave(self._token)
```

The callers (`stores/history_db.py` — AREA B frozen, not touched by this step):
`_gated` calls `begin()` before **every write statement**; `_release` calls
`end()` on **commit**; `_gated`'s except path and `_closed` call `drop()`.
So the contract is: *first write of a transaction takes the gate, commit gives
it back* — and "whose transaction" is invisible to a single flag.

Failure sequence (the §8.10 journal, generalised to any two tasks T1/T2 on one
`HistoryDB`):

```
T1 write stmt  → begin: flag False→True, gate.enter(token)   gate depth 1
T2 write stmt  → begin: flag already True → no-op             gate depth 1
T1 commit      → end:   flag True→False, gate.leave(token)    gate depth 0  ← T2 is mid-transaction!
   [window: any other connection can now take the gate while T2's rows are uncommitted]
T2 write stmt  → begin: flag False→True, gate.enter(token)    gate depth 1  (re-entry)
T2 commit      → end:   flag→False, leave                     depth 0       (this interleaving recovers…)
```

…and the interleaving that does **not** recover — the one §8.10 captured, where
T2's re-entry lands *before* T1's leave is processed (depth 1→2) and T2's
single leave decrements to 1: the turn stays held by a connection that later
closes, every subsequent writer waits 15 s and **fails open**, and exclusion is
silently off for the rest of the process. A third defect the flag has: T2's
failed statement calls `drop()`, clearing **T1's** turn as well.

### 5.2 The fix: a set of writer tasks, gate held for the union

`begin()`/`end()` are keyed by `asyncio.current_task()`. The gate is taken on
the **first** writer and given back only when the **last** one finishes — union
semantics, which is what file-level exclusion actually requires.

```python
_NO_TASK = object()          # key for a begin/end outside any asyncio task

class WriteTurn:
    def __init__(self, token, path: str = ""):
        self._token = token
        self._gate = gate_for(path)
        self._writers: set = set()

    @property
    def held(self) -> bool:                 # the two assertFalse(…) pins read this
        return bool(self._writers)

    async def begin(self) -> bool:
        key = asyncio.current_task() or _NO_TASK
        if key in self._writers:
            return True                     # a further statement of THIS transaction
        self._writers.add(key)
        if len(self._writers) > 1:
            return True                     # the gate is already held for this connection
        return await self._gate.enter(self._token)

    def end(self) -> None:
        key = asyncio.current_task() or _NO_TASK
        if key not in self._writers:
            return                          # an end from a task that never wrote: no-op
        self._writers.discard(key)
        if self._writers:
            return                          # another transaction is still open
        self._gate.leave(self._token)

    def drop(self) -> None:
        """The connection is unusable: abandon EVERY open turn (old semantics)."""
        if not self._writers:
            return
        self._writers.clear()
        self._gate.leave(self._token)
```

Why a **set of tasks** and not the "nesting count per task" §8.10 sketched:
`_gated` calls `begin()` per *statement*, while `end()` arrives per *commit*. A
counting design (shared or per-task) therefore leaks by construction — five
statements plus one commit leaves count 4 — unless something tells `begin`
whether a call is a new transaction or the same one's next statement. Nothing
at the statement level can know that; the **task identity** can, because one
task runs one transaction at a time on one connection (SQLite commits are
connection-wide, so an "inner transaction" of the same task does not exist at
the DB level either). Per-task membership makes `begin` idempotent exactly
where the docstring always claimed it was ("idempotent per transaction") and
makes `end` release exactly one transaction. This is the design §8.10 meant;
the count formulation is recorded here as rejected, with the arithmetic.

Semantics deliberately preserved from the flag version:

* `end()` from a task that never began is a **no-op** (old: `if not held`), so
  cross-task commits can no longer release another task's turn — that release
  *was* the desync, not a feature. Every production path pairs write and
  commit inside one task (`_gated`→`_release`), and the one test that calls
  `turn.begin()` directly commits in the same task.
* `drop()` **clears everything**, matching the old single-flag clear, because
  both its callers mean "this connection is done": `_closed` (close) must not
  leave the gate held by a dead connection — that is §8.10's leak — and
  `_gated`'s except path treats a failed statement as poisoning the whole
  connection transaction, which SQLite's semantics agree with (a rollback is
  connection-wide). A per-task `drop` was considered and rejected: it would
  reintroduce the dead-connection leak for depth > 1.
* A fail-open `begin` (gate.enter → False after `WAIT_S`) still sets the
  writer and still writes: availability over exclusion after 15 s is the
  documented I-17 behaviour; nested begins inherit the fail-open state, as
  they inherited `held=True` before.
* Cancellation between `begin`'s `_writers.add` and a commit leaves the task's
  membership until `close()`/`drop()` — the identical exposure the flag had
  (`held=True` set before `await enter`). Not worsened; recorded.

### 5.3 Contracts checked before the edit, not after

| Contract | Effect of the fix |
|---|---|
| `tests/test_world_write_gate.py` 383/442: `assertFalse(…turn.held)` | `held` is a property returning `bool` — reads unchanged; no test assigns `.held` (grep: only `world_lock.py` itself did) |
| `TestGateUnit::test_the_same_token_may_enter_twice` | pins `WorldGate`, untouched |
| `test_the_queue_write_waits_for_the_archive_transaction` | `db.turn.begin()` + `db.commit()` in one task → membership added and removed by the same key |
| `test_a_failed_statement_gives_the_turn_back` | single writer, failed statement → `drop()` clears → `held` False, gate free — as before |
| AREA B (`stores/history_db.py` frozen) | zero changes to `history_db.py`; the fix lives entirely in `world_lock.py`, which no golden file pins |
| AREA D snapshot | `stores/` is outside its scope |
| SYSTEM_OF_RECORD I-17 | "take the SAME gate from their first write until the transaction ends" — now true per transaction *and* for overlapping ones; the row needs no edit, and the file is at its §18.4 ceiling |
| `services/undo_support.py` `schedule_save` docstring | states "the connection's `WriteTurn` tracks 'held' with ONE flag" as the bug's mechanism — becomes stale; rewritten in the same commit (RULE 17) to past tense, keeping the queueing fix's *other* justification (DELETE-all/INSERT-all interleaving is data-level and independent of the gate) |
| Round F archive §8.10 | archived docs are not edited to catch up (RULE 17), but the repo's own practice (§8.12.4, §8.13.3 "RESOLVED — …") is a one-line resolution pointer; F3c's residual-risk paragraph gets exactly that |

### 5.4 Tests (RULE 8, §16.3 — each must fail with the fix reverted)

New class `TestWriteTurnUnion` in `tests/test_world_write_gate.py` (the file
whose docstring says "two things are pinned here: 1. **the gate**"). Six
tests, interleavings forced with `asyncio.Event`, not sleeps:

1. `test_the_gate_survives_the_first_of_two_overlapping_commits` — two tasks
   `begin()` one turn; the first `end()`s; the gate must still be busy and
   `held` still True; a foreign token's `gate.enter` inside a shrunken
   `WAIT_S` must fail (this is the exclusion proof); the second `end()` frees
   it. **Fails pre-fix** at the first assertion pair (old code releases).
2. `test_a_second_statement_of_one_transaction_never_double_holds` — one task:
   begin, begin, end → freed, gate depth back to 0 (pins `_gated`'s
   per-statement begin; a naive counter design fails this).
3. `test_a_commit_from_a_task_that_never_wrote_releases_nothing` — T1 begins;
   T2 `end()`s → still held (old code: released — the desync); T1 `end()`s →
   free.
4. `test_drop_gives_back_every_writer_of_a_dead_connection` — two tasks begin;
   `drop()` → `held` False, gate free (pins `_closed` semantics; a per-task
   drop fails this).
5. `test_overlapping_transactions_on_one_real_history_db` — the §8.10 scenario
   end-to-end on a real `HistoryDB` over a temp world file: two concurrent
   tasks each `set_meta` (a real INSERT through `_gated`) with the commit held
   open on an event; while both are open, a foreign `world_write` token cannot
   take the gate; after T1 commits it still cannot (old code: it can — the
   assertion that fails pre-fix); after T2 commits it can.
6. `test_a_fail_open_turn_still_tracks_and_ends_cleanly` — added during
   execution, for two reasons. It pins I-17's third documented property
   against the new class (a turn whose `gate.enter` timed out still tracks its
   writer, and its `end` must not release the real holder's turn), and it
   recovered the one coverage line the fix legitimately orphaned: the old
   flag's spurious mismatched `gate.leave` calls were the only thing executing
   `WorldGate.leave`'s ignore guard (line 122), and removing spurious leaves
   *is* the fix. The guard stays reachable through the fail-open `end`; the
   test walks that path, so `world_lock.py` ends the step with no missed line
   or branch that HEAD did not also miss. Passes pre- and post-fix (a
   semantics pin, like tests 2 and 4).

Negative checks: tests 1, 3 and 5 run against `git show HEAD:stores/world_lock.py`
compiled into a probe module; the expected pre-fix failures are recorded in §6.
Existing pins: the full 826-line file must pass **unchanged** — not one
assertion edited (the F1 §8.1 discipline: `git diff tests/` shows only added
code).

### 5.5 Dishonest reductions rejected (§16.6 requires recording these)

* **Raising the 3 s test budget or `WAIT_S`** — §8.10 said it outright: hides
  the defect and leaves exclusion silently off.
* **Deleting the §9.7 flake report instead of fixing its mechanism** — the
  observation stands; G1 removes the mechanism it named.
* **A shared integer counter** — leaks with per-statement `begin` (§5.2
  arithmetic); would have passed a "two writers" test and failed the real
  call pattern.
* **Per-task counts** — same leak, plus cleanup burden for dead tasks.
* **Editing `history_db.py` to make `_gated` transaction-aware** — AREA B
  frozen module; the fix must live in `world_lock.py` alone.
* **Moving the tests to a new file to avoid growing the 826-line gate file** —
  the gate file is the documented home of gate pins; §18.5 invents no
  `ideal-size:` note for test files (§8.12.5's ruling), and the growth (~110
  lines) is recorded in §6 rather than hidden.

### 5.6 Targets to verify after G1

| Measure | Before | Target |
|---|---|---|
| Full suite | 1 failed / 2 800 passed | **0 failed**, ≥ 2 800 + new tests, no test losing status |
| `WriteTurn` desync (five new tests) | n/a | pass; each **fails pre-fix** (negative check recorded) |
| `world_lock.py` worst CC | 5 | ≤ 10 (methods are CC ≤ 3) |
| `WriteTurn` class LOC | 25 | ≤ 120 ideal (expected ~45 with docstrings) |
| Line / branch coverage | 91.77 % / 86.96 % (recorded §10.7/§11.7) | **not below**; `world_lock.py` expected 100 % statement on the new class |
| `rule16_gate.py --with-clones` | rc=0 | rc=0, 0 new clone groups |
| vulture ≥ 90 % | 7 | 7, none new (`_NO_TASK`, `held` property are used) |
| pylint on touched files | — | no new message types |
| JS suites | 26/26 | 26/26 (untouched; re-run as a cheap regression) |
| Docs in the same commit (RULE 17) | — | `undo_support.py` docstring rewritten; §8.10 pointer added; archive index + docs map updated for this folder |

## 6. Outcome (recorded after execution, 2026-09-13)

G1 is implemented: the suite is green at HEAD's successor state, and the
write-gate desync (F3c) is closed with a negative-checked test class.

### 6.1 Targets vs achieved

| Measure | Before (measured this session) | Target | Achieved | |
|---|---|---|---|---|
| Full suite | **1 failed** / 2 800 passed / 2 skipped / 897 subtests | 0 failed, ≥ 2 807 | **2 808 passed / 0 failed**, 2 skipped, 1 deselected, 1 xfailed, 898 subtests, 8 m 09 s — reconciles exactly: the fixed test (+1), its split into two methods (+1), six new union tests (+6); the +1 subtest is the stored block's `subTest` | ✅ |
| F3c negative check | n/a | union tests fail pre-fix | **3 failed / 3 passed** against `git show HEAD:stores/world_lock.py` — exactly the predicted split: the two overlapping-commit tests and the stranger-commit test fail; the second-statement, drop-clears-all and fail-open pins pass under both versions | ✅ |
| `world_lock.py` worst radon CC | 5 (`retry_locked`) | ≤ 10 | **5** unchanged; the new `begin`/`end` are CC 4, cognitive 3, nesting 1 | ✅ |
| `WriteTurn` class | 25 LOC, flag | ≤ 120 ideal | **67 LOC** (docstring included), 5 methods, longest method 15 LOC — inside the RULE 18 ideals, not just the RULE 16 fail lines | ✅ |
| `world_lock.py` file | 241 lines, MI 58.69 | §18.2 band | **285 lines** (150–300 band), MI 55.90 | ✅ |
| Coverage, same-sandbox HEAD comparison | HEAD: line 90.90 % (14 315/15 586), branch 86.99 % (3 264/3 752) | not below | line **90.91 %** (14 328/15 599), branch **87.01 %** (3 270/3 758) — both totals **up**; `world_lock.py` 97.71 → 98.00 % line, 0 missed branches before and after | ✅ |
| §16.3 recorded floors (2026-09-10) | line 90.44 %, branch 84.38 % | ≥ | 90.91 / 87.01 — above both | ✅ |
| `rule16_gate.py --with-clones` | rc=0 | rc=0 | **rc=0**, "All owned functions fit. Ratchet intact. No stale overrides.", clone scan 0 new / 0 stale | ✅ |
| `tests/test_rule16_new_code.py` | 23 passed | 23 passed | **23 passed** | ✅ |
| vulture ≥ 90 % | 7 | 7, none new | **7**, same set, none in the touched files (`_NO_TASK` and the `held` property are consumed) | ✅ |
| pylint message profile, touched production files | HEAD's profile | no new types | **identical** to HEAD's (`W0718` ×3 + `R1720` ×1 on `world_lock.py`; `undo_support.py` unchanged — its docstring-only edit moves no message) | ✅ |
| JS suites | 26/26 | 26/26 | **26/26** measured this session; no JS file is touched by G1 | ✅ |
| Docs in the same commit (RULE 17) | — | all four | `undo_support.schedule_save` docstring rewritten (flag story → past tense, queueing justification kept); §8.10 RESOLVED pointer added; `docs/archive/README.md` gained **two** groups — this one and the never-indexed `2026-09-13-round-f/` — with the count corrected 83/16 → 86/18; `docs/README.md` tree and counts fixed | ✅ |

### 6.2 What the execution found that the design did not predict

* **The fix orphaned one coverage line, and the honest remedy was a new pin.**
  The first post-fix coverage run showed `world_lock.py` missing lines
  [122, 129, 226, 227] against HEAD's [127, 182, 183] — i.e. HEAD's three
  (renumbered) plus line 122, `WorldGate.leave`'s ignore-guard. The old flag
  reached that guard through *spurious* mismatched leaves (a stranger's `end`,
  a fail-open `end`); removing spurious leaves is the fix, so the guard lost
  its incidental cover. It stays reachable through the fail-open `end`, and
  test 6 (§5.4) now walks that path deliberately, pinning I-17's fail-open
  property for the union class at the same time. Post-fix miss set measured:
  **[129, 226, 227]** — exactly HEAD's miss set renumbered (`leave`'s
  defensive `except RuntimeError` and `_rollback`'s `except/pass`), and
  missed branches are 0 before and after.
* **`services/undo_support.py` carries an unused `import copy`** (pylint
  W0611, invisible to the repo-wide vulture for §10.4's cross-module reason).
  Pre-existing; NOT removed in this commit — G1's `undo_support.py` edit is
  docstring-only so the equivalence gate stays clean. Added to §1f's hygiene
  list for G6.
* **The archive index had drifted before this round**: `2026-09-13-round-f/`
  (F5's doc) existed on disk but was in neither the group table nor the
  section list of `docs/archive/README.md`, and its counts said 83/16 against
  17 folders on disk. Registering this round's folder could not leave that
  inconsistency standing, so both groups were indexed and the counts
  re-measured with `find` (86 docs, 18 groups). The deeper `docs/README.md`
  "Current vs. historical" table stays G6's.

### 6.3 RULE 16 / RULE 18 recheck (§16.7 checklist, self-review)

```text
[x] No new function > 30 physical LOC        (longest new: begin, 15)
[x] No new class > 150 LOC or > 15 methods   (WriteTurn 67 LOC, 5 methods)
[x] No new function with > 4 params          (max 2: __init__)
[x] radon CC ≤ 10, cognitive ≤ 15, nesting ≤ 4 on every new/edited function
    (measured: CC 4/4/1, cognitive 3/3/1, nesting 1/1/1)
[x] overall line coverage ≥ 80% and not below baseline; branch ≥ 75%
    (same-sandbox HEAD comparison above; both totals rose)
[x] every new function has a test that would fail if deleted
    (held/begin/end/drop each drive an assertion in TestWriteTurnUnion;
     delete the union logic and 3 tests fail — measured, §6.1 row 2)
[x] no new vulture findings; no new duplication groups (both re-run, 7 / 0)
[x] quality-override comments used only with a real constraint (none used)
[x] did not game metrics with dummy helpers (the two rejected designs and
    the coverage-line episode are recorded, §5.5 and §6.2)
[x] new code aims at the RULE 18 ideals (every function 4–20 lines; the file
    stays in its 150–300 band; no ideal-size: note needed anywhere)
[x] any complexity/size remediation followed the RULE 19 order
    (nothing was over a complexity line; this was a correctness fix — the
     class grew 25→67 LOC *because* the decision structure became honest,
     which is the order's spirit: semantics first, size last)
[x] SYSTEM_OF_RECORD.md + docs/README.md updated if behaviour/docs moved
    (I-17's text is unchanged and remains true — verified by reading it
     against the new semantics; docs/README.md and the archive index updated)
```

One §16.5 note, because the rule is about *not growing offenders*: no legacy
offender was touched. `WriteTurn` was inside every threshold before and after;
`world_lock.py` grew 241 → 285 lines, inside §18.2's band, the growth being
the docstring that records the bug class — the constraint §18.5 exists for is
not needed because no ideal was exceeded.

## Reproduction

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python tools/build_stubs.py                    # Qt stubs for a headless box

# the red baseline (1 failed)
QT_QPA_PLATFORM=offscreen LD_LIBRARY_PATH=/tmp/stublibs \
  .venv/bin/python -m pytest tests -q --tb=short -rf \
  --deselect=tests/test_sash_webengine.py::TestSashWebEngine::test_grid_in_real_webengine

# static audit -> /tmp/audit_g.json
.venv/bin/python tools/metrics/current_audit.py

# gates
.venv/bin/python tools/metrics/rule16_gate.py --with-clones
.venv/bin/python tools/metrics/stores_modules.py
.venv/bin/vulture core actions backend bridge services stores app main.py --min-confidence 90
for f in tests/test_*.js; do node "$f"; done
```
