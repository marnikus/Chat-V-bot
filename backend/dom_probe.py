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

from backend.probe_requests import (  # noqa: F401  (re-exported: constants moved)
    MATCH_CONTAINS, MATCH_EXACT, ProbeSpec)


def _js_str(value: str) -> str:
    """Encode a Python string as a safe JavaScript string literal."""
    return json.dumps(str(value), ensure_ascii=False)


#: The three fragments of the generated probe script, in the order they are
#: concatenated. They are module constants rather than one inline literal so
#: that `build_probe` reads as a composition of named stages (RULE 18.2) and
#: each stage can be reasoned about on its own. The `%(...)s` placeholders in
#: `_PROBE_SCAN` are filled by `build_probe`; raw strings keep the JS regex
#: escapes literal.
_PROBE_HEAD = r"""
(function(){
  var out = {
    query: null, total: 0, found: false, index: -1, text: '',
    visible: false, disabled: false, clickable: false,
    clicked: false, clicked_target: null, candidates: [], error: null
  };
"""

#: The visibility helper every probe embeds: computed style first, then box
#: metrics, because a display:none ancestor leaves the metrics all zero.
_PROBE_VISIBILITY = r"""  function probeVisible(el) {
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
"""

#: The scan: read the knobs, walk the nodes, keep a bounded candidate sample,
#: and return the whole result as one JSON string.
_PROBE_SCAN = r"""  try {
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
      var label = (node.textContent || '').trim().replace(/\s+/g, ' ');
      if (childSel) {
        var c = node.querySelector(childSel);
        if (c) { el = c; label = (c.textContent || '').trim().replace(/\s+/g, ' '); }
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
"""


def _click_target(spec: ProbeSpec) -> str:
    """The JS expression for the element that should receive the click.

    A declared child wins, then the row itself, then the label child the probe
    already resolved. Order matters: the click must land on the narrowest
    element the caller named, or the site's own handler never fires.
    """
    if spec.click_selector:
        return "(node.querySelector(%s) || el)" % _js_str(spec.click_selector)
    if spec.click_root:
        return "node"
    return "el"


def _click_block(spec: ProbeSpec) -> str:
    """The click fragment spliced into the scan, or '' when not clicking.

    Empty for a plain visibility probe, which is why the template can carry
    `%(click_js)s` unconditionally. `out.text` and `out.index` are re-pointed
    at the clicked element so the caller reports what was actually pressed
    rather than the first match the scan happened to find.
    """
    if not spec.click:
        return ""
    return f"""
        var target = {_click_target(spec)};
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


def build_probe(selector: str, spec: Optional[ProbeSpec] = None) -> str:
    """Return a JS expression string that resolves to the probe JSON.

    Round I step I-2: this was one 107-LOC function carrying a single string.
    It now composes three named fragments of the generated script — the result
    shape, the visibility helper and the scan — plus the click block above.
    The emitted JavaScript is byte-identical to before;
    `tests/unit/backend/test_dom_probe_shape.py` pins it against goldens
    captured from the un-split function.

    :param selector: CSS selector for querySelectorAll.
    :param spec:     the knobs (label child selector, text match, click
                     target, candidate sample) as one :class:`ProbeSpec`;
                     None means "plain visibility probe, no click".
    """
    spec = spec or ProbeSpec()
    return (_PROBE_HEAD + _PROBE_VISIBILITY + _PROBE_SCAN) % {
        "selector": _js_str(selector),
        "label_selector": (_js_str(spec.label_selector)
                           if spec.label_selector else "null"),
        "match_text": _js_str(spec.match_text) if spec.match_text else "null",
        "exact": "true" if spec.match_mode == MATCH_EXACT else "false",
        "click_js": _click_block(spec),
        "maxcand": int(spec.max_candidates),
    }


def _candidate_snip(cand: dict) -> str:
    """One candidate of a failed probe, exactly as the log shows it."""
    return (f"[{cand.get('index')}] “{cand.get('text','')[:40]}”"
            f"({('visible,' if cand.get('visible') else 'hidden,')}"
            f"{'clickable' if cand.get('clickable') else 'not clickable'})")


def _candidates_suffix(candidates: list) -> str:
    """The " Candidates: …." tail of a failure message ("" when there are none).

    Four is the pinned sample size: enough to recognise the wrong pane
    without turning one log line into a DOM dump.
    """
    if not candidates:
        return ""
    return (" Candidates: "
            + "; ".join(_candidate_snip(c) for c in candidates[:4]) + ".")


def _failure_message(result: dict, total: int, label: str) -> str:
    """The not-found message, naming up to four of the matched candidates."""
    return (f"❌ Failed to find element: {label} — selector matched {total} "
            f"node(s), none with the required text/properties."
            + _candidates_suffix(result.get("candidates") or []))


def _found_message(result: dict, base: str) -> tuple[str, str]:
    """The visibility / clickability verdict for an element that WAS found."""
    if not result.get("visible"):
        return base + " — ⚠ NOT visible (hidden/zero-size) — will not click", "warn"
    if result.get("disabled"):
        return base + " — ⚠ disabled (or pointer-events:none) — will not click", "warn"
    if result.get("clicked") is True:
        return base + " — clickable: yes — clicked ✔", "success"
    if "clicked" in result:
        return base + " — clickable: yes — click FAILED", "error"
    return base + " — clickable: yes", "success"


def interpret(result, label: str = "element") -> tuple[str, str]:
    """Turn the probe result into a (message, level) pair.

    Levels: success (element found/clicked), warn (found but not clickable),
    error (search failed/probe error).
    """
    if not isinstance(result, dict):
        return f"❌ Probe returned no usable data for “{label}”", "error"
    total = int(result.get("total", 0) or 0)
    if result.get("error"):
        return f"❌ Probe error while searching {label}: {result['error']}", "error"
    if not result.get("found"):
        return _failure_message(result, total, label), "error"
    # found — report visibility/clickability
    text = result.get("text", "")[:60]
    return _found_message(result, f"✅ {label} found: “{text}”")


def interpret_wait(result, label: str = "element") -> tuple[str, str]:
    """Variant for wait-for-element style probes (no click attempted)."""
    if not isinstance(result, dict):
        return f"❌ Probe returned no usable data for “{label}”", "error"
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
