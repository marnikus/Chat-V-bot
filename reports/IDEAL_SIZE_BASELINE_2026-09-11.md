# Ideal-size baseline — measured 2026-09-11

Snapshot of this checkout against the **ideal sizes** of
`docs/current/AGENT_RULES.md` RULE 18. These are preferences, not gates; the
enforced thresholds and their baseline live in
`reports/CODE_QUALITY_METRICS_2026-09-10.md`. Nothing here fails a build.

Counting rule: the inclusive physical span (`node.end_lineno - node.lineno + 1`),
docstring included, decorator lines excluded, nested functions counted
separately — the same count `tests/test_rule16_new_code.py` uses.

## 1. Functions (ideal 4–20 lines)

**1668 production functions** — mean 10.3, median 6, p90 23, p99 49, max 122.

| Band | Count | Share | Verdict |
|---|---:|---:|---|
| 1–3 lines | 483 | 29.0% | fine when the name earns it (§18.1) |
| **4–20 lines (ideal)** | 962 | 57.7% | in band |
| 21–30 lines | 149 | 8.9% | over the ideal, inside the RULE 16 fail line (30) |
| 31–56 lines | 67 | 4.0% | over the fail line — legacy |
| > 56 lines | 7 | 0.4% | worst offenders, listed below |

### Functions over 56 lines

| LOC | Function |
|---:|---|
| 122 | `backend/dom_probe.py` · `build_probe` |
| 92 | `actions/wait_page.py` · `execute` |
| 79 | `stores/migration.py` · `migrate_legacy_config` |
| 75 | `actions/cancellation.py` · `await_with_stop` |
| 70 | `backend/message_injector.py` · `_run_type_strategies` |
| 67 | `services/run/error_recovery.py` · `_execute_for_user` |
| 60 | `services/history/runtime.py` · `switch_db` |

## 2. Files (ideal 150–300 lines)

**141 production files** — mean 177, median 130, max 771.

| Band | Count | Share |
|---|---:|---:|
| < 150 lines | 78 | 55.3% |
| **150–300 lines (ideal)** | 37 | 26.2% |
| 301–500 lines | 17 | 12.1% |
| > 500 lines | 9 | 6.4% |

### Files over 500 lines (known debt — §16.5 landmines)

| Lines | File |
|---:|---|
| 771 | `backend/chat_sync.py` |
| 671 | `backend/scroll_parser.py` |
| 665 | `services/db_deletion.py` |
| 578 | `services/collector_service.py` |
| 563 | `services/undo_service.py` |
| 554 | `backend/history_query.py` |
| 528 | `bridge/history_bridge.py` |
| 512 | `backend/dom_highlight.py` |
| 509 | `services/db_deletion_flow.py` |

## 3. Modules (ideal 5–15 cohesive files)

| Directory | Files | Verdict |
|---|---:|---|
| `stores/` | 35 | held by prefix families — promote a family to a sub-package before adding more |
| `backend/` | 30 | held by prefix families — promote a family to a sub-package before adding more |
| `actions/` | 23 | held by prefix families — promote a family to a sub-package before adding more |
| `services/` | 16 | held by prefix families — promote a family to a sub-package before adding more |
| `bridge/` | 12 | in band |
| `services/run/` | 9 | in band |
| `core/` | 5 | in band |
| `services/history/` | 5 | in band |
| `app/` | 4 | small leaf package |
| `services/run_service/` | 1 | small leaf package |
| `./` | 1 | small leaf package |

## 4. Context files (ideal 60–200 lines)

| Lines | File | Verdict |
|---:|---|---|
| 80 | `docs/README.md` | in band |
| 697 | `docs/current/AGENT_RULES.md` | over the band — see RULE 18 §18.4 |
| 338 | `docs/current/DOM_SELECTORS.md` | over the band — see RULE 18 §18.4 |
| 303 | `docs/current/SYSTEM_OF_RECORD.md` | over the band — see RULE 18 §18.4 |

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
