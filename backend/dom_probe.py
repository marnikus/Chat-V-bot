"""Structured DOM probing for the debugger.

Every click/search style action runs ONE JavaScript probe that returns a
JSON diagnostic object instead of a bare boolean:

    {
      "query":  "<selector>",
      "total":  12,            // nodes matched by the base selector
      "found":  true,          // an element satisfied the (optional) text match
      "index":  3,             // index of the matched node
      "text":   "Гостиная",    // label text of the matched element
      "visible": true,         // element has layout (offset/rects)
      "disabled": false,       // disabled attribute / pointer-events:none
      "clickable": true,       // visible && !disabled
      "clicked": true,         // click() was dispatched and did not throw
      "candidates": [ {index, text, visible, clickable}, ... ],
      "error": null
    }

This gives the UI logger everything it needs to answer:
  * was the element search a success or failure?
  * was the found element clickable?
  * did the click actually happen?
"""

import json
from typing import Optional

# Match modes for the (optional) text comparison
MATCH_CONTAINS = "contains"
MATCH_EXACT = "exact"


def _js_str(value: str) -> str:
    """Encode a Python string as a safe JavaScript string literal."""
    return json.dumps(str(value), ensure_ascii=False)


def build_probe(
    selector: str,
    label_selector: Optional[str] = None,
    match_text: Optional[str] = None,
    match_mode: str = MATCH_CONTAINS,
    click: bool = False,
    click_selector: Optional[str] = None,
    click_root: bool = False,
    max_candidates: int = 6,
) -> str:
    """Return a JS expression string that resolves to the probe JSON.

    :param selector:        CSS selector for querySelectorAll.
    :param label_selector:  optional child CSS selector whose text is used
                            for the label / text match (falls back to node).
    :param match_text:      if set, only elements whose label contains (or
                            exactly equals) this text are considered matches.
    :param match_mode:      MATCH_CONTAINS or MATCH_EXACT.
    :param click:           if True, click the resolved click target when a
                            match is found and clickable.
    :param click_selector:  optional child CSS selector used as the click
                            target (e.g. ".user-container" inside user-item).
    :param click_root:      if True click the root matched node instead of the
                            label element (used by tab clicks).
    :param max_candidates:  how many candidate rows to include in the result.
    """
    click_js = ""
    if click:
        if click_selector:
            target_expr = ("(node.querySelector(%s) || el)" % _js_str(click_selector))
        elif click_root:
            target_expr = "node"
        else:
            target_expr = "el"
        click_js = f"""
        var target = {target_expr};
        var visInfo = probeVisible(target);
        out.visible = visInfo.visible;
        out.disabled = visInfo.disabled;
        out.clickable = out.visible && !out.disabled;
        out.clicked_target = target.tagName ? target.tagName.toLowerCase() + (
            target.className ? '.' + String(target.className).trim().split(/\\s+/).join('.') : '') : null;
        if (out.clickable) {{
            try {{
                target.click();
                out.clicked = true;
                out.text = label;   /* reflect the element that was actually clicked */
                out.index = i;
            }}
            catch(err) {{ out.error = String(err && err.message || err); }}
        }}
        """

    expr = """
(function(){
  var out = {
    query: null, total: 0, found: false, index: -1, text: '',
    visible: false, disabled: false, clickable: false,
    clicked: false, clicked_target: null, candidates: [], error: null
  };
  function probeVisible(el) {
    var st = null;
    try { st = window.getComputedStyle(el); } catch(e) {}
    if (st) {
      if (st.display === 'none' || st.visibility === 'hidden') {
        return {visible: false, disabled: !!el.disabled || st.pointerEvents === 'none'};
      }
    }
    var metrics = !!(el.offsetWidth || el.offsetHeight ||
                     (el.getClientRects && el.getClientRects().length));
    return {visible: metrics,
            disabled: !!el.disabled || (st && st.pointerEvents === 'none')};
  }
  try {
    var sel = %(selector)s;
    var childSel = %(label_selector)s;
    var matchText = %(match_text)s;
    var exact = %(exact)s;
    out.query = sel;
    var nodes = Array.prototype.slice.call(document.querySelectorAll(sel));
    out.total = nodes.length;
    var cands = [];
    for (var i = 0; i < nodes.length; i++) {
      var node = nodes[i];
      var el = node;
      var label = (node.textContent || '').trim().replace(/\\s+/g, ' ');
      if (childSel) {
        var c = node.querySelector(childSel);
        if (c) { el = c; label = (c.textContent || '').trim().replace(/\\s+/g, ' '); }
      }
      if (label.length > 120) label = label.slice(0, 120) + '…';
      if (matchText !== null && matchText !== undefined && matchText !== '') {
        if (exact) { if (label !== matchText) continue; }
        else { if (label.indexOf(matchText) < 0) continue; }
      }
      var vi = probeVisible(el);
      var visible = vi.visible;
      var disabled = vi.disabled;
      if (!out.found) {
        out.found = true; out.index = i; out.text = label;
        out.visible = visible; out.disabled = disabled;
        out.clickable = visible && !disabled;
      }
      cands.push({index: i, text: label, visible: visible, clickable: visible && !disabled});
      %(click_js)s
      if (out.clicked) break;
    }
    out.candidates = cands.slice(0, %(maxcand)s);
  } catch (err) {
    out.error = String(err && err.message || err);
  }
  return JSON.stringify(out);
})()
""" % {
        "selector": _js_str(selector),
        "label_selector": _js_str(label_selector) if label_selector else "null",
        "match_text": _js_str(match_text) if match_text else "null",
        "exact": "true" if match_mode == MATCH_EXACT else "false",
        "click_js": click_js,
        "maxcand": int(max_candidates),
    }
    return expr


def interpret(result, label: str = "element") -> tuple[str, str]:
    """Turn the probe result into a (message, level) pair.

    Levels: success (element found/clicked), warn (found but not clickable),
    error (search failed/probe error).
    """
    if not result:
        return f"❌ Probe returned no data for “{label}”", "error"
    total = int(result.get("total", 0) or 0)
    found = bool(result.get("found"))
    if result.get("error"):
        return f"❌ Probe error while searching {label}: {result['error']}", "error"
    if not found:
        msg = (f"❌ Failed to find element: {label} — selector matched {total} "
               f"node(s), none with the required text/properties.")
        cands = result.get("candidates") or []
        if cands:
            parts = []
            for c in cands[:4]:
                parts.append(f"[{c.get('index')}] “{c.get('text','')[:40]}”"
                             f"({('visible,' if c.get('visible') else 'hidden,')}"
                             f"{'clickable' if c.get('clickable') else 'not clickable'})")
            msg += " Candidates: " + "; ".join(parts) + "."
        return msg, "error"
    # found — report visibility/clickability
    visible = bool(result.get("visible"))
    disabled = bool(result.get("disabled"))
    text = result.get("text", "")[:60]
    base = f"✅ {label} found: “{text}”"
    if not visible:
        return base + " — ⚠ NOT visible (hidden/zero-size) — will not click", "warn"
    if disabled:
        return base + " — ⚠ disabled (or pointer-events:none) — will not click", "warn"
    if result.get("clicked") is True:
        return base + " — clickable: yes — clicked ✔", "success"
    if "clicked" in result:
        return base + " — clickable: yes — click FAILED", "error"
    return base + " — clickable: yes", "success"


def interpret_wait(result, label: str = "element") -> tuple[str, str]:
    """Variant for wait-for-element style probes (no click attempted)."""
    if not result:
        return f"❌ Probe returned no data for “{label}”", "error"
    if result.get("error"):
        return f"❌ Probe error while waiting for {label}: {result['error']}", "error"
    if not result.get("found"):
        total = int(result.get("total", 0) or 0)
        return (f"⏳ {label} not yet present (selector matched {total} node(s))",
                "warn")
    visible = bool(result.get("visible"))
    disabled = bool(result.get("disabled"))
    status = "visible & enabled" if visible and not disabled \
        else "found but not interactive"
    return f"✅ {label} found — {status}", "success"
