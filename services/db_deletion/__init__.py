"""The fail-closed permanent-deletion family, in one package.

Four modules grew as one cohesive family and were promoted to a package
(2026-09-12, god-class round step 2): the pure path/inventory/plan/policy
helpers (``db_deletion.py``), the mutating pipeline (``db_deletion_flow.py``),
the read-only scan half (``db_deletion_scan.py``) and the strict media scan
(``db_media_scan.py``). Import order is a DAG:

    constants → paths → (inventory, plan, files, outcome)
              → state → media → scan → flow

``flow`` and ``scan`` keep calling the patch-sensitive helpers
(``build_deletion_inventory``, ``canonical``, ``is_within``,
``prune_empty_dirs``, …) through this package, so the safety tests that patch
``services.db_deletion.<name>`` keep landing on the code that runs.

The names re-exported below are the frozen seam: `db_lifecycle`
(``delete_world``), `db_registry` (``_append_db_files``), and
`tests/integration/safety_deletion/` (the public helpers) all import them
from this package.
"""

from __future__ import annotations

from .constants import DB_GROUP_SUFFIXES, SUPPORTED_BOUNDARY
from .files import prune_empty_dirs, unlink_one
from .inventory import (DeletionInventory, _append_db_files, _dedup,
                        build_deletion_inventory)
from .media import MediaScanResult, scan_world_media, sqlite_ro_uri
from .outcome import DeletionOutcome
from .paths import (abspath_or_none, canonical, is_same_file, is_within,
                    lexists, same_canonical)
from .plan import (DeletionPlan, classify_candidate, collect_discovered_files,
                   plan_deletion)
from .state import _DeleteState, _Fail, _PhaseRefusal, observed_active, \
    raise_refusal
from .flow import delete_world
from .scan import run_scan

__all__ = [
    "DB_GROUP_SUFFIXES",
    "SUPPORTED_BOUNDARY",
    "DeletionInventory",
    "DeletionOutcome",
    "DeletionPlan",
    "MediaScanResult",
    "build_deletion_inventory",
    "canonical",
    "classify_candidate",
    "collect_discovered_files",
    "delete_world",
    "is_same_file",
    "is_within",
    "plan_deletion",
    "prune_empty_dirs",
    "run_scan",
    "scan_world_media",
    "sqlite_ro_uri",
    "unlink_one",
]
