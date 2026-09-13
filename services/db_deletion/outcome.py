"""`DeletionOutcome` — the result dict shape of the delete pipeline.

Pinned bit-for-bit by `tests/integration/safety_deletion/`; `as_dict()` is
the wire contract the bridge and tests read. Imports nothing from the
package (it is a leaf).
"""

from __future__ import annotations

from dataclasses import dataclass, field


def _as_list(value) -> list:
    """List copy of an outcome field (None-safe; outcomes default to lists)."""
    return list(value or [])


@dataclass
class DeletionOutcome:
    ok: bool
    phase: str  # validate | scan | switch | detach | database | media | finalize
    error: str = ""
    partial: bool = False
    world_changed: bool = False
    active_path: str = ""
    removed_paths: list = field(default_factory=list)
    retained_paths: list = field(default_factory=list)
    failed_paths: list = field(default_factory=list)
    media_files_removed: int = 0
    # compat
    op: str = "delete"
    path: str = ""
    was_active: bool = False
    before_path: str = ""
    extra: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        d = {
            "ok": bool(self.ok),
            "op": self.op or "delete",
            "path": self.path,
            "was_active": bool(self.was_active),
            "before_path": self.before_path or self.path,
            "media_files_removed": int(self.media_files_removed or 0),
            "phase": self.phase,
            "partial": bool(self.partial),
            "world_changed": bool(self.world_changed),
            "active_path": self.active_path,
            "removed_paths": _as_list(self.removed_paths),
            "retained_paths": _as_list(self.retained_paths),
            "failed_paths": _as_list(self.failed_paths),
        }
        if self.error:
            d["error"] = self.error
        # Preserve last_database flag and diagnostics when present.
        if self.extra:
            for k, v in self.extra.items():
                if k not in d:
                    d[k] = v
        return d
