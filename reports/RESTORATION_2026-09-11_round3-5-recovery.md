# Restoration report — 2026-09-11: recovering the round 3/4/5 CC-tail work

Branch: `arena/01a0920c-chat-v-bot`. Author of this record: the recovery run,
not the original round. Everything below is measured on this tree with the
repository's own tools; no figure is re-typed from an older report.

---

## 1. Why the work could not be restored

`main`'s tip is **a commit with no parents**:

```
$ git rev-parse origin/main
5118273daf764c44f3dd9ac0d7020e253c5cd548
$ git log -1 --format='%h parents=[%p] %s' origin/main
5118273 parents=[] Merge remote-tracking branch 'origin/arena/01a08da4-chat-v-bot'
$ git rev-list --count origin/main
1
```

The message says "Merge", but the object has an empty parent list: `main` was
re-rooted into a **single orphan snapshot**. Its 240-commit history was
severed. The consequence is total, and it is the whole failure:

```
$ git merge-base origin/main origin/arena/01a08dc3-chat-v-bot
(no output, exit 1)          # <- NO common ancestor exists
$ git merge-base --is-ancestor origin/main origin/arena/01a08dc3-chat-v-bot
NO
```

This branch was cut from that orphan, so it inherits the disconnect. Git
cannot merge, cherry-pick, rebase or `log --follow` across an absent merge
base — every attempt either refuses ("refusing to merge unrelated histories")
or silently produces a 237-file diff in which the newer work is indistinguishable
from a deletion. **That is what made the previous work look lost.** It was not
lost; it was unreachable by history.

Round 3's own report already recorded the symptom from the inside
(`reports/CODE_QUALITY_METRICS_2026-09-11_round3.md`):

> **Baseline caveat (read first).** This checkout has exactly one commit
> (`git rev-list --count HEAD` = 1), so the previous tree cannot be re-measured.

---

## 2. Does the round-E job exist? Verified answer

**The reports round3/4/5: yes. The round-E ("CC tail … queue exhausted")
delivery and commit `c49e51f`: no — it was never pushed to GitHub.**

| Searched | Result |
|---|---|
| All 33 remote branches (`git ls-remote`, then full fetch) | `c49e51f` absent |
| `gh api repos/.../commits/c49e51f` | HTTP 422 `No commit found for SHA` |
| GitHub commit search `"Wave E2"` | `total_count: 0` |
| All 3 pull refs (`refs/pull/{1,2,3}/head`, `refs/pull/3/merge`) | heads are `9f81938`, `eb3dc43`, `5329ec3`, `5f4a244` — none is `c49e51f` |
| Tags | none exist |
| Every subject line of all **280** commits reachable from any ref, grepped for `wave`, `round e`, `e2:`, `tail cc`, `exhaust` | 0 hits |
| `git grep -I` across all branch trees for `wave e2`, `round e`, `queue exhausted` | 0 hits |

### Which branches contain the round3/4/5 reports

Exactly **one** branch, in exactly **one** commit:

```
origin/arena/01a08dc3-chat-v-bot  @ 607bee5 (2026-09-11 18:00:02 UTC)
  "Round 5: make RULE 16 §5 real, run the browser suites, fail the delete tool closed"

  reports/CODE_QUALITY_METRICS_2026-09-11_round3.md
  reports/CODE_QUALITY_METRICS_2026-09-11_round4.md
  reports/CODE_QUALITY_METRICS_2026-09-11_round5.md
```

`git log --all -- <path>` returns `607bee5` for all three files and nothing
else. No other branch, and no commit on `main`, has ever contained them.

Round 5's report states its own provenance problem, which is why round E is
missing too:

> `git log` on this branch ends at the base commit `53ba5fb` — rounds 1–4 were
> written into the working tree but never committed (the branch's history
> reverted to the base at some point, and **pushing is blocked by the
> sandbox's GitHub auth**).

Round E died the same way: it lived in a sandbox working tree whose push never
landed. When that sandbox was torn down, waves A–E2 went with it.

---

## 3. The quoted baseline is authentic — reproduced exactly

Measured with `tools/metrics/current_audit.py` (the frozen definitions, scope
`core actions backend bridge services stores app main.py`), on the true common
ancestor `53ba5fb` of the round work:

| Metric | Your baseline | Measured on `53ba5fb` | |
|---|---:|---:|---|
| Functions CC > 10 | 63 (max 28) | **63** (max **28**) | exact |
| Mean CC | 3.30 | **3.30** | exact |
| Cognitive > 15 | 21 (max 40) | **21** (max **40**) | exact |
| Nesting > 4 | 3 (max 6) | **3** (max **6**) | exact |
| Function LOC > 30 | 74 | **74** | exact |
| Functions in scope | 1,668 | **1,668** | exact |

The `main` snapshot measures the same 63 / 28 / 21 / 40 / 3 / 6 / 74, so the
baseline you were quoted is real and reproducible. The **final** column
(0 offenders, max CC 10, mean 3.10, 2 cognitive, 0 nesting, 44 LOC, 2,578
tests) is not reproducible from anything on GitHub — that state no longer
exists anywhere retrievable.

One independent corroboration that the round-E report was honest rather than
invented: it named the only two functions left over the cognitive gate as the
frozen/exempt `_build_router_class` and legacy `settings_store.get`. On this
recovered tree those two are still the top of the remaining list, both at
cognitive **17** — precisely the max the round-E report quoted:

```
cog 17  CC 10  bridge/router.py:113      _build_router_class
cog 17  CC  7  stores/settings_store.py:89  get
```

---

## 4. How the recovery was done

History could not supply a merge base, so one was reconstructed. `53ba5fb` is
the genuine common ancestor of the round work and of `arena/01a09022` (whose
tree `main`'s snapshot differs from by only 22 files):

```
$ git merge-base origin/arena/01a08dc3-chat-v-bot origin/arena/01a09022-chat-v-bot
53ba5fb6ef9cf6c5ac6f3460fae403c0e5c401c1
```

`main`'s tree was re-rooted onto that ancestor with a synthetic anchor commit
(`git commit-tree <main-tree> -p 53ba5fb`), which gave git the base it had
lost, and `607bee5` was then merged normally:

```
Automatic merge went well; stopped before committing as requested
CONFLICTS: (none)
35 files changed, 4834 insertions(+), 649 deletions(-)
```

**Zero conflicts.** Only one file (`tests/test_db_unified_world.py`) had been
touched on both sides, and it auto-merged.

This was the right base and not `main` itself: merging `dc3` onto `main`
directly would have *deleted* 22 files of newer work that `dc3` predates —
`bridge/file_bridge.py`, `services/preset_io.py`, `core/version.py`,
`ui/js/window-presets.js`, `tools/ci/quality-gate.yml`, the preset-IO and
file-bridge suites. After the merge all of them were verified still present,
alongside all 13 recovered round-5 files.

---

## 5. Verified state of the recovered tree

Measured with the same script, and tested with the repository's own runbook
(`QT_QPA_PLATFORM=offscreen`, `tools/build_stubs.py` for the headless GL/NSS
stubs, the one documented WebEngine deselect):

| Metric | baseline `53ba5fb` | `main` snapshot | **recovered (this branch)** |
|---|---:|---:|---:|
| Functions in scope | 1,668 | 1,754 | **1,835** |
| Functions CC > 10 | 63 | 63 | **42** |
| Max CC / mean CC | 28 / 3.30 | 28 / 3.34 | **19 / 3.22** |
| Cognitive > 15 / max | 21 / 40 | 21 / 40 | **10 / 22** |
| Nesting > 4 / max | 3 / 6 | 3 / 6 | **2 / 6** |
| Functions LOC > 30 | 74 | 74 | **61** |
| Mean function LOC | 10.3 | 10.3 | **10.1** |
| Python suite | 2,545 pass | — | **2,725 passed, 0 failed**, 6 skipped, 1 xfailed, 782 subtests, 287 s |
| RULE 16 gate violations | — | 248 (0 with reason) | **248 (7 accepted with reason)** |

The recovered tree is a **superset**, not a trade: it carries 1,835 functions
— `main`'s newer feature code *plus* the round-5 decomposition — and still
holds the round-5 complexity numbers. The suite is 147 tests larger than the
round-E figure you quoted, because it is the union of both sides.

### Two pre-existing failures, fixed (not merge damage)

The first full run gave `2 failed, 2723 passed`. Both failures reproduce
**identically on the untouched `main` snapshot**, so they are debt `main`
carried in and never re-gated — not damage from the recovery:

1. **Exact-clone group** `stores/preset_store.py:70 | stores/window_preset_store.py:33`
   — the per-path singleton `__new__`, duplicated line for line.
   `window_preset_store.py` exists only on `main`, so the pair is main-side
   duplication. Fixed by moving the bookkeeping to `per_path_instance()` in
   `stores/json_store.py` — the lifecycle base both classes already inherit,
   so no new module (the stores file-count ratchet stays at 36) and each class
   keeps its own `super().__new__`, leaving the MRO untouched.
2. **stores-import pin** counted 37 against 38 real imports. The +1 is the
   portable window-preset feature importing into `stores/` from outside
   (`backend/config_manager.py`, `bridge/router.py`) — the case the pin's own
   comment explicitly permits. Bumped to 38 with that reason recorded beside
   the number, rather than silently.

Neither was papered over with a baseline entry or a `skip`.

---

## 6. What is recovered, and what is permanently gone

**Recovered onto this branch (39 files, +4,881 / −679 vs the `main` snapshot),
plus the 240 commits of real history that `main` had severed:**

* the round3 / round4 / round5 metrics reports, `PROBLEM_PRIORITIES_2026-09-11.md`,
  `docs/CC_TAIL_ALL_DESIGN_2026-09-11.md`;
* the round-4/5 CC-tail decomposition across 22 production files
  (CC offenders 63 → 42, project max CC 28 → 19, cognitive 21 → 10, LOC>30 74 → 61);
* the metrics tooling the rounds were measured with — `gate_check.py` (including
  the RULE 16 §5 `# quality-override:` mechanism), `cc_inventory.py`,
  `cc_tail_table.py`;
* 5 new test suites — browser-suite runner, override-format, silent-`except`
  deletion, unverifiable-world refusal, cancellation helpers.

**Gone, and not recoverable from GitHub:** round E's waves A–E2, i.e. the
42 → **0** CC-offender reduction, nesting 2 → 0, LOC>30 61 → 44, mean CC →
3.10 and the 2,578-test figure. Commit `c49e51f` was never pushed. If any
sandbox working tree from that session still exists on your machine, that is
the only copy; otherwise those waves have to be re-run.

### The remaining queue, so round E can be restarted from fact not memory

42 functions are over the CC gate; the top of the list is:

| CC | cog | LOC | where |
|---:|---:|---:|---|
| 19 | 14 | 79 | `stores/migration.py:39 migrate_legacy_config` (frozen on purpose) |
| 15 | 14 | 26 | `backend/chat_sync.py:216 plan` |
| 15 | 15 | 30 | `backend/chat_sync.py:633 _settle_at_top` |
| 15 | 11 | 31 | `backend/history_query.py:560 person_stats` |
| 15 | 13 | 39 | `services/collector_service.py:434 handle_push` |
| 15 | 9 | 20 | `stores/history_models.py:109 from_dict` |
| 15 | 14 | 26 | `stores/history_repo_identity.py:161 _ui_record` |
| 14 | 22 | 38 | `backend/dom_probe.py:163 interpret` |
| 14 | 19 | 41 | `services/undo_service.py:436 work` |
| 14 | 18 | 39 | `stores/user_memory.py:210 replace_all` |

Regenerate the full ordered list at any time with
`python3 tools/metrics/cc_tail_table.py BASE NOW BASE_COV NOW_COV`, and the
whole gate picture with
`python3 tools/metrics/gate_check.py main.py core actions backend bridge services stores app --classes`.

Nesting > 4 is down to two sites (`backend/cdp_client.py:187 fetch_tabs` at 5,
`bridge/collector_bridge.py:97 collector_command` at 6).

---

## 7. Recommendation: stop this happening again

`main` being an orphan is the root cause and it is still true upstream — the
next branch cut from `main` will hit the identical wall.

1. Re-root `main` onto real history. The 240-commit lineage is now carried by
   this branch (second parent `607bee5`), so it is no longer at risk; making
   `main` descend from it restores `merge-base` for every future branch.
2. Push before a sandbox is torn down. Rounds 1–4 and round E were both lost
   to uncommitted working trees; round 5's report documents the auth failure
   that caused it.
3. Keep `reports/` and `docs/` committed in the same commit as the code they
   measure — round E's report survived only as chat text, which is why its
   numbers could be quoted but not verified.
