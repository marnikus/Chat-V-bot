# Docs: start here

This repository has **three current docs** and **78 archived ones**. That is
deliberate: the current set is small enough to keep true, and nothing has been
thrown away.

```
docs/
├── README.md                        ← you are here (the map)
├── current/                         ← true TODAY. Read these.
│   ├── SYSTEM_OF_RECORD.md          ← behaviour, invariants, flows, links outward
│   ├── AGENT_RULES.md               ← RULE 1–18: what every code change must obey
│   └── DOM_SELECTORS.md             ← verified DOM selectors of the target site
└── archive/                         ← historical. One folder per date+topic.
    ├── README.md                    ← index of all 78 archived docs
    ├── 2026-09-04-foundation/
    ├── 2026-09-05-grid-scroll-undo/
    ├── 2026-09-06-collector-and-history/
    ├── 2026-09-07-labels-and-collector/
    ├── 2026-09-08-one-db-one-world/
    ├── 2026-09-09-four-area-refactor/
    ├── 2026-09-09-test-suite/
    ├── 2026-09-10-safety-refactor/
    ├── 2026-09-10-quality-gates/
    ├── 2026-09-10-history-push-and-sort/
    ├── 2026-09-10-agent-rules-v1/
    └── 2026-09-11-db-undo-restore/   ← the write gate + verified undo (newest)
```

Also in the repo, not under `docs/`:

| Path | What it is |
|---|---|
| [`README.md`](../README.md) | User manual: install, Chrome flags, UI tour |
| [`reports/`](../reports/) | Measured code-quality snapshots (the coverage/complexity **baseline** the rules compare against) |
| `tests/` | The executable spec — 157 Python test files + 23 Node harness files |

---

## Pick your entry point

| You want to… | Read |
|---|---|
| Know how the app behaves right now | [`current/SYSTEM_OF_RECORD.md`](current/SYSTEM_OF_RECORD.md) |
| Change code and not break a contract | [`current/AGENT_RULES.md`](current/AGENT_RULES.md) — then the matching section of the system of record |
| Touch a DOM probe or selector | [`current/DOM_SELECTORS.md`](current/DOM_SELECTORS.md) |
| Understand *why* something is the way it is | [`archive/README.md`](archive/README.md), or the "history of X" table at the bottom of the system of record |
| Install and drive the app | [`../README.md`](../README.md) |

**Conflict rule:** if an archived doc disagrees with
[`current/SYSTEM_OF_RECORD.md`](current/SYSTEM_OF_RECORD.md), the current file
wins. Archived docs are true as of the date in their folder name.

---

## Current vs. historical at a glance

| Topic | Current (read this) | Historical (why it is that way) |
|---|---|---|
| Overall architecture | [`current/SYSTEM_OF_RECORD.md`](current/SYSTEM_OF_RECORD.md) §1, §6 | [`2026-09-04-foundation/ARCHITECTURE.md`](archive/2026-09-04-foundation/ARCHITECTURE.md) (design-phase, superseded), [`2026-09-09-four-area-refactor/`](archive/2026-09-09-four-area-refactor/) (the split into layers) |
| Rules for AI agents | [`current/AGENT_RULES.md`](current/AGENT_RULES.md) | [`2026-09-10-agent-rules-v1/`](archive/2026-09-10-agent-rules-v1/) (the two files it replaced), [`2026-09-10-quality-gates/`](archive/2026-09-10-quality-gates/) (where the thresholds came from) |
| Run engine (plan → execute) | system of record §3.1 | [`2026-09-10-safety-refactor/SAFETY_REFACTOR_AREA_C_DESIGN_2026-09-10.md`](archive/2026-09-10-safety-refactor/SAFETY_REFACTOR_AREA_C_DESIGN_2026-09-10.md) |
| Deletion / safety | system of record §3.3, invariant I-15/I-16/I-18 | [`2026-09-10-safety-refactor/`](archive/2026-09-10-safety-refactor/), [`2026-09-11-db-undo-restore/`](archive/2026-09-11-db-undo-restore/DB_UNDO_RESTORE_DESIGN_2026-09-11.md) (the DB window’s delete / undo / trash ladder) |
| Storage model (one DB = one world) | system of record §5 | [`2026-09-08-one-db-one-world/`](archive/2026-09-08-one-db-one-world/) |
| Message archive + collector | system of record §2, §3.2 | [`2026-09-06-collector-and-history/`](archive/2026-09-06-collector-and-history/), [`2026-09-07-labels-and-collector/`](archive/2026-09-07-labels-and-collector/) |
| Undo, locking, DB-window refresh | system of record §2, invariants I-10, I-17, I-18 | [`2026-09-11-db-undo-restore/`](archive/2026-09-11-db-undo-restore/DB_UNDO_RESTORE_DESIGN_2026-09-11.md) |
| Blocks, grid, undo, scroll | system of record §2, invariants I-1…I-11 | [`2026-09-05-grid-scroll-undo/`](archive/2026-09-05-grid-scroll-undo/) |
| Tests | system of record §7 | [`2026-09-09-test-suite/`](archive/2026-09-09-test-suite/) |

---

## Maintaining this (RULE 17)

* **Never add a new top-level doc for a feature.** Write the design into
  `docs/archive/<YYYY-MM-DD>-<topic>/`, then update the rows of
  `current/SYSTEM_OF_RECORD.md` it affects and the map above.
* `current/` holds only what is true today. If a statement there stops being
  true, fix it in the same change that made it untrue.
* Archived docs are never rewritten to catch up. A one-line correction note is
  allowed (e.g. marking a deliverable that was never produced).
* Reference docs by full repo-relative path, on one line, so they stay
  greppable: `docs/archive/2026-09-08-one-db-one-world/DB_CREATION_DELETION_REDESIGN_DESIGN_2026-09-08.md`.
