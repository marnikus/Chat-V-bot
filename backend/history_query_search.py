"""The search back-end of the archive: FTS5 with a LIKE fallback.

Part of the `history_query` family (facade: `backend/history_query.py`,
Round H step H-B2). Search has two interchangeable back-ends: FTS5 when
SQLite offers it, a `text_lc LIKE` scan when it does not. Both fold case
for Cyrillic — the `text_lc` column is lower-cased in Python, because
SQLite's own LIKE folds ASCII only.

Everything here is request-text touching SQL, so the same discipline
applies: FTS tokens are quoted into `MATCH` (`_fts_query`), LIKE wildcards
are escaped (`_like_escape`, also the escape the request's own
`where()`/`order()` use), and nothing user-typed ever reaches a clause as
structure.
"""

from __future__ import annotations

import logging
import re

log = logging.getLogger("chatbot")

SNIPPET_RADIUS = 40


def _like_escape(text: str) -> str:
    return (text.replace("\\", "\\\\").replace("%", "\\%")
                .replace("_", "\\_"))


def _fts_query(raw: str) -> str:
    """Turn user input into a safe FTS5 MATCH expression.

    Every token is quoted, so `AND`, `*`, quotes and stray punctuation are
    data, never syntax.
    """
    tokens = [t for t in re.split(r"[^\w\u0400-\u04FF]+", raw or "") if t]
    if not tokens:
        return ""
    return " ".join('"%s"' % t.replace('"', '""') for t in tokens)


def _snippet(text: str, needle: str, radius: int = SNIPPET_RADIUS) -> str:
    body = text or ""
    if not needle:
        return body[: radius * 2]
    pos = body.lower().find(needle.lower())
    if pos < 0:
        return body[: radius * 2]
    start = max(0, pos - radius)
    end = min(len(body), pos + len(needle) + radius)
    return ("…" if start else "") + body[start:end] + ("…" if end < len(body)
                                                       else "")


async def search(db, person_id, query: str, limit: int, offset: int):
    """`(rows, total)` for one search — FTS5 first, the LIKE scan as the
    fallback (both an absent index and a failed FTS query take it)."""
    text = (query or "").strip()
    if not text:
        return [], 0
    where = "p.deleted_at IS NULL AND m.deleted_at=''"
    params: list = []
    if person_id is not None:
        where += " AND m.person_id=?"
        params.append(person_id)

    select = ("SELECT m.*, md.url AS media_url, md.kind AS media_kind, "
              "md.state AS media_state, md.cache_path AS cache_path, "
              "p.nick AS nick FROM messages m "
              "JOIN persons p ON p.id = m.person_id "
              "LEFT JOIN media md ON md.id = m.media_id ")

    if db.fts_enabled:
        match = _fts_query(text)
        if not match:
            return [], 0
        try:
            base = (select +
                    "JOIN messages_fts f ON f.rowid = m.id "
                    f"WHERE {where} AND messages_fts MATCH ? ")
            total = int(await db.scalar(
                "SELECT COUNT(*) FROM messages m "
                "JOIN persons p ON p.id = m.person_id "
                "JOIN messages_fts f ON f.rowid = m.id "
                f"WHERE {where} AND messages_fts MATCH ?",
                params + [match], 0))
            rows = await db.fetchdicts(
                base + "ORDER BY m.person_id, m.ord LIMIT ? OFFSET ?",
                params + [match, limit, offset])
            return rows, total
        except Exception as e:                    # noqa: BLE001
            log.warning("FTS search failed (%s) — using LIKE", e)

    needle = "%" + _like_escape(text.lower()) + "%"
    total = int(await db.scalar(
        "SELECT COUNT(*) FROM messages m "
        "JOIN persons p ON p.id = m.person_id "
        f"WHERE {where} AND m.text_lc LIKE ? ESCAPE '\\'",
        params + [needle], 0))
    rows = await db.fetchdicts(
        select + f"WHERE {where} AND m.text_lc LIKE ? ESCAPE '\\' "
        "ORDER BY m.person_id, m.ord LIMIT ? OFFSET ?",
        params + [needle, limit, offset])
    return rows, total
