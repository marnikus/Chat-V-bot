# Logic-duplication inventory — Round I

Measured tree-wide, not just in the gate's scoped packages:

```
pylint --disable=all --enable=R0801 core actions backend bridge services stores app main.py
```

| Point in Round I | R0801 pairs |
|---|---|
| I0 baseline | 10 |
| after I2 (the two the audit named) | 8 |
| after I6 | **4** |

The audit's F4 covered only the two pairs inside `backend/ bridge/`. Widening
the scan to all eight production packages found eight more; six are now gone
and the four survivors are argued below rather than left unexplained.

## Removed in I6

| Pair | Resolution |
|---|---|
| `bridge/label_bridge.py` ↔ `services/undo_apply.py` — `_values_equal` | `undo_apply` already OWNED this comparison (`router.py` injects it into other bridges as `_values_equal`/`_stacks_equal`). `label_bridge` had re-implemented it byte-for-byte; it now delegates. Two copies of "is this the same edit" can disagree about whether an edit is worth recording. |
| `services/preset_io.py` ↔ `stores/atomic.py` — temp-file cleanup | Extracted as `stores.atomic.discard_temp`, with the rule written down: a failure to clean up must not mask the original error. `stores` is the right owner — `services` imports `stores` one-way. |
| `stores/jsonio.py` — a **third** copy of the same cleanup | Found only after the first fix shifted it into view. Also delegates to `discard_temp`. |
| `actions/click_user.py` ↔ `backend/visual_click.py` — probe-JSON parsing | `visual_click` already owned probe reading and `click_user` already imported from it. `_parse` became the public `parse_probe_json`, documenting that "unusable" folds three cases (nothing back, not JSON, not an object) the callers all treat alike. |
| `services/run/coordinator.py` ↔ `services/run/queue.py` — the `UserRecord` import shim | The optional-import fallback existed twice in one package, so a missing `stores.user_memory` would have produced **two different `UserRecord` classes in one process**. `queue` owns it (coordinator already imports queue); coordinator re-exports. |
| — | Removing the shim stranded `dataclass`, `datetime` and `RunTracer` imports in `coordinator.py`; all three were dead and are deleted (RULE 16.2). |

## The 4 that remain, and why

| Pair | Verdict |
|---|---|
| `actions/click_back` ↔ `actions/click_main_tab` (span 14) | **Structural, keep.** Two sibling action blocks declaring the same *configuration surface* — `find_defaults`, `FIELDS = tab_fields()`, and a constructor of defaults. The shared logic was already extracted in G7 (`actions.base.tab_fields()`); what pylint sees now is the declaration of two different blocks' defaults. Merging them would mean one block class pretending to be two, which RULE 3 forbids: a block's `__init__` signature IS its preset wire format. |
| `services/run/__init__` ↔ `services/run_service/__init__` (span 9) | **Deliberate, keep.** `run_service` is the compatibility alias for `run`; the duplicated lines are the `__all__` list that makes the two names export the same surface. Deriving one from the other would make the alias's surface invisible to readers and to `dump_public_api.py`. |
| `services/db_deletion_pre` ↔ `services/db_deletion_scan` ×2 (spans 5, 5) | **Intentional double-check, keep.** These are the same verification run at two different points either side of H2's irreversible boundary: `scan` enumerates worlds and media *before* anything is touched, `pre` RE-verifies both *after* handles are detached and immediately before deletion. The wording differs accordingly ("cannot verify" vs "cannot re-verify"). Collapsing them into one call site would delete the second check, which is the one that catches a world appearing during detach. |

None of the four is a case of the same *decision* written twice, which is what
R0801 is worth acting on. They are recorded here so a later round can tell
"considered and kept" from "not yet looked at".
