"""`PersonPageRequest` — one request for a page of the Full User Database.

Owns the parameter object that replaced six positional arguments on
`HistoryQuery.list_persons`, together with the SQL fragments it knows how to
build for itself (`where`, `order`, `columns`). Pure: it reads no database.
"""

from __future__ import annotations

from dataclasses import dataclass

from backend.history_query.sorting import (DEFAULT_LIMIT, DEFAULT_SORT,
                                           SORT_COLUMNS, SORT_TIEBREAK)
from backend.history_query.sqltext import _like_escape

@dataclass(frozen=True)
class PersonPageRequest:
    """

from __future__ import annotations
One request for a page of the Full User Database.

    The UI sends these six options together in a single JSON blob, so they
    travel together: one frozen value instead of six parameters. Freezing it
    also means a request cannot be mutated between the bridge and the
    database, which makes a mismatched page impossible to explain away.

    The methods here own the SQL fragments, and none of them is built from
    request text — columns and directions are looked up in `SORT_COLUMNS`, and
    the nick is always a bound parameter.
    """

    q: str = ""
    limit: int = DEFAULT_LIMIT
    offset: int = 0
    sort: str = DEFAULT_SORT
    dir: str = ""
    include_deleted: bool = False

    # ── the pieces the caller asks about ────────────────────────

    def needle(self) -> str:
        """The lower-cased, trimmed search text — empty means 'no filter'."""
        return str(self.q or "").strip().lower()

    def spec(self) -> tuple[tuple[str, str], ...]:
        """The whitelisted columns for this key (the default if unknown)."""
        return SORT_COLUMNS.get(str(self.sort or ""),
                                SORT_COLUMNS[DEFAULT_SORT])

    def resolved_dir(self) -> str:
        """`"asc"` / `"desc"` — the direction actually applied.

        An empty (or unrecognised) `dir` means *the key's natural direction*,
        the direction of its first column. Reporting the resolved value back
        is what lets the header show the right arrow without duplicating
        `SORT_COLUMNS` in JavaScript.
        """
        asked = self._asked_dir()
        if asked:
            return asked
        return self.spec()[0][1].lower()

    # ── the SQL fragments ───────────────────────────────────────

    def where(self) -> tuple[str, list]:
        """The row filter and its parameters (nick bound, wildcards escaped)."""
        clause = "1=1" if self.include_deleted else "deleted_at IS NULL"
        needle = self.needle()
        if not needle:
            return clause, []
        return (clause + " AND nick_lc LIKE ? ESCAPE '\\'",
                ["%" + _like_escape(needle) + "%"])

    def order(self) -> tuple[str, list]:
        """The `ORDER BY` body and its parameters.

        While searching, relevance stays outermost: an exact prefix outranks a
        longer nick that merely contains the needle, and among equally good
        matches the shorter nick wins. Inside a tier the chosen column
        decides.

        The prefix-boost `LIKE` is a literal prefix, so its parameter differs
        from the `where()` one — callers bind this list *after* the where
        parameters.
        """
        body = self.columns()
        needle = self.needle()
        if not needle:
            return body, []
        return ("(nick_lc LIKE ? ESCAPE '\\') DESC, "
                f"LENGTH(nick_lc) ASC, {body}",
                [_like_escape(needle) + "%"])

    # ── internals ───────────────────────────────────────────────

    def _asked_dir(self) -> str:
        """The requested direction when it is a usable one, else `""`."""
        asked = str(self.dir or "").strip().lower()
        return asked if asked in ("asc", "desc") else ""

    def columns(self) -> str:
        """The `ORDER BY` column list — whitelist only, tiebreaker included.

        An explicit direction flips **every** column of the key, so the
        secondary column stays consistent with the primary one (`msgs`
        descending = busiest first, and among equals the *oldest* activity
        last).
        """
        asked = self._asked_dir()
        parts = [f"{column} {asked.upper() if asked else natural}"
                 for column, natural in self.spec()]
        used = {column for column, _ in self.spec()}
        parts += [f"{column} ASC"
                  for column in SORT_TIEBREAK if column not in used]
        return ", ".join(parts)
