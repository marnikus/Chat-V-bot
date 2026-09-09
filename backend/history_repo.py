"""HistoryRepo shim — composes <150 parts (was 1217)."""
from .history_repo_parts.helpers import align_batch, resolve_days, _minutes, _as_record
from .history_repo_parts.base import HistoryRepoBase
from .history_repo_parts.mixin1 import HistoryRepoMixin1
from .history_repo_parts.mixin2a import HistoryRepoMixin2a
from .history_repo_parts.mixin2b import HistoryRepoMixin2b
from .history_repo_parts.mixin3a import HistoryRepoMixin3a
from .history_repo_parts.mixin3b import HistoryRepoMixin3b
from .history_repo_parts.mixin3c import HistoryRepoMixin3c
from .history_repo_parts.mixin4 import HistoryRepoMixin4
from .history_repo_parts.mixin5a import HistoryRepoMixin5a
from .history_repo_parts.mixin5b import HistoryRepoMixin5b
from .history_repo_parts.mixin5c import HistoryRepoMixin5c
from .history_repo_parts.mixin6 import HistoryRepoMixin6
from .history_repo_parts.mixin7a import HistoryRepoMixin7a
from .history_repo_parts.mixin7b import HistoryRepoMixin7b
class HistoryRepo(HistoryRepoMixin1, HistoryRepoMixin2a, HistoryRepoMixin2b, HistoryRepoMixin3a, HistoryRepoMixin3b, HistoryRepoMixin3c, HistoryRepoMixin4, HistoryRepoMixin5a, HistoryRepoMixin5b, HistoryRepoMixin5c, HistoryRepoMixin6, HistoryRepoMixin7a, HistoryRepoMixin7b, HistoryRepoBase):
    """Archive repo — composed from <150 mixins, reusable without Qt."""
    pass
__all__ = ["HistoryRepo", "align_batch", "resolve_days"]
