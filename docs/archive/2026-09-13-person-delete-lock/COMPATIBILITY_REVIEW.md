# Validation refinements (2026-09-13)

The first full run exposed two compatibility constraints; neither test was relaxed.

* A legacy users table can lack UNIQUE(nick) before world migration. SQLite's
  targeted ON CONFLICT(nick) requires that index and failed the real migration
  test. Use a single INSERT ... SELECT ... WHERE NOT EXISTS instead: it works
  before migration, remains one SQLite write statement, and does not suppress
  NOT NULL/other constraint failures. The serialized queue writer still covers
  discovery and full replacements. New/known and metadata semantics are unchanged.
* The stores package has an existing 36-file cohesion ceiling. The first placement
  of two short support modules exceeded it. Both helpers are used by exactly one
  owner, so keep them as private implementations beside those owners:
  `_serialized_write` in stores/user_memory.py and `_HistoryAccess` in
  stores/history_db.py. No new package files, public API, changed baseline or
  hidden subpackage was introduced to evade the gate.

Cancellation while cursor acquisition is still pending also needs ownership:
shield acquisition, reap/close its cursor on cancellation, and only then release
statement access. A deterministic cancellation regression failed before this
cleanup was added. Normal reads close in finally; cancellation still propagates.

These refinements supersede the initial helper filenames/UPSERT spelling in the
preceding design notes. Successful commits remain with existing mutation owners;
there is no autocommit or SQLite schema change. HistoryDB is 306 physical lines
(6 above the RULE 18 preference); keeping its small private access owner beside
its lifecycle/schema facade is preferable to exceeding the module-file budget.
The legacy HistoryDB/UserMemory class spans do not grow, and hard gates still fit.
