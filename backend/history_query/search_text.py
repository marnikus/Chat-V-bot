"""Pure text helpers for the two search back-ends.

FTS5 when SQLite offers it, a `text_lc LIKE` scan when it does not. Both fold
case for Cyrillic — the `text_lc` column is lower-cased in Python, because
SQLite's own LIKE folds ASCII only.
"""

import re

from .constants import SNIPPET_RADIUS


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
