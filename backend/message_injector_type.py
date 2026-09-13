"""The verified typing ladder (injector family 2/3).

Owns the three write strategies — native value setter, clipboard + real
Ctrl+V paste, CDP ``Input.insertText`` — and the shared ladder that runs
them in order, verifying each write by reading the field back. Split out
of ``backend.message_injector`` (Round G3, RULE 18); the ladder itself was
redesigned per RULE 19 §19.5: one context dataclass, one shared
acceptance check, one small function per rung, wording byte-identical to
the previous 70-line monolith (pinned by the composer/search tests).
"""

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Callable, Optional

from backend.cdp_client import CDPClient
from backend.message_injector_field import (
    _field_value, _focus_and_select_all, _js, _rep, _same_text)

log = logging.getLogger("chatbot")

async def _try_set_value(cdp: CDPClient, sel: str, text: str) -> Optional[str]:
    """Strategy 1 — native prototype setter + input/change events.

    The value setter is taken from the element's OWN prototype
    (HTMLInputElement for <input>, HTMLTextAreaElement for <textarea>) —
    calling the textarea setter on an <input> silently misbehaves in some
    browsers.
    """
    js = """(function(){
        var ta = document.querySelector(__SEL__);
        if(!ta) return 'no-element';
        ta.focus();
        var isTextarea = ta.tagName && ta.tagName.toLowerCase() === 'textarea';
        var proto = isTextarea ? window.HTMLTextAreaElement.prototype
                               : window.HTMLInputElement.prototype;
        var setter = proto ? Object.getOwnPropertyDescriptor(proto,'value').set
                           : null;
        try {
            if (setter) setter.call(ta, __TEXT__);
            else ta.value = __TEXT__;
        } catch (e) {
            try { ta.value = __TEXT__; }
            catch (e2) { return 'error'; }
        }
        ta.dispatchEvent(new Event('input',{bubbles:true}));
        ta.dispatchEvent(new Event('change',{bubbles:true}));
        return 'ok';
    })()"""
    js = js.replace("__SEL__", _js(sel)).replace("__TEXT__", _js(text))
    try:
        result = await cdp.evaluate(js)
    except Exception as exc:
        return f"error:{exc}"
    return result if isinstance(result, str) else str(result)


async def _grant_clipboard(cdp: CDPClient) -> bool:
    """Let the page script write the browser clipboard for its own origin."""
    try:
        origin = await cdp.evaluate("location.origin")
        if not origin or origin in ("null", "undefined"):
            return False
        await cdp.send("Browser.grantPermissions", {
            "origin": origin,
            "permissions": ["clipboardReadWrite", "clipboardSanitizedWrite"]})
        return True
    except Exception:
        return False


async def _try_clipboard_paste(cdp: CDPClient, sel: str,
                               text: str) -> Optional[str]:
    """Strategy 2 — write the text to the clipboard and paste with Ctrl+V."""
    if not await _focus_and_select_all(cdp, sel):
        return "could-not-focus"
    await _grant_clipboard(cdp)
    try:
        js = ("(async function(){ try {"
              "  if (!navigator.clipboard) return 'no-clipboard-api';"
              "  await navigator.clipboard.writeText(" + _js(text) + ");"
              "  return 'ok';"
              "} catch (e) { return 'err:' + String(e && e.message || e); }"
              "})()")
        raw = await cdp.evaluate(js)
    except Exception as exc:
        raw = f"err:{exc}"
    if raw != "ok":
        return f"clipboard-write:{raw}"
    try:
        # A real Ctrl+V: the browser performs the paste default action into
        # the focused field, exactly like a human paste.
        for ev_type in ("rawKeyDown", "keyUp"):
            await cdp.send("Input.dispatchKeyEvent", {
                "type": ev_type, "modifiers": 2, "key": "v", "code": "KeyV",
                "windowsVirtualKeyCode": 86, "nativeVirtualKeyCode": 86})
    except Exception as exc:
        return f"key-event:{exc}"
    await asyncio.sleep(0.2)  # let the page's own handlers run
    return "ok"


async def _try_insert_text(cdp: CDPClient, sel: str, text: str) -> Optional[str]:
    """Strategy 3 — CDP Input.insertText into the focused editable."""
    if not await _focus_and_select_all(cdp, sel):
        return "could-not-focus"
    try:
        await cdp.send("Input.insertText", {"text": text})
    except Exception as exc:
        return f"insert:{exc}"
    await asyncio.sleep(0.1)
    return "ok"


@dataclass
class _TypeCtx:
    """One ladder run's inputs (parameters become data — the F5 pattern).

    ``attempts`` collects the per-rung failure phrasings for the final
    joined error line, exactly as the monolithic ladder did.
    """

    cdp: CDPClient
    sel: str
    text: str
    speed_ms: int
    report: Optional[Callable]
    #: "message" or "search" — selects the ladder's log wording
    kind: str = "message"
    attempts: list = field(default_factory=list)
    #: derived from `kind` in `__post_init__` (the `_ladder_words` pair)
    noun: str = ""
    warn_direct: str = ""
    warn_paste: str = ""

    def __post_init__(self):
        self.noun, self.warn_direct, self.warn_paste = _ladder_words(self.kind)

    @property
    def noun_cap(self) -> str:
        """The capitalised noun of the final failure line."""
        return "Search field" if self.kind == "search" else "Textarea"


def _ladder_words(kind: str) -> tuple:
    """The ladder's two wording branches, selected by ``kind``."""
    if kind == "search":
        return ("search field",
                "⚠ Direct search field value injection was not accepted — "
                "copying the text and pasting with Ctrl+V…",
                "⚠ Clipboard paste not accepted — falling back to CDP "
                "Input.insertText…")
    return ("textarea",
            "⚠ Direct textarea value injection was not accepted — copying "
            "the text and pasting with Ctrl+V…",
            "⚠ Clipboard paste not accepted — falling back to CDP "
            "Input.insertText…")


async def _accepted(ctx: _TypeCtx, strategy) -> tuple:
    """Run one rung and verify it: the check every strategy shared.

    Returns ``(verified, result)`` — ``result`` is the strategy's raw
    return (``"ok"`` or a diagnostic string); ``verified`` is True only
    when the strategy reported ``"ok"`` AND the field read-back equals
    what was sent.
    """
    result = await strategy(ctx.cdp, ctx.sel, ctx.text)
    if result != "ok":
        return False, result
    actual = await _field_value(ctx.cdp, ctx.sel)
    return _same_text(actual, ctx.text), result


async def _attempt_set_value(ctx: _TypeCtx) -> bool:
    """Rung 1 — direct value injection (fast path)."""
    verified, result = await _accepted(ctx, _try_set_value)
    if verified:
        n = len(ctx.text)
        _rep(ctx.report, f"⌨️ Typed {n} char(s) into {ctx.noun} '{ctx.sel}' "
                         f"(speed {ctx.speed_ms} ms/char)", "success")
        log.info("%s typed (%d chars)", ctx.noun, n)
        return True
    if result == "ok":
        ctx.attempts.append("direct value set was not accepted by the page")
    else:
        ctx.attempts.append(f"direct value set failed ({result})")
    return False


async def _attempt_paste(ctx: _TypeCtx) -> bool:
    """Rung 2 — clipboard + real Ctrl+V paste into the selected field."""
    verified, result = await _accepted(ctx, _try_clipboard_paste)
    if verified:
        n = len(ctx.text)
        _rep(ctx.report, f"📋 Pasted {n} char(s) with Ctrl+V into "
                         f"{ctx.noun} '{ctx.sel}'", "success")
        log.info("Text pasted via Ctrl+V (%d chars)", n)
        return True
    if result == "ok":
        ctx.attempts.append(
            "Ctrl+V paste ran but the page still did not accept it")
    else:
        ctx.attempts.append(f"Ctrl+V paste unavailable ({result})")
    return False


async def _attempt_insert_text(ctx: _TypeCtx) -> bool:
    """Rung 3 — CDP-level text insertion into the focused field."""
    verified, result = await _accepted(ctx, _try_insert_text)
    if verified:
        n = len(ctx.text)
        _rep(ctx.report, f"⌨️ Inserted {n} char(s) into {ctx.noun} "
                         f"'{ctx.sel}' (Input.insertText)", "success")
        log.info("Text inserted via Input.insertText (%d chars)", n)
        return True
    if result == "ok":
        ctx.attempts.append(
            "insertText ran but the page still did not accept it")
    else:
        ctx.attempts.append(f"insertText unavailable ({result})")
    return False


async def _run_type_strategies(ctx: _TypeCtx) -> bool:
    """Shared verified typing ladder: value setter → Ctrl+V → insertText.

    `ctx.kind` selects the log wording — "message" reproduces the original
    Type Message strings byte-for-byte, "search" is used for the users-list
    search box. Returns True only when the page actually accepted the text
    (read-back equals what was sent).
    """
    if await _attempt_set_value(ctx):
        return True
    _rep(ctx.report, ctx.warn_direct, "warn")
    if await _attempt_paste(ctx):
        return True
    _rep(ctx.report, ctx.warn_paste, "warn")
    if await _attempt_insert_text(ctx):
        return True
    _rep(ctx.report,
         f"❌ {ctx.noun_cap} value injection failed (page did not accept "
         "input): " + "; ".join(ctx.attempts), "error")
    return False
