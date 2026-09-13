"""Field discovery, probing and the field-side JS payloads (injector 1/3).

Family file of ``backend.message_injector`` (Round G3, RULE 18): the
selector constants for the message textarea and the users-list search box,
the three injected JS snippets that read/focus a field, and the shared
low-level helpers (_rep reporting, _js string embedding, field probes).
The typing ladder lives in ``message_injector_type``, the send-button
family in ``message_injector_send``; both import this module, never the
other way round.
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

# The users-list search box: structural selectors only — "Поиск" is a
# floating <mat-label>, NOT a placeholder, and the #mat-input-N ids are
# regenerated every time the users-list component mounts, so both are
# unusable in selectors.
SEARCH_SELECTOR = ".search-field input[matinput]"
SEARCH_FALLBACK = "input[maxlength='20']"

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
    # exactly ONE trailing newline of difference is tolerated (editors
    # append one on paste) — rstrip() used to forgive ANY number, so a
    # page that ATE a blank line at the end still verified as "typed".
    return a == b or a == b + "\n" or a + "\n" == b


async def _focus_and_select_all(cdp: CDPClient, sel: str) -> bool:
    try:
        return bool(await cdp.evaluate(
            _SELECT_ALL_JS.replace("__SEL__", _js(sel))))
    except Exception:
        return False
