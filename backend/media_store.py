"""Hybrid media storage for the archive.

Decision D-1: the database keeps the URL plus a hash; the BYTES live on disk
under a size cap. Previews then survive the site expiring an image, without
turning history.db into a multi-gigabyte blob store.

Bytes are fetched by an in-page `fetch()` (the page owns the session cookies)
and travel back as base64 through one CDP evaluate. When that host blocks
CORS the store falls back to a cookied Python download, then to reading the
network response body of the request the browser itself already made for the
visible `<img>` (CDP `Network.getResponseBody`). Everything here is
best-effort: a missing file, a dead URL or a disabled cache degrades to
"show the link", never to an exception in the UI.
"""

from __future__ import annotations

import aiohttp
import asyncio
import base64
import hashlib
import json
import logging
import os
import re
from datetime import datetime
from typing import Optional
from urllib.parse import urljoin, urlparse

from backend import chat_agent_js
from backend.history_db import HistoryDB

log = logging.getLogger("chatbot")

IMAGE_EXT = {".jpg": "image", ".jpeg": "image", ".png": "image",
             ".webp": "image", ".bmp": "image", ".gif": "gif"}
MIME_EXT = {"image/gif": ".gif", "image/png": ".png", "image/jpeg": ".jpg",
            "image/webp": ".webp", "image/bmp": ".bmp"}

#: Cyrillic → Latin, so `Хорошо Все` becomes a folder anybody can type,
#: open in Explorer and paste into a path. Latin-only was an explicit
#: requirement of the 2026-09-07 bug report.
TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "c", "ч": "ch", "ш": "sh", "щ": "sch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
    "і": "i", "ї": "yi", "є": "ye", "ґ": "g", "ў": "u",
}
SAFE_CHARS = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
RESERVED = {"con", "prn", "aux", "nul", "clock$"} | {
    f"{stem}{i}" for stem in ("com", "lpt") for i in range(1, 10)}


def slugify_nick(nick: str) -> str:
    """A Latin, filesystem-safe folder name for a person.

    `Хорошо Все` → `Horosho_Vse`, `Lizalo4ka` → `Lizalo4ka`. A short hash is
    appended only when the nick cannot be transliterated faithfully (emoji,
    CJK, punctuation), so the common case stays readable.
    """
    raw = " ".join(str(nick or "").split())
    if not raw:
        return "unknown"
    out, lossy = [], False
    for ch in raw:
        low = ch.lower()
        if ch in SAFE_CHARS or ch in "._-":
            out.append(ch)
        elif ch.isspace():
            out.append("_")
        elif low in TRANSLIT:
            mapped = TRANSLIT[low]
            out.append(mapped.capitalize() if (ch != low and mapped)
                       else mapped)
        else:
            lossy = True
            out.append("_")
    slug = "".join(out).strip("._ ")
    if "__" not in raw:
        while "__" in slug:
            slug = slug.replace("__", "_")
    if not slug or set(slug) <= {"_"}:
        slug, lossy = "user", True
    if slug.lower() in RESERVED:
        slug, lossy = slug + "_", True
    if lossy:
        slug += "_" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:4]
    return slug[:64]


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def infer_kind(url: str) -> str:
    ext = os.path.splitext(urlparse(str(url or "")).path)[1].lower()
    return IMAGE_EXT.get(ext, "image")


def _extension(url: str, mime: str) -> str:
    ext = os.path.splitext(urlparse(str(url or "")).path)[1].lower()
    if ext in IMAGE_EXT:
        return ext
    return MIME_EXT.get((mime or "").split(";")[0].strip(), ".bin")


class MediaStore:
    """URL registry + on-disk byte cache for images and GIFs."""

    def __init__(self, db: HistoryDB, cdp=None, cache_dir: str = "saved_media",
                 max_file_mb: float = 25, max_cache_mb: float = 10,
                 enabled: bool = True):
        self.db = db
        self.cdp = cdp
        self.cache_dir = cache_dir
        self.now = datetime.now
        self.max_file_bytes = int(float(max_file_mb) * 1024 * 1024)
        self.max_cache_bytes = int(float(max_cache_mb) * 1024 * 1024)
        self.enabled = bool(enabled)
        self.paused = False
        self._dirs: dict[str, str] = {}      # nick → person folder
        self._http_fetcher = None            # test hook for the Python downloader

    # ── the readable tree on disk ────────────────────────────────
    NICK_MARKER = "_nick.txt"

    def folder_for(self, nick: str, kind: str = "") -> str:
        """`<cache_dir>/<Latin nick>[/images|/gifs]`, absolute."""
        parts = [self._person_dir(nick)]
        if kind:
            parts.append("gifs" if kind == "gif" else "images")
        return os.path.join(*parts)

    def _person_dir(self, nick: str) -> str:
        """One folder per person, kept stable across restarts.

        Two different nicks can transliterate to the same Latin name
        (`Ански` and `Anski`); the folder therefore carries a `_nick.txt`
        marker naming its owner, and a late-comer gets a hashed variant.
        """
        key = " ".join(str(nick or "").split())
        cached = self._dirs.get(key)
        if cached:
            return cached
        root = os.path.abspath(self.cache_dir)
        slug = slugify_nick(key)
        folder = os.path.join(root, slug)
        owner = self._marker(folder)
        if owner and owner != key:
            digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:4]
            folder = os.path.join(root, f"{slug}_{digest}")
        self._dirs[key] = folder
        return folder

    def _marker(self, folder: str) -> str:
        try:
            with open(os.path.join(folder, self.NICK_MARKER),
                      encoding="utf-8") as handle:
                return handle.read().strip()
        except OSError:
            return ""

    def _write_marker(self, folder: str, nick: str) -> None:
        path = os.path.join(folder, self.NICK_MARKER)
        if os.path.exists(path):
            return
        try:
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(" ".join(str(nick or "").split()) or "unknown")
        except OSError as e:                         # noqa: BLE001
            log.debug("cannot write the nick marker in %s: %s", folder, e)

    def _free_name(self, folder: str, day: str, ext: str) -> str:
        """`YYYY-MM-DD_007.gif` — short, dated, sorted, unique."""
        used = 0
        try:
            for name in os.listdir(folder):
                if not name.startswith(day + "_"):
                    continue
                stem = os.path.splitext(name)[0][len(day) + 1:]
                if stem.isdigit():
                    used = max(used, int(stem))
        except OSError:
            pass
        return os.path.join(folder, f"{day}_{used + 1:03d}{ext}")

    def _target_path(self, nick: str, kind: str, day: str, ext: str) -> str:
        person = self._person_dir(nick)
        folder = os.path.join(person, "gifs" if kind == "gif" else "images")
        os.makedirs(folder, exist_ok=True)
        self._write_marker(person, nick)
        return self._free_name(folder, day, ext)

    def _day(self, value=None) -> str:
        text = str(value or "")[:10]
        if len(text) == 10 and text[4] == "-" and text[7] == "-":
            return text
        return self.now().strftime("%Y-%m-%d")

    # ── registration ─────────────────────────────────────────────
    async def register(self, url: str, kind: Optional[str] = None,
                       nick: str = "", day: str = "") -> Optional[int]:
        """Remember a media URL. Returns its id (existing rows are reused).

        `nick` is the conversation the file belongs to — it decides which
        person folder the bytes land in.
        """
        clean = str(url or "").strip()
        if not clean:
            return None
        resolved = (kind or "").strip() or infer_kind(clean)
        if resolved not in ("image", "gif"):
            resolved = infer_kind(clean)
        owner = " ".join(str(nick or "").split())
        await self.db.execute(
            "INSERT INTO media(url, kind, state, owner, day, ref_count, "
            "created_at, last_used) VALUES(?,?,'pending',?,?,1,?,?) "
            "ON CONFLICT(url) DO UPDATE SET ref_count=ref_count+1, "
            "owner=CASE WHEN media.owner='' THEN excluded.owner "
            "ELSE media.owner END, "
            "day=CASE WHEN media.day='' THEN excluded.day "
            "ELSE media.day END, "
            "last_used=excluded.last_used",
            (clean, resolved, owner, self._day(day) if day else "",
             _now(), _now()))
        await self.db.commit()
        row = await self.db.fetchone("SELECT id FROM media WHERE url=?",
                                     (clean,))
        return int(row[0]) if row else None

    async def get(self, media_id) -> Optional[dict]:
        row = await self.db.fetchone("SELECT * FROM media WHERE id=?",
                                     (self._as_id(media_id),))
        return dict(row) if row else None

    async def get_by_url(self, url: str) -> Optional[dict]:
        row = await self.db.fetchone("SELECT * FROM media WHERE url=?",
                                     (str(url or "").strip(),))
        return dict(row) if row else None

    @staticmethod
    def _as_id(value) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return -1

    # ── downloading ──────────────────────────────────────────────
    async def process_pending(self, limit: int = 25) -> int:
        """Cache up to `limit` pending files. Returns how many were stored."""
        if not self.enabled or self.paused or self.cdp is None:
            return 0
        rows = await self.db.fetchdicts(
            "SELECT id, url, kind, owner, day FROM media WHERE "
            "state='pending' ORDER BY id LIMIT ?", (max(1, int(limit)),))
        stored = 0
        for row in rows:
            if not self.enabled or self.paused:
                break
            if await self._fetch_one(row):
                stored += 1
        return stored

    async def _abs_url(self, url: str) -> str:
        """Resolve a relative/`//` image URL against the live page address.

        The chat page may keep the real address in `data-src` or hand the
        collector a path like `m_Питер2к7_7a861….jpg` instead of a full URL.
        The `<img>` element resolves it against the page, so Python has to do
        the same or every download gets a bogus relative path.
        """
        text = str(url or "").strip()
        if not text:
            return text
        if text.startswith(("data:", "blob:", "javascript:", "about:")) \
                or "://" in text:
            return text
        if callable(getattr(self.cdp, "evaluate", None)):
            try:
                # document.baseURI follows the page's <base href> — the chat
                # can keep its CDN in <base> so the visible <img> works while
                # location.href alone would resolve the path to the wrong host.
                base = await self.cdp.evaluate("document.baseURI")
                if str(base or "").startswith(("http://", "https://")):
                    return urljoin(str(base), text)
            except Exception:                    # noqa: BLE001
                pass
        return text

    async def _fetch_one(self, row: dict) -> bool:
        """Cache one media row.

        The in-page fetch is tried first (fastest). When the image host has no
        CORS headers the page fetch fails — the fallback downloads from Python
        with the browser's cookies instead, which is exactly the case the bug
        report showed.  The last resort reads the bytes out of the network
        request the browser itself already made for the visible `<img>`.
        """
        url = await self._abs_url(row["url"])
        payload = await self._fetch_in_page(url)
        page_ok = bool(payload.get("ok"))
        page_error = (payload.get("error") or "") if not page_ok else ""
        python_error = ""
        if not payload.get("ok"):
            payload = await self._fetch_via_python(url)
            python_error = payload.get("error") or ""
        network_error = ""
        if not payload.get("ok"):
            payload = await self._fetch_via_network(url)
            network_error = payload.get("error") or ""
        if not payload.get("ok"):
            errors = [e for e in (page_error, python_error, network_error)
                      if e and e != "no downloadable media"]
            if not errors:
                errors = [payload.get("error") or "no downloadable media"]
            await self._fail(row["id"], "CORS/page fetch failed: "
                              + " / ".join(dict.fromkeys(errors)))
            return False
        try:
            data = base64.b64decode(payload.get("b64") or "")
        except Exception as e:                        # noqa: BLE001
            await self._fail(row["id"], f"undecodable payload: {e}")
            return False
        if len(data) > self.max_file_bytes:
            await self._skip(row["id"], "too large (%d bytes, cap %d)"
                             % (len(data), self.max_file_bytes))
            return False
        digest = hashlib.sha256(data).hexdigest()
        ext = _extension(url, payload.get("mime", ""))
        kind = row.get("kind") or infer_kind(url)
        try:
            # identical bytes already filed for this person ⇒ reuse the file
            path = await self._twin(row.get("owner") or "", digest)
            if not path:
                path = self._target_path(row.get("owner") or "", kind,
                                         self._day(row.get("day")), ext)
                with open(path, "wb") as handle:
                    handle.write(data)
        except OSError as e:
            await self._fail(row["id"], f"cannot write cache: {e}")
            return False
        await self.db.execute(
            "UPDATE media SET state='cached', sha256=?, bytes=?, "
            "cache_path=?, fail_reason='', last_used=? WHERE id=?",
            (digest, len(data), path, _now(), row["id"]))
        await self.db.commit()
        return True

    async def _fetch_in_page(self, url: str) -> dict:
        """The original page-origin fetch (works when CORS permits it)."""
        try:
            raw = await self.cdp.evaluate(
                chat_agent_js.fetch_media_expression(url))
        except Exception as e:                        # noqa: BLE001
            return {"ok": False, "error": f"probe error: {e}"}
        payload = raw
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except (TypeError, ValueError):
                payload = None
        if not isinstance(payload, dict) or not payload.get("ok"):
            reason = (payload or {}).get("error") if isinstance(payload, dict) \
                else "no answer from the page"
            return {"ok": False, "error": str(reason or "no answer")}
        return payload

    async def _fetch_via_python(self, url: str) -> dict:
        """Download with the browser session cookies (CORS-free fallback)."""
        if callable(self._http_fetcher):
            return await self._http_fetcher(url)
        if self.cdp is None or not hasattr(self.cdp, "get_cookies"):
            return {"ok": False, "error": "no authenticated download available"}
        try:
            cookies = await self.cdp.get_cookies(url)
        except Exception as e:                        # noqa: BLE001
            cookies = ""
        parsed = urlparse(str(url or ""))
        referer = f"{parsed.scheme}://{parsed.netloc}/" if parsed.netloc \
            else "https://ru.virt-chat.com/"
        headers = {
            "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                           "AppleWebKit/537.36 (KHTML, like Gecko) "
                           "Chrome/131.0.0.0 Safari/537.36"),
            "Referer": referer,
            "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9,ru;q=0.8",
        }
        if cookies:
            headers["Cookie"] = cookies
        try:
            timeout = aiohttp.ClientTimeout(total=30)
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers,
                                       timeout=timeout,
                                       allow_redirects=True) as resp:
                    if resp.status != 200:
                        return {"ok": False,
                                "error": f"HTTP {resp.status}"}
                    data = await resp.read()
                    if len(data) > self.max_file_bytes:
                        return {"ok": False,
                                "error": "too large (%d bytes, cap %d)"
                                         % (len(data), self.max_file_bytes)}
                    return {"ok": True,
                            "b64": base64.b64encode(data).decode(),
                            "mime": resp.headers.get("Content-Type", ""),
                            "bytes": len(data)}
        except Exception as e:                        # noqa: BLE001
            return {"ok": False, "error": str(e)}

    async def _fetch_via_network(self, url: str) -> dict:
        """Grab the response bytes through the browser's normal <img> path.

        The page can render an image even when `fetch()` is CORS-blocked and
        a plain Python download is rejected by the host.  CDP lets us watch
        the real network request made by an `<img>` element and read its
        response body, so we save exactly the bytes the viewport shows.
        """
        if self.cdp is None or not all(
                hasattr(self.cdp, name) for name in ("send", "on_event",
                                                     "off_event")):
            return {"ok": False, "error": "CDP network capture unavailable"}
        loop = asyncio.get_running_loop()
        fut = loop.create_future()
        info = {"request_id": None, "mime": ""}

        def clean(value: Optional[str]) -> str:
            return str(value or "").split("#", 1)[0].split("?", 1)[0]

        def matches(value: Optional[str]) -> bool:
            return clean(value) == clean(url)

        def on_request(params) -> None:
            if fut.done():
                return
            request = (params or {}).get("request") or {}
            if matches(request.get("url")):
                info["request_id"] = (params or {}).get("requestId")

        def on_response(params) -> None:
            if fut.done():
                return
            response = (params or {}).get("response") or {}
            rid = (params or {}).get("requestId")
            if matches(response.get("url")):
                info["request_id"] = rid or info["request_id"]
            # a CORS/CDN redirect can change the visible URL; keep the bytes
            # and the real MIME for any response on the request we started.
            if rid and rid == info["request_id"]:
                info["mime"] = (response.get("mimeType") or
                                (response.get("headers") or {})
                                .get("Content-Type", ""))

        def on_finished(params) -> None:
            if fut.done():
                return
            if (params or {}).get("requestId") == info["request_id"]:
                self._finish_network_body(fut, info)

        def on_failed(params) -> None:
            if fut.done():
                return
            if (params or {}).get("requestId") == info["request_id"]:
                fut.set_result({"ok": False,
                                "error": (params or {}).get("errorText")
                                or "network load failed"})

        on_req = self.cdp.on_event("Network.requestWillBeSent", on_request)
        on_resp = self.cdp.on_event("Network.responseReceived", on_response)
        cb = self.cdp.on_event("Network.loadingFinished", on_finished)
        on_fail = self.cdp.on_event("Network.loadingFailed", on_failed)
        try:
            try:
                await self.cdp.send("Network.setCacheDisabled",
                                    {"cacheDisabled": True})
            except Exception:                        # noqa: BLE001
                pass
            js = ("(function(){window.__cvbFetchImage=new Image();"
                  "window.__cvbFetchImage.src=%s;})()"
                  % json.dumps(url, ensure_ascii=False))
            try:
                await self.cdp.evaluate(js)
            except Exception as e:                    # noqa: BLE001
                return {"ok": False, "error": f"load trigger failed: {e}"}
            try:
                return await asyncio.wait_for(fut, timeout=10)
            except asyncio.TimeoutError:
                return {"ok": False, "error": "network capture timed out"}
        finally:
            self.cdp.off_event("Network.requestWillBeSent", on_req)
            self.cdp.off_event("Network.responseReceived", on_resp)
            self.cdp.off_event("Network.loadingFinished", cb)
            self.cdp.off_event("Network.loadingFailed", on_fail)
            try:
                await self.cdp.send("Network.setCacheDisabled",
                                    {"cacheDisabled": False})
            except Exception:                        # noqa: BLE001
                pass

    def _finish_network_body(self, fut: asyncio.Future, info: dict) -> None:
        async def work():
            if fut.done():
                return
            rid = info.get("request_id")
            try:
                raw = await self.cdp.send("Network.getResponseBody",
                                          {"requestId": rid})
                result = (raw or {}).get("result", {}) or {}
                body = result.get("body") or ""
                if result.get("base64Encoded"):
                    data = base64.b64decode(body)
                    b64 = body
                else:
                    data = body.encode("utf-8")
                    b64 = base64.b64encode(data).decode()
                if not data:
                    fut.set_result({"ok": False,
                                    "error": "empty response body"})
                    return
                fut.set_result({"ok": True, "b64": b64,
                                "mime": info.get("mime") or "",
                                "bytes": len(data)})
            except Exception as e:                    # noqa: BLE001
                fut.set_result({"ok": False,
                                "error": f"getResponseBody: {e}"})
        asyncio.ensure_future(work())

    async def _twin(self, owner: str, digest: str) -> str:
        """An already-cached file with the same bytes in the same folder."""
        rows = await self.db.fetchdicts(
            "SELECT cache_path FROM media WHERE sha256=? AND owner=? "
            "AND state='cached' AND cache_path<>''", (digest, owner))
        for row in rows:
            if os.path.exists(row["cache_path"]):
                return row["cache_path"]
        return ""

    async def migrate_layout(self) -> int:
        """Move an older flat `<sha256>.<ext>` cache into the person tree."""
        rows = await self.db.fetchdicts(
            "SELECT id, url, kind, owner, day, cache_path, created_at "
            "FROM media WHERE state='cached' AND cache_path<>''")
        moved = 0
        root = os.path.abspath(self.cache_dir)
        for row in rows:
            old = row["cache_path"]
            if not old or not os.path.exists(old):
                continue
            if os.path.dirname(os.path.abspath(old)) != root:
                continue                       # already inside the tree
            ext = os.path.splitext(old)[1] or _extension(row["url"], "")
            day = self._day(row.get("day") or row.get("created_at"))
            try:
                new = self._target_path(row.get("owner") or "",
                                        row.get("kind") or "image", day, ext)
                os.replace(old, new)
            except OSError as e:               # noqa: PERF203
                log.warning("cannot move %s into the media tree: %s", old, e)
                continue
            await self.db.execute(
                "UPDATE media SET cache_path=? WHERE id=?", (new, row["id"]))
            moved += 1
        if moved:
            await self.db.commit()
        return moved

    async def _fail(self, media_id: int, reason: str) -> None:
        await self.db.execute(
            "UPDATE media SET state='failed', fail_reason=? WHERE id=?",
            (reason[:300], media_id))
        await self.db.commit()

    async def _skip(self, media_id: int, reason: str) -> None:
        await self.db.execute(
            "UPDATE media SET state='skipped', fail_reason=? WHERE id=?",
            (reason[:300], media_id))
        await self.db.commit()

    async def retry_failed(self) -> int:
        """Explicitly give up-front failures another chance (user action)."""
        cur = await self.db.execute(
            "UPDATE media SET state='pending', fail_reason='', "
            "recovered_at=?, recovery_attempts=recovery_attempts+1 "
            "WHERE state IN ('failed','skipped')",
            (_now(),))
        await self.db.commit()
        return int(cur.rowcount or 0)

    async def requeue(self, media_id, reason: str = "retry") -> bool:
        """Re-queue one failed/skipped media row for another download.

        Used by backfill recovery. The row is stamped so the UI/DB can prove
        it was recovered (or tried again) and so a single backfill never
        loops over the same URL endlessly.
        """
        row = await self.get(media_id)
        if not row or not row.get("url"):
            return False
        if row.get("state") not in ("failed", "skipped"):
            return False
        await self.db.execute(
            "UPDATE media SET state='pending', fail_reason='', "
            "recovered_at=?, recovery_attempts=recovery_attempts+1, "
            "last_used=? WHERE id=?",
            (_now(), _now(), self._as_id(media_id)))
        await self.db.commit()
        return True

    async def download_one(self, media_id) -> dict:
        """Force a single media row through the downloader and return its state.

        Used by the "click to restore" marker in the History window.  A row
        that is already cached and whose file still exists is returned as-is;
        anything failed, skipped, pending or whose saved file is gone is
        re-queued and downloaded once right here.
        """
        row = await self.get(media_id)
        if not row:
            return {"state": "missing", "id": media_id, "path": "", "url": ""}
        if not self.enabled or self.paused or self.cdp is None:
            return await self.path_for(media_id)
        path = row.get("cache_path") or ""
        if row.get("state") == "cached" and path and os.path.exists(path):
            return await self.path_for(media_id)
        await self.db.execute(
            "UPDATE media SET state='pending', fail_reason='', "
            "recovered_at=?, recovery_attempts=recovery_attempts+1, "
            "last_used=? WHERE id=?",
            (_now(), _now(), self._as_id(media_id)))
        await self.db.commit()
        row = await self.get(media_id)
        if row:
            await self._fetch_one(row)
        return await self.path_for(media_id)

    async def retry_failed_uncached(self) -> int:
        """Re-queue failed rows that have no local file.

        This is the one-time startup repair for the CORS download regression:
        rows that were marked failed by the old page-only fetch get a chance
        with the Python/cookie downloader.
        """
        cur = await self.db.execute(
            "UPDATE media SET state='pending', fail_reason='', "
            "recovered_at=?, recovery_attempts=recovery_attempts+1 "
            "WHERE state='failed' AND (cache_path='' OR cache_path IS NULL)",
            (_now(),))
        await self.db.commit()
        return int(cur.rowcount or 0)

    # ── serving ──────────────────────────────────────────────────
    async def path_for(self, media_id) -> dict:
        row = await self.get(media_id)
        if not row:
            return {"state": "missing", "path": "", "url": ""}
        path = row.get("cache_path") or ""
        usable = row.get("state") == "cached" and path and os.path.exists(path)
        if usable:
            await self.db.execute("UPDATE media SET last_used=? WHERE id=?",
                                  (_now(), row["id"]))
            await self.db.commit()
        return {"state": row.get("state"), "path": path if usable else "",
                "url": row.get("url") or "", "kind": row.get("kind") or "image",
                "bytes": int(row.get("bytes") or 0)}

    async def clipboard_payload(self, media_id) -> dict:
        """What the UI should put on the clipboard for a left click."""
        row = await self.get(media_id)
        if not row:
            return {"ok": False, "mode": "", "path": "", "text": "",
                    "url": "", "error": f"media {media_id} not found"}
        info = await self.path_for(row["id"])
        url = row.get("url") or ""
        if info["path"]:
            mode = "file_link" if row.get("kind") == "gif" else "image"
            return {"ok": True, "mode": mode, "path": info["path"],
                    "text": url, "url": url, "error": ""}
        return {"ok": True, "mode": "link", "path": "", "text": url,
                "url": url, "error": ""}

    # ── housekeeping ─────────────────────────────────────────────
    async def cache_usage(self) -> dict:
        row = await self.db.fetchone(
            "SELECT COUNT(*) AS files, COALESCE(SUM(bytes),0) AS bytes "
            "FROM media WHERE state='cached'")
        pending = int(await self.db.scalar(
            "SELECT COUNT(*) FROM media WHERE state='pending'", (), 0))
        failed = int(await self.db.scalar(
            "SELECT COUNT(*) FROM media WHERE state IN ('failed','skipped')",
            (), 0))
        return {"files": int(row["files"] or 0), "bytes": int(row["bytes"] or 0),
                "max_bytes": self.max_cache_bytes, "pending": pending,
                "failed": failed, "dir": self.cache_dir,
                "enabled": self.enabled, "paused": self.paused}

    async def evict_if_needed(self) -> int:
        """Drop least-recently-used files until we are under the cap."""
        removed = 0
        while True:
            total = int(await self.db.scalar(
                "SELECT COALESCE(SUM(bytes),0) FROM media WHERE state='cached'",
                (), 0))
            if total <= self.max_cache_bytes:
                return removed
            row = await self.db.fetchone(
                "SELECT id FROM media WHERE state='cached' "
                "ORDER BY last_used ASC, id ASC LIMIT 1")
            if not row:
                return removed
            await self._evict(int(row[0]))
            removed += 1

    async def _evict(self, media_id: int) -> None:
        row = await self.get(media_id)
        if not row:
            return
        path = row.get("cache_path") or ""
        shared = int(await self.db.scalar(
            "SELECT COUNT(*) FROM media WHERE cache_path=? AND state='cached' "
            "AND id<>?", (path, media_id), 0))
        if path and not shared and os.path.exists(path):
            try:
                os.remove(path)
            except OSError as e:
                log.warning("cannot remove cached media %s: %s", path, e)
        await self.db.execute(
            "UPDATE media SET state='evicted', bytes=0 WHERE id=?", (media_id,))
        await self.db.commit()

    async def clear_cache(self) -> int:
        rows = await self.db.fetchdicts(
            "SELECT id FROM media WHERE state='cached'")
        for row in rows:
            await self._evict(int(row["id"]))
        return len(rows)
