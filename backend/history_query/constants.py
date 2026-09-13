"""The read path's limits and the Full User Database sort whitelist."""

DEFAULT_LIMIT = 50
MAX_LIMIT = 500
SNIPPET_RADIUS = 40

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
