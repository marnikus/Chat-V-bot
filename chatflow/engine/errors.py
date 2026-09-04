"""Engine error types."""
from __future__ import annotations


class OpError(Exception):
    """A guarded Playwright operation failed (element missing, timeout…)."""


class StopRequested(Exception):
    """User pressed STOP; long operations must unwind."""


class NoTarget(Exception):
    """pick_target found an empty queue."""
