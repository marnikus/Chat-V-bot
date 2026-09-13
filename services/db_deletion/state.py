"""The deletion run's shared state and the refusal signal.

`_DeleteState` is the mutable state carried through one deletion run.
`raise_refusal` builds the standard failure outcome for a phase and stops the
pipeline via `_PhaseRefusal`, caught once in `flow.delete_world`.

Imports `outcome` (DeletionOutcome) only — a leaf above `flow`/`scan`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .outcome import DeletionOutcome


class _PhaseRefusal(Exception):
    """Internal signal: stop the pipeline and return ``outcome``."""

    def __init__(self, outcome: dict):
        super().__init__(outcome.get("error", ""))
        self.outcome = outcome


@dataclass
class _Fail:
    """Optional overrides for a failure outcome (a plain refusal needs none)."""

    partial: bool = False
    media_count: int | None = None
    extra: dict | None = None
    path: str | None = None
    before_path: str | None = None
    was_active: bool | None = None


@dataclass
class _DeleteState:
    """Mutable state carried through one deletion run."""

    path: str
    registry: object = None
    target: str = ""
    target_abs: str = ""
    was_active: bool = False
    world_changed: bool = False
    plan: object = None
    plan_retained: set = field(default_factory=set)
    base_abs: str = ""
    victim_folder_abs: str = ""
    folder_exclusive: bool = False
    other_folders: set = field(default_factory=set)
    keep: set = field(default_factory=set)
    footprint: set = field(default_factory=set)
    outside_refs: set = field(default_factory=set)
    keep_snapshot: frozenset = frozenset()
    inventory_snapshot: tuple = ()
    removed: list = field(default_factory=list)
    failed: list = field(default_factory=list)
    media_removed: list = field(default_factory=list)
    irreversible_started: bool = False


def observed_active(registry) -> str:
    """Read the current active path defensively ('' if the registry raises)."""
    try:
        return registry.active_path()
    except Exception:  # noqa: BLE001
        return ""


def raise_refusal(st: _DeleteState, phase: str, error: str,
                  opt: _Fail | None = None) -> None:
    """Build the standard failure outcome for ``phase`` and stop the run."""
    opt = opt or _Fail()
    outcome = DeletionOutcome(
        ok=False, phase=phase, error=error, partial=opt.partial,
        world_changed=st.world_changed,
        active_path=observed_active(st.registry),
        removed_paths=list(st.removed),
        retained_paths=sorted(st.plan_retained),
        failed_paths=list(st.failed),
        media_files_removed=(len(st.media_removed)
                             if opt.media_count is None else opt.media_count),
        path=(st.target if opt.path is None else opt.path),
        before_path=(st.target if opt.before_path is None
                     else opt.before_path),
        was_active=(st.was_active if opt.was_active is None
                    else opt.was_active),
        extra=opt.extra or {})
    raise _PhaseRefusal(outcome.as_dict())
