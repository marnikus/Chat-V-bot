"""The wire of the CDP client — socket lifecycle, framing, tab discovery.

Part of the `cdp_client` family (facade: `backend/cdp_client.py`).
Everything that talks to the WebSocket lives here: the connect/disconnect
lifecycle, the id-stamped request/response framing, the receive loop, tab
discovery over HTTP and the command helpers (script injection, cookies,
input events, file-input injection). The priority lease and `TabInfo` stay
on the facade because the public API snapshot pins them to
`backend.cdp_client` (tests/unit/backend/backend_api_snapshot.json).

Everything is a function taking the client, which owns the mutable state
(`_ws`, `_cmd_id`, `_pending`, `_connected`, `_receive_task`) and the Qt
signals — so the historical test seam (shadowing `cdp.send`, assigning
`cdp._ws` / `cdp._connected`) works exactly as before the split, and no
cycle can form: this module never imports the facade.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any
from urllib.parse import urlparse

import aiohttp
import websockets

log = logging.getLogger("chatbot")


class BrowserTransport:
    """Production adapter; only this boundary acquires browser sockets/HTTP."""

    async def connect(self, ws_url: str):
        return await websockets.connect(ws_url, max_size=50 * 1024 * 1024,
                                        open_timeout=10, close_timeout=5)

    async def discover(self, base_url: str) -> list[dict]:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{base_url}/json/list",
                                   timeout=aiohttp.ClientTimeout(total=5)) as r:
                return await r.json() if r.status == 200 else []


def _domain_matches(host: str, domain: str) -> bool:
    """Whether a cookie's domain covers the requested host.

    A leading dot is already stripped by the caller, so `example.com` covers
    both itself and every subdomain of it.
    """
    return domain == host or host.endswith("." + domain)


def _cookie_pairs(cookies: list, host: str) -> list[str]:
    """`name=value` for every cookie that applies to `host`.

    With no host (or a cookie with no domain) there is nothing to match
    against, so the cookie is kept — the caller asked for "the cookies".
    """
    pairs = []
    for cookie in cookies:
        name, value = cookie.get("name"), cookie.get("value")
        if not name:
            continue
        domain = str(cookie.get("domain") or "").strip().lower().lstrip(".")
        if host and domain and not _domain_matches(host, domain):
            continue
        pairs.append(f"{name}={value or ''}")
    return pairs


# ── the connection lifecycle ──────────────────────────────────────
async def open_client(client, ws_url: str) -> bool:
    """Connect, enable the four domains and start the receive loop."""
    await close_client(client)
    try:
        client._ws = await client._transport.connect(ws_url)
        client._connected = True
        client._receive_task = asyncio.create_task(receive_loop(client))
        for dom in ("Page", "DOM", "Runtime", "Network"):
            await client.send(f"{dom}.enable")
        log.info("CDP connected: %s", ws_url[:80])
        client.connected.emit()
        return True
    except Exception as e:
        log.error("CDP connect failed: %s", e)
        client.error.emit(str(e))
        return False


async def close_client(client) -> None:
    client._connected = False
    if client._receive_task:
        client._receive_task.cancel()
        client._receive_task = None
    if client._ws:
        try:
            await client._ws.close()
        except Exception:
            pass
        client._ws = None
    client._pending.clear()
    client.disconnected.emit()


async def raw_send(client, method: str, params: dict | None = None) -> dict:
    if not client._ws:
        raise ConnectionError("CDP not connected")
    client._cmd_id += 1
    fut: asyncio.Future = asyncio.get_event_loop().create_future()
    client._pending[client._cmd_id] = fut
    await client._ws.send(json.dumps({"id": client._cmd_id, "method": method,
                                      "params": params or {}}))
    return await asyncio.wait_for(fut, timeout=30)


async def receive_loop(client) -> None:
    try:
        async for raw in client._ws:
            data = json.loads(raw)
            mid = data.get("id")
            if mid and mid in client._pending:
                client._pending.pop(mid).set_result(data)
            elif data.get("method"):
                client._dispatch_event(data)
    except (websockets.ConnectionClosed, asyncio.CancelledError):
        pass
    except Exception as e:
        log.error("CDP receive error: %s", e)
    finally:
        client._connected = False
        client.disconnected.emit()


# ── tab discovery (plain HTTP, not the socket) ────────────────────
async def _fetch_tab_list(client) -> list:
    """The raw `/json/list` payload (empty when the endpoint is unhappy)."""
    return await client._transport.discover(client.base_url)


async def fetch_tabs(client) -> list[dict]:
    """Page-type entries from `/json/list` (empty when the endpoint fails).

    Returns raw dicts — the facade maps them onto `TabInfo`, which the API
    snapshot pins to `backend.cdp_client` (and importing it here would close
    an import cycle with the facade).
    """
    try:
        items = await _fetch_tab_list(client)
    except Exception as e:                     # noqa: BLE001
        log.warning("Tab discovery failed: %s", e)
        return []
    return [item for item in items if item.get("type") == "page"]


# ── command helpers (all go through client.send, so a test that
# shadows `cdp.send` with a fake still intercepts every one of them) ──
async def add_binding(client, name: str) -> bool:
    """Expose `window[name](payload)` as a `Runtime.bindingCalled` event."""
    try:
        await client.send("Runtime.addBinding", {"name": name})
        return True
    except Exception as e:                # noqa: BLE001
        log.warning("addBinding(%s) failed: %s", name, e)
        return False


async def add_script_on_new_document(client, source: str) -> str:
    """Re-inject `source` after every navigation. Returns its identifier."""
    try:
        res = await client.send(
            "Page.addScriptToEvaluateOnNewDocument", {"source": source})
        return res.get("result", {}).get("identifier", "")
    except Exception as e:                # noqa: BLE001
        log.warning("addScriptToEvaluateOnNewDocument failed: %s", e)
        return ""


async def remove_script_on_new_document(client, identifier: str) -> bool:
    if not identifier:
        return False
    try:
        await client.send("Page.removeScriptToEvaluateOnNewDocument",
                          {"identifier": identifier})
        return True
    except Exception:                     # noqa: BLE001
        return False


async def evaluate(client, expression: str) -> Any:
    r = await client.send("Runtime.evaluate",
                          {"expression": expression, "returnByValue": True,
                           "awaitPromise": True})
    return r.get("result", {}).get("result", {}).get("value")


async def cookie_header(client, url: str = "") -> str:
    """A `Cookie` header string for the given origin.

    Used by the media cache's Python download path: the browser tab can
    load `images.virt-chat.com` through an `<img>` tag with the session
    cookies (no CORS), but the in-page `fetch()` needed for the old cache
    can be blocked by CORS. Downloading from Python with the same cookies
    bypasses that while still authenticating like the page.
    """
    try:
        result = await client.send("Network.getAllCookies")
    except Exception as e:                     # noqa: BLE001
        log.debug("getCookies failed: %s", e)
        return ""
    cookies = result.get("result", {}).get("cookies", []) or []
    host = str(urlparse(str(url or "")).hostname or "").lower()
    return "; ".join(_cookie_pairs(cookies, host))


async def click_at(client, x: float, y: float) -> None:
    for t in ("mousePressed", "mouseReleased"):
        await client.send("Input.dispatchMouseEvent",
                          {"type": t, "x": x, "y": y, "button": "left",
                           "clickCount": 1})


async def mouse_wheel(client, dx: float, dy: float,
                      x: float, y: float) -> None:
    await client.send("Input.dispatchMouseEvent",
                      {"type": "mouseWheel", "x": x, "y": y,
                       "deltaX": dx, "deltaY": dy})


async def get_element_rect(client, selector: str) -> dict | None:
    js = (f"(function(){{var e=document.querySelector('{selector}');"
          f"if(!e)return null;var r=e.getBoundingClientRect();"
          f"return{{x:r.x,y:r.y,width:r.width,height:r.height}};}})()")
    return await evaluate(client, js)


async def set_file_input_files(client, selector: str,
                               files: list[str]) -> None:
    res = await client.send("DOM.getDocument")
    root_id = res.get("result", {}).get("root", {}).get("nodeId", 0)
    res = await client.send("DOM.querySelector",
                            {"nodeId": root_id, "selector": selector})
    node_id = res.get("result", {}).get("nodeId", 0)
    if node_id:
        await client.send("DOM.setFileInputFiles",
                          {"files": files, "nodeId": node_id})
