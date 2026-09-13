"""`HistoryQuery` — the facade over the three read surfaces.

The class composes three single-responsibility mixins (paging / search /
userdb); it owns only construction and the two SQL fragments the mixins
share. See `docs/archive/2026-09-12-god-classes/STEP5_HISTORY_QUERY_DESIGN_2026-09-12.md`.
"""

from __future__ import annotations

from stores.history_db import HistoryDB

from .paging import PagingMixin
from .search import SearchMixin
from .userdb import UserDbMixin


class HistoryQuery(PagingMixin, SearchMixin, UserDbMixin):
    """Every read the UI performs against the archive."""

    def __init__(self, db: HistoryDB):
        self.db = db

    _SELECT = ("SELECT m.*, md.url AS media_url, md.kind AS media_kind, "
               "md.state AS media_state, md.cache_path AS cache_path "
               "FROM messages m LEFT JOIN media md ON md.id = m.media_id ")
    #: soft-deleted rows are invisible to every read (they exist only so a
    #: single Ctrl+Z can bring them back)
    _COUNT_ALIVE = ("SELECT COUNT(*) FROM messages WHERE person_id=? AND "
                    "deleted_at=''")
