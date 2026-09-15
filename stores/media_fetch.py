"""The three-tier byte fetcher behind the media cache.

Download half of `stores/media_store.py`. Bytes tried in order: in-page
`fetch()` (page owns session cookies), cookied Python download, and CDP
`Network.getResponseBody`. Best-effort — dead URL or CORS block leaves
`failed` row, never exception in UI.

H-C4: network finisher moved to `media_network.py`. H-C5: HTTP tiers moved
to `media_fetch_http.py`, predicates extracted per RULE 19 step 3.
Orchestration only here — 150-300 LOC ideal.

Design: AREA_C H-C4 + H-C5 MI lift.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import os
from urllib.parse import urljoin

from stores.media_fetch_http import MediaFetchHttp
from stores.media_layout import _extension, _now, infer_kind
from stores.media_network import NetworkBodyFinisher, _NetworkWatch  # noqa: F401

log = logging.getLogger("chatbot")


def _is_data_or_special(url: str) -> bool:
    return url.startswith(("data:", "blob:", "javascript:", "about:"))


def _is_absolute_url(url: str) -> bool:
    return "://" in url


def _is_http_base(base: str) -> bool:
    return str(base or "").startswith(("http://", "https://"))


def _has_evaluate(cdp) -> bool:
    return callable(getattr(cdp, "evaluate", None))


def _is_enabled(owner) -> bool:
    return bool(owner.enabled and not owner.paused and owner.cdp is not None)


def _is_valid_limit(limit: int) -> bool:
    return int(limit) > 0


def _is_payload_ok(payload: dict) -> bool:
    return bool(payload.get("ok"))


def _is_empty_data(data: bytes) -> bool:
    return not data


def _is_too_large(size: int, cap: int) -> bool:
    return size > cap


def _is_cached_row(row: dict, path: str) -> bool:
    return row.get("state") == "cached" and bool(path) and os.path.exists(path)


def _is_failed_or_skipped(state: str) -> bool:
    return state in ("failed", "skipped")


def _is_valid_row(row: dict | None) -> bool:
    return bool(row and row.get("url"))


def _download_errors(payload: dict, errors: list) -> list:
    useful = [e for e in errors if e and e != "no downloadable media"]
    return useful or [payload.get("error") or "no downloadable media"]


class MediaFetcher:
    """Three-tier fetcher — orchestration only."""

    def __init__(self, owner):
        self._owner = owner
        self._network = NetworkBodyFinisher(self)
        self._http = MediaFetchHttp(owner)

    async def process_pending(self, limit: int = 25) -> int:
        if not _is_enabled(self._owner):
            return 0
        if not _is_valid_limit(limit):
            return 0
        rows = await self._owner.db.fetchdicts(
            "SELECT id, url, kind, owner, day FROM media WHERE state='pending' ORDER BY id LIMIT ?", (int(limit),)
        )
        stored = 0
        for row in rows:
            if not _is_enabled(self._owner):
                break
            if await self._fetch_one(row):
                stored += 1
        return stored

    async def _abs_url(self, url: str) -> str:
        text = str(url or "").strip()
        if not text:
            return text
        if _is_data_or_special(text) or _is_absolute_url(text):
            return text
        if _has_evaluate(self._owner.cdp):
            try:
                base = await self._owner.cdp.evaluate("document.baseURI")
                if _is_http_base(str(base)):
                    return urljoin(str(base), text)
            except Exception:  # noqa: BLE001
                pass
        return text

    async def _fetch_one(self, row: dict) -> bool:
        url = await self._abs_url(row["url"])
        payload, errors = await self._download(url)
        if not _is_payload_ok(payload):
            reason = "CORS/page fetch failed: " + " / ".join(dict.fromkeys(errors))
            await self._owner._fail(row["id"], reason)
            return False
        try:
            data = base64.b64decode(payload.get("b64") or "")
        except Exception as exc:  # noqa: BLE001
            await self._owner._fail(row["id"], f"undecodable payload: {exc}")
            return False
        if _is_empty_data(data):
            await self._owner._fail(row["id"], "empty payload")
            return False
        if _is_too_large(len(data), self._owner.max_file_bytes):
            await self._owner._skip(row["id"], "too large (%d bytes, cap %d)" % (len(data), self._owner.max_file_bytes))
            return False
        return await self._file_bytes(row, url, data, payload)

    async def _download(self, url: str) -> tuple[dict, list]:
        payload = await self._http.fetch_in_page(url)
        errors: list = [] if _is_payload_ok(payload) else [payload.get("error") or ""]
        for step in (self._http.fetch_via_python, self._fetch_via_network):
            if _is_payload_ok(payload):
                break
            payload = await step(url)
            if not _is_payload_ok(payload):
                errors.append(payload.get("error") or "")
        if _is_payload_ok(payload):
            return payload, []
        return payload, _download_errors(payload, errors)

    async def _file_bytes(self, row: dict, url: str, data: bytes, payload: dict) -> bool:
        digest = hashlib.sha256(data).hexdigest()
        ext = _extension(url, payload.get("mime", ""))
        kind = row.get("kind") or infer_kind(url)
        try:
            path = await self._owner._twin(row.get("owner") or "", digest)
            if not path:
                path = self._owner._target_path(row.get("owner") or "", kind, self._owner._day(row.get("day")), ext)
                with open(path, "wb") as handle:
                    handle.write(data)
        except OSError as exc:
            await self._owner._fail(row["id"], f"cannot write cache: {exc}")
            return False
        await self._owner.db.execute(
            "UPDATE media SET state='cached', sha256=?, bytes=?, cache_path=?, fail_reason='', last_used=? WHERE id=?",
            (digest, len(data), path, _now(), row["id"]),
        )
        await self._owner.db.commit()
        return True

    async def _fetch_via_network(self, url: str) -> dict:
        return await self._network._fetch_via_network(url)

    def _finish_network_body(self, fut: asyncio.Future, info: dict) -> None:
        return self._network._finish_network_body(fut, info)

    async def _cache_disabled(self, cdp, value: bool) -> None:
        return await self._network._cache_disabled(cdp, value)

    async def retry_failed(self) -> int:
        cur = await self._owner.db.execute(
            "UPDATE media SET state='pending', fail_reason='', recovered_at=?, recovery_attempts=recovery_attempts+1 WHERE state IN ('failed','skipped')",
            (_now(),),
        )
        await self._owner.db.commit()
        return int(cur.rowcount or 0)

    async def requeue(self, media_id, reason: str = "retry") -> bool:
        row = await self._owner.get(media_id)
        if not _is_valid_row(row):
            return False
        if not _is_failed_or_skipped(row.get("state") or ""):
            return False
        await self._owner.db.execute(
            "UPDATE media SET state='pending', fail_reason='', recovered_at=?, recovery_attempts=recovery_attempts+1, last_used=? WHERE id=?",
            (_now(), _now(), self._owner._as_id(media_id)),
        )
        await self._owner.db.commit()
        return True

    async def download_one(self, media_id) -> dict:
        row = await self._owner.get(media_id)
        if not row:
            return {"state": "missing", "id": media_id, "path": "", "url": ""}
        if not _is_enabled(self._owner):
            return await self._owner.path_for(media_id)
        path = row.get("cache_path") or ""
        if _is_cached_row(row, path):
            return await self._owner.path_for(media_id)
        await self._owner.db.execute(
            "UPDATE media SET state='pending', fail_reason='', recovered_at=?, recovery_attempts=recovery_attempts+1, last_used=? WHERE id=?",
            (_now(), _now(), self._owner._as_id(media_id)),
        )
        await self._owner.db.commit()
        row = await self._owner.get(media_id)
        if row:
            await self._fetch_one(row)
        return await self._owner.path_for(media_id)

    async def retry_failed_uncached(self) -> int:
        cur = await self._owner.db.execute(
            "UPDATE media SET state='pending', fail_reason='', recovered_at=?, recovery_attempts=recovery_attempts+1 WHERE state='failed' AND (cache_path='' OR cache_path IS NULL)",
            (_now(),),
        )
        await self._owner.db.commit()
        return int(cur.rowcount or 0)
