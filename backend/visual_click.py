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
import dataclasses
import json
import logging
from dataclasses import dataclass
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


@dataclass(frozen=True, slots=True)
class ClickRequest:
    """What to find, what to click, and how long to make the user look.

    The ten keyword arguments `find_and_click()` takes, in one value: a block
    can build it once (from its own settings) and hand it to `run_click()`,
    and the phases below take one argument instead of threading ten.
    `find_and_click()` stays the documented entry point — RULE 1 says every
    block clicks through it — and is now an adapter over `run_click()`.
    """

    selector: str = ""
    label_selector: str = ""
    match_text: str = ""
    match_mode: str = MATCH_CONTAINS
    click_enabled: bool = True
    click_selector: str = ""
    highlight_enabled: bool = True
    confirm_pause_ms: int = 700
    highlight_ms: int = 1200
    #: how the two log lines call the thing we are after
    label: str = "element"

    @classmethod
    def from_kwargs(cls, **kwargs) -> "ClickRequest":
        """From a block's `to_dict()` — unknown keys are dropped, not fatal."""
        known = {f.name for f in dataclasses.fields(cls)}
        return cls(**{k: v for k, v in kwargs.items() if k in known})

    # ── the probes this request turns into ───────────────────────
    def find_probe(self) -> str:
        return build_find_probe(
            selector=self.selector,
            label_selector=self.label_selector or None,
            match_text=self.match_text or None,
            match_mode=self.match_mode,
            highlight=self.highlight_enabled,
            highlight_ms=self.highlight_ms,
        )

    def staged_probe(self) -> str:
        """The ORANGE outline, without clicking yet."""
        return build_click_probe(
            click_selector=self.click_selector or None,
            highlight=self.highlight_enabled,
            highlight_ms=self.highlight_ms,
            do_click=False,
        )

    def click_probe(self) -> str:
        return build_click_probe(click_selector=self.click_selector or None,
                                 highlight=False, do_click=True)

    def holds_confirmation(self) -> bool:
        return bool(self.highlight_enabled and self.confirm_pause_ms > 0)

    def click_target_description(self, find_result: dict) -> str:
        return (self.click_selector.strip() if self.click_selector
                else (find_result.get("target_desc") or "the found element"))


async def find_phase(cdp: CDPClient, request: ClickRequest,
                     engine: Optional[object] = None) -> Optional[dict]:
    """Phase 1: locate it, say what was found, draw the RED outline.

    None means "do not go on" — and the reason is already in the log, in the
    wording the debugger pane shows.
    """
    _report(engine, f"🔍 FIND phase: searching {request.label}", "info")
    try:
        raw = await cdp.evaluate(request.find_probe())
    except Exception as exc:
        _report(engine, f"❌ FIND failed: CDP error during element search: {exc}",
                "error")
        log.error("visual_click CDP error (find): %s", exc)
        return None
    res = _parse(raw)
    if res is None:
        _report(engine, f"❌ FIND failed: {request.label} — no data returned "
                        "from the page (page context unavailable?)", "error")
        return None
    _report(engine, f"🔍 Selector matched {int(res.get('total', 0) or 0)} "
                    "node(s)", "info")
    msg, level = interpret_find(res, request.label)
    _report(engine, msg, level)
    if not res.get("found"):
        log.warning("FIND failed: %s", request.label)
        return None
    log.info("FIND success: %s (node #%s)", request.label, res.get("index"))
    return res


async def click_phase(cdp: CDPClient, request: ClickRequest, found: dict,
                      engine: Optional[object] = None) -> str:
    """Phase 2: ORANGE outline on the click target, then the click itself."""
    if not request.click_enabled:
        _report(engine, "ℹ Click disabled for this block — find-only mode",
                "info")
        return ActionResult.OK if found.get("found") else ActionResult.FAIL
    if not found.get("visible"):
        _report(engine, f"❌ CLICK skipped: {request.label} was found but is "
                        "not visible", "error")
        return ActionResult.FAIL

    target = request.click_target_description(found)
    _report(engine, f"🖱 CLICK phase: target = {target}", "info")
    pre = await _stage(cdp, request, engine)
    if pre is None or not pre.get("clickable"):
        return ActionResult.FAIL
    if request.highlight_enabled and CLICK_PAUSE_MS > 0:
        await asyncio.sleep(CLICK_PAUSE_MS / 1000.0)
    done = await _dispatch(cdp, request, engine)
    if done is None:
        return ActionResult.FAIL
    msg, level = interpret_click(done, request.label)
    _report(engine, msg, level)
    if done.get("clicked"):
        log.info("CLICK success: %s", request.label)
        return ActionResult.OK
    log.warning("CLICK failed: %s", request.label)
    return ActionResult.FAIL


async def _stage(cdp, request, engine) -> Optional[dict]:
    """Resolve and highlight the click target — and refuse it if unusable."""
    try:
        raw = await cdp.evaluate(request.staged_probe())
    except Exception as exc:
        _report(engine, f"❌ CLICK failed: CDP error while resolving the click "
                        f"target: {exc}", "error")
        return None
    pre = _parse(raw)
    if pre is None:
        _report(engine, "❌ CLICK failed: no data returned while resolving the "
                        "click target", "error")
        return None
    if pre.get("error"):
        _report(engine, f"❌ CLICK failed: {pre['error']}", "error")
        return None
    msg, level = interpret_click_target(pre)
    _report(engine, msg, level)
    if not pre.get("clickable"):
        log.warning("CLICK target not clickable: %s", request.label)
        return None
    return pre


async def _dispatch(cdp, request, engine) -> Optional[dict]:
    """The actual click. No second outline: the orange one is still up."""
    try:
        raw = await cdp.evaluate(request.click_probe())
    except Exception as exc:
        _report(engine, f"❌ CLICK failed: CDP error during click: {exc}",
                "error")
        return None
    done = _parse(raw)
    if done is None:
        _report(engine, "❌ CLICK failed: no data returned from the click",
                "error")
    return done


async def run_click(cdp: CDPClient, request: ClickRequest,
                    engine: Optional[object] = None) -> str:
    """Both phases, in order, as one call."""
    if not request.selector or not str(request.selector).strip():
        _report(engine, "❌ `selector` is empty — configure the block first",
                "error")
        return ActionResult.FAIL
    found = await find_phase(cdp, request, engine)
    if found is None:
        return ActionResult.FAIL
    if request.holds_confirmation():
        _report(engine, f"⏸ Holding {request.confirm_pause_ms} ms for visual "
                        "confirmation…", "info")
        await asyncio.sleep(request.confirm_pause_ms / 1000.0)
    return await click_phase(cdp, request, found, engine)


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
    """Run the two-phase find/click and return an :class:`ActionResult` value.

    The thin façade over :func:`run_click`: this signature is what every
    block in `actions/` calls (RULE 1), so it stays exactly as it is.
    """
    return await run_click(
        cdp,
        ClickRequest(selector=selector, label_selector=label_selector,
                     match_text=match_text, match_mode=match_mode,
                     click_enabled=click_enabled,
                     click_selector=click_selector,
                     highlight_enabled=highlight_enabled,
                     confirm_pause_ms=confirm_pause_ms,
                     highlight_ms=highlight_ms, label=label),
        engine=engine)


async def find_and_click_exact(cdp: CDPClient, *, text: str, **kw) -> str:
    """:func:`find_and_click` with an exact (not substring) text match."""
    kw.pop("match_mode", None)
    return await find_and_click(cdp, match_text=text, match_mode=MATCH_EXACT, **kw)
