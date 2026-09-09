"""Per-DB media files — backward-compat shim over stores/.

Canonical implementation: :mod:`stores.media_store` (see BUG-02 in
``docs/ACTIONS_TEST_DESIGN_2026-09-09.md`` §12). New code imports from
``stores``; this module re-exports the public surface.
"""

from stores.media_store import MediaStore, slugify_nick  # noqa: F401

__all__ = ["MediaStore", "slugify_nick"]
