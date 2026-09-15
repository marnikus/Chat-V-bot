"""PersonPageRequest — the Full User Database request value.

Part of the `history_query` family (facade: `backend/history_query.py`,
Round H step H-B2b). This file owns the request value object and the
sortable-columns whitelist that guards ORDER BY.

Design: docs/archive/2026-09-14-round-h/AREA_H_FINAL_VALIDATION_2026-09-14.md §6.1
"""

from __future__ import annotations

from dataclasses import dataclass

from backend.history_query_search import _like_escape

DEFAULT_LIMIT = 50
MAX_LIMIT = 500

#: The Full User Database's sortable columns — key → the columns it orders
#: by, each with its **natural** direction: what a first click on that header
#: gives, and what every caller that sends no `dir` gets.
#:
#: This dict IS the whitelist. A `sort` that is not a key here falls back to
#: ``DEFAULT_SORT``, so no request text can ever reach `ORDER BY` — the same
#: discipline `_like_escape` / `_fts_query` apply to the search paths.
SORT_COLUMNS: dict[str, tuple[tuple[str, str], ...]] = {
    "nick": (("nick_lc", "ASC"),),
    "msgs": (("message_count", "DESC"), ("last_seen", "DESC")),
    "media": (("media_count", "DESC"), ("last_seen", "DESC")),
    "first": (("first_seen", "ASC"),),
    "last": (("last_seen", "DESC"), ("message_count", "DESC")),
    "my_nick": (("my_nicks", "ASC"),),
    "messages": (("message_count", "DESC"), ("last_seen", "DESC")),
    "recent": (("last_seen", "DESC"), ("message_count", "DESC")),
}
DEFAULT_SORT = "recent"
SORT_TIEBREAK: tuple[str, ...] = ("nick_lc", "id")


@dataclass(frozen=True)
class PersonPageRequest:
    """One request for a page of the Full User Database."""

    q: str = ""
    limit: int = DEFAULT_LIMIT
    offset: int = 0
    sort: str = DEFAULT_SORT
    dir: str = ""
    include_deleted: bool = False

    def needle(self) -> str:
        return str(self.q or "").strip().lower()

    def spec(self) -> tuple[tuple[str, str], ...]:
        return SORT_COLUMNS.get(str(self.sort or ""), SORT_COLUMNS[DEFAULT_SORT])

    def resolved_dir(self) -> str:
        asked = self._asked_dir()
        if asked:
            return asked
        return self.spec()[0][1].lower()

    def where(self) -> tuple[str, list]:
        clause = "1=1" if self.include_deleted else "deleted_at IS NULL"
        needle = self.needle()
        if not needle:
            return clause, []
        return (clause + " AND nick_lc LIKE ? ESCAPE '\\'",
                ["%" + _like_escape(needle) + "%"])

    def order(self) -> tuple[str, list]:
        body = self.columns()
        needle = self.needle()
        if not needle:
            return body, []
        return ("(nick_lc LIKE ? ESCAPE '\\') DESC, "
                f"LENGTH(nick_lc) ASC, {body}",
                [_like_escape(needle) + "%"])

    def _asked_dir(self) -> str:
        asked = str(self.dir or "").strip().lower()
        return asked if asked in ("asc", "desc") else ""

    def columns(self) -> str:
        asked = self._asked_dir()
        parts = [f"{column} {asked.upper() if asked else natural}"
                 for column, natural in self.spec()]
        used = {column for column, _ in self.spec()}
        parts += [f"{column} ASC"
                  for column in SORT_TIEBREAK if column not in used]
        return ", ".join(parts)
