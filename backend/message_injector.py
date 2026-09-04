"""Message injection into Virt-Chat textarea via CDP (with debugger detail).

Both helpers accept an optional `report(message, level)` callback so the
engine can stream step-by-step results (element search → found/failed →
clickable → action outcome) into the UI log console and run trace.
"""

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


def _rep(report: Optional[Callable], message: str, level: str = "info") -> None:
    if report:
        try:
            report(message, level)
        except Exception:
            pass
    log.log(getattr(logging, level.upper(), logging.INFO), "%s", message)


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


async def type_message(cdp: CDPClient, text: str, typing_speed_ms: int = 30,
                       report: Optional[Callable] = None) -> bool:
    """Set textarea value and dispatch Angular-compatible input events."""
    sel = await _find_textarea(cdp, report)
    if not sel:
        _rep(report, "❌ Type Message aborted: no message textarea found", "error")
        return False
    if not text:
        _rep(report, "⚠ Message text is empty — nothing typed", "warn")
        return False
    esc = text.replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n")
    js = f"""(function(){{
        var ta = document.querySelector('{sel}');
        if(!ta) return false;
        ta.focus();
        var setter = Object.getOwnPropertyDescriptor(
            window.HTMLTextAreaElement.prototype,'value').set;
        setter.call(ta,'{esc}');
        ta.dispatchEvent(new Event('input',{{bubbles:true}}));
        ta.dispatchEvent(new Event('change',{{bubbles:true}}));
        return true;
    }})()"""
    try:
        result = await cdp.evaluate(js)
    except Exception as exc:
        _rep(report, f"❌ Injection error: {exc}", "error")
        return False
    if result:
        _rep(report, f"⌨️ Typed {len(text)} char(s) into textarea '{sel}' "
                     f"(speed {typing_speed_ms} ms/char)", "success")
        log.info("Message typed (%d chars)", len(text))
        return True
    _rep(report, "❌ Textarea value injection failed (page did not accept input)",
         "error")
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
