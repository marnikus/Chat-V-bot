"""Message injection into Virt-Chat textarea via CDP (with debugger detail).

Both helpers accept an optional `report(message, level)` callback so the
engine can stream step-by-step results (element search → found/failed →
clickable → action outcome) into the UI log console and run trace.

type_message() uses a verified fallback chain. Some pages (and some message
content) reject a programmatic .value write, so when the first strategy
does not verify the text is instead copied to the clipboard and pasted with
a real Ctrl+V into the focused field, and if the clipboard is unavailable
it is inserted through CDP's Input.insertText.

Family map (Round G3, RULE 18): this seam owns the two public entries
(type_message, type_search) and re-exports the family's public surface.
Field discovery and the field JS payloads live in
`backend.message_injector_field`, the verified typing ladder in
`backend.message_injector_type`, the send-button family in
`backend.message_injector_send`. One-way imports: seam → siblings,
type/send → field; every public name stays reachable here unchanged.
"""

import asyncio
from typing import Callable, Optional

from backend.cdp_client import CDPClient
from backend.message_injector_field import (
    SEARCH_FALLBACK, SEARCH_SELECTOR, TEXTAREA_FALLBACK, TEXTAREA_SELECTOR,
    _field_focused, _find_field, _rep)
# Tests read _js/_same_text through the seam; re-export only (the
# db_deletion.py shim's discipline for names the seam itself never calls).
from backend.message_injector_field import (  # noqa: F401  # pylint: disable=unused-import
    _js, _same_text)
from backend.message_injector_send import SEND_SELECTOR, click_send
from backend.message_injector_type import _run_type_strategies
# tests/test_search_users.py runs inspect.getsource(injector._try_set_value),
# which follows __module__ to the sibling; re-export only.
from backend.message_injector_type import (  # noqa: F401  # pylint: disable=unused-import
    _try_set_value)

__all__ = ["SEARCH_FALLBACK", "SEARCH_SELECTOR", "SEND_SELECTOR",
           "TEXTAREA_FALLBACK", "TEXTAREA_SELECTOR",
           "click_send", "type_message", "type_search"]

async def type_message(cdp: CDPClient, text: str, typing_speed_ms: int = 30,
                       report: Optional[Callable] = None) -> bool:
    """Put `text` into the message textarea, verifying the page accepted it.

    Tries, in order: native value setter → clipboard Ctrl+V paste → CDP
    Input.insertText. The first strategy whose write verifies wins; the log
    records which one delivered the text.
    """
    sel = await _find_field(cdp, (TEXTAREA_SELECTOR, TEXTAREA_FALLBACK),
                            "message textarea", report)
    if not sel:
        _rep(report, "❌ Type Message aborted: no message textarea found", "error")
        return False
    if not text:
        _rep(report, "⚠ Message text is empty — nothing typed", "warn")
        return False
    return await _run_type_strategies(cdp, sel, text, typing_speed_ms,
                                      report, "message")


async def type_search(cdp: CDPClient, text: str,
                      report: Optional[Callable] = None) -> bool:
    """Type `text` into the users-list Поиск search box, VERIFIED.

    Beyond the same strategy ladder as Type Message, this checks the two
    things that were missing: the field was really clicked and the cursor
    is inside it (document.activeElement === the input; a real click on the
    field centre is issued first when needed), and the text really landed
    in the box (value read-back). Every stage is logged.
    """
    sel = await _find_field(cdp, (SEARCH_SELECTOR, SEARCH_FALLBACK),
                            "search field", report)
    if not sel:
        _rep(report, "❌ Search Users aborted: no search field found", "error")
        return False
    if not text:
        _rep(report, "⚠ Search text is empty — nothing typed", "warn")
        return False

    # ── focus: make sure the cursor is inside the field ──────────
    if await _field_focused(cdp, sel):
        _rep(report, "⌨️ Search field already focused — cursor inside", "success")
    else:
        _rep(report, "⚠ Search field not focused — clicking it to place the "
                     "cursor…", "warn")
        try:
            rect = await cdp.get_element_rect(sel)
            if rect:
                await cdp.click_at(rect["x"] + rect["width"] / 2,
                                   rect["y"] + rect["height"] / 2)
                await asyncio.sleep(0.1)
        except Exception as exc:
            _rep(report, f"❌ Could not click the search field: {exc}",
                 "error")
        if not await _field_focused(cdp, sel):
            _rep(report, "❌ Search field could not be focused — the cursor "
                         "is not inside it", "error")
            return False
        _rep(report, "✅ Search field clicked — cursor inside", "success")

    return await _run_type_strategies(cdp, sel, text, 0, report, "search")
