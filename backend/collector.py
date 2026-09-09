"""Collector shim — composes <150 parts (was 776)."""
from .collector_parts.base import CollectorBase, CollectorState, DEFAULTS, IDLE_STATES, MAX_PROBE_PENALTY
from .collector_parts.mixin1 import CollectorMixin1
from .collector_parts.mixin2 import CollectorMixin2
from .collector_parts.mixin3a import CollectorMixin3a
from .collector_parts.mixin3b import CollectorMixin3b
from .collector_parts.mixin3c import CollectorMixin3c
from .collector_parts.mixin3d import CollectorMixin3d
from .collector_parts.mixin4a import CollectorMixin4a
from .collector_parts.mixin4b import CollectorMixin4b
from .collector_parts.mixin5 import CollectorMixin5
class Collector(CollectorMixin1, CollectorMixin2, CollectorMixin3a, CollectorMixin3b, CollectorMixin3c, CollectorMixin3d, CollectorMixin4a, CollectorMixin4b, CollectorMixin5, CollectorBase):
    """Non-blocking monitor — composed from <150 mixins, reusable without Qt."""
    pass
__all__ = ["Collector", "CollectorState", "DEFAULTS", "IDLE_STATES", "MAX_PROBE_PENALTY"]
