"""CDP connection and chat-tab discovery (worker thread, async)."""
from __future__ import annotations

from ..engine.errors import OpError


def _endpoint(host: str, port: int) -> str:
    return f"http://{host}:{port}"


def tab_matches(pattern: str, url: str) -> bool:
    """Substring match; empty pattern or '*' means 'any real tab'."""
    pat = (pattern or "").strip()
    if pat in ("", "*"):
        return bool(url) and url != "about:blank"
    return pat in (url or "")


async def _start_pw():
    from playwright.async_api import async_playwright
    return await async_playwright().start()


async def _stop_pw(pw) -> None:
    try:
        await pw.stop()
    except Exception:
        pass


async def connect_and_find(settings) -> tuple:
    """Connect over CDP and locate the chat tab. Returns (pw, browser, page)."""
    pw = await _start_pw()
    try:
        browser = await pw.chromium.connect_over_cdp(
            _endpoint(settings.cdp_host, settings.cdp_port), timeout=8000)
        page = await find_chat_page(browser, settings.tab_url_pattern)
        return pw, browser, page
    except Exception as e:
        await _stop_pw(pw)
        hint = ""
        if "ECONNREFUSED" in str(e) or "refused" in str(e).lower():
            hint = (" — is Chrome running with --remote-debugging-port="
                    f"{settings.cdp_port}? (Chrome 136+ also requires a "
                    "separate --user-data-dir; verify at "
                    f"http://{settings.cdp_host}:{settings.cdp_port}/json/version)")
        raise OpError(f"CDP connect failed ({_endpoint(settings.cdp_host, settings.cdp_port)}): {e}{hint}")


async def find_chat_page(browser, pattern: str):
    """First page whose URL matches `pattern` (substring; '*' = any tab)."""
    pages = [p for c in browser.contexts for p in c.pages]
    for page in pages:
        if tab_matches(pattern, page.url or ""):
            await page.bring_to_front()
            return page
    open_urls = [p.url for p in pages if p.url and p.url != "about:blank"][:5]
    raise OpError(f"No tab matches pattern '{pattern}'. Open tabs: "
                  f"{open_urls or 'none (only blank tabs)'}")


async def test_connection(settings) -> dict:
    """F-BR-04: cheap pre-run diagnostic (no side effects on the page)."""
    pw = await _start_pw()
    try:
        browser = await pw.chromium.connect_over_cdp(
            _endpoint(settings.cdp_host, settings.cdp_port), timeout=5000)
        urls = [p.url for c in browser.contexts for p in c.pages]
        found = any(tab_matches(settings.tab_url_pattern, u) for u in urls)
        return {"ok": True, "chat_tab_found": found, "pages": len(urls),
                "tabs": [u for u in urls if u][:10]}
    except Exception as e:
        return {"ok": False, "error": str(e).splitlines()[0][:300]}
    finally:
        await _stop_pw(pw)


async def close_quiet(pw) -> None:
    await _stop_pw(pw)
