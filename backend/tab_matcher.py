"""URL → Chrome-tab matching (pure logic, no I/O).

Given a user-supplied URL / keyword and the list of open Chrome tabs,
score every tab and return the best matches so the UI can auto-select
and connect to the right tab.

Scoring (higher wins):
  kind "url_exact"  = normalized URL equality            (+500)
  kind "url_path"   = same host, requested path prefix   (+300)
  kind "host"       = same hostname                      (+200)
  kind "keyword"    = substring in host+path / title     (+ 60)
"""

from urllib.parse import unquote, urlparse
from typing import Iterable, Optional

# Hosts we know are "the same site" regardless of subdomain (e.g. www.)
_SITE_ROOTS = ("virt-chat.com",)


def _normalize_url(url: str) -> str:
    url = (url or "").strip().lower()
    if not url:
        return ""
    # Drop common prefixes that do not matter for matching
    for p in ("https://", "http://"):
        if url.startswith(p):
            url = url[len(p):]
    # Drop everything after '#'
    url = url.split("#", 1)[0]
    # Drop trailing slash (but keep root as empty path)
    while url.endswith("/"):
        url = url[:-1]
    try:
        url = unquote(url)
    except Exception:
        pass
    return url


def _parse(query: str):
    """Parse a normalized query into (host, path, is_url_like)."""
    q = _normalize_url(query)
    if not q:
        return "", "", False
    if "/" in q or "." in q:
        # Looks like a host/path or hostname
        path = ""
        host = q
        if "/" in q:
            host, path = q.split("/", 1)
            path = "/" + path
        # strip :port
        if ":" in host:
            host = host.split(":", 1)[0]
        return host, path, True
    return "", "", False  # keyword


def _site_key(host: str) -> str:
    """Reduce host to the registered-site key, or the host itself."""
    host = (host or "").lower()
    parts = host.split(".")
    for root in _SITE_ROOTS:
        if host == root or host.endswith("." + root):
            return root
    return host


def _tab_url(tab: dict) -> str:
    """The address a tab record is matched on (ws_url is the fallback)."""
    return tab.get("url") or tab.get("ws_url") or ""


def _parsed_target(tab_url: str) -> tuple[str, str]:
    """(host, path) of a tab URL; ("", "") when parsing fails."""
    try:
        parsed = urlparse(tab_url)
    except Exception:
        return "", ""
    return (parsed.hostname or "").lower(), unquote(parsed.path or "")


def _score_url_like(query_parts: tuple[str, str], q_norm: str,
                    tab_parts: tuple[str, str]) -> Optional[tuple[int, str]]:
    """The site-ladder verdict for a URL-like query, or None."""
    q_host, q_path = query_parts
    tab_host, tab_path = tab_parts
    if _site_key(tab_host) != _site_key(q_host):
        # full keyword against host+path
        return (60, "keyword") if q_norm in f"{tab_host}{tab_path}" else None
    if q_path and tab_path.startswith(q_path):
        return 300, "url_path"
    if not q_path:
        return 200, "host"
    # same site root but different path → weak host match
    return 60, "keyword"


def _score_keyword(q_norm: str, url_norm: str,
                   tab_title: str) -> tuple[int, str]:
    """Keyword fallback: anywhere in normalized URL or title."""
    if q_norm and (q_norm in url_norm or q_norm in (tab_title or "").lower()):
        return 60, "keyword"
    return 0, ""


def score_tab(query: str, tab_url: str, tab_title: str = "") -> tuple[int, str]:
    """Return (score, kind) for one tab URL vs a query. 0 = no match."""
    query = (query or "").strip()
    if not query or not tab_url:
        return 0, ""
    q_norm = _normalize_url(query)
    url_norm = _normalize_url(tab_url)

    # 1) exact URL (ignoring protocol/#/trailing slash)
    if q_norm and url_norm == q_norm:
        return 500, "url_exact"

    q_host, q_path, is_url_like = _parse(query)
    if is_url_like and q_host:
        verdict = _score_url_like((q_host, q_path), q_norm,
                                  _parsed_target(tab_url))
        if verdict is not None:
            return verdict

    # 2) keyword fallback
    return _score_keyword(q_norm, url_norm, tab_title)


def best_matches(query: str, tabs: Iterable[dict], top_n: int = 5) -> list[dict]:
    """Score tabs; return sorted list of match dicts (best first)."""
    scored: list[tuple[int, dict]] = []
    for tab in tabs or []:
        score, _kind = score_tab(query, _tab_url(tab), tab.get("title") or "")
        if score > 0:
            scored.append((score, tab))
    scored.sort(key=lambda x: -x[0])
    out: list[dict] = []
    for score, tab in scored[: max(1, int(top_n))]:
        _sc, kind = score_tab(query, _tab_url(tab), tab.get("title") or "")
        out.append({
            "id": tab.get("id", ""),
            "title": tab.get("title", ""),
            "url": tab.get("url", ""),
            "ws_url": tab.get("ws_url", ""),
            "score": score,
            "kind": kind,
        })
    return out
