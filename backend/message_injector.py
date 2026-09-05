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


async def _find_textarea(cdp: CDPClient, report) -> Optional[str]:
    """Return the selector of the first textarea that is present."""
    for sel in (TEXTAREA_SELECTOR, TEXTAREA_FALLBACK):
        _rep(report, f"🔍 Searching message textarea: selector '{sel}'", "info")
        try:
            raw = await cdp.evaluate(build_probe(selector=sel))
            res = json.loads(raw) if raw else None
        except Exception as exc:
            _rep(report, f"❌ Probe error: {exc}", "error")
            res = None
        if res and res.get("found"):
            msg, level = interpret_wait(res, f"textarea '{sel}'")
            _rep(report, msg, level)
            return sel
        total = int((res or {}).get("total", 0) or 0)
        _rep(report, f"❌ Failed to find element: textarea '{sel}' "
                     f"(matched {total} node(s))", "warn")
    return None


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
    """Strategy 1 — native prototype setter + input/change events."""
    js = """(function(){
        var ta = document.querySelector(__SEL__);
        if(!ta) return 'no-element';
        ta.focus();
        var setter = Object.getOwnPropertyDescriptor(
            window.HTMLTextAreaElement.prototype,'value').set;
        if (!setter && ta.tagName !== 'TEXTAREA') {
            setter = Object.getOwnPropertyDescriptor(
                window.HTMLInputElement.prototype,'value').set;
        }
        try {
            setter.call(ta, __TEXT__);
        } catch (e) {
            ta.value = __TEXT__;
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


async def type_message(cdp: CDPClient, text: str, typing_speed_ms: int = 30,
                       report: Optional[Callable] = None) -> bool:
    """Put `text` into the message field, verifying the page accepted it.

    Tries, in order: native value setter → clipboard Ctrl+V paste → CDP
    Input.insertText. The first strategy whose write verifies wins; the log
    records which one delivered the text.
    """
    sel = await _find_textarea(cdp, report)
    if not sel:
        _rep(report, "❌ Type Message aborted: no message textarea found", "error")
        return False
    if not text:
        _rep(report, "⚠ Message text is empty — nothing typed", "warn")
        return False

    attempts = []
    # Strategy 1 — direct value injection (fast path).
    result = await _try_set_value(cdp, sel, text)
    if result == "ok":
        actual = await _field_value(cdp, sel)
        if _same_text(actual, text):
            _rep(report, f"⌨️ Typed {len(text)} char(s) into textarea '{sel}' "
                         f"(speed {typing_speed_ms} ms/char)", "success")
            log.info("Message typed (%d chars)", len(text))
            return True
        attempts.append("direct value set was not accepted by the page")
    else:
        attempts.append(f"direct value set failed ({result})")

    # Strategy 2 — clipboard + real Ctrl+V paste into the selected field.
    _rep(report, "⚠ Direct textarea value injection was not accepted — "
                 "copying the text and pasting with Ctrl+V…", "warn")
    result = await _try_clipboard_paste(cdp, sel, text)
    if result == "ok":
        actual = await _field_value(cdp, sel)
        if _same_text(actual, text):
            _rep(report, f"📋 Pasted {len(text)} char(s) with Ctrl+V into "
                         f"textarea '{sel}'", "success")
            log.info("Message pasted via Ctrl+V (%d chars)", len(text))
            return True
        attempts.append("Ctrl+V paste ran but the page still did not accept it")
    else:
        attempts.append(f"Ctrl+V paste unavailable ({result})")

    # Strategy 3 — CDP-level text insertion into the focused field.
    _rep(report, "⚠ Clipboard paste not accepted — falling back to CDP "
                 "Input.insertText…", "warn")
    result = await _try_insert_text(cdp, sel, text)
    if result == "ok":
        actual = await _field_value(cdp, sel)
        if _same_text(actual, text):
            _rep(report, f"⌨️ Inserted {len(text)} char(s) into textarea "
                         f"'{sel}' (Input.insertText)", "success")
            log.info("Message inserted via Input.insertText (%d chars)",
                     len(text))
            return True
        attempts.append("insertText ran but the page still did not accept it")
    else:
        attempts.append(f"insertText unavailable ({result})")

    _rep(report, "❌ Textarea value injection failed (page did not accept "
                 "input): " + "; ".join(attempts), "error")
    return False


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
