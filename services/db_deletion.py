"""Deletion plan / inventory / path policy / bounded helpers (AREA A).

Public face of the `db_deletion_*` family. The implementation lives in the five
siblings below; this file re-exports it so that both existing import styles keep
working unchanged — `from services.db_deletion import ...` and the
`db_deletion.<name>` attribute access used by `db_deletion_scan` and
`db_registry`.

    db_deletion_paths       canonical(), is_within(), is_same_file()
    db_deletion_inventory   what exists on disk
    db_deletion_plan        what a deletion would touch
    db_deletion_policy      what is safe to unlink
    db_deletion_exec        bounded unlink / rmdir, and DeletionOutcome

Import direction is one-way down that list, and nothing in the family imports
this shim, so it cannot close a cycle. No framework, no generic transaction
abstraction, no new dependency.
"""

from __future__ import annotations

from services.db_deletion_exec import (  # noqa: F401  (re-exported: the seam)
    DeletionOutcome, prune_empty_dirs, unlink_one)
from services.db_deletion_inventory import (  # noqa: F401
    DeletionInventory, build_deletion_inventory)
# Re-exported although private: `db_registry` reaches it as
# `db_deletion._append_db_files`. Keeping the name here preserves that call site
# unchanged; making it properly public is tracked separately (Round F, step F1b).
from services.db_deletion_inventory import (  # noqa: F401  # pylint: disable=unused-import
    _append_db_files)
from services.db_deletion_paths import (  # noqa: F401
    canonical, is_same_file, is_within)
from services.db_deletion_plan import (  # noqa: F401
    DeletionPlan, collect_discovered_files)
from services.db_deletion_policy import (  # noqa: F401
    classify_candidate, plan_deletion)

#: SQLite file group members removed on delete. `SUFFIXES` in db_service
#: stays ("","-wal","-shm") for size/compat; deletion also best-effort
#: removes a rollback-journal sibling when present.
DB_GROUP_SUFFIXES = ("", "-wal", "-shm", "-journal")

SUPPORTED_BOUNDARY = (
    "active folder scan + active file + victim-directory scan + "
    "remembered in-root .db paths (deduped). Worlds outside this boundary "
    "are NOT scanned and NOT protected."
)

__all__ = [
    "DB_GROUP_SUFFIXES", "SUPPORTED_BOUNDARY",
    "DeletionInventory", "DeletionOutcome", "DeletionPlan",
    "build_deletion_inventory", "canonical", "classify_candidate",
    "collect_discovered_files", "is_same_file", "is_within",
    "plan_deletion", "prune_empty_dirs", "unlink_one",
]
