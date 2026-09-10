# 🧪 Backend (Section C) Test Design — Bug-Finding Pass

> **Version:** 2026-09-09
> **Scope:** Section C of `docs/archive/2026-09-09-test-suite/TEST_COVERAGE_REF_DESIGN_2026-09-09.md` — `backend/` engine & parser layer (22 modules, incl. their real homes in `services/` and `stores/` behind the compatibility shims).
> **Method:** Design-first. This document was written from module docstrings, public signatures and the existing test inventory — **before** reading implementation bodies. Tests are black-box contract probes: each one targets a failure mode that would be a *real bug in production*, not a mirror of the code.

---

## 1. Rules of this pass

1. **No copy tests.** A test that re-states what an existing test already proves is dead weight. Every new test fills a gap from the matrix in §3.
2. **Bug-finding assertions.** Each test asserts an *observable contract* (what the UI/log/archive must show), so a violation = a shipped bug. Input classes chosen from real failure sources: hostile strings, corrupt files, empty sets, boundaries, concurrency, Unicode.
3. **Contracts, not implementation.** Expected values come from docstrings/README/design docs. If a test fails, the first question is *“which contract is right — the test's or the code's?”* before any fix.
4. **Repo conventions.** `unittest` style, `sys.path` bootstrap, runnable standalone (`python3 tests/<file>.py`) and under pytest; real SQLite temp files, fake CDP/page objects like the existing suites.
5. **Bug protocol.** A red test ends as: (a) **BUG** — code violates the written contract → file in §6 with repro; (b) **SPEC** — the contract was wrong/underspecified → fix the test and record the decided contract here.

---

## 2. Module → real implementation map

The `backend/*.py` names are compatibility shims; the logic under test lives at:

| Table name | Real home |
|---|---|
| `backend/action_engine.py` | `services/run_service.py` + `actions/base_action.py` + `actions/registry.py` |
| `backend/db_manager.py` | `services/db_service.py` |
| `backend/history_service.py` | `services/history_service.py` |
| `backend/history_repo.py` | `stores/history_repo.py` |
| `backend/history_db.py` | `stores/history_db.py` |
| `backend/history_models.py` | `stores/history_models.py` |
| `backend/media_store.py` | `stores/media_store.py` |
| `backend/preset_store.py` | `stores/preset_store.py` |
| `backend/label_store.py` | `stores/label_store.py` |
| `backend/user_memory.py` | `stores/user_memory.py` |
| the rest | implemented in `backend/*.py` directly |

---

## 3. Gap matrix and new test files

Legend: ✅ covered by an existing suite · 🟡 partially covered · ⬛ gap (new file below).

### P0

| Module | Existing | Design target | Still missing → new file |
|---|---|---|---|
| `chat_parser` | `test_chat_parser_delta.py` (33) | delta, entity, corrupt, **concurrent** | ⬛ concurrent/re-entrant syncs, cross-person isolation, more corrupt payload shapes → `tests/test_chat_parser_concurrent.py` |
| `action_engine` | `test_engine_standalone_run.py` (8), `integration/services/test_run_service_paths.py` | **sequence, rollback, failure stop** | ⬛ stack-order execution, first failure halts a user's remaining blocks, Stop/Pause honoured between blocks, `normalize_blocks` hostile payloads, RunTracer JSONL, repeat cycles → `tests/test_action_engine_sequence.py` |
| `db_manager` | `test_db_manager.py` (42) | open/close, migrate, **corrupt, concurrent** | ⬛ corrupt file on load/create/info, name/path escape via `safe_db_name`/`resolve`, concurrent create of same world, WAL-aware sizes → `tests/test_db_manager_corrupt.py` |
| `config_manager` | `unit/backend/test_config_manager.py` (4), `test_stores_split.py` (18) | **load, merge, missing, invalid** | ⬛ missing single store file, corrupt per-store JSON, deep-path get/set merge, named_* CRUD round-trip, `set()` arity abuse, save-reload identity → `tests/unit/backend/test_config_manager_contract.py` |
| `history_service` | none direct (indirect via db/undo suites) | **aggregate, filter, export**, lifecycle | ⬛ init/close lifecycle, settings deep-merge + persistence, per-world isolation on `switch_db` (two worlds never leak), meta flags, gaze save/restore, seed vs load app settings → `tests/test_history_service_lifecycle.py` |

### P1

| Module | Existing | Design target | Still missing → new file |
|---|---|---|---|
| `criteria_engine` | `unit/backend/test_criteria_engine.py` (9) | **all operators, compound, empty** | ⬛ compound AND across classes, all-disabled = match-all, empty user list, DB save/load round-trip, wrong-shape JSON (list/null), unknown class keys → `tests/unit/backend/test_criteria_engine_contract.py` |
| `scroll_parser` | `test_scroll_parse_pipeline.py` (31), `test_scroll_only_seek.py` | block detect, **boundary** | ⬛ exact geometry boundary (at-bottom epsilon), single-screen non-scrollable list, stall-threshold stop before max_scrolls, boundary duplicates across page flips → `tests/test_scroll_parser_boundary.py` |
| `dom_highlight` | `test_find_click_visual.py` (22) | highlight, **remove, selector** | ⬛ JS-literal injection safety of captions/selectors, clear-probe removes every overlay idempotently, interpreters survive malformed results → `tests/unit/backend/test_dom_highlight_contract.py` |
| `dom_probe` | none direct | **probe, element, nil** | ⬛ build_probe escaping (quotes, U+2028/2029, backslash), max_candidates cap, match_mode comparator, `interpret*` on `None`/`"null"`/garbage → `tests/unit/backend/test_dom_probe_contract.py` |
| `visual_click` | via `test_find_click_visual.py` | confirmation **pass/fail** | ⬛ runner-level: click disabled = find-only ok, found-but-unclcatable = fail with reason, find-fail skips phase 2, exact wrapper, `_parse` tolerance → `tests/test_visual_click_contract.py` |
| `history_query` | `test_history_query.py` (28) | **complex query, pagination, empty** | ⬛ FTS user input that is invalid MATCH syntax must never raise, LIKE wildcards escaped, page() out-of-range cursors + limit clamp, list_persons sort/include_deleted/offset, stats on empty DB → `tests/test_history_query_edges.py` |
| `history_repo` | `test_history_repo.py` (29), `test_archive_delete_undo.py` | CRUD, **version** | ⬛ token semantics of soft-delete → restore → purge (exact reversal, double-restore no-op), merge_persons folding + resequencing, rename-when-nick-changed refusal path, `resolve_days` midnight rollover → `tests/test_history_repo_lifecycle.py` |
| `media_handler` | `test_attach_image.py`, `test_media_recovery*` | recovery, **missing, path** | ⬛ `parse_patterns` normalisation edge cases, `list_image_files` path/case/subdir contract, missing folder → clean failure → `tests/test_media_handler_paths.py` |
| `media_store` | `test_media_store.py` (21) | path, duplicate, limit | ⬛ `slugify_nick` traversal/Cyrillic/emoji, `folder_for` stability, `_free_name` sequence within one day, missing-day records → `tests/test_media_store_paths.py` |
| `message_injector` | `test_message_block_composer.py`, `test_search_users.py` | inject, **format, failure** | ⬛ `_same_text` tolerance matrix (CRLF, 1 trailing newline, 2 ≠ 1), `_js` hostile-text embedding, multiline message must land intact → `tests/test_message_injector_text.py` |

### P2

| Module | Existing | Design target | Still missing → new file |
|---|---|---|---|
| `history_db` | `test_db_schema_migration.py` (9) | schema | ⬛ meta get/set/overwrite, fetch shapes, `file_size` includes WAL, fresh file with `use_fts=False`, two concurrent connections → `tests/test_history_db_unit.py` |
| `history_models` | indirect only | **model validation** | ⬛ fingerprint stability + UTF-16 astral-plane (emoji) sensitivity, `dedupe_key` ignores occ, `MessageRecord.from_dict` on agent garbage, round-trip losslessness, result-object `to_dict` JSON-safe → `tests/unit/backend/test_history_models.py` |
| `person_filter` | only inside scroll suites | include, exclude, **empty** | ⬛ `normalize` tri-state coercion matrix, missing person keys, all-`any` empty filter, verdict reasons, `sort_people` ordering contract → `tests/unit/backend/test_person_filter_contract.py` |
| `preset_store` | `test_stores_split.py` (partial) | load/default | ⬛ stack/template CRUD round-trip + overwrite, dirty/force save semantics, reopen persistence, `import_legacy` runs once → `tests/test_preset_store_unit.py` |
| `label_store` | `test_person_labels.py` (41, config-mode), `test_labels_ui_js.js` | label **contract** | ⬛ db-bound world mode: flush → reload, per-world isolation, `normalize_color`/`normalize_name` hostile inputs, snapshot/restore deep-copy → `tests/unit/backend/test_label_store_dbmode.py` |
| `tab_matcher` | **none** | match, fallback | ⬛ whole module: URL normalisation, scoring tiers, site-key folding, best_matches order/cap, non-URL queries → `tests/test_tab_matcher.py` |
| `user_memory` | `test_click_user_memory.py` (engine-level) | graph, cycle, missing | ⬛ direct store contract: upsert idempotency, missing-nick ops, queue order, `set_messaged` flip, `replace_all` snapshot, `switch_db` world isolation, persistence across reopen → `tests/test_user_memory_unit.py` |

---

## 4. Contract statements the new tests enforce

Derived from docstrings/README (the promises the code makes to its callers). Each `X#n` id below is referenced by the tests' docstrings.

### chat_parser (concurrent)
- `CP#1` Two overlapping `sync_conversation()` runs for the same person must leave the archive **identical** to one run (append is idempotent through fingerprints) — no duplicate rows, no gap rows.
- `CP#2` Concurrent syncs of **different** persons never cross-file rows (person identity from the archive, not call order).
- `CP#3` `parse_records()` never raises on any JSON the page could produce: `{}`, `{"ok":false}`, `{"items": "text"}`, `null` items, records with unknown kinds, non-string nicks; unusable records are dropped, usable ones kept.
- `CP#4` `drain()` is consume-once even when called while a sync is in flight (second call gets `[]`).

### action_engine (sequence / rollback / failure stop)
- `AE#1` Blocks execute in **stack order** per user; every block sees the same `engine`/context (observable via a recording action).
- `AE#2` A block returning fail **stops that user's remaining blocks** (failure stop) and the failure is reported with the block name; the run itself ends without processing later users only if the failure is fatal — the contract here: user-level stop + loud report.
- `AE#3` `stop()` called mid-run is honoured **between blocks** (no further block starts after the stop flag).
- `AE#4` `pause()` suspends before the next block; `resume()` continues from the same place (no double-run, no skipped block).
- `AE#5` `normalize_blocks()` sanitises hostile payloads: `None` → `[]`, non-list → `[]`, non-dict entries dropped, `{{nick}}`-carrying strings survive, retired keys stripped, `USER_SCOPED_BLOCKS` classification intact.
- `AE#6` `RunTracer` appends one JSON line per `note()` to `logs/run_trace_<run_id>.jsonl` and `close()` leaves the file complete/valid JSONL.
- `AE#7` Repeat: the whole stack runs once per cycle and the queue advances between cycles (second cycle must not re-run the same unmessaged user).

### db_manager (corrupt / concurrent)
- `DB#1` `create()`/`resolve()` cannot produce a path outside the app root, whatever name is given (`../../x`, absolute paths, `.`/empty, embedded separators).
- `DB#2` Loading a **corrupt** (non-SQLite) file fails with a clear error and leaves the previously open world connected (no half-switched state, no crash).
- `DB#3` `info()`/`list_dbs()` work on a folder containing corrupt `*.db` files (they are listed, not fatal).
- `DB#4` Two concurrent `create(name)` calls for the same name end with **one** world file and both calls reporting coherently (no duplicate file, no torn schema).
- `DB#5` `file_group_size` counts `-wal`/`-shm` siblings so the DB window's read-out is the truth.

### config_manager (load / merge / missing / invalid)
- `CF#1` Empty config dir → every `get()` returns documented defaults; `to_dict()` exposes all sections.
- `CF#2` **One** store file missing → that section defaults, all other sections keep their values (partial-failure isolation).
- `CF#3` **Corrupt** JSON in one store file → load survives, section resets to defaults, other sections intact.
- `CF#4` `set("a","b",…,value)` deep-merges: sibling keys survive; `get()` with a missing intermediate key returns the default (never KeyError).
- `CF#5` `named_set/get/delete` round-trip persists to disk and shows up after reopen.
- `CF#6` `set()` with a missing value is a loud error, not silent corruption; after a rejected `set()`, `save()` still writes valid JSON.
- `CF#7` `get_copy()` returns a deep copy — mutating it never reaches the store (regression guard).

### history_service (aggregate / lifecycle / world isolation)
- `HS#1` `init()` on a fresh path creates a working archive; `close()` is idempotent and leaves the file readable.
- `HS#2` `apply_settings()` deep-merges the patch (untouched keys survive), persists, and survives service restart.
- `HS#3` Meta flags round-trip and survive close/reopen.
- `HS#4` **World isolation:** after `switch_db()`, reads show the new world only; switching back shows the original data untouched. Writes in world A never appear in world B.
- `HS#5` A fresh world is seeded with the app-template settings; a world with its own stored settings loads its own instead.
- `HS#6` Gaze (radar partner + counters) saved before switch is restored after switching back.

### criteria_engine
- `CE#1` Compound: with `female=required` **and** `registered=required`, a user must satisfy both; failing either rejects with that criterion as reason.
- `CE#2` All criteria disabled → `filter_users` returns everyone (empty = match all).
- `CE#3` Empty input list → empty output, no error; non-dict entries are ignored safely.
- `CE#4` `save_to_db` → `load_from_db` round-trip preserves the exact criteria state.
- `CE#5` `load_json()` on wrong shapes (`[]`, `null`, `"x"`, `{"criteria": 5}`) never raises and keeps a usable engine.

### scroll_parser (boundary)
- `SC#1` When `scrollTop + clientHeight >= scrollHeight` the list is at its end — no further scroll is dispatched (boundary epsilon, not just strict `<`).
- `SC#2` A single-screen list (not scrollable) is parsed exactly once with zero scroll events.
- `SC#3` A stalled list (identical snapshots) stops after `stall_threshold` stalled scrolls — before burning `max_scrolls`.
- `SC#4` People seen near a page boundary are collected exactly once across the flip (boundary duplicate guard).

### dom_highlight
- `DH#1` Captions/labels/match text containing quotes, backslashes, newlines or `</script>` must land in the generated JS **escaped** — the page probe must stay syntactically valid JS (checked with `node --check`).
- `DH#2` `build_clear_probe()` must remove every overlay and be safe to run twice / with none present.
- `DH#3` `interpret_find`/`interpret_click` on malformed results (`None`, missing keys, garbage) return an error *message pair*, never raise.

### dom_probe
- `DP#1` `_js_str` escapes `\` `"` control chars and U+2028/U+2029 (the classic JS line-terminators that break `<script>` embedding).
- `DP#2` `build_probe` caps candidates at `max_candidates` and switches comparator with `match_mode` (exact vs substring vs startswith).
- `DP#3` `interpret`/`interpret_wait` on `None`/`"null"`/`{}`/garbage produce clear (message, level) pairs — the "nil" path is loud, not a crash.

### visual_click
- `VC#1` `click_enabled=False` → find-only run: found = success **without any click probe**.
- `VC#2` Found but unclickable (hidden/pointer-events) → fail result that says *why*; no click is reported as done.
- `VC#3` Find phase fails → the click phase must not even be attempted.
- `VC#4` `find_and_click_exact` forces exact match (substring hit alone must not click).
- `VC#5` `_parse` tolerates `None`, non-dict and string results.

### history_query
- `HQ#1` Any user search text (FTS operators `" * ( ) OR AND NOT NEAR ^`, unbalanced quotes, CJK, emoji) must return a result — never an sqlite `OperationalError` leaking out.
- `HQ#2` `%`/`_` in a person filter must not act as LIKE wildcards.
- `HQ#3` `page()` with out-of-range cursors (`before_ord` beyond head, `after_ord` beyond tail) and clamped limits returns sane pages (no crash, correct order oldest→newest).
- `HQ#4` `list_persons`: sort modes, `q` nick filter, `include_deleted=False` hides soft-deleted, offset beyond end → `[]`.
- `HQ#5` `db_stats`/`person_stats` on an **empty** DB return zeros (no ZeroDivision, no None leaks).

### history_repo
- `HR#1` soft-delete → `restore_deleted` is the **exact reversal** (same rows visible again, counters restored); restoring twice is a no-op; restoring with a foreign token touches nothing.
- `HR#2` `purge_deleted` removes the bytes for real (`deleted_count` → 0) but only for the purged person.
- `HR#3` soft `delete_person` → `restore_person` brings rows back; hard delete cannot be restored.
- `HR#4` `merge_persons` moves rows, folds duplicates by identity, leaves the source empty/gone, and the survivor's `ord` sequence stays contiguous.
- `HR#5` `rename_if_same_conversation` adopts the archive when signatures match and **refuses** when they don't (never files a stranger's lines under the old nick).
- `HR#6` `resolve_days`: `["23:59","00:05"]` is a midnight rollover — different days, correct order; a lone future minute belongs to the previous day.

### media_handler
- `MH#1` `parse_patterns(None/'', 'a,b ; c d.JPG')` → lowercase glob list; empty pattern means "all images", not "nothing".
- `MH#2` `list_image_files`: case-insensitive extensions, no subdirectories, no hidden/temp files, deterministic order.
- `MH#3` `attach_image` on a missing/empty folder fails with a clear message — never a traceback.

### media_store
- `MS#1` `slugify_nick` on `../../etc`, `".."`, empty, Cyrillic, emoji-only nicks → safe single-path-segment Latin names (no traversal, no empty component).
- `MS#2` `folder_for(nick, kind)` is stable across calls and separates `images` vs `gifs`.
- `MS#3` `_free_name` sequence within one day: `_001`, `_002`, … no collision after simulated restarts.

### message_injector
- `MI#1` `_same_text` matrix: CRLF==LF; one trailing `\n` tolerated; **two** trailing newlines are a mismatch; internal whitespace is significant.
- `MI#2` `_js` on hostile text (quotes, `\`, newlines, U+2028) yields a literal that `node --check` accepts and that round-trips to the original string.
- `MI#3` A multiline message lands with its newlines intact (value-set strategy — Enter must never submit early).

### person_filter
- `PF#1` `normalize()` coerces every garbage value the UI/preset can hold (`True`, `1`, `'yes'`, `None`, `''`) into a valid tri-state, honouring the given default.
- `PF#2` `check()` with **missing keys** treats them as unknown → the tri-state rule decides (`required` rejects, `forbidden` accepts, `any` accepts).
- `PF#3` All-`any` filter is `is_empty()` and accepts everything; `describe()`/`rules()` tell the truth about it.
- `PF#4` `sort_people`: unmessaged first A–Z, messaged sink to the bottom A–Z, stable, empty-safe.

### preset_store
- `PS#1` Stack + template CRUD round-trip, overwrite-in-place, delete removes from listing.
- `PS#2` `dirty` tracking: load → clean, mutate → dirty; reopen persistence through a fresh instance.
- `PS#3` `import_legacy` imports at most once; second call is a no-op that doesn't duplicate.

### label_store (db-bound world mode)
- `LB#1` Bound mode: create/assign → `flush_to_db` → a fresh store `load_from_db` sees the same state.
- `LB#2` Two worlds hold independent label sets; switching bound db swaps state cleanly.
- `LB#3` `normalize_color` returns a safe `#rrggbb` for garbage (`red`, `#fff`, `#GGGGGG`, `None`), never raising.
- `LB#4` `normalize_name` caps length and collapses whitespace; empty → `''`.
- `LB#5` `snapshot()`/`restore()` round-trip is deep (mutating the snapshot must not touch the store).

### tab_matcher
- `TM#1` `_normalize_url` folds scheme/www/trailing-slash/fragment/host-case.
- `TM#2` Scoring tiers: full URL > path > host > title; unrelated = 0.
- `TM#3` `_site_key` folds sub-hosts of one registered site together.
- `TM#4` `best_matches`: best-first order, `top_n` cap, empty tab list → `[]`.
- `TM#5` Non-URL queries (plain words) fall back to title matching.

### user_memory
- `UM#1` `upsert_user` is idempotent per nick (update, not duplicate); `upsert_many` is transactional.
- `UM#2` Operations on a missing nick (`mark_messaged`, `set_messaged`, `delete_user`) are safe no-ops/False, never raises.
- `UM#3` `get_queue` returns only unmessaged users in stable order; `count_unmessaged` agrees with it.
- `UM#4` `replace_all` restores an exact snapshot (wipe + insert).
- `UM#5` `switch_db` re-points the queue; the old world's rows are untouched and restored on switching back; data persists across close/reopen.

### history_db
- `HD#1` `get_meta`/`set_meta` round-trip, overwrite, and default on missing key.
- `HD#2` `fetchall`→tuples, `fetchdicts`→dicts, `scalar` default; parameter binding (no format-string SQL).
- `HD#3` `file_size()` includes `-wal`/`-shm` siblings.
- `HD#4` A fresh DB with `use_fts=False` opens cleanly without FTS tables; `use_fts=True` builds them.
- `HD#5` Two open connections (concurrent worlds/tools) don't corrupt each other's writes.

### history_models
- `HM#1` `fingerprint` is stable across calls and occurrence-sensitive.
- `HM#2` Occurrence counting over UTF-16 units: astral-plane emoji must count as 2 units (JS-string semantics), so `😀`-vs-BMP collisions cannot produce equal fps.
- `HM#3` `dedupe_key` ignores `occ` but binds direction/nick/ts/kind/payload.
- `HM#4` `MessageRecord.from_dict` on agent garbage (missing keys, wrong types) yields a usable record or raises a *clear* error — never a deep TypeError.
- `HM#5` `to_dict()` of every result object is JSON-serialisable and `from_dict(to_dict(x)) == x` where defined.

---

## 5. Test-file inventory (new)

| File | Covers | Tests |
|---|---|---|
| `tests/test_chat_parser_concurrent.py` | CP#1–4 | P0 |
| `tests/test_action_engine_sequence.py` | AE#1–7 | P0 |
| `tests/test_db_manager_corrupt.py` | DB#1–5 | P0 |
| `tests/unit/backend/test_config_manager_contract.py` | CF#1–7 | P0 |
| `tests/test_history_service_lifecycle.py` | HS#1–6 | P0 |
| `tests/unit/backend/test_criteria_engine_contract.py` | CE#1–5 | P1 |
| `tests/test_scroll_parser_boundary.py` | SC#1–4 | P1 |
| `tests/unit/backend/test_dom_highlight_contract.py` | DH#1–3 | P1 |
| `tests/unit/backend/test_dom_probe_contract.py` | DP#1–3 | P1 |
| `tests/test_visual_click_contract.py` | VC#1–5 | P1 |
| `tests/test_history_query_edges.py` | HQ#1–5 | P1 |
| `tests/test_history_repo_lifecycle.py` | HR#1–6 | P1 |
| `tests/test_media_handler_paths.py` | MH#1–3 | P1 |
| `tests/test_media_store_paths.py` | MS#1–3 | P1 |
| `tests/test_message_injector_text.py` | MI#1–3 | P1 |
| `tests/unit/backend/test_person_filter_contract.py` | PF#1–4 | P2 |
| `tests/test_preset_store_unit.py` | PS#1–3 | P2 |
| `tests/unit/backend/test_label_store_dbmode.py` | LB#1–5 | P2 |
| `tests/test_tab_matcher.py` | TM#1–5 | P2 |
| `tests/test_user_memory_unit.py` | UM#1–5 | P2 |
| `tests/test_history_db_unit.py` | HD#1–5 | P2 |
| `tests/unit/backend/test_history_models.py` | HM#1–5 | P2 |

22 new files, ≈ 120+ assertions, zero overlap with existing suites.

---

## 6. Bug ledger

Filled during implementation. One row per red test and its verdict.

| # | Test | Verdict | Detail |
|---|---|---|---|
| — | — | — | — |

*(populated in §6 after the run — see final report)*
