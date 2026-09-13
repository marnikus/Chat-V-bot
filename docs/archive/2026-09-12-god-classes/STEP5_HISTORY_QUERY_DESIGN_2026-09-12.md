# Step 5 — split `backend/history_query.py` into `backend/history_query/`

Done 2026-09-12. Target: the round plan's step 5 — `backend/history_query.py`
(**606 LOC**, MI 33.5). The plan's success metric: *file 606 → ≤300*.

## Why it is one step

The file is the read path of the message archive and grew as one family: the
sort whitelist, the FTS/LIKE text helpers, the person-row projection, the
`PersonPageRequest` value object, and the 14-method `HistoryQuery` class
(paging / search / the Full User Database window / stats). It was never touched
by the complexity rounds (its CC is green), so this is pure size debt — and a
§16.5 landmine, pinned by `test_person_item.py`, `test_person_page_request.py`,
`test_history_query*.py`, `test_userdb_sort_query.py` and the public-API
snapshot.

## The seam to preserve (the one risk)

Three importers plus the tests read this module by name:

* `bridge/history_bridge.py` — `DEFAULT_LIMIT, DEFAULT_SORT, PersonPageRequest`;
* `services/collector_service.py` (now `services/collector/push.py`) and
  `services/history/__init__.py` — `HistoryQuery`;
* tests also import the *private* helpers `_person_item`, `_fts_query`,
  `_like_escape` and the constants `MAX_LIMIT`, `SORT_COLUMNS`, `SORT_TIEBREAK`,
  `DEFAULT_SORT` from `backend.history_query`, and call
  `HistoryQuery._clamp(...)` / `_person_row` / `_item` / `_my_nicks` on the
  class.

So `backend/history_query/__init__.py` re-exports the full frozen surface —
including the three private helpers the tests reach for. The golden snapshot
(`dump_public_api.py --write`) is regenerated (the `backend.history_query`
module key becomes `backend.history_query.*` leaves), exactly as steps 1 and 3
did.

The stores-import invariant (count 42) is preserved: the single
`from stores.history_db import HistoryDB` (the `db` type hint) relocates to the
facade leaf unchanged.

## The split

| Module | Owns | LOC |
|---|---:|---:|
| `constants.py` | `DEFAULT_LIMIT`, `MAX_LIMIT`, `SNIPPET_RADIUS`, `SORT_COLUMNS`, `DEFAULT_SORT`, `SORT_TIEBREAK` | ~65 |
| `search_text.py` | `_like_escape`, `_fts_query`, `_snippet` (pure text helpers) | ~45 |
| `person.py` | `_person_item`, `_FIELD_SPECS`, `_FIELD_SPECS_TAIL`, `_apply_specs`, `_stat_int`, `_day_bounds`, `_item_media` | ~110 |
| `request.py` | `PersonPageRequest` (the frozen sort request) | ~100 |
| `paging.py` | `PagingMixin`: `_clamp`, `_person_row`, `_item`, `page`, `around`, `gaps` | ~150 |
| `search.py` | `SearchMixin`: `search_person`, `search_global`, `_search` | ~95 |
| `userdb.py` | `UserDbMixin`: `_my_nicks`, `list_persons`, `db_stats`, `person_stats` | ~130 |
| `query.py` | `HistoryQuery(PagingMixin, SearchMixin, UserDbMixin)`: `__init__`, `_SELECT`, `_COUNT_ALIVE` | ~30 |
| `__init__.py` | frozen seam re-exports | ~20 |

Import order is a DAG, leaves first: `constants → (search_text, person,
request)` → the three mixins → `query` → `__init__`. The mixins share `self.db`
and resolve each other's helpers through the MRO, so `HistoryQuery._clamp`,
`_person_row`, `_item`, `_my_nicks`, `_search` stay callable exactly as before.

## Rejected dishonest reductions

* **Leaving `HistoryQuery` as one 312-LOC class in a slimmed file** was
  rejected: the plan's metric is *file ≤300*, and a single `query.py` holding
  the whole class would still exceed it. Splitting the class into three
  mixins (paging / search / userdb) is the honest way to meet the number.
* **Merging the three text/person/request leaves into one `helpers.py`** was
  rejected: they are four unrelated vocabularies; one `helpers.py` would
  recreate the mixed-responsibility file being removed.
* **Collapsing the mixins into the facade** was rejected: the mixins are
  three distinct read surfaces (paging / search / userdb), and one class would
  exceed the file budget again.

## Pre-existing duplicates removed (behaviour-preserving)

The extraction surfaced two pre-existing merge artifacts, both removed because
they are behaviour-neutral dead code and the round's whole point is shrinking
size debt:

* `_day_bounds` was defined **twice**, identically — the second definition
  shadowed the first, so one copy is dead. One definition kept.
* `person_stats` returned the key `"hidden"` **twice** with the same idempotent
  COUNT query — the dict literal ran the query twice and kept the last value.
  One key kept (one redundant COUNT round-trip removed; the result is
  identical).

## Gates

* `radon cc -s backend/history_query/` — worst ≤ 9 (A).
* `tools/metrics/rule16_gate.py` clean (and `--with-clones`).
* `test_person_item`, `test_person_page_request`, `test_history_query`,
  `test_history_query_edges`, `test_userdb_sort_query`,
  `test_history_repo_lifecycle`, `test_archive_delete_undo`,
  `test_world_write_gate`, `test_backend_api_snapshot` (snapshot regenerated),
  `test_stores_public_api` (count 42) — green.
