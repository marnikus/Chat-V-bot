# Code quality audit — Round H baseline

**Date:** 2026-09-13 · **Branch:** `arena/01a09b51-chat-v-bot` · **Snapshot:** `e7328e1`
**Scope:** `core/ actions/ backend/ bridge/ services/ stores/ app/ main.py`
(191 production files, 24,690 non-blank non-comment lines, 2,107 functions,
233 classes)

---

## 0. Headline

**Complexity is closed. Coupling is healthy. Dead code is nil. Tests are
strong. The entire remaining debt is FILE LENGTH — and it is twelve files.**

The previous round's closing report named "26 classes over 15 methods" as the
biggest problem and `bridge/history_bridge.py` as its worst case. **Both claims
were wrong**, and this audit's first job was to disprove them. See §3.

---

## 1. The six metric families, measured

### 1.1 Complexity — closed

| Metric | Threshold | Measured | |
|---|---|---:|---|
| Cyclomatic complexity | ≤ 10 | max **10**, mean **2.97**, 0 above | ✅ |
| Functions at the CC ceiling | — | **5** | ✅ |
| Cognitive complexity | ≤ 15 | max **15**, 0 above | ✅ |
| Nesting depth | ≤ 3–4 | max **4**, 0 above | ✅ |

Nothing in this family needs work. Across 2,107 functions the mean cyclomatic
complexity is under 3.

### 1.2 Size and volume — the debt

| Metric | Threshold | Measured | |
|---|---|---:|---|
| Function LOC | ≤ 20–30 | mean 9.48, median 7, p90 20 | ✅ |
| Functions > 30 LOC | few | **38** (1.8%) | ⚠️ tail |
| Longest function | — | 122 (`dom_probe.build_probe`, §16.1.5 JS literal) | ✅ exempt |
| RULE 18.1 band (4–20 LOC) | aim | **62.6%** | ⚠️ |
| Class LOC | ≤ 200–300 | **7** over 300, max **457** | ⚠️ |
| Methods per class | ≤ 10–15 | **26** over 15, max 44 | ⚠️ but see §3 |
| Parameters | ≤ 3–4 | **52** over 4, max 20 | ❌ but see §4 |
| **Files ≥ 400 LOC** | RULE 18 | **12** | ❌ **the target** |

### 1.3 Coupling and cohesion — healthy

Measured Ca/Ce/I over intra-project imports for the twelve largest files:

| Module | Ca | Ce | I |
|---|---:|---:|---:|
| `bridge/router.py` | 1 | 17 | 0.94 |
| `backend/media_handler.py` | 1 | 4 | 0.80 |
| `backend/config_manager.py` | 3 | 10 | 0.77 |
| `bridge/history_bridge.py` | 1 | 3 | 0.75 |
| `stores/history_repo_lifecycle.py` | 1 | 3 | 0.75 |
| `services/db_deletion_flow.py` | 2 | 4 | 0.67 |
| `backend/chat_parser.py` | 5 | 4 | 0.44 |
| `backend/dom_highlight.py` | 2 | 1 | 0.33 |

No module is both heavily depended upon and heavily dependent. `router.py`'s
I=0.94 is correct for a composition root — it is *supposed* to be unstable and
depended on by nobody. **There is no coupling debt in this codebase.**

### 1.4 Tests — strong

| Metric | Target | Measured | |
|---|---|---:|---|
| Line coverage | ≥ 80% | **91.07%** | ✅ |
| Branch coverage | ≥ 75% | **87.05%** | ✅ |
| Mutation score | ≥ 70% | **90.0%** (360/400 reached) | ✅ |
| Test : code | ~1:1 | **1.56 : 1** | ✅ |
| Suite | green | 2,856 passed, 897 subtests | ✅ |

### 1.5 Code smells — nearly clean

| Smell | Measured | |
|---|---|---|
| Duplication | **2** exact groups, 26 physical lines (+10 baselined) | ✅ |
| Dead code | vulture ≥80%: **1** stale import, 6 protocol/dunder params | ✅ |
| Long methods | 38 functions > 30 LOC (1.8%) | ⚠️ small tail |
| God classes | **0** genuine — see §3 | ✅ |
| Feature envy | not detected at LCOM level | ✅ |

### 1.6 Maintainability

| Metric | Measured | |
|---|---|---|
| Mean MI | **68.68** | ✅ |
| Files below MI 45 | **28** | ⚠️ |
| Technical-debt ratio | not computed (no issue-tracker baseline) | — |
| Code churn | **unmeasurable** — git history is 2 commits deep | — |
| Bug density | **unmeasurable** — same reason | — |

---

## 2. The central finding: MI here measures LENGTH, not difficulty

Correlation between file LOC and file MI across all 191 production files:

> **corr(LOC, MI) = −0.819**

Two thirds of the MI variance is explained by file length alone. Checking the
28 files below MI 45 against their own complexity confirms it — *every one of
them is inside every complexity threshold*:

| File | MI | LOC | max CC | mean CC | functions |
|---|---:|---:|---:|---:|---:|
| `bridge/history_bridge.py` | 25.8 | 563 | 9 | **3.3** | 48 |
| `services/db_deletion_flow.py` | 32.7 | 527 | 8 | **4.5** | 27 |
| `stores/media_fetch.py` | 33.0 | 462 | 9 | **4.5** | 30 |
| `services/collector_tick.py` | 33.6 | 446 | 9 | **3.8** | 27 |
| `backend/config_manager.py` | 41.0 | 509 | 6 | **1.9** | 50 |
| `bridge/router.py` | 44.9 | 508 | 7 | **1.8** | 44 |

`config_manager.py` scores MI 41 with a *mean cyclomatic complexity of 1.9*.
`router.py` scores 44.9 at mean 1.8. Nothing in either file is hard; there is
simply a lot of it in one place.

**Consequences for this round.** Of the 12 files at or above 400 LOC, **10 are
below MI 45** — while only 18 of the other 179 files are. Splitting the twelve
is therefore the same work as fixing the MI backlog, and both reduce to one
RULE 18 question: *does this file fit the reader's context budget?* Chasing MI
directly would be metric-gaming; chasing length is the real fix, and MI will
follow as a side effect rather than as a goal.

---

## 3. Correcting the previous round's headline claim

Round G's closing report ranked "26 classes over 15 methods / 7 over 300 LOC"
as the biggest problem, led by `bridge/history_bridge.py` (44 methods). That
ranking counted method signatures without asking what the methods *do*.
Re-measured with delegation ratio and LCOM together:

| Class | Methods | Single-statement | LCOM | Verdict |
|---|---:|---:|---:|---|
| `stores/history_repo.py::HistoryRepo` | 44 | **93%** | 0.74 | facade — already decomposed |
| `services/collector_service.py::Collector` | 40 | **85%** | 0.87 | facade |
| `stores/label_store.py::LabelStore` | 38 | **94%** | 0.69 | facade |
| `stores/media_store.py::MediaStore` | 33 | **75%** | 0.73 | facade |
| `stores/history_db.py::HistoryDB` | 30 | **66%** | 0.68 | facade |
| `services/undo_service.py::UndoService` | 28 | **89%** | 0.77 | facade |
| `services/history/export.py::HistoryExportService` | 21 | **66%** | 0.80 | facade |
| `services/db_service.py::DbManager` | 19 | **94%** | 0.51 | facade |
| **`bridge/history_bridge.py::HistoryBridge`** | **31** | 12% | **0.31** | **cohesive, not a god class** |

Eight of the largest "god classes" are **facades whose methods are one
delegating line each**, left in place deliberately so the public API survived
earlier splits — each carries a docstring saying so ("the name stays on the
facade, which is what `services/`, the bridges and the media tests call").
Counting them as debt double-counts finished work, exactly as G4 found for
parameter objects.

And `HistoryBridge` — the file this round was expected to attack — has **LCOM
0.31**, one of the most cohesive classes in the tree. AGENT_RULES §18.2 already
settles the case: *"when size and LCOM disagree, LCOM wins."* Its 31 methods
share state and belong together. It needs to be **shorter**, not **split into
pieces that pretend not to know each other**.

### 3.1 A measurement bug found while doing this

The first LCOM pass scored `services/layout_service.py::LayoutService` at
**1.00** — apparently the worst class in the codebase. It is not: every method
is a `@classmethod` and the cohesion runs through `cls.V3_WINDOW_IDS`,
`cls.GRID_VERSION` and intra-class calls, none of which a `self.*`-only
attribute walk can see. Re-measured over `self` *and* `cls` plus call edges, it
scores **0.73** and 12 of its 15 methods are connected.

With that fix, **no class in the codebase exceeds LCOM 0.87**, and the top of
the corrected ranking is dominated by facades. There are **no god classes**.
The metric, not the code, was the problem — the third time this round of
auditing that a gate has been found measuring the wrong thing.

---

## 4. The parameter tail is still a measurement artefact

52 functions take more than 4 parameters, worst 20. Unchanged from G4's
finding, restated here so it is not re-discovered a third time: the five widest
non-`actions/` functions each already own a parameter object and keep the long
signature as their documented contract (`ScrollOptions`, `SyncOptions`,
`WriteContext`, `ClickRequest`, `AttachOptions`). The remaining bulk is the 15
`actions/` block `__init__`s, where the parameter list **is** the schema —
mirrored by `config_schema()` and `BUILTIN_BLOCKS` in `ui/js/stack-dnd.js`, and
§16.1.1 forbids hiding it behind `**kwargs`.

**This is an audit-definition defect, not a code defect, and Round H will not
chase it.** Fixing it means teaching the audit to exempt a signature that has a
documented parameter-object twin — a tools change, listed as step H6.

---

## 5. What Round H will do

The twelve files at or above 400 LOC, ranked by (LOC × 1/MI):

| # | File | LOC | MI | Character |
|---|---|---:|---:|---|
| 1 | `bridge/history_bridge.py` | 563 | 25.8 | cohesive class, 31 slots + 17 helpers |
| 2 | `services/db_deletion_flow.py` | 527 | 32.7 | 29 flat phase functions |
| 3 | `stores/media_fetch.py` | 462 | 33.0 | fetch strategies + network watch |
| 4 | `services/collector_tick.py` | 446 | 33.6 | one tick pipeline |
| 5 | `backend/config_manager.py` | 509 | 41.0 | 5 owner classes + manager |
| 6 | `stores/history_repo_lifecycle.py` | 450 | 38.8 | person lifecycle |
| 7 | `backend/chat_parser.py` | 441 | 40.7 | privacy gate + sync |
| 8 | `stores/history_schema_repair.py` | 440 | 41.8 | migrations |
| 9 | `backend/message_injector.py` | 482 | 43.1 | type strategies |
| 10 | `bridge/router.py` | 508 | 44.9 | composition root |
| 11 | `backend/media_handler.py` | 480 | 46.6 | attach pipeline |
| 12 | `backend/dom_highlight.py` | 590 | 54.8 | JS payloads (likely §16.1.5) |

Steps are sized at ~8–16 h each and defined in
[`ROUND_H_PLAN_2026-09-13.md`](../docs/current/ROUND_H_PLAN_2026-09-13.md).
