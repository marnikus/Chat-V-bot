"""HistoryDB shim — composes <150 parts (was 746)."""
from .history_db_parts.helpers import _create_table_sql, _version_tuple
from .history_db_parts.mixin1 import HistoryDBMixin1
from .history_db_parts.mixin2a import HistoryDBMixin2a
from .history_db_parts.mixin2b import HistoryDBMixin2b
from .history_db_parts.mixin3 import HistoryDBMixin3
from .history_db_parts.mixin4 import HistoryDBMixin4
class HistoryDB(HistoryDBMixin1, HistoryDBMixin2a, HistoryDBMixin2b, HistoryDBMixin3, HistoryDBMixin4):
    """HistoryDB — composed from <150 mixins, reusable without Qt."""
    pass
__all__ = ["HistoryDB", "_create_table_sql", "_version_tuple"]
