# Ideal-size baseline — measured 2026-09-11 (re-measured 2026-09-12, 2026-09-13)

Snapshot of this checkout against the **ideal sizes** of
`docs/current/AGENT_RULES.md` RULE 18. These are preferences, not gates; the
enforced thresholds and their baseline live in
`reports/CODE_QUALITY_METRICS_2026-09-10.md`. Nothing here fails a build.

Counting rule: the inclusive physical span (`node.end_lineno - node.lineno + 1`),
docstring included, decorator lines excluded, nested functions counted
separately — the same count `tests/test_rule16_new_code.py` uses. A
"production file" is any `.py` under `core/ actions/ backend/ bridge/ services/
stores/ app/` plus `main.py`, `__pycache__` excluded — **224 files** on
2026-09-13.

## 1. Functions (ideal 4–20 lines)

**1991 production functions** — mean 9.6, median 7, p90 20, p99 40, max 122.

| Band | Count | Share | Verdict |
|---|---:|---:|---|
| 1–3 lines | 522 | 26.2% | fine when the name earns it (§18.1) |
| **4–20 lines (ideal)** | 1277 | 64.1% | in band |
| 21–30 lines | 150 | 7.5% | over the ideal, inside the RULE 16 fail line (30) |
| 31–56 lines | 40 | 2.0% | over the fail line — legacy |
| > 56 lines | 2 | 0.1% | worst offenders, listed below |

> Re-measured 2026-09-12 after porting the DB-undo-restore feature
> (`arena/01a08fc5`): 324 functions added, 333 moved. The six brand-new
> feature modules (`stores/world_lock.py`, `services/undo_archive.py`,
> `services/undo_timeline.py`, `services/world_events.py`,
> `services/history/trash.py`, `services/history/migrate.py`) put **90.3%**
> of their 62 functions in the 4–20 band (max 20, no function over CC 10).
> The three feature functions that started above the ideal
> (`purge_tokens` 24, `ArchiveCommands.run` 22, `TimelineCommit.commit` 21)
> were split — `_marked_counts`, `ArchiveCommands._apply`,
> `TimelineCommit._next_seq` — so every new function now lands in band.
>
> Re-measured 2026-09-13 after the god-class round's steps 1–7 and the
> boot world-wait port. **Function lengths barely moved** — mean 9.6 and
> median 7 are unchanged, in-band 64.2% → 64.1%, p99 39 → 40, max still 122
> (`backend/dom_probe.py` · `build_probe`). That is the point of splitting by
> *responsibility* rather than by length: the file count grew by 70 (154 → 224)
> as seven god modules became packages, without buying or selling a single long
> function. What the port added is two
> functions, both in band: `services/world_events.py` ·
> `wait_for_world_open` **20 LOC / 3 params / CC 6** and ·
> `run_when_world_open` **16 LOC / 4 params / CC 3**; it also made one
> smaller — `bridge/history_bridge/runner.py` · `_run_async` went 8 → **4
> LOC** and lost its nested `guarded()` closure when the guard moved into
> `services/`.

### Functions over 56 lines

| LOC | Function |
|---:|---|
| 122 | `backend/dom_probe.py` · `build_probe` |
| 70 | `backend/message_injector.py` · `_run_type_strategies` |

## 2. Files (ideal 150–300 lines)

**224 production files** — mean 132, median 99, max 523.

| Band | Count | Share |
|---|---:|---:|
| < 150 lines | 152 | 67.9% |
| **150–300 lines (ideal)** | 52 | 23.2% |
| 301–500 lines | 18 | 8.0% |
| > 500 lines | **2** | 0.9% |

Compare 2026-09-12: 154 files, mean 182, median 145, max **791**, ten files
over 500. The round's steps 1–7 turned the seven worst modules into packages,
which is why the median *fell* (99) while the count rose (224) — leaves are
smaller than the god modules they came from, and §18.2 calls a small leaf
"normal and good". Files over 500 went **10 → 2**, so step 8's target
("files > 500 → 0") is two files away: `backend/dom_highlight.py` (523) and
`backend/config_manager.py` (502).

### Files over 500 lines (remaining known debt)

| Lines | File |
|---:|---|
| 523 | `backend/dom_highlight.py` |
| 502 | `backend/config_manager.py` |

### Largest ten (all inside step 8's reach)

| Lines | File |
|---:|---|
| 523 | `backend/dom_highlight.py` |
| 502 | `backend/config_manager.py` |
| 478 | `backend/message_injector.py` |
| 478 | `backend/media_handler.py` |
| 471 | `bridge/router.py` |
| 458 | `stores/media_fetch.py` |
| 432 | `stores/history_repo_lifecycle.py` |
| 425 | `services/collector_tick.py` |
| 423 | `backend/chat_parser.py` |
| 420 | `stores/history_schema_repair.py` |

UI files are measured separately (RULE 18 §18.2 counts them the same way, but
they are not in the production-file set above): `ui/js/sash-grid.js` **1359**,
`ui/js/stack-dnd.js` **1247**, `ui/js/labels.js` 778, `ui/js/sash-core.js` 632,
`ui/js/app.js` **490**, `ui/js/history-db.js` **447**. The last two carry the
reason they are over the ideal: `history-db.js` states it in its own
`ideal-size:` header, and `app.js`'s growth (477 → 490, the boot-fix re-ask) is
recorded in
[`docs/archive/2026-09-13-boot-world-wait/BOOT_WORLD_WAIT_DESIGN_2026-09-13.md`](../docs/archive/2026-09-13-boot-world-wait/BOOT_WORLD_WAIT_DESIGN_2026-09-13.md).
`sash-grid.js` and `stack-dnd.js` remain the tree's largest **unannotated**
files and are the honest next candidates.

## 3. Modules (ideal 5–15 cohesive files)

| Directory | Files | Verdict |
|---|---:|---|
| `stores/` | 37 | over the band — held by prefix families (`history_*`, `world_*`, `label_*`); promote a family to a sub-package before adding more |
| `backend/` | 27 | over the band — same story (`chat_*`, `dom_*`, `media_*`) |
| `actions/` | 23 | over the band — one file per action block; cohesive by design, split only if it grows |
| `services/` | 16 | over the band by one; the round moved its families out (`run/`, `history/`, `collector/`, `db_deletion/`, `undo_service/`) |
| `bridge/` | 12 | in band |
| `services/undo_service/` | 12 | in band (step 7) |
| `backend/scroll_parser/` | 11 | in band (step 3) |
| `services/db_deletion/` | 11 | in band (step 2) |
| `backend/chat_sync/` | 10 | in band (step 1) |
| `bridge/history_bridge/` | 10 | in band (step 6) |
| `services/run/` | 10 | in band |
| `backend/history_query/` | 9 | in band (step 5) |
| `bridge/stack_bridge/` | 9 | in band (step 6) |
| `services/collector/` | 8 | in band (step 4) |
| `services/history/` | 7 | in band |
| `core/` | 6 | in band |
| `app/` | 4 | small leaf package |
| `services/run_service/` | 1 | small leaf package (compatibility shim for the pre-split name) |
| `./` | 1 | `main.py` |

Every package the round created is inside 5–15 — the splits produced modules,
not shards.

## 4. Context files (ideal 60–200 lines)

| Lines | File | Verdict |
|---:|---|---|
| 85 | `docs/README.md` | in band |
| 741 | `docs/current/AGENT_RULES.md` | over the band — see RULE 18 §18.4 |
| 338 | `docs/current/DOM_SELECTORS.md` | over the band — see RULE 18 §18.4 |
| 325 | `docs/current/SYSTEM_OF_RECORD.md` | over the band — see RULE 18 §18.4 |

## Reproduction

```bash
# file sizes (largest first)
wc -l $(git ls-files '*.py' | grep -E '^(core|actions|backend|bridge|services|stores|app)/') main.py | sort -n | tail -15
# per-file LOC / SLOC / comments
.venv/bin/radon raw -s <file>
# module size (top level of a package)
ls stores/*.py | wc -l
# context files
wc -l docs/README.md docs/current/*.md
```

Function lengths and the band table come from the AST walker in
`tests/test_rule16_new_code.py` (`node.end_lineno - node.lineno + 1` over every
`FunctionDef` / `AsyncFunctionDef` in the production files), not from a line
grep; the 2026-09-13 numbers were produced by that walker over the same file
set.
