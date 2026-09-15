# Area D design — verification and measurement debt

Round H · 2026-09-14 · owns `tools/**`, `tests/**` (existing files), `docs/**`,
`reports/**`, `setup.cfg` — **no production file**
Part of [`ROUND_H_DESIGN_2026-09-14.md`](ROUND_H_DESIGN_2026-09-14.md).
Source of numbers: [`reports/CODE_QUALITY_METRICS_2026-09-14.md`](../../../reports/CODE_QUALITY_METRICS_2026-09-14.md),
`/tmp/coverage_h.json`, `/tmp/mutmut_results.txt`. **Plan only — nothing implemented.**

## 1. Why this area exists, and why it can run in parallel

The suite measures **strongly**: 3,172 passed / 0 failed, line 92.64%, branch
88.03%, mutation 99.37%. Those numbers are real. But three measurement gaps sit
directly on top of the risk:

1. **One mutation job, one module.** `setup.cfg [mutmut]` mutates
   `backend/history_query.py` only; the 99.37% is a statement about 1 of 208
   files. Every other module's mutation score is unknown.
2. **Coverage hides the risky files in the average.** The global floor is met
   while `backend/message_injector_send.py` sits at 26.3%, `backend/cdp_client.py`
   at 65.2% and `bridge/history_bridge.py` — the worst-MI file in the project —
   at 66.4%. A global number cannot see a hole; only a per-file floor can.
3. **The suite can be green while a feature is dead.** The last round's P1 proved
   it: `FakeArchive` carried a `labels` attribute `HistoryService` does not have,
   so the tests verified the double and the real app could never label anyone
   (`BOT_CHAT_DEFECTS_2026-09-13.md` P1). The mechanism — a fake that invents an
   interface — is mechanical, and nothing in the repo detects it.

Because this area owns tools and tests rather than production code, it can be
executed at any point relative to Areas A–C, and it is the only area that can
*safely* be done first if the owner wants the later areas' verification to be
stronger while they run.

## 2. Measured state

### 2a. Lowest-covered modules (≥ 30 statements)

| Coverage | Missing | File |
|---:|---:|---|
| **26.3%** | 42 | `backend/message_injector_send.py` |
| 65.2% | 80 | `backend/cdp_client.py` |
| 66.4% | 122 | `bridge/history_bridge.py` |
| 66.7% | 23 | `app/lifecycle.py` |
| 69.3% | 35 | `services/db_deletion_flow_remove.py` |
| 70.1% | 29 | `bridge/layout_bridge.py` |
| 70.7% | 48 | `services/db_registry.py` |
| 70.9% | 34 | `services/db_deletion_scan.py` |
| 73.6% | 14 | `backend/chat_text.py` |
| 73.9% | 30 | `actions/cancellation.py` |

### 2b. Mutation, as configured today

1,141 mutants generated in `backend/history_query.py`: **982 unreachable**
("no tests", excluded by the documented convention), **158 killed**, **1
survivor** — `HistoryQuery._my_nicks` mutant 7 (was 9 survivors on 2026-09-12;
Round G's test-debt step closed 8). Reachable score **158/159 = 99.37%**.

`setup.cfg` also records a measured decision: adding
`tests/test_history_query_edges.py` to the job would take the reachable set from
159 to **910 of 1,141** mutants, and was rejected as a default because the job's
~25 seconds would grow with it.

### 2c. Wide parameter lists (the measured RULE 16 §16.1 tail)

11 functions take more than 4 parameters — down from 51 before Round G:

| Params | Function | Status |
|---:|---|---|
| 20 | `actions/scroll_parse.py:155 __init__` | RULE 3 block settings — documented override |
| 13 | `actions/click_user.py:60 __init__` | RULE 3 |
| 11 | `actions/custom_find.py:53 __init__` | RULE 3 |
| 9 | `actions/attach_image.py:36 __init__` | RULE 3 |
| 9 | `actions/collect_history.py:37 __init__` | RULE 3 |
| 8 | `bridge/router.py:200 __init__` | **not a block** — candidate for an options object (Area B, H-B5) |
| 7 | `actions/click_back.py`, `click_main_tab.py`, `click_send.py` `__init__` | RULE 3 |
| 5 | `actions/type_message.py:22 __init__` | RULE 3 |
| 5 | `backend/chat_sync.py:69 run_sync` | **not a block** — candidate for a request object |

### 2d. Doc and baseline currency

* `docs/current/AGENT_RULES.md` §16.3 still quotes the 2026-09-10 floors
  (**line 90.44%, branch 84.38%**) as the numbers a change must not fall below,
  while the tree measures **92.64 / 88.03**. The floors must be re-quoted from
  this snapshot or the rule under-protects.
* §18.2's measured bullet lists "4 still over 500: `backend/history_query.py`
  (601), `bridge/history_bridge.py` (544 …), `backend/dom_highlight.py` (514),
  `backend/config_manager.py` (507)" — the 507 is stale (511 now), and the list
  will move again as Areas B/C work.
* `docs/README.md`'s "Current vs. historical" table and `docs/archive/README.md`
  both need this round registered (RULE 17) — the mechanism the previous round
  used for `2026-09-13-round-g-write-gate/`.

### 2e. Smell inventory

* `vulture --min-confidence 90`: **7 findings**, unchanged — `actions/registry.py:18`
  (`Iterator`), `backend/cdp_client.py:35` (`exc_type`, `tb`),
  `services/run/coordinator.py:62` (`scroll_parser`), `services/run/hooks.py:68/71/74`
  (`coordinator`).
* `clone_scan.py`: **13 groups / 96 lines**, all frozen in `CLONE_BASELINE`,
  0 new / 0 stale under `rule16_gate.py --with-clones`. Every group is a shared
  import header.
* Boundary crossings (inspection): `bridge/router.py:471`,
  `bridge/undo_bridge.py:178`, `services/db_service.py:160/163`,
  `services/history/query.py:97/132/139` reach for another module's private
  member.

## 3. Steps

### H-D1 — make mutation a platform measurement, not a module measurement

1. Add a second job over a **pure** module family with no Qt in the import path
   (candidates: `stores/label_*` or `services/bot_variables.py` +
   `services/bot_reactions.py` + `services/bot_providers.py` — the newest code,
   which has never been mutation-measured).
2. Widen the `history_query.py` job to include
   `tests/test_history_query_edges.py`, accepting the measured 159 → 910
   reachable-mutant growth, **once Area B's H-B2 has finished touching that
   file** (otherwise the numbers are measured against moving code).
3. Record both scores in a report, with the reachable-set arithmetic stated
   explicitly (the convention `setup.cfg` documents: an unreachable mutant is
   never counted as killed, and a survivor means "no *selected* suite kills it").

**Owner decision D2** covers the runtime cost.

### H-D2 — the RULE 8 double audit (the mechanism that hid a dead feature)

Deliverable: a **test-double inventory** and a parity check for every fake that
stands in for a production class.

* Inventory: grep the suite for classes named `Fake*`/`Stub*`/`Dummy*` and for
  `__getattr__`-based catch-all doubles, and list, per double, the production
  class it imitates and the attributes/methods it provides.
* Parity check: for each double whose production class is importable without
  Qt/CDP, assert the double does not offer an attribute the real class lacks
  (`hasattr(real, name)`), and that every member the *code under test* uses
  exists on the real class. `FakeArchive.labels` would fail this immediately.
* Landing rule for the future: §16.3 already says what "tested" means; this adds
  *"a double may not invent an interface"* as an executable check rather than a
  norm.

### H-D3 — the per-file coverage floor (closes §2a)

The global floor cannot see a hole. Add a **file-floor test**: every production
module with ≥ 30 statements must hold ≥ 80% line coverage, with a ratchet table
for the files below the line today (§2a) that may only rise. Wire it from the
existing `coverage.json` (RULE 16 §16.3's measurement, no new tool). Then work
the list down: each of the ten files in §2a reaches 80%.

Two of those files ( `history_bridge.py`, `cdp_client.py` ) are Area B's H-B1/H-B6
targets — **this step owns the floor and the ratchet; Area B owns its files.**
The other eight are this area's to fix (`message_injector_send.py` first: 26.3%
of the send path of the composer).

### H-D4 — baseline and documentation currency (§2d)

1. Re-quote RULE 16 §16.3's floors from this snapshot (92.64 / 88.03) and state
   the measurement date.
2. Correct RULE 18.2's file list and §18.4's measured bullets to the numbers in
   `reports/CODE_QUALITY_METRICS_2026-09-14.md`.
3. Register this round in `docs/archive/README.md` and `docs/README.md` (RULE 17)
   and add the JS gate to the tool table if D1 is approved.

### H-D5 — the smell ratchet (§2e)

* Each of the 7 vulture findings is either deleted (if a test proves the member
  is unused) or annotated as protocol surface with a reason — no scan-and-ignore.
* The 4 boundary crossings become either public names (with their callers
  updated) or a recorded decision that the private access is intended; the many
  `self.p._x` accesses inside Round-G part classes are already the documented
  part pattern and are excluded by name.
* The wide-parameter tail (§2c): verify the 9 RULE 3 overrides document a real
  constraint, and queue the two non-block functions (`bridge/router.py::__init__`,
  `backend/chat_sync.py::run_sync`) as parameter-object migrations — the first
  belongs to Area B's H-B5, the second to a follow-up in Area B.

## 4. What this area must not do

* **No production-code edits.** Everything here is tools, tests, docs, `setup.cfg`.
  Any production change discovered on the way is handed to Area A/B/C as a note
  in this document.
* **No weakening of an assertion to make a floor pass.** §16.2's anti-gaming
  rules apply to ratchets exactly as they do to complexity.

## 5. Verification battery

```bash
# the floors this area manages
QT_QPA_PLATFORM=offscreen LD_LIBRARY_PATH=/tmp/stublibs .venv/bin/python -m coverage run \
  --branch --source=core,actions,backend,bridge,services,stores,app,main -m pytest tests -q \
  --deselect=tests/test_sash_webengine.py::TestSashWebEngine::test_grid_in_real_webengine
COVERAGE_FILE=/tmp/.coverage_h .venv/bin/python -m coverage json -o /tmp/coverage_h.json

# mutation (both jobs once H-D1 lands)
QT_QPA_PLATFORM=offscreen LD_LIBRARY_PATH=/tmp/stublibs .venv/bin/mutmut run
QT_QPA_PLATFORM=offscreen LD_LIBRARY_PATH=/tmp/stublibs .venv/bin/mutmut results
rm -rf mutants/                      # not gitignored; must not reach a commit

# smells + gates
.venv/bin/vulture --min-confidence 90 core actions backend bridge services stores app
.venv/bin/python tools/metrics/rule16_gate.py --with-clones
.venv/bin/python tools/metrics/clone_scan.py .
```

## 6. Cross-area notes

* The file-floor ratchet (H-D3) must be written so that Areas B and C can lower
  their own files' rows in their own commits, the same protocol
  `rule16_gate.py`'s `RATCHET` table uses.
* H-D1's widening of the `history_query.py` job is sequenced **after** B's H-B2.
* This area owns `tests/**` existing files; new test files written by Areas A/B/C
  stay with those areas (so a merge conflict is only possible inside test files
  deliberately shared by two areas — none are).
