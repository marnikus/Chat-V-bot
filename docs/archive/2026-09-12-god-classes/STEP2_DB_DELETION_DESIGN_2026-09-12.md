# Step 2 — split the deletion family into `services/db_deletion/`

Done 2026-09-12. Target: the second-largest cohesive debt cluster after
`chat_sync` — the four deletion modules that grew as one family
(`services/db_deletion.py` 665 LOC + `db_deletion_flow.py` 509 +
`db_deletion_scan.py` 216 + `db_media_scan.py` 232 = **1 622 LOC**). The
baseline already describes them as a family (`AGENT_RULES.md` RULE 19 §19.4
cites `services/db_deletion*`), but they were never promoted to a package.

## Why these four are one step

They are a §16.5 landmine ("need a design doc before quickly fixing"): the
fail-closed permanent-delete pipeline, pinned bit-for-bit by
`tests/integration/safety_deletion/`. The four files already import each other
along a one-directional seam (`flow` → `scan` → `deletion`; `deletion` → pure
helpers), so the split is a relocation of an already-separated family — same
shape as step 1, same low risk, but with a patch-target contract to preserve
(detailed below).

## The split

| Module | Owns | LOC |
|---|---:|---:|
| `constants.py` | `DB_GROUP_SUFFIXES`, `SUPPORTED_BOUNDARY` | ~25 |
| `paths.py` | `canonical`, `is_within`, `is_same_file`, `lexists`, `abspath_or_none`, `same_canonical` | ~120 |
| `inventory.py` | `DeletionInventory`, `_InventoryCollector`, `build_deletion_inventory`, `_append_db_files` | ~180 |
| `plan.py` | `DeletionPlan`, `collect_discovered_files`, the retain-reason predicates, `classify_candidate`, `plan_deletion` | ~270 |
| `files.py` | `unlink_one`, `prune_empty_dirs` (the bounded filesystem helpers) | ~90 |
| `outcome.py` | `DeletionOutcome`, `_as_list` | ~70 |
| `state.py` | `_PhaseRefusal`, `_Fail`, `_DeleteState`, `raise_refusal`, `observed_active` | ~90 |
| `media.py` | `MediaScanResult`, `sqlite_ro_uri`, `scan_world_media` (was `db_media_scan.py`) | 234 |
| `scan.py` | `run_scan` and the read-only phases (was `db_deletion_scan.py`) | 216 |
| `flow.py` | `delete_world` and the mutating phases (was `db_deletion_flow.py`) | 413 |
| `__init__.py` | the frozen public + internal seam (re-exports) | 60 |

`flow.py` is the one file over the 300-line ideal (§18.2): it is a single
responsibility — the fail-closed pipeline, one small function per phase — and
the phases share one `_DeleteState` plus the refusal seam, so splitting further
would fragment one decision across files (the anti-pattern §19.4 names). It
shrank 509 → 413 and is recorded as accepted debt, not grown.

Import order is a DAG: `constants → paths → (inventory, plan, files, outcome)
→ state → media → scan → flow`, with `__init__` at the top re-exporting.

## The patch-target contract (the one risk)

Three safety tests inject faults by patching `services.db_deletion.*`. The
split must keep those patches landing on the code that actually runs:

1. `test_cancel_concurrency.py` patches
   `services.db_deletion.build_deletion_inventory` and expects `flow`'s
   revalidation to see it. **Preserved:** `flow.py` keeps
   `from services import db_deletion` and calls `db_deletion.build_deletion_inventory(...)`
   at runtime (attribute lookup on the package), exactly as it does today.
2. `test_deletion_unit.py` patches `services.db_deletion.canonical` and calls
   `is_within`/`is_same_file`. Those two live *next to* `canonical` in
   `paths.py` and call it locally, so their two patch targets move to
   `services.db_deletion.paths.canonical`. Intent unchanged.
3. `test_deletion_defensive.py` patches `services.db_deletion.canonical`
   (`mock.patch.object(D, "canonical")`) and expects `_dedup`,
   `build_deletion_inventory`, `classify_candidate` and `prune_empty_dirs` to
   see it. **Preserved** by making `inventory.py` / `plan.py` / `files.py`
   call `db_deletion.canonical(...)` through the package (the same seam
   `flow`/`scan` already used) instead of binding it at import time — so those
   nine patch sites land unchanged. `paths.py` stays self-contained: its own
   `is_within`/`is_same_file` reference the local `canonical`.
4. `test_scan_unit.py` patches `os.path.getsize` / `aiosqlite.connect`
   (global names, not module attributes) — unaffected by the move.

`db_registry.py` already calls `db_deletion._append_db_files` through the
package seam; `db_lifecycle.py`'s function-local `from services.db_deletion_flow
import delete_world` becomes `from services.db_deletion import delete_world`.

## Honest reductions rejected

* Did **not** merge `plan.py`'s policy back into `inventory.py` to cut a file
  — inventory (what worlds exist) and policy (what may be removed) are two
  responsibilities with two different test suites.
* Did **not** rename the patch-sensitive public names to avoid touching tests
  — the test edits are one-line path changes, not behaviour changes.

## Verification

* `tests/integration/safety_deletion/` — the whole 18-file suite passes.
* `tests/test_db_manager*.py`, `test_db_unified_world.py`, `test_db_switch_*` —
  pass.
* `radon cc -s services/db_deletion/` — every function ≤ 10.
* `tools/metrics/rule16_gate.py` — "All owned functions fit."
* `dump_public_api --diff` / stores import count — unchanged (no `backend`/
  `actions`/`stores` surface touched).
