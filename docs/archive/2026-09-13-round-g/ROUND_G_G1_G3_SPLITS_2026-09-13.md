# Round G steps G1–G3 — the three splits G0 unblocked

**Date:** 2026-09-13 · **Base:** `37d43b4` · **Status:** G0, G1, G2, G3 complete
**Decision that unblocked them:** [`AREA_D_DECISION_2026-09-13.md`](AREA_D_DECISION_2026-09-13.md)
**Plan:** [`ROUND_G_PLAN_2026-09-13.md`](ROUND_G_PLAN_2026-09-13.md)
**Audit:** `reports/CODE_QUALITY_METRICS_2026-09-13.md`

## 1. What changed, in numbers

| Metric | Before (`37d43b4`) | After | |
|---|---:|---:|---|
| Files over 500 lines | 7 | **4** | −3 |
| Worst file MI | **11.4** | **24.9** | +13.5 |
| Mean MI | 66.36 | **68.08** | +1.72 |
| Files below MI 40 | 19 | **16** | −3 |
| Production files | 171 | **190** | +19 |
| Classes over 300 LOC | 9 | **8** | −1 |
| Largest class | 532 LOC / 39 methods | **406 / 25** | the god class is gone |
| Tests passed | 2,800 | **2,810** | +10 |
| Line coverage | 90.87% | **90.93%** | +0.06 pp |
| Branch coverage | 86.94% | **86.97%** | +0.03 pp |
| CC > 10 / nesting > 4 | 0 / 0 | **0 / 0** | held |

Per split:

| Step | File | Was | Worst successor MI | Modules |
|---|---|---|---:|---:|
| G1 | `backend/chat_sync.py` | 807 lines, **MI 11.4** | **40.6** | 7 |
| G2 | `backend/scroll_parser.py` | 706 lines, MI 28.6, class 532/39 | **56.7** | 7 |
| G3 | `backend/history_query.py` | 603 lines, MI 35.4 | **43.1** | 5 |

## 2. The design rule each split followed

Every package has the same shape, and the shape is the point:

* **one `__init__.py` that re-exports the previous public surface verbatim** —
  `owns()` makes a submodule symbol count as owned, it does **not** make an
  un-exported one appear;
* **a module-ownership table in the package docstring**, saying what each file
  owns and which way imports go;
* **imports point one way only**, so no module imports the front door and there
  is no cycle;
* collaborators reach the owning object through the **host protocol**
  (`host.options`, `host._say()`, …) that `services/collector_*` already uses.

`test_backend_api_snapshot.py` passes **unrefreshed** after all three. That is
the proof the splits lost nothing — the golden file was never updated to agree
with the new code.

## 3. G3 and the cohesion rule — why one class was *not* split

G1 and G2 split classes. G3 deliberately did not, and the reason generalises.

`HistoryQuery` is 14 methods at **LCOM 0.74** that all read `self.db` and share
the `_SELECT` / `_COUNT_ALIVE` fragments. That is real cohesion. Splitting it by
line count would have raised coupling to lower a number — precisely what the
audit warned about when it ranked `SchemaMigrator` (406 LOC, **LCOM 0.12**) as
*not* a target despite being the third-largest class in the tree.

So the **module** split and the class did not: everything that never touched the
database moved out (constants, SQL text escaping, the request object, row
shaping), and `query.py` shrank 362 → 313 LOC by losing only what did not belong
to it. Each extracted module is now testable without a database.

**Rule for the next round:** when size and LCOM disagree, LCOM wins.

## 4. What the verification caught that reading would not have

Five findings, all from running the gates rather than from inspection. They are
recorded because each is a trap the next split will hit.

**4.1 `from __future__ import annotations` changes the public API.** It
stringifies every annotation, so adding it (G2) or dropping it (G3) makes the
snapshot report every signature in the module as changed. The fix is to match
what the original module did — *not* to refresh the golden file. G2 removed it
from seven modules; G3 re-added it to six.

**4.2 A package split renames classes inside annotations.**
`backend.scroll_parser.ScrollParser` began rendering as
`backend.scroll_parser.parser.ScrollParser` — same class, same import path for
every caller, only the defining file moved. `_collapse_submodules()` in the
dumper now normalises the segments *between* an area package and the final
symbol. A move to a **different area** still reports as drift; verified on six
cases including two negatives (`backend.chat_syncster` is not
`backend.chat_sync.*`).

**4.3 Monkeypatching a module patches nothing once it is a package.**
`test_pause_happens_before_the_person_is_added` patched
`backend.scroll_parser.asyncio`. After the split the hold lives in `judge.py`
with its own `asyncio` reference, so the patch would have silently stopped
taking effect — the test would still pass while testing nothing. Repointed at
the owning module; the assertion is untouched.

**4.4 The gate's own paths rot silently.** `rule16_gate.py` held the deleted
path in `OWNED`, `RATCHET` and `SMELL_FILES` (crash), and its duplication filter
matched the literal `"history_query.py"` — which after the split matches nothing
and would have **quietly stopped reporting duplication** in a file the gate is
scoped to. Both fixed; `HistoryQuery` re-frozen **down** at 313/14 (was 362/14),
because a ratchet you relax is not a ratchet.

**4.5 A grep-based invariant can move without anything depending on more.**
`test_stores_public_api.py` counts *lines* mentioning `stores`. Splitting one
importer into four files raised it 40 → 42 while the imported *surface* stayed
the same three symbols (`MAX_LIMIT` aside: `MAX_LIVE_ITEMS`, `SyncResult`,
`align_batch`) — verified before and after. Bumped with the limitation recorded
in place rather than dodged.

## 5. What is left, and what changed about it

The four files still over 500 lines:

| Lines | MI | File | Status |
|---:|---:|---|---|
| 544 | **24.9** | `bridge/history_bridge.py` | 23 QWebChannel slots — the one genuine wire constraint left |
| 534 | 55.9 | `backend/dom_highlight.py` | **unblocked**; largely a JS-literal builder (§16.1.5) |
| 509 | 41.0 | `backend/config_manager.py` | **unblocked** |
| 509 | 31.5 | `services/db_deletion_flow.py` | never frozen; inside the F1 family |

The important change is categorical: three of the four are now *unblocked debt*
rather than *structural exemptions*. Only `history_bridge.py` still has a
contract that genuinely pins it, and even that pins the **slot set**, not the
file — the non-slot helpers could move.

Remaining Round G steps, unchanged in priority from the plan: **G4** wide
parameters (51 → ≤ 35), **G5** widen mutation scope beyond one file, **G6** the
CC-10 frontier and the two cognitive-17 functions, **G7** the two real clone
groups, **G8** density pass on the five small low-MI files.

Two plan corrections worth carrying forward:

* **G2 as planned was wrong.** The plan named `services/collector_service.py`
  `Collector` (40 methods, LCOM 0.97) as the worst god class. Re-measured before
  touching it: 32 of its 40 methods are one-line delegators to six real
  collaborators that already exist — it is a **facade**, and its LCOM is an
  artefact of that. The real god class was `ScrollParser` (532 LOC, 39 methods,
  LCOM 0.88), which G0 had just unfrozen. G2 was retargeted.
* **LCOM on a facade means nothing.** Any future ranking by LCOM must first ask
  whether the methods have bodies.

## 6. RULE 18 / RULE 16 recheck

| Check | Result |
|---|---|
| RULE 16.2 CC ≤ 10 | ✅ 0 above, over 2,090 functions |
| RULE 16.2 nesting ≤ 4 | ✅ 0 above |
| RULE 16.2 cognitive ≤ 15 | ⚠️ 2 (unchanged, `_build_router_class`, `settings_store.get` — step G6) |
| RULE 16.1 new functions ≤ 30 LOC / ≤ 4 params | ✅ no new violations; every moved function kept its shape |
| RULE 16.1 new classes ≤ 150 LOC / ≤ 15 methods | ✅ no new class added |
| RULE 16.3 coverage ≥ 80% line / 75% branch, never down | ✅ 90.93% / 86.97%, both up |
| RULE 16.4 smells | ✅ 0 new clone groups, vulture unchanged at 7 known findings |
| RULE 16 gate + ratchet | ✅ green, ratchet moved **down** |
| RULE 18.1 functions 4–20 | 61.7% in band (was 61.9%) — unchanged by relocation |
| RULE 18.2 files 150–300 | ✅ 19 new modules all in band; median 126, over-500 count 7 → 4 |
| RULE 18.3 modules 5–15 files | ✅ three new packages at 5–7 files each |
| RULE 18.4 context files | ⚠️ `AGENT_RULES.md` 778 vs ~730 budget — **recorded in §18.4**, with the next extraction named |

The one deliberate overrun is `AGENT_RULES.md`: §18.2's frozen-`backend/`
paragraph became false the moment G0 landed and had to be rewritten. §18.3 was
compressed to pay part of the cost, and §18.4 now states the measured number and
names the next candidate for extraction, per the rule's own "extract first, then
add" requirement.
