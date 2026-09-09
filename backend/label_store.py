"""User labels — backward-compat shim over stores/.

Canonical implementation: :mod:`stores.label_store` (see BUG-02 in
``docs/ACTIONS_TEST_DESIGN_2026-09-09.md`` §12). New code imports from
``stores``; this module re-exports the public surface.
"""

from stores.label_store import PALETTE, LabelStore  # noqa: F401

__all__ = ["LabelStore", "PALETTE"]
