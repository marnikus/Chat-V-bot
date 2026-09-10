# RULE 16 conformance of the sortable-columns feature

Date: 2026-09-10
Status: measurement first, then redesign of what fails
Scope: the production **Python** added/changed by
`docs/SORTABLE_DATABASE_COLUMNS_DESIGN_2026-09-10.md`

> `docs/AGENT_RULES_CODE_QUALITY.md` does not exist in this repository and
> "RULE 16" appears nowhere in it (`grep -rn "RULE 16"` → no hits;
> `docs/AGENT_RULES.md` ends at RULE 15). The thresholds below are therefore
> treated as **newly proposed**, and this document is the first record of them
> being applied. They are measured, not asserted.

---

## 1. Measurement

Tools: `radon` (CC), `cognitive_complexity` (cognitive), an AST walk for
physical LOC / params / nesting (`elif` counted as a nested `if`),
`pytest --cov --branch`, `pylint --enable=R0801`, `vulture`.

Every figure below was produced by running those tools, and the *baseline*
column is the same measurement at commit `3820136` — so "mine" and
"already broken" are separated rather than blurred.

| Subject | Limit | Baseline `3820136` | After the feature | Verdict |
|---|---|---|---|---|
| `_sort_spec` | — | *(did not exist)* | 3 LOC · 1 prm · CC 2 · cog 1 · nest 0 | ✅ new, fits |
| `_resolved_dir` | — | *(did not exist)* | 12 LOC · 2 prm · CC 3 · cog 2 · nest 1 | ✅ new, fits |
| `_order_by` | — | *(did not exist)* | 25 LOC · 2 prm · CC 7 · cog 10 · nest 2 | ✅ new, fits |
| `HistoryQuery.list_persons` | 30 / 4 / 10 | **47 LOC · 5 prm · CC 15** | **46 LOC · 6 prm · CC 14** | ❌ fails — and already failed |
| `HistoryBridge.userdb_page` | 30 / 4 / 10 | 21 LOC · 2 prm · CC 2 | 24 LOC · 2 prm · CC 2 | ✅ fits |
| `class HistoryQuery` | 300 LOC / 15 methods | **362 LOC** · 14 methods | **361 LOC** · 14 methods | ❌ pre-existing |
| `class HistoryBridge` | 300 LOC / 15 methods | **490 LOC · 45 methods** | **493 LOC · 45 methods** | ❌ pre-existing |
| line coverage, new lines | ≥ 80% | — | **96.6%** (28/29) | ✅ |
| branch coverage, new lines | ≥ 75% | — | **91.7%** (11/12) | ✅ |
| new duplicated blocks | 0 | 2 pre-existing pairs | **0 new** | ✅ |
| unused imports (both files) | 0 | — | 0 · pylint 10.00/10 | ✅ |
| dead code (vulture ≥80%) | 0 | — | 0 reported, **but see §1.2** | ⚠ |

### 1.1 What the feature actually broke

Exactly one thing: `list_persons` went from **5 parameters to 6** when `dir`
was added. Its LOC and CC got *better* (47→46, 15→14) because the inline
ORDER BY dict moved out into `_order_by`, but it was already over all three
limits before this feature existed. So the honest statement is:

> the feature did not introduce the violation, it inherited it and made one
> axis (param count) worse.

Under "rules apply to code you change", that is a fail and gets fixed (§3).

### 1.2 The one genuinely new defect

`_order_by` contained

```python
for column, natural in _sort_spec(sort):
    if column in used:      # ← line 94
        continue
```

No spec in `SORT_COLUMNS` repeats a column, so that `continue` **can never
execute**. It is the single uncovered new line and the single uncovered new
branch — defensive code that is unreachable by construction. It is removed in
§3.3 rather than covered by a contrived test.

(The `used` set itself is *not* dead: the tiebreaker loop must skip `nick_lc`
when the key is `nick`, and that branch is covered.)

### 1.3 What is deliberately NOT refactored here

`HistoryQuery` (361 LOC) and `HistoryBridge` (493 LOC / 45 methods) both exceed
the class limits, and both did so before this feature. They are not split in
this change, for two concrete repo-specific reasons:

1. **`HistoryQuery`'s surface is frozen.** `tests/unit/backend/test_backend_api_snapshot.py`
   fails on any *removed* method unless it moved into a shared base. Decomposing
   the class to satisfy a size rule would trip the repo's own frozen-contract
   gate.
2. **`HistoryBridge`'s 45 slots are a wire contract.** It is one QWebChannel
   object; `tests/test_bridge_router.js` pins the object name and the method
   set the UI calls. Splitting it changes what JavaScript sees.

This feature *shrinks* `HistoryQuery` (362 → 340 LOC, measured) as a side
effect. Getting
either class under 300 is a separate refactor with its own design doc.

---

## 2. The redesign

`list_persons` fails on **three** axes at once, and they share one cause: six
independent options travel together everywhere — the UI sends them as one JSON
blob, the bridge unpacks them into six locals, the query consumes six
parameters. Collapsing them into one request object fixes the parameter count
directly and gives the ORDER BY / WHERE builders a home, which fixes LOC and
CC as a consequence.

### 2.1 `PersonPageRequest` — the request object

```python
@dataclass(frozen=True)
class PersonPageRequest:
    q: str = ""
    limit: int = DEFAULT_LIMIT
    offset: int = 0
    sort: str = DEFAULT_SORT
    dir: str = ""
    include_deleted: bool = False
```

Frozen, because a request must not be mutated on the way to the database, and
because `frozen=True` gives `__eq__` for free, which the tests use.

It owns the three SQL-fragment builders, all of which were previously either
module functions or inline code in `list_persons`:

| method | returns | replaces |
|---|---|---|
| `needle()` | the lower-cased, stripped search text | inline `(q or "").strip().lower()` |
| `where()` | `(clause, params)` | the inline `where` / `params` pair |
| `order()` | `(body, params)` | `_order_by` **+** the inline prefix-boost branch |
| `resolved_dir()` | `"asc"` / `"desc"` | `_resolved_dir` |
| `spec()` | the whitelisted column tuple | `_sort_spec` |
| `columns()` | the ORDER BY column list | the body of `_order_by` |

Six methods, ~60 LOC — inside both class limits.

**Why the WHERE/ORDER split matters beyond the rule.** Today the COUNT query
uses `params[:1] if needle else []` — positional surgery on a parameter list to
drop the ORDER BY placeholder. Splitting `where()` from `order()` removes that
entirely: COUNT binds `where_params`, SELECT binds
`where_params + order_params + [limit, offset]`. Same behaviour, no index
arithmetic.

### 2.2 `list_persons` after the change

```python
async def list_persons(self, req: PersonPageRequest) -> dict:
```

One parameter. The body becomes: clamp, unpack two fragment pairs, COUNT,
SELECT, map rows through `_person_item`, return the envelope. Measured at
**25 LOC, CC 3** (was 46 / 14).

`_person_item(row, my_nicks)` is a **module-level function, not a method**.
That is deliberate: adding it as a method would have taken `HistoryQuery` from
14 methods to 15, and the ratchet in `tests/test_rule16_new_code.py` caught
exactly that before it shipped. The mapping is a pure projection of one row, so
it does not belong to the query class anyway.

### 2.3 The bridge

`HistoryBridge.userdb_page` builds the request from the JSON blob via a new
module-level `_person_request(opts)`. Building the request *outside* the
closure made the closure shorter, not longer: `work()` measured **13 LOC**
(the whole `userdb_page` is 17), where the pre-refactor closure was 24.

### 2.4 Behaviour is unchanged

This is a **pure refactor**. Every existing assertion must hold verbatim:

* `sort` / `dir` semantics, natural directions, the whitelist fallback;
* the `nick_lc ASC, id ASC` tiebreaker and therefore paging stability;
* the search prefix-boost ranking;
* tombstone hiding; the response envelope keys.

The 23 query tests, 6 bridge tests and the pre-existing
`test_history_query.py` / `test_history_query_edges.py` /
`test_archive_delete_undo.py` assertions are the safety net; they are not
weakened, only re-aimed at the new signature.

---

## 3. Changes

### 3.1 Signature

`list_persons(self, q, limit, offset, sort, dir, include_deleted)`
→ `list_persons(self, req: PersonPageRequest)`.

This is the second change to this signature, so the AREA D golden file is
updated again and the diff reviewed to contain only that line plus the new
class. All 30 call sites in the repo (1 in `bridge/`, 29 in `tests/`) use
keyword arguments only, so the rewrite is mechanical and the suite proves it.

### 3.2 Module functions become methods

`_sort_spec`, `_resolved_dir`, `_order_by` were module-private and are now
methods of `PersonPageRequest`. They were private, so nothing outside
`history_query.py` could import them; `SORT_COLUMNS`, `DEFAULT_SORT` and
`SORT_TIEBREAK` stay module-level constants (new public constants are allowed
by the snapshot test) because tests and future callers read the whitelist.

### 3.3 Dead branch removed

`columns()` is a comprehension over the spec plus a filtered tiebreaker, so
there is no `if column in used: continue` to be unreachable. New-code line and
branch coverage both reach 100%.

---

## 4. Test plan (written before the refactor)

1. **`tests/test_rule16_new_code.py` (new).** The thresholds become executable,
   so this cannot silently rot:
   * every function this feature owns is ≤30 LOC, ≤4 params, CC ≤10,
     cognitive ≤15, nesting ≤4 — hard fail;
   * `PersonPageRequest` itself is ≤300 LOC / ≤15 methods;
   * a **ratchet** on the two pre-existing oversized classes: their LOC and
     method count must not exceed the recorded baseline, so debt cannot grow
     quietly while the rule is "known failing";
   * `vulture` finds no dead code in the two production files;
   * `pylint R0801` reports no duplication pair involving them.
2. **`tests/test_person_page_request.py` (new).** Unit tests for the request
   object in isolation: each key's natural direction, `dir` override, unknown
   key/`dir` fallback, the tiebreaker and its `nick` dedup, the WHERE clause
   with and without a needle, the prefix-boost parameter order, and that a
   frozen instance rejects mutation.
3. **Existing suites re-aimed, not weakened** — the 23 + 6 sort tests and the
   three pre-existing query/archive suites keep every assertion they had.
4. Full `pytest` and all `tests/*.js` must stay green.

## 5. Verification matrix

| Claim | Proven by |
|---|---|
| every new/changed function fits all six size+complexity limits | `test_rule16_new_code.py` |
| pre-existing class debt does not grow | the ratchet in the same file |
| no new duplication, no dead code | `pylint R0801` + `vulture` assertions |
| new-code line/branch coverage is 100% | `pytest --cov --branch` (command in §6) |
| behaviour is unchanged by the refactor | the 5 pre-existing + 2 new Python suites, all assertions intact |

## 6. The commands these numbers come from

```bash
# size / complexity
radon cc -a -nc backend/history_query.py bridge/history_bridge.py
# coverage of the new lines specifically
pytest --cov=backend.history_query --cov=bridge.history_bridge --cov-branch \
       --cov-report=json tests/test_userdb_sort_query.py tests/test_userdb_sort_bridge.py \
       tests/test_history_query.py tests/test_history_query_edges.py \
       tests/test_history_bridge.py tests/test_archive_delete_undo.py tests/test_person_page_request.py
# smells
pylint --disable=all --enable=R0801 backend/ bridge/
vulture backend/history_query.py bridge/history_bridge.py --min-confidence 80
# the thresholds, as the project's own test
pytest tests/test_rule16_new_code.py
```

---

## 7. Result — measured after the refactor

Everything below was produced by re-running the same tools, not estimated.

### 7.1 Functions this feature owns (all six limits)

| Function | LOC /30 | prm /4 | CC /10 | cog /15 | nest /4 |
|---|---|---|---|---|---|
| `PersonPageRequest.needle` | 3 | 0 | 2 | 1 | 0 |
| `PersonPageRequest.spec` | 4 | 0 | 2 | 1 | 0 |
| `PersonPageRequest.resolved_dir` | 12 | 0 | 2 | 1 | 1 |
| `PersonPageRequest.where` | 8 | 0 | 3 | 2 | 1 |
| `PersonPageRequest.order` | 19 | 0 | 2 | 1 | 1 |
| `PersonPageRequest._asked_dir` | 4 | 0 | 3 | 2 | 0 |
| `PersonPageRequest.columns` | 15 | 0 | 6 | 1 | 0 |
| `_person_item` | 19 | 2 | 7 | 6 | 0 |
| `HistoryQuery.list_persons` | **25** | **1** | **3** | 1 | 0 |
| `_person_request` (bridge) | 16 | 1 | 6 | 5 | 0 |
| `HistoryBridge.userdb_page` | 17 | 2 | 2 | 5 | — |

`list_persons` was **46 LOC / 6 params / CC 14** before this refactor and
**47 / 5 / 15** before the feature existed. All three failing axes are now
inside limits.

`PersonPageRequest` itself: **97 LOC / 7 methods** — inside both class limits.

### 7.2 The two class limits that are still red

| Class | Baseline | Now | Still failing |
|---|---|---|---|
| `HistoryQuery` | 362 LOC / 14 methods | **340 LOC** / 14 methods | LOC > 300 |
| `HistoryBridge` | 490 LOC / 45 methods | **486 LOC** / 45 methods | LOC > 300, methods > 15 |

Both shrank. Neither is fixed, for the contract reasons in §1.3. The ratchet in
`tests/test_rule16_new_code.py` pins these numbers so they cannot creep back up.

The ratchet earned its place during this work: the first cut of the refactor
extracted `_person_item` as a *method*, which took `HistoryQuery` to 15
methods. The ratchet failed the suite, and `_person_item` became a module
function instead.

### 7.3 Coverage, dupes, dead code

| Check | Limit | Result |
|---|---|---|
| line coverage, lines added vs `3820136` | ≥ 80% | **100%** (51/51 in `history_query.py`, 5/5 in `history_bridge.py`) |
| branch coverage, same lines | ≥ 75% | **100%** (6/6) |
| new duplicated blocks (pylint R0801) | 0 | **0** — the only two pairs in `backend/` + `bridge/` are pre-existing and involve neither file |
| dead code (vulture ≥ 80%) | 0 | **0** |
| unused imports (pylint W0611/W0612) | 0 | **0**, both files 10.00/10 |

The unreachable `continue` from §1.2 is gone, which is what moved branch
coverage from 91.7% to 100%.

### 7.4 Suites

```
tests/test_person_page_request.py       20 passed
tests/test_rule16_new_code.py            9 passed
tests/test_userdb_sort_query.py + test_userdb_sort_bridge.py
  + test_history_query.py + test_history_query_edges.py
  + test_history_bridge.py + test_archive_delete_undo.py
  + the two above                      146 passed
tests/unit/backend/test_backend_api_snapshot.py
                                         9 passed   (one golden line updated:
                                         list_persons → (self, req))
full pytest (--deselect test_sash_webengine.py)
                                     2187 passed, 3 skipped, 1 xfailed,
                                     771 subtests   (was 2158 before the gate)
tests/*.js                              22/24 pass — both failures
                                        (js_harness.js, test_bridge_router.js)
                                        reproduce at 3820136
```

Every assertion in the 29 pre-existing query/archive tests survived the
signature change unchanged; only the call syntax moved.
