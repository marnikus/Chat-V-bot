"""HistoryService shim — composes <150 parts (was 867)."""
from .history_parts.base import HistoryServiceBase, HISTORY_DEFAULTS, OLD_MAX_FILE_MB, MAX_FILE_MB_DEFAULT, SETTING_KEYS, _merge, _db_stem
from .history_parts.settings_mixin import HistorySettingsMixin
from .history_parts.persistence_mixin import HistoryPersistenceMixin
from .history_parts.lifecycle_mixin import HistoryLifecycleMixin
from .history_parts.world_a_mixin import HistoryWorldAMixin
from .history_parts.world_b_mixin import HistoryWorldBMixin
from .history_parts.undo_query_mixin import HistoryUndoQueryMixin
class HistoryService(HistorySettingsMixin, HistoryPersistenceMixin, HistoryLifecycleMixin, HistoryWorldAMixin, HistoryWorldBMixin, HistoryUndoQueryMixin, HistoryServiceBase):
    """One DB = one world — composed from <150 mixins, reusable without Qt."""
    pass
__all__ = ["HistoryService", "HISTORY_DEFAULTS", "OLD_MAX_FILE_MB", "MAX_FILE_MB_DEFAULT", "SETTING_KEYS", "_merge", "_db_stem"]
