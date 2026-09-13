"""Read path of the message archive.

Feeds the two new windows: chronological paging that stays stable while the
collector appends underneath, search inside one conversation and across the
whole archive, the master person list and the header counters.

Search has two interchangeable back-ends: FTS5 when SQLite offers it, a
`text_lc LIKE` scan when it does not. Both fold case for Cyrillic — the
`text_lc` column is lower-cased in Python, because SQLite's own LIKE folds
ASCII only.

The module was split by single responsibility in the god-class round, step 5
(`docs/archive/2026-09-12-god-classes/STEP5_HISTORY_QUERY_DESIGN_2026-09-12.md`).
This `__init__` re-exports the frozen seam other areas AND the tests import —
including the private helpers `_person_item`, `_fts_query` and `_like_escape`,
which the characterisation tests reach for by name.
"""

from .constants import (DEFAULT_LIMIT, DEFAULT_SORT, MAX_LIMIT, SNIPPET_RADIUS,
                        SORT_COLUMNS, SORT_TIEBREAK)
from .person import _person_item
from .query import HistoryQuery
from .request import PersonPageRequest
from .search_text import _fts_query, _like_escape, _snippet

__all__ = [
    "DEFAULT_LIMIT",
    "DEFAULT_SORT",
    "HistoryQuery",
    "MAX_LIMIT",
    "PersonPageRequest",
    "SNIPPET_RADIUS",
    "SORT_COLUMNS",
    "SORT_TIEBREAK",
    "_fts_query",
    "_like_escape",
    "_person_item",
    "_snippet",
]
