# Porting the DB-undo-restore feature onto the CC-tail tree

**Date:** 2026-09-12 · **Branch:** `arena/01a09227-chat-v-bot`
**Source:** `arena/01a08fc5-chat-v-bot`, commits `6346884` → `883ff8f` → `5329ec3`
→ `a0a8a65` → `fc66365`
**The feature's own reasoning:** [`../2026-09-11-db-undo-restore/DB_UNDO_RESTORE_DESIGN_2026-09-11.md`](../2026-09-11-db-undo-restore/DB_UNDO_RESTORE_DESIGN_2026-09-11.md)
— reproduced here verbatim. This file records only what porting it onto *this*
tree required, because that tree had independently been through the CC-tail
round ([`../2026-09-11-cc-tail/`](../2026-09-11-cc-tail/CC_TAIL_FIXES_DESIGN_2026-09-11.md)).

---

## 1. Why this is a hand port, not a merge

The two branches have **unrelated histories**. This branch is rooted at the
squashed `main` snapshot `8266c0d` (8 commits); the source branch is rooted at
the real `831d4f4` (252 commits). `git merge-base` returns nothing, so neither
a merge nor a cherry-pick can express the change.

What made the port tractable is that `main`'s tree is very close to the source
branch's commit `3fc511b` — the commit the feature started from. Measured
against `3fc511b`, this tree differs only by the CC-tail round (51 files). So
the feature could be taken as one patch, `3fc511b..fc66365`, and applied
three-way onto the refactored tree:

```bash
git diff 3fc511b fc66365 -- app bridge services stores tools ui tests > feature-code.patch
git apply --3way feature-code.patch
```

28 files: 24 applied cleanly, **4 conflicted**. Six modules and five test files
were new and landed verbatim.

## 2. The four conflicts, and how each was resolved

| File | Ours (CC-tail) | Theirs (feature) | Resolution |
|---|---|---|---|
| `services/history/export.py` | `init` calls the module-level `_load_labels(self)` extracted to cut its CC | `init` calls `self._worlds.load_labels()`, shared with the switch path | **Theirs.** The two bodies were behaviourally identical; the feature's version is the de-duplicated one, so mine was deleted rather than left as a second copy (§16.4). |
| `services/undo_service.py` | `_apply_people_command` / `_apply_labels_command` as *methods*; `_apply_db_command` split into `_db_delete_op` / `_db_op_forward` / `_db_switch_op` | the same two helpers as *module-level* functions taking `host`; `_schedule` and `import asyncio` removed in favour of `TimelineCommit.spawn` | **Both, by theme.** Theirs for the people/labels helpers and the verified `_apply_archive_command`; ours kept for the `_apply_db_command` decomposition, with its `self._schedule(work())` becoming `self._timeline_commit.spawn("db command", work())`. |
| `stores/history_repo_lifecycle.py` | module-level `_hidden_row_key`, `_sig_or` | module-level `_delete_hidden`, `_erase_person`, `_erase_tombstones` | **Union.** Disjoint helper families; all five are live (`_hidden_row_key` at the restore path, `_sig_or` at the cursor write, the erase trio at `purge_deleted`). |
| `tests/unit/stores/test_stores_public_api.py` | the stores-import pin at **38** (window-preset shim) | the same pin at **39** (`world_lock` +2) | **Measured, not averaged: 40.** Both changes are real and additive, so the pin carries both dated reasons. |

`docs/current/SYSTEM_OF_RECORD.md` conflicted too, in the §8 metrics row. Ours
was kept (it links `reports/IDEAL_SIZE_BASELINE_2026-09-11.md` and carries the
RULE 19 row the source branch does not have) and every number in it was
re-measured on the merged tree rather than copied.

`docs/current/AGENT_RULES.md` was **not** patched at all. The source branch's
change to it is purely a re-measurement of RULE 18's "Measured today" lines, and
this tree's copy is the newer one (it has RULE 19). Those three lines were
re-measured here instead — length-neutrally, because §18.4 puts the file at its
~730-line budget and it is at 737.

## 3. A bug the port exposed — and it is the feature's, not the merge's

**Symptom.** The suite finished but the process never exited: `py-spy` showed
the main thread parked in `threading._shutdown` waiting on one non-daemon
`aiosqlite` `_connection_worker_thread`. The run was also ~4× slower than
baseline.

**Cause.** `stores/history_db.py::init()` stamps `schema_meta` through
`set_meta()`, which writes through the **gated** `execute()` and so takes the
world's writer turn. `init()` then committed through the **raw** connection:

```python
await self._conn.commit()      # commits, but never calls turn.end()
```

The gated `HistoryDB.commit()` is `_release(self.conn.commit, self.turn)` —
commit *and* hand the turn back. Bypassing it left the turn held until
`close()`. Two consequences, both measured:

1. `UserMemory` — the second connection on the same world file, the exact pair
   the gate exists to serialize — blocked for `WAIT_S = 15 s` on its first write
   and then **failed open**. That is the slowdown, and in the app it is a 15 s
   stall after opening a world.
2. `stores/world_lock.py::_GATES` is a process-wide registry, and a held gate
   keeps `_token` — the `HistoryDB` — reachable, which keeps its open connection
   reachable. `aiosqlite.Connection.__del__` is what normally stops the worker
   thread; pinned, it never ran, and the non-daemon thread blocked interpreter
   exit. Before the port, GC covered for any store a test forgot to close.

**This is in the source branch too** — `git show fc66365:stores/history_db.py`
line 116 is the same raw commit. It is invisible there because
`HistoryService.init()` commits again a few lines later through the gated path,
which releases the turn. Only a *bare* `HistoryDB.init()` shows it, and the
feature's own tests always go through the service.

**Fix.** One line — commit through the gate:

```python
await self.commit()    # gated: hands the world's writer turn back
```

Reproduction, before the fix (`init` leaves the gate held, the queue waits it
out, and the script then hangs at exit):

```
after bare HistoryDB.init(): busy = True  holder = HistoryDB
turn.held = True
queue write took 15.02s (WAIT_S=15.0)
world /tmp/.../v.db is still busy after 15s — writing anyway
```

**Pinned by** `tests/test_world_write_gate.py::TestOpenGivesTheTurnBack` (2 new
tests), written at the level that owns the invariant — a bare `HistoryDB`, not
the service that masks it. RULE 8 mutation check:

| | result |
|---|---|
| with the fix | 2 passed in **0.19 s** |
| fix reverted | 2 failed in **15.22 s**, on the fail-open warning |

`init` stays at **54 LOC** — exactly its pre-port size. The first draft of this
fix explained itself in an eight-line comment, which took `init` to 63 LOC and
tripped `test_no_single_method_body_beyond_the_ceiling` (ceiling 60); that is
§16.5 (never grow a legacy offender), so the rationale moved here and the site
keeps one trailing comment.

## 4. The two structural gates that had to move

* **`stores/` file count 36 → 37** (`test_the_package_keeps_a_reasonable_file_count`).
  `stores/world_lock.py` is a new leaf — no Qt, no `backend/` or `services/`
  import — and it belongs beside the two stores it serializes. RULE 18.3 counts
  the prefix families as the real modules here (`history_*` 9, `label_*` 6,
  `media_*` 4), so this is a cohesive addition, not a decomposition fragment.
  The reason is recorded at the assertion, in the style that pin already used.
* **stores-import pin 38 → 40** (`test_stores_public_api.py`) — see §2. Both
  increments are the sanctioned "another area legitimately grows the surface"
  case: a new leaf store, imported by the two services that must survive a
  locked world file.

No limit was relaxed to make failing code pass; both are counts that a real new
file legitimately moves, and both say so where they are asserted.

## 5. Measured on the merged tree

RULE 16 hard limits (`tools/metrics/current_audit.py`, production packages only):

| Metric | Before the port | After | Limit |
|---|---:|---:|---:|
| functions CC > 10 | 0 (max 10) | **0 (max 10)** | 0 |
| mean CC | 3.106 | **3.093** | — |
| cognitive > 15 | 2 (max 17) | **2 (max 17)** | frozen pair only |
| nesting > 4 | 0 (max 4) | **0 (max 4)** | 0 |
| function LOC > 30 | 44 | **42** | no new offenders |
| production functions | 1 929 | 1 997 | — |

The two surviving `cognitive > 15` sites are the frozen, explicitly exempt pair
`bridge/router.py::_build_router_class` and `stores/settings_store.py::get`.
The port *improved* mean CC and removed two LOC>30 offenders, because the
feature's own extractions (`undo_timeline.py`, `trash.py`, `migrate.py`,
`undo_archive.py`) are decomposition, not addition.

§16.5 landmines — the port must not grow them. `services/undo_service.py` is the
one this feature touches hardest:

| `undo_service.py` | file LOC | class LOC | methods |
|---|---:|---:|---:|
| `3fc511b` baseline | 563 | 444 | 26 |
| this tree, pre-port | 589 | 470 | 31 |
| source branch, final | 554 | 399 | 25 |
| **merged** | **573** | **418** | **28** |

Against the tree being changed, every one of the three went **down**, so the
landmine shrank. It is larger than the source branch's 554 because this tree
keeps the CC-tail decomposition of `_apply_db_command` (three methods that buy
CC 15 → 3); that is the deliberate difference recorded in §2.

RULE 18 ideals (preferences, re-measured 2026-09-12; reproduction in §7):

| | value |
|---|---|
| functions in the 4–20 band | **63.6%** of 1 997 (median 7, mean 9.7, p90 21) |
| production files | **154**, median **142** lines, mean 184 |
| files over 500 | **10** — `backend/chat_sync.py` 800, `backend/scroll_parser.py` 699, `services/db_deletion.py` 665, `services/collector_service.py` 601, `backend/history_query.py` 596, `services/undo_service.py` 573, `bridge/history_bridge.py` 542, `backend/dom_highlight.py` 527, `services/db_deletion_flow.py` 509, `backend/config_manager.py` 502 |
| new files, all inside the ideal | `world_events.py` 55 · `migrate.py` 92 · `trash.py` 129 · `undo_timeline.py` 146 · `undo_archive.py` 230 · `world_lock.py` 241 |
| modules in band | `core/` 6, `app/` 4, `bridge/` 14, `services/history/` 7, `services/run/` 10 |
| modules over 15 | `services/` 21, `stores/` 37, `backend/` 30, `actions/` 23 — held by prefix families |

`services/` crossing 21 is worth naming: the `undo_*` family is now four files
(`undo_service`, `undo_support`, `undo_archive`, `undo_timeline`). RULE 18.3's
answer when a family grows again is to promote it to a sub-package
(`services/undo/`). That was **not** done here — it is a move of the feature's
own layout, touching every importer, and it belongs in a change of its own
rather than riding along with a port. Recorded as the next debt.

`stores/history_repo_lifecycle.py` (439) and `bridge/router.py` (471) stay over
300 for the reasons the feature's design doc gives: the person lifecycle *is*
the one responsibility that file owns, and the router is the bridge layer's
single QObject facade.

## 6. Test evidence

| | before the port | after |
|---|---|---|
| Python | 2 650 passed, 6 skipped, 1 xfailed, 774 subtests | **2 707 passed, 6 skipped, 1 xfailed, 777 subtests** |
| Node harness | 25 files green | **26 files green** |
| process exit | clean | **clean** (the shutdown hang is fixed, §3) |
| `rule16_gate.py --with-clones` | exit 0 | **exit 0** — 0 new / 0 stale clone groups, ratchet intact |
| coverage (line / branch) | 90.44% / 84.38% (2026-09-10 baseline on record) | **91.43% / 86.32%** — floors are 80% / 75%, and §16.3's "never below baseline" holds: +0.99 line, +1.94 branch |

+57 Python tests: the feature's own suites (`test_world_write_gate.py` 35,
`test_world_events.py` 6, `test_world_ready.py` 3, `test_app_lifecycle.py` 3,
the extended `test_history_repo_lifecycle.py` and undo-support contract) plus
the 2 regression tests from §3.

## 7. Reproduction

```bash
pip install -r requirements-dev.txt          # into .venv/
python tools/build_stubs.py .venv /tmp/stublibs   # headless Qt, no GL/X11/NSS

export QT_QPA_PLATFORM=offscreen LD_LIBRARY_PATH=/tmp/stublibs
.venv/bin/python -m pytest tests -q \
  --deselect=tests/test_sash_webengine.py::TestSashWebEngine::test_grid_in_real_webengine
for f in tests/test_*.js; do node "$f"; done

.venv/bin/python tools/metrics/rule16_gate.py --with-clones   # exit 0
.venv/bin/python tools/metrics/current_audit.py > audit.json  # §5 table
```
