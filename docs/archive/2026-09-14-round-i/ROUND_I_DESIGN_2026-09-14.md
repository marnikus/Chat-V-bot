# Round I design — the repository's two worst files, the functions that break the cap, and the tests that only pass by luck

Date 2026-09-14 · branch `arena/01a0a136-chat-v-bot` · base `3d7f799` + Round H Area C (H-C1…H-C6, uncommitted)

**Status: PLAN, then implementation in the same session.** Every number below was
measured on this tree with the commands in *Reproduction* at the end. Required
by RULE 16 §16.6 step 2 and RULE 17.

---

## 1. Where the problem is now — measured after Round H Area C

Round H Area C closed the services/stores tail. The centre of gravity has moved
out of `services/` and `stores/` and into `bridge/` and `backend/`.

| Category | State at Round H base `5197ce0` | State now | Evidence |
|---|---|---|---|
| **Complexity** | 0 functions over CC 10 | unchanged | `current_audit.py` |
| **Size (Python)** | 39 functions > 30 LOC; 23 files > 300 | **35 functions > 30 LOC; 15 files > 300** | `audit_final.json` |
| **Maintainability** | mean MI 68.05, floor 24.9 | **mean MI 69.32**, floor still **24.9** (`bridge/history_bridge.py`) | `current_audit.py` |
| **Tests** | 3,172 passed; line 92.64 % | **3,186 passed; line 95.51 %** | full suite + `--cov` |
| **Smells** | 13 clone groups | **16 groups** (3 added by the H-C4/H-C5 splits, all import headers, 0 new/stale per the gate) | `rule16_gate.py --with-clones` |
| **Cohesion** | 36 classes > 150 LOC or > 15 methods | **36** — Area C's own offenders are fixed; what remains is bridge/backend | `audit_final.json` |

### The ranking, by impact × feasibility

1. **`bridge/history_bridge.py` is the worst file in the repository and has
   been for two rounds.** 544 lines, **MI 24.9**, a 467-LOC / 31-method
   `HistoryBridge`, **66.4 % covered**, `history_delete_person` at 44 LOC.
   Round H named it the top Area B target; Area B was never implemented.
   Low coverage plus the worst MI in the tree is the combination §16.5 calls a
   landmine: the file is both the hardest to change and the least verified.

2. **`backend/history_query.py` is the largest file in the repository.**
   601 lines, MI 35.3, and it owns the 3rd- and 5th-longest functions in the
   tree (`page` 53 LOC, `_search` 49 LOC). Its `HistoryQuery` class is an
   existing `RATCHET` entry at {362, 14}, which means the gate *permits* it to
   stay broken. Ratchets exist to stop growth, not to grant immunity.

3. **`backend/dom_probe.py::build_probe` is 107 LOC.** That is 3.6× the RULE 16
   cap and more than double the next-worst function in the repository. It is
   the single clearest hard-fail line in the tree and it is not ratcheted —
   it is simply in a file the gate does not own.

4. **Round H's own new modules are under-covered.** The H-C3/H-C4 extractions
   moved code into leaves that no test drives directly:
   `services/db_lifecycle_files.py` 71.9 %, `stores/media_download.py` 75.6 %,
   `stores/media_network.py` 76.1 %. Moving code does not create coverage, and
   the round that moved it should have paid for it.

5. **Tests that pass by luck.** Round H Area C hit two real bugs that only
   surfaced under full-suite load, and one of them —
   `test_patch_lands_in_the_worlds_app_settings` — failed twice in a row while
   a pristine-HEAD worktree ran clean. The suite contains **81
   `asyncio.sleep(0.0N)`-and-hope call sites across 20+ files**. Under
   coverage one more test failed that passes in every smaller run
   (`test_nick_placeholder.py::test_no_click_user_falls_back_to_the_step_user`,
   not reproduced since). A suite whose verdict depends on machine load is not
   a gate.

### Why this is one round and not four areas

Unlike Round H, these five items are **not** disjoint file sets — items 1, 2
and 3 all touch the archive path, and item 5 is cross-cutting by nature. They
are therefore sequenced, not parallelised. Order is chosen so that each step
leaves the suite green and independently revertable.

---

## 2. I-1 — the flaky-by-construction tests (do this first)

A red suite that cannot be reproduced costs more than any metric in this
document. Fix the *mechanism*, not the symptom.

* **I-1.1** Inventory the 81 `asyncio.sleep(0.0N)` sites. Classify each as
  (a) waiting for a real timer the product owns — legitimate; (b) waiting for
  an unawaited task to happen to run — a race; (c) waiting for nothing at all —
  dead weight.
* **I-1.2** For every (b), give the test a deterministic wait: await the task,
  or expose the pending-task set the production code now keeps (the
  `_pending_persist_tasks` pattern Round H added) and drain it.
* **I-1.3** Add a gate that fails when a new `asyncio.sleep(0.0N)` appears in a
  test without an allowlisted reason, so the count can only go down.

**Do not** fix these by raising the sleep. That trades a fast flake for a slow
one.

## 3. I-2 — `backend/dom_probe.py::build_probe`, 107 LOC

Split by the probe's own stages. The function builds one large JS expression;
its stages are already commented. Each stage becomes a named builder returning
a fragment, and `build_probe` becomes their composition. No signature change —
`build_probe` is called from `backend/` and pinned by the JS-shape tests.

Target: `build_probe` ≤ 30 LOC, every stage helper ≤ 30 LOC, CC ≤ 10, and the
generated JS **byte-identical** (assert it against a golden string, not by
eyeball).

## 4. I-3 — `backend/history_query.py`, 601 lines

Coverage is already acceptable; the problem is size and the two long
functions.

* **I-3.1** `page` 53 → ≤ 30 LOC and `_search` 49 → ≤ 30 LOC, by naming the
  stages each already runs.
* **I-3.2** Split the file on the seam between *query building* and *row
  shaping*. Target: no file > 300 lines, `HistoryQuery` ≤ 15 methods, and the
  `RATCHET` entry for it **removed** rather than lowered.

## 5. I-4 — `bridge/history_bridge.py`, 544 lines, MI 24.9, 66.4 % covered

**Coverage first, always** — §16.5. Raise the file to ≥ 85 % before moving a
line, because a split of an under-tested bridge is how frozen interfaces get
broken silently.

* **I-4.1** Cover the uncovered third: `history_delete_person` (44 LOC) and the
  emit paths. Target ≥ 85 %.
* **I-4.2** Only then split, by the bridge's own resource groups. Target: no
  file > 300 lines, `HistoryBridge` ≤ 15 methods, `RATCHET` entry removed, MI
  ≥ 45 on every resulting file.

## 6. I-5 — pay for Round H's new modules

Add direct tests for the leaves Round H created that none exist for:
`services/db_lifecycle_files.py` (71.9 %), `stores/media_download.py`
(75.6 %), `stores/media_network.py` (76.1 %), and `services/db_registry.py`
(70.7 %, the H-C3 "coverage first" target that was never done). Target: each
≥ 90 %, and no production file below 70 % except where a recorded reason says
why.

---

## 7. Deliberately out of scope

* **`UndoService`'s 28 methods.** Round H recorded why it cannot reach 15
  (three independent pins, one of them a module-level monkeypatch target). No
  new evidence this round; re-litigating it would just break Area B.
* **The seven recorded facades** (`HistoryRepo` 44 m, `Collector` 40 m,
  `LabelStore` 38 m, `MediaStore` 33 m, `HistoryDB` 30 m,
  `HistoryExportService`, `ScrollParser`). Their delegators are the frozen API.
* **Area A (frontend JS) and Area D (verification/mutation debt).** Both are
  real and both remain open from Round H; neither is touched here.
* **Branch coverage.** `--cov-branch` was not run this session; the 88.03 %
  branch figure from Round H is therefore *unverified*, not confirmed.

## 8. Definition of done

1. Full suite green — 0 failed, not "1 known flake".
2. No production file > 500 lines; no file > 300 lines without a split or a
   recorded reason.
3. No function > 30 LOC in the files this round touches.
4. `HistoryQuery` and `HistoryBridge` out of `RATCHET`, not lower in it.
5. Line coverage ≥ 95.51 % (must not regress) and branch coverage measured.
6. `rule16_gate.py --with-clones` green; `stores_modules.py` in band.
7. MI floor ≥ 45 across `services/`, `stores/`, `backend/`, `bridge/`.
8. Zero `asyncio.sleep(0.0N)`-and-hope sites left without an allowlisted
   reason, enforced by a gate.
9. `docs/current/*` updated in the same change.

## Reproduction (evidence for every number above)

```bash
cd /home/user/Chat-V-bot
QT_QPA_PLATFORM=offscreen LD_LIBRARY_PATH=/tmp/stublibs \
  .venv/bin/python -m pytest tests -q -p no:randomly \
  --deselect=tests/test_sash_webengine.py::TestSashWebEngine::test_grid_in_real_webengine
.venv/bin/python tools/metrics/current_audit.py > /tmp/audit_final.json
.venv/bin/python tools/metrics/rule16_gate.py --with-clones
.venv/bin/python tools/metrics/stores_modules.py
QT_QPA_PLATFORM=offscreen LD_LIBRARY_PATH=/tmp/stublibs \
  .venv/bin/python -m pytest tests -q -p no:randomly --cov=. \
  --cov-report=json:/tmp/cov_h.json --cov-report=term:skip-covered
```

Results as measured: **3,186 passed / 0 failed** plain; **3,185 passed / 1
failed** under `--cov` (the unreproduced `test_nick_placeholder` failure —
item I-1 exists because of it); line **95.51 %** (47,901 / 50,155); mean MI
**69.32** over 231 files; 15 files > 300 LOC; 35 functions > 30 LOC; 36 classes
over a RULE 16 class line; clone scan **0 new / 0 stale**.

---

## 9. Status — what this session actually did

| Step | State | Measured result |
|---|---|---|
| **I-1.1** inventory | **done** | 100 `asyncio.sleep` sites in `tests/`; **64 literal short sleeps (< 0.2 s) across 26 files**. The rest are `sleep(0)` (a correct yield point) or `sleep(step)`/`sleep(hold)` against a named product interval. |
| **I-1.3** ratchet gate | **done** | `tests/unit/test_sleep_and_hope_ratchet.py` — per-file ceilings, plus a stale-ceiling test so the ratchet cannot silently stop binding, plus a total that stops files trading with each other. Verified both directions: adding one `sleep(0.05)` to `test_db_manager.py` fails with `1 short sleep(s) at lines [538], ceiling is 0`. |
| **I-1.2** convert the races | **not done** | 64 sites remain. The gate freezes them; converting them is the next session's work. |
| **I-2** `build_probe` 107 LOC | **done** | Split into `_PROBE_HEAD` / `_PROBE_VISIBILITY` / `_PROBE_SCAN` + `_click_target` / `_click_block`. `build_probe` **107 → 25 LOC**; longest function in the file now 28. Generated JS proven **byte-identical** across all 8 `ProbeSpec` combinations against goldens captured from the un-split function, then pinned permanently in `tests/unit/backend/test_dom_probe_shape.py` (verified: perturbing the JS fails the digest). |
| **I-3** `history_query.py` 601 lines | **not done** | |
| **I-4** `history_bridge.py` 544 / MI 24.9 | **not done** | Still the worst file in the repository. |
| **I-5** cover Round H's new leaves | **not done** | |

**Suite: 3,192 passed / 0 failed** (was 3,186 before this round; +6 new tests).
`rule16_gate.py --with-clones`: green, 0 new / 0 stale.

### What the two completed steps have in common

Both were fixed by *freezing a measurement* rather than by editing until it
looked right. I-1.3 makes the sleep count monotonic; I-2's digest makes the
generated JavaScript immovable. In each case the gate was then deliberately
broken to prove it bites — a gate that has never failed is not evidence.

### Carried forward

I-1.2 (64 conversions), I-3, I-4, I-5, and everything Round H left open:
branch coverage still unmeasured, `services/db_registry.py` at 70.7 %, the MI
floor below 45 in 17 Area C files, and `docs/current/*` still not updated.
