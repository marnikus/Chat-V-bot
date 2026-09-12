# Ideal-size baseline — measured 2026-09-11 (re-measured 2026-09-12)

Snapshot of this checkout against the **ideal sizes** of
`docs/current/AGENT_RULES.md` RULE 18. These are preferences, not gates; the
enforced thresholds and their baseline live in
`reports/CODE_QUALITY_METRICS_2026-09-10.md`. Nothing here fails a build.

Counting rule: the inclusive physical span (`node.end_lineno - node.lineno + 1`),
docstring included, decorator lines excluded, nested functions counted
separately — the same count `tests/test_rule16_new_code.py` uses.

## 1. Functions (ideal 4–20 lines)

**1992 production functions** — mean 9.6, median 7, p90 20, p99 39, max 122.

| Band | Count | Share | Verdict |
|---|---:|---:|---|
| 1–3 lines | 522 | 26.2% | fine when the name earns it (§18.1) |
| **4–20 lines (ideal)** | 1278 | 64.2% | in band |
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

### Functions over 56 lines

| LOC | Function |
|---:|---|
| 122 | `backend/dom_probe.py` · `build_probe` |
| 70 | `backend/message_injector.py` · `_run_type_strategies` |

## 2. Files (ideal 150–300 lines)

**154 production files** — mean 182, median 145, max 791.

| Band | Count | Share |
|---|---:|---:|
| < 150 lines | 79 | 51.3% |
| **150–300 lines (ideal)** | 47 | 30.5% |
| 301–500 lines | 18 | 11.7% |
| > 500 lines | 10 | 6.5% |

### Files over 500 lines (known debt — §16.5 landmines)

| Lines | File |
|---:|---|
| 791 | `backend/chat_sync.py` |
| 674 | `backend/scroll_parser.py` |
| 665 | `services/db_deletion.py` |
| 606 | `backend/history_query.py` |
| 593 | `services/collector_service.py` |
| 564 | `services/undo_service.py` |
| 537 | `bridge/history_bridge.py` |
| 523 | `backend/dom_highlight.py` |
| 509 | `services/db_deletion_flow.py` |
| 502 | `backend/config_manager.py` |

## 3. Modules (ideal 5–15 cohesive files)

| Directory | Files | Verdict |
|---|---:|---|
| `stores/` | 37 | held by prefix families — promote a family to a sub-package before adding more |
| `backend/` | 30 | held by prefix families — promote a family to a sub-package before adding more |
| `actions/` | 23 | held by prefix families — promote a family to a sub-package before adding more |
| `services/` | 21 | held by prefix families — promote a family to a sub-package before adding more |
| `bridge/` | 14 | in band |
| `services/run/` | 10 | in band |
| `core/` | 6 | in band |
| `services/history/` | 7 | in band |
| `app/` | 4 | small leaf package |
| `services/run_service/` | 1 | small leaf package |
| `./` | 1 | small leaf package |

## 4. Context files (ideal 60–200 lines)

| Lines | File | Verdict |
|---:|---|---|
| 82 | `docs/README.md` | in band |
| 741 | `docs/current/AGENT_RULES.md` | over the band — see RULE 18 §18.4 |
| 338 | `docs/current/DOM_SELECTORS.md` | over the band — see RULE 18 §18.4 |
| 315 | `docs/current/SYSTEM_OF_RECORD.md` | over the band — see RULE 18 §18.4 |

## Reproduction

```bash
# file sizes (largest first)
wc -l $(git ls-files '*.py' | grep -E '^(core|actions|backend|bridge|services|stores|app)/') main.py | sort -n | tail -15
# per-file LOC / SLOC / comments
.venv/bin/radon raw -s <file>
# module size
ls stores/*.py | wc -l
# context files
wc -l docs/README.md docs/current/*.md
```

Function lengths come from the AST walker in `tests/test_rule16_new_code.py`,
not from a line grep.
