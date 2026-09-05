"""Shared visual-confirmation click runner — THE way blocks click elements.

Every action block that locates a DOM element and clicks it MUST go through
this module. It guarantees one uniform, observable contract:

    Phase 1  FIND   — log success/failure, draw a thin RED outline, pause.
    Phase 2  CLICK  — log clickability, draw a thin ORANGE outline, click.

Do NOT hand-roll a probe that calls ``element.click()`` inside a block; see
``docs/AGENT_RULES.md``.

Public API
----------
``find_and_click(cdp, selector=..., ...)``
    Locate an element (optionally by the text of a child) and click it.
``find_and_click_exact(cdp, selector=..., label_selector=..., text=...)``
    Same, but the label text must match exactly — used when a nickname must
    not collide with a longer nickname that merely contains it.
"""

import asyncio
import json
import logging
from typing import Optional

from actions.base_action import ActionResult
from backend.cdp_client import CDPClient
from backend.dom_highlight import (
    build_click_probe,
    build_find_probe,
    interpret_click,
    interpret_click_target,
    interpret_find,
)
from backend.dom_probe import MATCH_CONTAINS, MATCH_EXACT

log = logging.getLogger("chatbot")

#: Short beat between drawing the orange outline and dispatching the click.
CLICK_PAUSE_MS = 250


def _report(engine, message: str, level: str = "info") -> None:
    if engine is not None:
        engine.report(message, level)


def _parse(raw) -> Optional[dict]:
    try:
        res = json.loads(raw) if raw else None
    except (json.JSONDecodeError, TypeError):
        return None
    return res if isinstance(res, dict) else None


async def find_and_click(
    cdp: CDPClient,
    *,
    selector: str,
    label_selector: str = "",
    match_text: str = "",
    match_mode: str = MATCH_CONTAINS,
    click_enabled: bool = True,
    click_selector: str = "",
    highlight_enabled: bool = True,
    confirm_pause_ms: int = 700,
    highlight_ms: int = 1200,
    label: str = "element",
    engine: Optional[object] = None,
) -> str:
    """Run the two-phase find/click and return an :class:`ActionResult` value."""
    if not selector or not str(selector).strip():
        _report(engine, "❌ `selector` is empty — configure the block first", "error")
        return ActionResult.FAIL

    # ── Phase 1: FIND ────────────────────────────────────────────
    _report(engine, f"🔍 FIND phase: searching {label}", "info")
    try:
        raw = await cdp.evaluate(build_find_probe(
            selector=selector,
            label_selector=label_selector or None,
            match_text=match_text or None,
            match_mode=match_mode,
            highlight=highlight_enabled,
            highlight_ms=highlight_ms,
        ))
    except Exception as exc:
        _report(engine, f"❌ FIND failed: CDP error during element search: {exc}",
                "error")
        log.error("visual_click CDP error (find): %s", exc)
        return ActionResult.FAIL

    res = _parse(raw)
    if res is None:
        _report(engine, f"❌ FIND failed: {label} — no data returned from the page "
                        "(page context unavailable?)", "error")
        return ActionResult.FAIL

    _report(engine, f"🔍 Selector matched {int(res.get('total', 0) or 0)} node(s)",
            "info")
    msg, level = interpret_find(res, label)
    _report(engine, msg, level)
    if not res.get("found"):
        log.warning("FIND failed: %s", label)
        return ActionResult.FAIL
    log.info("FIND success: %s (node #%s)", label, res.get("index"))

    # Pause so the user can visually confirm the RED highlight.
    if highlight_enabled and confirm_pause_ms > 0:
        _report(engine, f"⏸ Holding {confirm_pause_ms} ms for visual confirmation…",
                "info")
        await asyncio.sleep(confirm_pause_ms / 1000.0)

    if not click_enabled:
        _report(engine, "ℹ Click disabled for this block — find-only mode", "info")
        return ActionResult.OK if res.get("found") else ActionResult.FAIL

    if not res.get("visible"):
        _report(engine, f"❌ CLICK skipped: {label} was found but is not visible",
                "error")
        return ActionResult.FAIL

    # ── Phase 2: CLICK ───────────────────────────────────────────
    target_desc = (click_selector.strip() if click_selector
                   else (res.get("target_desc") or "the found element"))
    _report(engine, f"🖱 CLICK phase: target = {target_desc}", "info")

    # 2a — highlight the click target in ORANGE, without clicking yet.
    try:
        raw = await cdp.evaluate(build_click_probe(
            click_selector=click_selector or None,
            highlight=highlight_enabled,
            highlight_ms=highlight_ms,
            do_click=False,
        ))
    except Exception as exc:
        _report(engine, f"❌ CLICK failed: CDP error while resolving the click "
                        f"target: {exc}", "error")
        return ActionResult.FAIL

    pre = _parse(raw)
    if pre is None:
        _report(engine, "❌ CLICK failed: no data returned while resolving the "
                        "click target", "error")
        return ActionResult.FAIL
    if pre.get("error"):
        _report(engine, f"❌ CLICK failed: {pre['error']}", "error")
        return ActionResult.FAIL

    msg, level = interpret_click_target(pre)
    _report(engine, msg, level)
    if not pre.get("clickable"):
        log.warning("CLICK target not clickable: %s", label)
        return ActionResult.FAIL

    if highlight_enabled and CLICK_PAUSE_MS > 0:
        await asyncio.sleep(CLICK_PAUSE_MS / 1000.0)

    # 2b — perform the actual click (no second outline; the first is still up).
    try:
        raw = await cdp.evaluate(build_click_probe(
            click_selector=click_selector or None,
            highlight=False,
            do_click=True,
        ))
    except Exception as exc:
        _report(engine, f"❌ CLICK failed: CDP error during click: {exc}", "error")
        return ActionResult.FAIL

    done = _parse(raw)
    if done is None:
        _report(engine, "❌ CLICK failed: no data returned from the click", "error")
        return ActionResult.FAIL

    msg, level = interpret_click(done, label)
    _report(engine, msg, level)
    if done.get("clicked"):
        log.info("CLICK success: %s", label)
        return ActionResult.OK
    log.warning("CLICK failed: %s", label)
    return ActionResult.FAIL


async def find_and_click_exact(cdp: CDPClient, *, text: str, **kw) -> str:
    """:func:`find_and_click` with an exact (not substring) text match."""
    kw.pop("match_mode", None)
    return await find_and_click(cdp, match_text=text, match_mode=MATCH_EXACT, **kw)
