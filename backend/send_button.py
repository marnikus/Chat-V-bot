"""Clicking the send button, and saying precisely why a click missed.

Split out of backend/message_injector.py in Round H (step H5), which was 482
lines holding two jobs that share no state: getting TEXT INTO the field
(a verified three-strategy fallback chain) and getting the field SENT. The
seam is exact — not one helper was used by both halves.

`SEND_SELECTOR` deliberately stays in `message_injector`: `actions/click_send.py`
imports it from there, and this split must not move a name another area
already depends on.
"""

import json
import logging
from typing import Callable, Optional

from backend.cdp_client import CDPClient
from backend.dom_probe import build_probe, interpret_wait
from backend.logger import report_and_log
from backend.message_injector import SEND_SELECTOR

log = logging.getLogger("chatbot")

#: the shared report-and-log helper; `_rep` stays as this module's spelling
_rep = report_and_log


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


async def _probe_send_button(cdp: CDPClient,
                             report: Optional[Callable]) -> Optional[dict]:
    """The structured probe of the real send button (None when it raised)."""
    try:
        raw = await cdp.evaluate(build_probe(selector=SEND_SELECTOR, click=True,
                                             click_root=True))
        return json.loads(raw) if raw else None
    except Exception as exc:                         # noqa: BLE001
        _rep(report, f"❌ Probe error: {exc}", "error")
        return None


def _announce_send_miss(res: Optional[dict],
                        report: Optional[Callable]) -> None:
    """Why the button probe did not click, before the icon fallback runs."""
    if res and res.get("found"):
        _rep(report, "⚠ Send button found but NOT clickable "
                     "(hidden or disabled) — trying icon fallback", "warn")
    else:
        _rep(report, "❌ Failed to find element: send button "
                     f"'{SEND_SELECTOR}' — trying mat-icon 'send' fallback", "warn")


async def _probe_send_icon(cdp: CDPClient,
                           report: Optional[Callable]) -> Optional[dict]:
    """The mat-icon 'send' fallback probe; None when it cannot be read.

    Every refusal reason is reported here, so the caller only has to ask
    whether there is a result to judge.
    """
    # Fallback: mat-icon 'send' inside a button
    _rep(report, "🔍 Fallback search: mat-icon 'send'", "info")
    try:
        raw = await cdp.evaluate(_SEND_ICON_JS)
        res = json.loads(raw) if raw else None
    except Exception as exc:                         # noqa: BLE001
        _rep(report, f"❌ Fallback probe error: {exc}", "error")
        return None
    if not res:
        _rep(report, "❌ Failed to find element: send icon fallback — no data",
             "error")
        return None
    if res.get("error"):
        _rep(report, f"❌ Send icon probe error: {res['error']}", "error")
        return None
    return res


def _report_send_icon(res: dict, report: Optional[Callable]) -> bool:
    """The icon fallback's verdict: True only when the click happened."""
    if res.get("clicked"):
        _rep(report, "✅ Send icon found — clickable: yes — clicked ✔", "success")
        log.info("Send button clicked via icon fallback")
        return True
    if res.get("found"):
        _rep(report, "⚠ Send icon found but its button is NOT clickable "
                     "(hidden/disabled)", "error")
    else:
        _rep(report, f"❌ Failed to find element: no mat-icon 'send' in "
                     f"{int(res.get('total', 0))} icon(s) on page", "error")
    return False


async def click_send(cdp: CDPClient, report: Optional[Callable] = None) -> bool:
    """Click the send button (submit type, with 'send' icon fallback)."""
    _rep(report, f"🔍 Searching send button: selector '{SEND_SELECTOR}'", "info")
    res = await _probe_send_button(cdp, report)
    if res and res.get("found") and res.get("clicked"):
        _rep(report, f"✅ Send button found — clickable: yes — clicked ✔", "success")
        log.info("Send button clicked")
        return True
    _announce_send_miss(res, report)
    res2 = await _probe_send_icon(cdp, report)
    if res2 is None:
        return False
    return _report_send_icon(res2, report)
