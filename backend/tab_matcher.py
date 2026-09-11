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


def _tab_host_path(tab_url: str) -> tuple[str, str]:
    """(host, path) of a tab URL; ("", "") when the URL cannot be parsed."""
    try:
        parsed = urlparse(tab_url)
        return (parsed.hostname or "").lower(), unquote(parsed.path or "")
    except Exception:
        return "", ""


def _score_same_site(q_host: str, q_path: str, tab_host: str,
                     tab_path: str) -> Optional[tuple[int, str]]:
    """The host/path ladder, or None when the tab is not on the queried site."""
    if _site_key(tab_host) != _site_key(q_host):
        return None
    if q_path and tab_path.startswith(q_path):
        return 300, "url_path"
    if not q_path:
        return 200, "host"
    # same site root but different path → weak host match
    return 60, "keyword"


def _score_within(q_norm: str, tab_host: str,
                  tab_path: str) -> Optional[tuple[int, str]]:
    """A hit of the whole query inside the tab's own host+path."""
    return (60, "keyword") if q_norm in f"{tab_host}{tab_path}" else None


def _score_keyword(q_norm: str, url_norm: str, tab_title: str) -> tuple[int, str]:
    """The last-resort substring rule: query in the URL or in the title."""
    if q_norm and (q_norm in url_norm or q_norm in (tab_title or "").lower()):
        return 60, "keyword"
    return 0, ""


def score_tab(query: str, tab_url: str, tab_title: str = "") -> tuple[int, str]:
    """Return (score, kind) for one tab URL vs a query. 0 = no match.

    A ranked ladder, best rule first; each scorer returns None when it has no
    opinion, so the chain below is the whole priority order in four lines.
    """
    query = (query or "").strip()
    if not query or not tab_url:
        return 0, ""
    q_norm, url_norm = _normalize_url(query), _normalize_url(tab_url)
    if q_norm and url_norm == q_norm:
        return 500, "url_exact"
    q_host, q_path, is_url_like = _parse(query)
    if not (is_url_like and q_host):
        return _score_keyword(q_norm, url_norm, tab_title)
    tab_host, tab_path = _tab_host_path(tab_url)
    return (_score_same_site(q_host, q_path, tab_host, tab_path)
            or _score_within(q_norm, tab_host, tab_path)
            or _score_keyword(q_norm, url_norm, tab_title))


def _match_row(tab: dict, score: int, kind: str) -> dict:
    """One entry of the tab picker: the tab's own fields plus the match result.

    `url` stays the tab's *declared* url (never the ws_url fallback used for
    scoring) because the UI writes this field back into the address box.
    """
    return {
        "id": tab.get("id", ""),
        "title": tab.get("title", ""),
        "url": tab.get("url", ""),
        "ws_url": tab.get("ws_url", ""),
        "score": score,
        "kind": kind,
    }


def best_matches(query: str, tabs: Iterable[dict], top_n: int = 5) -> list[dict]:
    """Score tabs once; return the best matches as picker rows (best first)."""
    scored: list[tuple[int, str, dict]] = []
    for tab in tabs or []:
        url = tab.get("url") or tab.get("ws_url") or ""
        title = tab.get("title") or ""
        score, kind = score_tab(query, url, title)
        if score > 0:
            scored.append((score, kind, tab))
    scored.sort(key=lambda item: -item[0])
    return [_match_row(tab, score, kind)
            for score, kind, tab in scored[: max(1, int(top_n))]]
