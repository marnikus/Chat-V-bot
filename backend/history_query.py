"""Read path of the message archive.

Feeds the two new windows: chronological paging that stays stable while the
collector appends underneath, search inside one conversation and across the
whole archive, the master person list and the header counters.

Search has two interchangeable back-ends: FTS5 when SQLite offers it, a
`text_lc LIKE` scan when it does not. Both fold case for Cyrillic — the
`text_lc` column is lower-cased in Python, because SQLite's own LIKE folds
ASCII only.

The two halves that are not the query surface live next door, split off in
Round H step H-B2 and Round J step J-2:

* `backend/history_query_search.py` — the FTS/LIKE back-end (`search`) and the
  request-text-to-SQL guards (`_fts_query` / `_like_escape` / `_snippet`);
* `backend/history_query_rows.py` — the row → payload projection
  (`person_item`, `item`, `item_media`, the field specs, the counters) and the
  three helpers the query methods share (`clamp`, `my_nicks`, `person_row`).

What stays here is what the archive services and the bridges call:
`PersonPageRequest`, `HistoryQuery` with page / around / gaps / the two search
entry points / list_persons / db_stats / person_stats, `SORT_COLUMNS` and the
limits. Those signatures are a frozen interface (Area B design §6).
"""

# ideal-size: the facade is the query surface the services and bridges call;
# the search back-end lives in history_query_search.py (H-B2a) and the row
# projection in history_query_rows.py (J-2), so this file holds the SQL of the
# paging / around / stats reads and nothing else.

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from stores.history_db import HistoryDB

from backend import history_query_reads as reads
from backend.history_query_search import _like_escape
from backend.history_query_rows import DEFAULT_LIMIT, MAX_LIMIT

# `DEFAULT_LIMIT` / `MAX_LIMIT` are imported, not redefined: `history_query_rows`
# owns them (it is the module that clamps), and every caller and test keeps
# importing them from here — the module the archive has always used. They are
# named in `__all__` because an import that exists to be imported *from* is
# not dead code (vulture reads `__all__`; RULE 16's smell check does not take
# prose for an answer).
__all__ = ["DEFAULT_LIMIT", "DEFAULT_SORT", "HistoryQuery", "MAX_LIMIT",
           "PersonPageRequest", "SORT_COLUMNS", "SORT_TIEBREAK"]

#: The Full User Database's sortable columns — key → the columns it orders
#: by, each with its **natural** direction: what a first click on that header
#: gives, and what every caller that sends no `dir` gets.
#:
#: This dict IS the whitelist. A `sort` that is not a key here falls back to
#: ``DEFAULT_SORT``, so no request text can ever reach `ORDER BY` — the same
#: discipline `_like_escape` / `_fts_query` apply to the search paths.
#:
#: `my_nicks` is a JSON array stored as text (`'["Me","Me2"]'`) and the column
#: shows it joined. Ordering the stored text needs no JSON1 extension (FTS5 is
#: already treated as optional here) and cannot fail on a hand-edited row; for
#: the common one-identity case it is exactly the displayed order. Known
#: wrinkle, pinned by a test: `["Me", "Old"]` sorts before `["Me"]`, because
#: `","` < `"]"`.
SORT_COLUMNS: dict[str, tuple[tuple[str, str], ...]] = {
    "nick": (("nick_lc", "ASC"),),
    "msgs": (("message_count", "DESC"), ("last_seen", "DESC")),
    "media": (("media_count", "DESC"), ("last_seen", "DESC")),
    "first": (("first_seen", "ASC"),),
    "last": (("last_seen", "DESC"), ("message_count", "DESC")),
    "my_nick": (("my_nicks", "ASC"),),
    # historical spellings, kept so payloads written before the header sort
    # existed keep meaning exactly what they meant
    "messages": (("message_count", "DESC"), ("last_seen", "DESC")),
    "recent": (("last_seen", "DESC"), ("message_count", "DESC")),
}
DEFAULT_SORT = "recent"

#: Appended to every order. `LIMIT ? OFFSET ?` over a *partial* order lets
#: SQLite re-shuffle the ties between two queries, so a person could be served
#: twice or never while the user scrolls. `nick` is unique, which makes the
#: resulting order total.
SORT_TIEBREAK: tuple[str, ...] = ("nick_lc", "id")


@dataclass(frozen=True)
class PersonPageRequest:
    """One request for a page of the Full User Database.

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


class HistoryQuery:
    """Every read the UI performs against the archive.

    The class is the frozen surface (Area B design §6): the archive services
    and the bridges call exactly these ten methods, and the API snapshot
    pins their signatures to this module. The SQL itself lives next door —
    paging / around / gaps / search / the counters in
    `history_query_reads.py`, the row projection in `history_query_rows.py`,
    the FTS-or-LIKE back-end in `history_query_search.py` — so each method
    here is one delegation, and what used to be this file's size problem is
    three testable modules.
    """

    def __init__(self, db: HistoryDB):
        self.db = db

    # ── paging (SQL in history_query_reads.py) ───────────────────
    async def page(self, nick: str, before_ord: Optional[int] = None,
                   after_ord: Optional[int] = None,
                   limit: int = DEFAULT_LIMIT) -> dict:
        """One screen of a conversation, oldest-first inside the page."""
        return await reads.page(self, nick, before_ord, after_ord, limit)

    async def around(self, nick: str, ord_: int, radius: int = 25) -> dict:
        """The page containing `ord_`, for the "jump to a search hit" path."""
        return await reads.around(self, nick, ord_, radius)

    async def gaps(self, person_id: int) -> list[dict]:
        """The collection gaps of one person, oldest first."""
        return await reads.gaps(self, person_id)

    # ── search ───────────────────────────────────────────────────
    async def search_person(self, nick: str, query: str,
                            limit: int = DEFAULT_LIMIT,
                            offset: int = 0) -> dict:
        """Search inside one conversation, newest first."""
        return await reads.search_person(self, nick, query, limit, offset)

    async def search_global(self, query: str, limit: int = 200,
                            per_person: int = 20) -> dict:
        """Search the whole archive, grouped per person, busiest first."""
        return await reads.search_global(self, query, limit, per_person)

    # ── the user database window ─────────────────────────────────
    async def list_persons(self, req: PersonPageRequest) -> dict:
        """One page of the Full User Database, in the order the header asks.

        `req` carries the six options the UI sends as one blob. The response
        echoes the sort key verbatim plus the *resolved* direction, so the UI
        paints the right arrow without duplicating `SORT_COLUMNS` in
        JavaScript.

        The COUNT binds only the `where()` parameters; the page query binds
        `where()` + `order()` + limit/offset, in that order.
        """
        return await reads.list_persons(self, req)

    async def db_stats(self) -> dict:
        """The archive-wide counters of the user-database header."""
        return await reads.db_stats(self)

    async def person_stats(self, nick: str) -> dict:
        """One person's counters, including first/last day and the gaps."""
        return await reads.person_stats(self, nick)
