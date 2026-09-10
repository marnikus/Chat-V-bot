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


class _ScanFault(Exception):
    """Internal signal: carry an already-built incomplete result."""

    def __init__(self, result: MediaScanResult):
        super().__init__(result.reason)
        self.result = result


def sqlite_ro_uri(path: str) -> str:
    """Read-only SQLite URI with correct escaping for ?, #, %, spaces, unicode.

    SQLite interprets `?` as the start of query parameters and `#` as a
    fragment, so a filename containing those characters must be percent
    encoded. Spaces and unicode are also encoded for robustness.
    """
    abs_path = os.path.abspath(str(path or ""))
    # Normalize separators for URI; keep drive prefix safe on Windows.
    # quote with safe=" /:" preserves POSIX root and Windows drive colon.
    # On Windows, backslashes are converted to slashes for the URI form.
    uri_path = abs_path.replace(os.sep, "/")
    # Preserve leading slash and colon, encode everything else that needs it.
    quoted = quote(uri_path, safe="/:")
    return f"file:{quoted}?mode=ro"


def _fault(apath: str, reason: str, detail: str,
           schema_version: str | None = None) -> MediaScanResult:
    """Build an incomplete (untrustworthy) scan result."""
    return MediaScanResult(
        path=apath, references=frozenset(), complete=False,
        reason=reason, detail=detail, schema_version=schema_version)


def _ok(apath: str, references=frozenset(),
        schema_version: str | None = None) -> MediaScanResult:
    """Build a complete scan result."""
    return MediaScanResult(
        path=apath, references=references, complete=True,
        reason="ok", detail="", schema_version=schema_version)


def _early_scan_result(apath: str, raw_path: str):
    """Missing-file or proven-empty (zero-byte) verdict before opening SQLite."""
    if not apath or not os.path.exists(apath):
        return _fault(
            apath, "missing_file",
            f"{os.path.basename(apath) or raw_path}: file not found")
    # Proven-empty exception: a zero-byte file cannot contain references, so
    # an empty set is trustworthy (lets placeholder/empty worlds delete while
    # still refusing non-empty corrupt worlds).
    try:
        if os.path.getsize(apath) == 0:
            return MediaScanResult(
                path=apath, references=frozenset(), complete=True,
                reason="ok", detail="empty file", schema_version=None)
    except OSError:
        pass
    return None


def _looks_corrupt(msg: str) -> bool:
    return ("file is not a database" in msg
            or "not a database" in msg
            or "database disk image is malformed" in msg
            or "unsupported file format" in msg)


def _classify_scan_exception(msg: str) -> tuple[str, str] | None:
    """Map a connection-level failure message to (reason, short phrase)."""
    if "locked" in msg or "busy" in msg:
        return "locked", "database is locked"
    if "no such table" in msg and "media" in msg:
        return "missing_media_table", "no media table"
    if _looks_corrupt(msg):
        return "corrupt", "unreadable database"
    return None


def _outer_fault(apath: str, exc: Exception) -> MediaScanResult:
    """Render a failure opening/using the connection (fail closed)."""
    name = os.path.basename(apath)
    msg = str(exc).lower()
    kind = _classify_scan_exception(msg)
    if kind is None:
        log.debug("strict media scan failed for %s: %s", apath, exc)
        return _fault(apath, "io_error", f"{name}: cannot scan ({exc})")
    reason, phrase = kind
    if reason == "locked":
        detail = f"{name}: database is locked ({exc})"
    elif reason == "missing_media_table":
        detail = f"{name}: no media table"
    else:
        detail = f"{name}: {phrase} ({exc})"
    return _fault(apath, reason, detail)


async def _read_media_table(conn, apath: str):
    """Return the sqlite_master row; None when the media table is absent."""
    try:
        cur = await conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name='media'")
        return await cur.fetchone()
    except Exception as exc:  # noqa: BLE001
        raise _ScanFault(_fault(
            apath, "corrupt",
            f"{os.path.basename(apath)}: cannot read schema ({exc})"))


async def _read_schema_version(conn):
    """Schema version when recorded; None when absent or unreadable."""
    try:
        cur = await conn.execute(
            "SELECT value FROM schema_meta "
            "WHERE key='schema_version'")
        vrow = await cur.fetchone()
        if vrow and vrow[0] is not None:
            return str(vrow[0])
    except Exception:  # noqa: BLE001
        return None
    return None


async def _read_media_rows(conn, apath: str, schema_version):
    """Return cached media rows; raise _ScanFault on a locked/query failure."""
    try:
        cur = await conn.execute(
            "SELECT cache_path FROM media "
            "WHERE state='cached' AND cache_path<>'' "
            "AND cache_path IS NOT NULL")
        return await cur.fetchall()
    except Exception as exc:  # noqa: BLE001
        msg = str(exc).lower()
        if "locked" in msg or "busy" in msg:
            raise _ScanFault(_fault(
                apath, "locked",
                f"{os.path.basename(apath)}: database is locked",
                schema_version))
        raise _ScanFault(_fault(
            apath, "query_error",
            f"{os.path.basename(apath)}: media query failed ({exc})",
            schema_version))


def _reference_set(rows) -> frozenset:
    refs: set[str] = set()
    for (cache_path,) in rows:
        text = str(cache_path or "").strip()
        if text:
            refs.add(os.path.abspath(text))
    return frozenset(refs)


async def _scan_connection(conn, apath: str) -> MediaScanResult:
    """Run the strict checks inside an open read-only connection."""
    try:
        table_row = await _read_media_table(conn, apath)
        if not table_row:
            return _fault(
                apath, "missing_media_table",
                f"{os.path.basename(apath)}: no media table; "
                "not a supported world")
        schema_version = await _read_schema_version(conn)
        if schema_version is not None and \
                schema_version not in SUPPORTED_SCHEMA_VERSIONS:
            return _fault(
                apath, "unsupported_schema",
                f"{os.path.basename(apath)}: unsupported schema "
                f"version {schema_version!r}",
                schema_version)
        rows = await _read_media_rows(conn, apath, schema_version)
        return _ok(apath, _reference_set(rows), schema_version)
    except _ScanFault as fault:
        return fault.result


async def scan_world_media(path: str, timeout_s: float = 2.0) -> MediaScanResult:
    """Strict scan of one world's cached `media.cache_path` values.

    Returns `complete=True` only when the scan is trustworthy. Any failure
    (missing file, corrupt, locked, missing media table, unsupported schema)
    returns `complete=False` with empty references and a diagnostic reason.
    """
    apath = os.path.abspath(str(path or ""))
    early = _early_scan_result(apath, path)
    if early is not None:
        return early
    # Non-empty files without a media table remain incomplete (unsupported),
    # never empty. A locked world fails fast via the short timeout.
    import aiosqlite
    uri = sqlite_ro_uri(apath)
    try:
        async with aiosqlite.connect(uri, uri=True,
                                     timeout=float(timeout_s)) as conn:
            return await _scan_connection(conn, apath)
    except Exception as exc:  # noqa: BLE001
        return _outer_fault(apath, exc)
