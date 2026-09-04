"""CDP connection and chat-tab discovery (worker thread, async)."""
from __future__ import annotations

from ..engine.errors import OpError


def _endpoint(host: str, port: int) -> str:
    return f"http://{host}:{port}"


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
        raise OpError(f"CDP connect failed ({_endpoint(settings.cdp_host, settings.cdp_port)}): {e}")


async def find_chat_page(browser, pattern: str):
    """First page whose URL contains `pattern` (F-BR-02)."""
    for context in browser.contexts:
        for page in context.pages:
            if pattern in (page.url or ""):
                await page.bring_to_front()
                return page
    raise OpError(f"No open tab matches URL pattern '{pattern}' — open the chat site first")


async def test_connection(settings) -> dict:
    """F-BR-04: cheap pre-run diagnostic (no side effects on the page)."""
    pw = await _start_pw()
    try:
        browser = await pw.chromium.connect_over_cdp(
            _endpoint(settings.cdp_host, settings.cdp_port), timeout=5000)
        urls = [p.url for c in browser.contexts for p in c.pages]
        return {"ok": True, "chat_tab_found":
                any(settings.tab_url_pattern in u for u in urls),
                "pages": len(urls), "tabs": [u for u in urls if u][:10]}
    except Exception as e:
        return {"ok": False, "error": str(e).splitlines()[0][:300]}
    finally:
        await _stop_pw(pw)


async def close_quiet(pw) -> None:
    await _stop_pw(pw)
