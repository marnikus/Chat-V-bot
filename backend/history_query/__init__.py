"""Read path of the message archive.

Feeds the two windows: chronological paging that stays stable while the
collector appends underneath, search inside one conversation and across the
whole archive, the master person list and the header counters.

Search has two interchangeable back-ends: FTS5 when SQLite offers it, a
`text_lc LIKE` scan when it does not. Both fold case for Cyrillic — the
`text_lc` column is lower-cased in Python, because SQLite's own LIKE folds
ASCII only.

## What each module owns, and which way the imports go

| Module | Owns | Imports from this package |
|---|---|---|
| `sorting.py` | paging limits, the `SORT_COLUMNS` whitelist, the tiebreak | — |
| `sqltext.py` | LIKE escaping, the FTS5 query builder, snippets | `sorting` |
| `request.py` | `PersonPageRequest` and the SQL fragments it builds | `sorting`, `sqltext` |
| `rows.py` | one database row → one UI item; field-spec tables | — |
| `query.py` | `HistoryQuery` — every read that touches the database | all of the above |

Imports only ever point *down* that table.

## Why the class was not split (Round G, step G3)

The module was 603 lines at maintainability index 35.4, and `HistoryQuery` was
310 LOC — but its LCOM is 0.74 across fourteen methods that all read `self.db`
and share the `_SELECT` / `_COUNT_ALIVE` fragments. That cohesion is real, so
splitting the class by line count would have raised coupling to lower a number
— exactly what the audit warned about when it ranked `SchemaMigrator` (406 LOC,
LCOM 0.12) as *not* a target.

What moved instead is everything that does **not** touch the database: the
constants, the text escaping, the request object and the row shaping. Each is
now importable and testable without a database, and `query.py` shrank to 338
lines by losing only code that never belonged to the reading.

**The rule that keeps the contract:** this `__init__` re-exports the module's
previous public surface verbatim. Split the file, keep the front door.
"""

from __future__ import annotations

from backend.history_query.query import HistoryQuery
from backend.history_query.request import PersonPageRequest
from backend.history_query.rows import (_apply_specs, _day_bounds, _item_media,
                                        _person_item, _stat_int)
from backend.history_query.sorting import (DEFAULT_LIMIT, DEFAULT_SORT,
                                           MAX_LIMIT, SNIPPET_RADIUS,
                                           SORT_COLUMNS, SORT_TIEBREAK)
from backend.history_query.sqltext import _fts_query, _like_escape, _snippet

__all__ = [
    "DEFAULT_LIMIT", "DEFAULT_SORT", "MAX_LIMIT", "SNIPPET_RADIUS",
    "SORT_COLUMNS", "SORT_TIEBREAK", "HistoryQuery", "PersonPageRequest",
]
