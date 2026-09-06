"""Message injection into Virt-Chat textarea via CDP (with debugger detail).

Both helpers accept an optional `report(message, level)` callback so the
engine can stream step-by-step results (element search → found/failed →
clickable → action outcome) into the UI log console and run trace.

type_message() uses a verified fallback chain. Some pages (and some message
content) reject a programmatic .value write, so when the first strategy
does not verify the text is instead copied to the clipboard and pasted with
a real Ctrl+V into the focused field, and if the clipboard is unavailable
it is inserted through CDP's Input.insertText.
"""

import asyncio
import json
import logging
from typing import Callable, Optional
from backend.cdp_client import CDPClient
from backend.dom_probe import build_probe, interpret_wait

log = logging.getLogger("chatbot")

# Verified selectors from saved HTML
TEXTAREA_SELECTOR = "textarea[placeholder='Сообщение']"
TEXTAREA_FALLBACK = "textarea#mat-input-1"
SEND_SELECTOR = "button[type='submit']"

# The users-list search box: structural selectors only — "Поиск" is a
# floating <mat-label>, NOT a placeholder, and the #mat-input-N ids are
# regenerated every time the users-list component mounts, so both are
# unusable in selectors.
SEARCH_SELECTOR = ".search-field input[matinput]"
SEARCH_FALLBACK = "input[maxlength='20']"

_SEND_ICON_JS = """(function(){
  var out = {found:false, clicked:false, total:0, error:null};
  try {
    var icons = document.querySelectorAll('mat-icon');
    out.total = icons.length;
    for (var i = 0; i < icons.length; i++) {
      if (icons[i].textContent.trim() === 'send') {
        var btn = icons[i].closest('button');
        if (btn) {
          var st = null; try { st = window.getComputedStyle(btn); } catch(e){}
          var visible = !!(btn.offsetWidth || btn.offsetHeight ||
                           (btn.getClientRects && btn.getClientRects().length));
          var disabled = !!btn.disabled || (st && st.pointerEvents === 'none');
          if (visible && !disabled) {
            btn.click();
            out.clicked = true; out.found = true;
            return JSON.stringify(out);
          }
          out.found = true;
          return JSON.stringify(out);
        }
      }
    }
  } catch (err) { out.error = String(err && err.message || err); }
  return JSON.stringify(out);
})()"""

# Focus the field and select whatever it currently contains so the next
# paste / insertion replaces the old content instead of appending to it.
_SELECT_ALL_JS = """(function(){
  var el = document.querySelector(__SEL__);
  if (!el) return false;
  el.focus();
  try {
    if (typeof el.select === 'function') el.select();
    else if (typeof el.setSelectionRange === 'function') {
      var len = (el.value || '').length;
      el.setSelectionRange(0, len);
    } else {
      var r = document.createRange(); r.selectNodeContents(el);
      var s = window.getSelection();
      if (s) { s.removeAllRanges(); s.addRange(r); }
    }
  } catch (e) {}
  return true;
})()"""

_READ_VALUE_JS = """(function(){
  var el = document.querySelector(__SEL__);
  if (!el) return null;
  return ('value' in el && el.value !== undefined) ? el.value : el.textContent;
})()"""

# True when the cursor is actually inside the field (document.activeElement
# is the element). Returns JSON so the caller can parse it safely.
_FOCUS_STATE_JS = """(function(){
  var el = document.querySelector(__SEL__);
  if (!el) return JSON.stringify({found:false, focused:false});
  return JSON.stringify({found:true, focused:document.activeElement === el,
                         tag:(el.tagName||'').toLowerCase()});
})()"""


def _rep(report: Optional[Callable], message: str, level: str = "info") -> None:
    if report:
        try:
            report(message, level)
        except Exception:
            pass
    log.log(getattr(logging, level.upper(), logging.INFO), "%s", message)


def _js(text: str) -> str:
    """Embed an arbitrary Python string inside a JS string literal.

    json.dumps with ensure_ascii escapes quotes, backslashes, CR, LF and the
    JS line/paragraph separators (U+2028/U+2029) that would otherwise break
    the injected script — a real cause of “page did not accept input”.
    """
    return json.dumps(text or "", ensure_ascii=True)


async def _find_field(cdp: CDPClient, selectors, what: str,
                      report) -> Optional[str]:
    """Return the selector of the first field (from `selectors`) that is
    present. `what` is a human label ("message textarea", "search field")."""
    for sel in selectors:
        _rep(report, f"🔍 Searching {what}: selector '{sel}'", "info")
        try:
            raw = await cdp.evaluate(build_probe(selector=sel))
            res = json.loads(raw) if raw else None
        except Exception as exc:
            _rep(report, f"❌ Probe error: {exc}", "error")
            res = None
        if res and res.get("found"):
            msg, level = interpret_wait(res, f"{what} '{sel}'")
            _rep(report, msg, level)
            return sel
        total = int((res or {}).get("total", 0) or 0)
        _rep(report, f"❌ Failed to find element: {what} '{sel}' "
                     f"(matched {total} node(s))", "warn")
    return None


async def _field_focused(cdp: CDPClient, sel: str) -> bool:
    """True when the cursor is inside the field (activeElement === it)."""
    try:
        raw = await cdp.evaluate(
            _FOCUS_STATE_JS.replace("__SEL__", _js(sel)))
        res = json.loads(raw) if raw else None
        return bool(res and res.get("found") and res.get("focused"))
    except Exception:
        return False


async def _field_value(cdp: CDPClient, sel: str) -> Optional[str]:
    """Read back the field's current content (value or textContent)."""
    try:
        raw = await cdp.evaluate(
            _READ_VALUE_JS.replace("__SEL__", _js(sel)))
    except Exception:
        return None
    return raw if isinstance(raw, str) else (str(raw) if raw else None)


def _same_text(actual: Optional[str], expected: str) -> bool:
    """Tolerant compare: normalise line endings; ignore a single trailing
    newline that some editors append on paste."""
    if actual is None:
        return False
    norm = lambda s: (s or "").replace("\r\n", "\n").replace("\r", "\n")
    a, b = norm(actual), norm(expected)
    return a == b or a.rstrip("\n") == b.rstrip("\n")


async def _focus_and_select_all(cdp: CDPClient, sel: str) -> bool:
    try:
        return bool(await cdp.evaluate(
            _SELECT_ALL_JS.replace("__SEL__", _js(sel))))
    except Exception:
        return False


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


async def _run_type_strategies(cdp: CDPClient, sel: str, text: str,
                               typing_speed_ms: int, report,
                               kind: str) -> bool:
    """Shared verified typing ladder: value setter → Ctrl+V → insertText.

    `kind` selects the log wording — "message" reproduces the original Type
    Message strings byte-for-byte, "search" is used for the users-list
    search box. Returns True only when the page actually accepted the text
    (read-back equals what was sent).
    """
    n = len(text)
    if kind == "search":
        noun, warn_direct, warn_paste = ("search field",
            "⚠ Direct search field value injection was not accepted — "
            "copying the text and pasting with Ctrl+V…",
            "⚠ Clipboard paste not accepted — falling back to CDP "
            "Input.insertText…")
    else:
        noun, warn_direct, warn_paste = ("textarea",
            "⚠ Direct textarea value injection was not accepted — copying "
            "the text and pasting with Ctrl+V…",
            "⚠ Clipboard paste not accepted — falling back to CDP "
            "Input.insertText…")

    attempts = []
    # Strategy 1 — direct value injection (fast path).
    result = await _try_set_value(cdp, sel, text)
    if result == "ok":
        actual = await _field_value(cdp, sel)
        if _same_text(actual, text):
            _rep(report, f"⌨️ Typed {n} char(s) into {noun} '{sel}' "
                         f"(speed {typing_speed_ms} ms/char)", "success")
            log.info("%s typed (%d chars)", noun, n)
            return True
        attempts.append("direct value set was not accepted by the page")
    else:
        attempts.append(f"direct value set failed ({result})")

    # Strategy 2 — clipboard + real Ctrl+V paste into the selected field.
    _rep(report, warn_direct, "warn")
    result = await _try_clipboard_paste(cdp, sel, text)
    if result == "ok":
        actual = await _field_value(cdp, sel)
        if _same_text(actual, text):
            _rep(report, f"📋 Pasted {n} char(s) with Ctrl+V into "
                         f"{noun} '{sel}'", "success")
            log.info("Text pasted via Ctrl+V (%d chars)", n)
            return True
        attempts.append("Ctrl+V paste ran but the page still did not accept it")
    else:
        attempts.append(f"Ctrl+V paste unavailable ({result})")

    # Strategy 3 — CDP-level text insertion into the focused field.
    _rep(report, warn_paste, "warn")
    result = await _try_insert_text(cdp, sel, text)
    if result == "ok":
        actual = await _field_value(cdp, sel)
        if _same_text(actual, text):
            _rep(report, f"⌨️ Inserted {n} char(s) into {noun} '{sel}' "
                         f"(Input.insertText)", "success")
            log.info("Text inserted via Input.insertText (%d chars)", n)
            return True
        attempts.append("insertText ran but the page still did not accept it")
    else:
        attempts.append(f"insertText unavailable ({result})")

    noun_cap = "Search field" if kind == "search" else "Textarea"
    _rep(report, f"❌ {noun_cap} value injection failed (page did not accept "
                 "input): " + "; ".join(attempts), "error")
    return False


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


async def click_send(cdp: CDPClient, report: Optional[Callable] = None) -> bool:
    """Click the send button (submit type, with 'send' icon fallback)."""
    _rep(report, f"🔍 Searching send button: selector '{SEND_SELECTOR}'", "info")
    try:
        raw = await cdp.evaluate(build_probe(selector=SEND_SELECTOR, click=True,
                                             click_root=True))
        res = json.loads(raw) if raw else None
    except Exception as exc:
        _rep(report, f"❌ Probe error: {exc}", "error")
        res = None
    if res and res.get("found") and res.get("clicked"):
        _rep(report, f"✅ Send button found — clickable: yes — clicked ✔", "success")
        log.info("Send button clicked")
        return True
    if res and res.get("found"):
        _rep(report, "⚠ Send button found but NOT clickable "
                     "(hidden or disabled) — trying icon fallback", "warn")
    else:
        _rep(report, "❌ Failed to find element: send button "
                     f"'{SEND_SELECTOR}' — trying mat-icon 'send' fallback", "warn")
    # Fallback: mat-icon 'send' inside a button
    _rep(report, "🔍 Fallback search: mat-icon 'send'", "info")
    try:
        raw2 = await cdp.evaluate(_SEND_ICON_JS)
        res2 = json.loads(raw2) if raw2 else None
    except Exception as exc:
        _rep(report, f"❌ Fallback probe error: {exc}", "error")
        return False
    if not res2:
        _rep(report, "❌ Failed to find element: send icon fallback — no data",
             "error")
        return False
    if res2.get("error"):
        _rep(report, f"❌ Send icon probe error: {res2['error']}", "error")
        return False
    if res2.get("clicked"):
        _rep(report, "✅ Send icon found — clickable: yes — clicked ✔", "success")
        log.info("Send button clicked via icon fallback")
        return True
    if res2.get("found"):
        _rep(report, "⚠ Send icon found but its button is NOT clickable "
                     "(hidden/disabled)", "error")
    else:
        _rep(report, f"❌ Failed to find element: no mat-icon 'send' in "
                     f"{int(res2.get('total', 0))} icon(s) on page", "error")
    return False
