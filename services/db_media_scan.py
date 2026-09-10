"""Strict read-only media scan for deletion safety (AREA A).

Legacy `services.db_service._media_references(path) -> set` is best-effort:
any failure returns an empty set, which a deleter cannot distinguish from
“no references”. Destructive deletion must use this strict scan instead.

A corrupt / locked / unsupported world is NOT empty: `complete` is False
and the caller must refuse deletion before any switch/unlink.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from urllib.parse import quote

log = logging.getLogger("chatbot")

SUPPORTED_SCHEMA_VERSIONS = frozenset({"5", "6"})


@dataclass(frozen=True)
class MediaScanResult:
    """One world's media references + completeness flag."""

    path: str
    references: frozenset
    complete: bool
    reason: str  # ok | missing_file | missing_media_table | unsupported_schema
    # corrupt | locked | io_error | query_error
    detail: str
    schema_version: str | None = None


def sqlite_ro_uri(path: str) -> str:
    """Read-only SQLite URI with correct escaping for ?, #, %, spaces, unicode.

    SQLite interprets `?` as the start of query parameters and `#` as a
    fragment, so a filename containing those characters must be percent
    encoded. Spaces and unicode are also encoded for robustness.
    """
    abs_path = os.path.abspath(str(path or ""))
    # Normalize separators for URI; keep drive prefix safe on Windows.
    # quote with safe="/:" preserves POSIX root and Windows drive colon.
    # On Windows, backslashes are converted to slashes for the URI form.
    uri_path = abs_path.replace(os.sep, "/")
    # Preserve leading slash and colon, encode everything else that needs it.
    quoted = quote(uri_path, safe="/:")
    return f"file:{quoted}?mode=ro"


async def scan_world_media(path: str, timeout_s: float = 2.0) -> MediaScanResult:
    """Strict scan of one world's cached `media.cache_path` values.

    Returns `complete=True` only when the scan is trustworthy. Any failure
    (missing file, corrupt, locked, missing media table, unsupported schema)
    returns `complete=False` with empty references and a diagnostic reason.
    """
    apath = os.path.abspath(str(path or ""))
    if not apath or not os.path.exists(apath):
        return MediaScanResult(
            path=apath, references=frozenset(), complete=False,
            reason="missing_file",
            detail=f"{os.path.basename(apath) or path}: file not found",
            schema_version=None)
    # Proven-empty exception: a zero-byte file cannot contain references, so
    # an empty set is trustworthy (lets placeholder/empty worlds delete while
    # still refusing non-empty corrupt worlds). Non-empty files without a
    # media table remain incomplete (unsupported), never empty.
    try:
        if os.path.getsize(apath) == 0:
            return MediaScanResult(
                path=apath, references=frozenset(), complete=True,
                reason="ok", detail="empty file",
                schema_version=None)
    except OSError:
        pass
    import aiosqlite
    uri = sqlite_ro_uri(apath)
    try:
        # Short timeout: a locked world must fail fast as incomplete,
        # not hang deletion.
        async with aiosqlite.connect(uri, uri=True,
                                     timeout=float(timeout_s)) as conn:
            # Missing media table → incomplete (not a valid empty world).
            try:
                cur = await conn.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='table' AND name='media'")
                row = await cur.fetchone()
            except Exception as exc:  # noqa: BLE001
                return MediaScanResult(
                    path=apath, references=frozenset(), complete=False,
                    reason="corrupt",
                    detail=f"{os.path.basename(apath)}: cannot read schema "
                           f"({exc})",
                    schema_version=None)
            if not row:
                return MediaScanResult(
                    path=apath, references=frozenset(), complete=False,
                    reason="missing_media_table",
                    detail=f"{os.path.basename(apath)}: no media table; "
                           "not a supported world",
                    schema_version=None)
            # Schema version when present (informational; missing with media
            # table present is treated as legacy-complete).
            schema_version = None
            try:
                cur = await conn.execute(
                    "SELECT value FROM schema_meta "
                    "WHERE key='schema_version'")
                vrow = await cur.fetchone()
                if vrow and vrow[0] is not None:
                    schema_version = str(vrow[0])
            except Exception:  # noqa: BLE001
                schema_version = None
            if schema_version is not None and \
                    schema_version not in SUPPORTED_SCHEMA_VERSIONS:
                return MediaScanResult(
                    path=apath, references=frozenset(), complete=False,
                    reason="unsupported_schema",
                    detail=f"{os.path.basename(apath)}: unsupported schema "
                           f"version {schema_version!r}",
                    schema_version=schema_version)
            # The actual references.
            try:
                cur = await conn.execute(
                    "SELECT cache_path FROM media "
                    "WHERE state='cached' AND cache_path<>'' "
                    "AND cache_path IS NOT NULL")
                rows = await cur.fetchall()
            except Exception as exc:  # noqa: BLE001
                msg = str(exc).lower()
                if "locked" in msg or "busy" in msg:
                    return MediaScanResult(
                        path=apath, references=frozenset(), complete=False,
                        reason="locked",
                        detail=f"{os.path.basename(apath)}: database is locked",
                        schema_version=schema_version)
                return MediaScanResult(
                    path=apath, references=frozenset(), complete=False,
                    reason="query_error",
                    detail=f"{os.path.basename(apath)}: media query failed "
                           f"({exc})",
                    schema_version=schema_version)
            refs: set[str] = set()
            for (cache_path,) in rows:
                text = str(cache_path or "").strip()
                if text:
                    refs.add(os.path.abspath(text))
            return MediaScanResult(
                path=apath, references=frozenset(refs), complete=True,
                reason="ok", detail="",
                schema_version=schema_version)
    except Exception as exc:  # noqa: BLE001
        msg = str(exc).lower()
        # aiosqlite wraps sqlite errors; detect lock/busy vs corrupt.
        if "locked" in msg or "busy" in msg:
            reason = "locked"
            detail = f"{os.path.basename(apath)}: database is locked ({exc})"
        elif "no such table" in msg and "media" in msg:
            reason = "missing_media_table"
            detail = f"{os.path.basename(apath)}: no media table"
        elif "file is not a database" in msg or "not a database" in msg \
                or "database disk image is malformed" in msg \
                or "unsupported file format" in msg:
            reason = "corrupt"
            detail = f"{os.path.basename(apath)}: unreadable database ({exc})"
        else:
            reason = "io_error"
            detail = f"{os.path.basename(apath)}: cannot scan ({exc})"
            log.debug("strict media scan failed for %s: %s", apath, exc)
        return MediaScanResult(
            path=apath, references=frozenset(), complete=False,
            reason=reason, detail=detail, schema_version=None)
