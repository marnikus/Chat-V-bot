"""Visual confirmation overlays + two-phase find/click probes.

The "Find & Click" blocks perform their work in TWO separate CDP round trips so
that the user can *see* what happened before anything is clicked:

  Phase 1 — FIND   : locate the element, report success/failure, draw a thin
                     RED outline over it, then pause.
  Phase 2 — CLICK  : re-check the stashed element, report clickability, draw a
                     thin ORANGE outline over the click target, then click.

Both phases return the same structured JSON diagnostic shape used by
``backend.dom_probe`` so the existing logging contract keeps working.

The overlay is a separate ``div`` with ``pointer-events:none`` and a transparent
background, so it can never intercept the click nor affect page layout.
"""

import json
from typing import Optional

from backend.dom_probe import MATCH_CONTAINS, MATCH_EXACT, _js_str  # noqa: F401

#: Outline colour used for the FIND phase.
COLOR_FIND = "#ff2d2d"      # red
#: Outline colour used for the CLICK phase.
COLOR_CLICK = "#ff9500"     # orange
#: Outline colour used when a person matches the filter and is collected.
COLOR_COLLECT = "#00c853"   # green

#: Attribute marking every overlay node so they can be bulk-removed.
HIGHLIGHT_ATTR = "data-cf-highlight"

#: Key on ``window`` where the matched element is stashed between phases.
STASH_KEY = "__cfStash"


# ── shared JS helpers, injected at the top of every probe ────────────────
_HELPERS_JS = """
  function probeVisible(el) {
    var st = null;
    try { st = window.getComputedStyle(el); } catch(e) {}
    if (st && (st.display === 'none' || st.visibility === 'hidden')) {
      return {visible: false,
              disabled: !!el.disabled || st.pointerEvents === 'none'};
    }
    var metrics = !!(el.offsetWidth || el.offsetHeight ||
                     (el.getClientRects && el.getClientRects().length));
    return {visible: metrics,
            disabled: !!el.disabled || (st && st.pointerEvents === 'none')};
  }
  function describe(el) {
    if (!el || !el.tagName) return null;
    var cls = '';
    try {
      cls = el.className && String(el.className).trim()
          ? '.' + String(el.className).trim().split(/\\s+/).join('.') : '';
    } catch(e) {}
    return el.tagName.toLowerCase() + cls;
  }
  function clearHighlights() {
    try {
      var old = document.querySelectorAll('[__ATTR__]');
      for (var k = 0; k < old.length; k++) {
        if (old[k].parentNode) old[k].parentNode.removeChild(old[k]);
      }
    } catch(e) {}
  }
  function highlight(el, color, ms, caption) {
    try {
      if (!el || !el.getBoundingClientRect) return null;
      var r = el.getBoundingClientRect();
      if (!r || (!r.width && !r.height)) return null;
      var box = document.createElement('div');
      box.setAttribute('__ATTR__', '1');
      box.style.cssText = [
        'position:fixed',
        'left:' + Math.max(0, r.left) + 'px',
        'top:' + Math.max(0, r.top) + 'px',
        'width:' + Math.max(0, r.width) + 'px',
        'height:' + Math.max(0, r.height) + 'px',
        'outline:2px solid ' + color,
        'outline-offset:-1px',
        'background:transparent',
        'pointer-events:none',
        'z-index:2147483647'
      ].join(';');
      if (caption) {
        var tag = document.createElement('div');
        tag.textContent = caption;
        tag.style.cssText = [
          'position:absolute', 'left:0', 'top:-16px',
          'font:700 10px/14px sans-serif', 'letter-spacing:.5px',
          'padding:0 4px', 'color:#fff', 'white-space:nowrap',
          'background:' + color, 'pointer-events:none'
        ].join(';');
        box.appendChild(tag);
      }
      (document.body || document.documentElement).appendChild(box);
      var life = ms > 0 ? ms : 1200;
      setTimeout(function(){
        if (box.parentNode) box.parentNode.removeChild(box);
      }, life);
      return {x: r.left, y: r.top, width: r.width, height: r.height};
    } catch(e) { return null; }
  }
""".replace("__ATTR__", HIGHLIGHT_ATTR)


def _base_out_js() -> str:
    """The empty diagnostic object shared by both phases."""
    return """
  var out = {
    phase: null, query: null, total: 0, found: false, index: -1, text: '',
    visible: false, disabled: false, clickable: false, clicked: false,
    clicked_target: null, target_desc: null, highlighted: false,
    rect: null, candidates: [], note: null, error: null
  };
"""


def build_find_probe(
    selector: str,
    label_selector: Optional[str] = None,
    match_text: Optional[str] = None,
    match_mode: str = MATCH_CONTAINS,
    highlight: bool = True,
    highlight_ms: int = 1200,
    color: str = COLOR_FIND,
    caption: str = "FOUND",
    max_candidates: int = 6,
) -> str:
    """Phase 1 probe: find the element, highlight it in RED, do NOT click.

    The matched node is stashed on ``window.__cfStash`` so the click phase can
    act on the exact same element instead of re-querying the DOM.
    """
    return """
(function(){
%(out)s
%(helpers)s
  try {
    out.phase = 'find';
    var sel = %(selector)s;
    var childSel = %(label_selector)s;
    var matchText = %(match_text)s;
    var exact = %(exact)s;
    var doHighlight = %(highlight)s;
    out.query = sel;
    clearHighlights();
    try { window.%(stash)s = null; } catch(e) {}
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
      if (label.length > 120) label = label.slice(0, 120) + '\\u2026';
      if (matchText !== null && matchText !== undefined && matchText !== '') {
        if (exact) { if (label !== matchText) { continue; } }
        else { if (label.indexOf(matchText) < 0) { continue; } }
      }
      /* Visibility/clickability must describe the node we will actually
         highlight and click (the root), not the inner label element: a label
         inside a display:none parent still reports its own style as visible. */
      var vi = probeVisible(node);
      if (!out.found) {
        out.found = true; out.index = i; out.text = label;
        out.visible = vi.visible; out.disabled = vi.disabled;
        out.clickable = vi.visible && !vi.disabled;
        out.target_desc = describe(node);
        try { window.%(stash)s = node; } catch(e) {}
        if (doHighlight) {
          var rect = highlight(node, %(color)s, %(hms)s, %(caption)s);
          out.rect = rect;
          out.highlighted = !!rect;
        }
      }
      cands.push({index: i, text: label, visible: vi.visible,
                  clickable: vi.visible && !vi.disabled});
    }
    out.candidates = cands.slice(0, %(maxcand)s);
  } catch (err) {
    out.error = String(err && err.message || err);
  }
  return JSON.stringify(out);
})()
""" % {
        "out": _base_out_js(),
        "helpers": _HELPERS_JS,
        "selector": _js_str(selector),
        "label_selector": _js_str(label_selector) if label_selector else "null",
        "match_text": _js_str(match_text) if match_text else "null",
        "exact": "true" if match_mode == MATCH_EXACT else "false",
        "highlight": "true" if highlight else "false",
        "color": _js_str(color),
        "caption": _js_str(caption),
        "hms": int(highlight_ms),
        "stash": STASH_KEY,
        "maxcand": int(max_candidates),
    }


def build_click_probe(
    click_selector: Optional[str] = None,
    highlight: bool = True,
    highlight_ms: int = 1200,
    color: str = COLOR_CLICK,
    caption: str = "CLICK",
    do_click: bool = True,
) -> str:
    """Phase 2 probe: highlight the click target in ORANGE, then click it.

    Operates on the element stashed by :func:`build_find_probe`. When
    ``click_selector`` is given, the click target is that element *inside* the
    stashed node; otherwise the stashed node itself is clicked.
    """
    return """
(function(){
%(out)s
%(helpers)s
  try {
    out.phase = 'click';
    var doHighlight = %(highlight)s;
    var doClick = %(do_click)s;
    var clickSel = %(click_selector)s;
    var root = null;
    try { root = window.%(stash)s; } catch(e) {}
    if (!root) {
      out.error = 'no element stashed from the find phase';
      return JSON.stringify(out);
    }
    if (!root.isConnected) {
      out.error = 'the found element is no longer attached to the page';
      return JSON.stringify(out);
    }
    var target = root;
    if (clickSel) {
      /* A CSS selector only matches DESCENDANTS of root. Users routinely set
         the click selector to the SAME selector they used to find the element
         (e.g. the saved "Tab Main" block), which finds nothing and used to
         make the block silently do nothing. Fall back to the root itself when
         the root is what the selector describes. */
      var inner = root.querySelector(clickSel);
      if (!inner) {
        var selfMatch = false;
        try {
          selfMatch = !!(root.matches && root.matches(clickSel));
        } catch (e) { selfMatch = false; }
        if (selfMatch) {
          inner = root;
          out.note = 'click selector matches the found element itself';
        }
      }
      if (!inner) {
        out.error = 'click target ' + clickSel + ' not found inside the element';
        return JSON.stringify(out);
      }
      target = inner;
    }
    out.found = true;
    out.text = (target.textContent || '').trim().replace(/\\s+/g, ' ').slice(0, 120);
    out.target_desc = describe(target);
    out.clicked_target = out.target_desc;
    var vi = probeVisible(target);
    out.visible = vi.visible;
    out.disabled = vi.disabled;
    out.clickable = vi.visible && !vi.disabled;
    if (doHighlight) {
      var rect = highlight(target, %(color)s, %(hms)s, %(caption)s);
      out.rect = rect;
      out.highlighted = !!rect;
    }
    if (doClick && out.clickable) {
      try {
        if (target.scrollIntoView) {
          target.scrollIntoView({block: 'center', inline: 'center'});
        }
      } catch(e) {}
      try { target.click(); out.clicked = true; }
      catch(err) { out.error = String(err && err.message || err); }
    }
  } catch (err) {
    out.error = String(err && err.message || err);
  }
  return JSON.stringify(out);
})()
""" % {
        "out": _base_out_js(),
        "helpers": _HELPERS_JS,
        "click_selector": _js_str(click_selector) if click_selector else "null",
        "highlight": "true" if highlight else "false",
        "do_click": "true" if do_click else "false",
        "color": _js_str(color),
        "caption": _js_str(caption),
        "hms": int(highlight_ms),
        "stash": STASH_KEY,
    }


def build_highlight_probe(
    selector: str,
    label_selector: Optional[str] = None,
    match_text: Optional[str] = None,
    match_mode: str = MATCH_EXACT,
    color: str = COLOR_COLLECT,
    caption: str = "MATCH",
    highlight_ms: int = 900,
    clear_first: bool = True,
) -> str:
    """Highlight an element WITHOUT clicking it or touching the click stash.

    Used for pure visual confirmation — e.g. showing which person just matched
    the filter during Scroll & Parse. Deliberately does NOT call
    ``scrollIntoView``: moving the viewport mid-scroll would corrupt the
    parser's position tracking.
    """
    return """
(function(){
%(out)s
%(helpers)s
  try {
    out.phase = 'highlight';
    var sel = %(selector)s;
    var childSel = %(label_selector)s;
    var matchText = %(match_text)s;
    var exact = %(exact)s;
    out.query = sel;
    if (%(clear)s) clearHighlights();
    var nodes = Array.prototype.slice.call(document.querySelectorAll(sel));
    out.total = nodes.length;
    for (var i = 0; i < nodes.length; i++) {
      var node = nodes[i];
      var el = node;
      var label = (node.textContent || '').trim().replace(/\\s+/g, ' ');
      if (childSel) {
        var c = node.querySelector(childSel);
        if (c) { el = c; label = (c.textContent || '').trim().replace(/\\s+/g, ' '); }
      }
      if (matchText !== null && matchText !== undefined && matchText !== '') {
        if (exact) { if (label !== matchText) { continue; } }
        else { if (label.indexOf(matchText) < 0) { continue; } }
      }
      var vi = probeVisible(node);
      out.found = true; out.index = i; out.text = label;
      out.visible = vi.visible; out.disabled = vi.disabled;
      out.clickable = vi.visible && !vi.disabled;
      out.target_desc = describe(node);
      var rect = highlight(node, %(color)s, %(hms)s, %(caption)s);
      out.rect = rect;
      out.highlighted = !!rect;
      break;
    }
  } catch (err) {
    out.error = String(err && err.message || err);
  }
  return JSON.stringify(out);
})()
""" % {
        "out": _base_out_js(),
        "helpers": _HELPERS_JS,
        "selector": _js_str(selector),
        "label_selector": _js_str(label_selector) if label_selector else "null",
        "match_text": _js_str(match_text) if match_text else "null",
        "exact": "true" if match_mode == MATCH_EXACT else "false",
        "clear": "true" if clear_first else "false",
        "color": _js_str(color),
        "caption": _js_str(caption),
        "hms": int(highlight_ms),
    }


def build_clear_probe() -> str:
    """Remove every leftover highlight overlay from the page."""
    return """
(function(){
  try {
    var old = document.querySelectorAll('[%(attr)s]');
    for (var k = 0; k < old.length; k++) {
      if (old[k].parentNode) old[k].parentNode.removeChild(old[k]);
    }
    return JSON.stringify({cleared: old.length});
  } catch (err) { return JSON.stringify({cleared: 0}); }
})()
""" % {"attr": HIGHLIGHT_ATTR}


# ── interpretation of the two phases ─────────────────────────────────────
def interpret_find(result, label: str = "element") -> tuple[str, str]:
    """Turn a FIND-phase result into a (message, level) pair."""
    if not result:
        return f"❌ FIND failed: no data returned for {label} " \
               "(page context unavailable?)", "error"
    if result.get("error"):
        return f"❌ FIND error while searching {label}: {result['error']}", "error"
    total = int(result.get("total", 0) or 0)
    if not result.get("found"):
        msg = (f"❌ FIND failed: {label} — selector matched {total} node(s), "
               "none with the required text/properties.")
        cands = result.get("candidates") or []
        if cands:
            parts = [
                f"[{c.get('index')}] “{str(c.get('text', ''))[:40]}” "
                f"({'visible' if c.get('visible') else 'hidden'}, "
                f"{'clickable' if c.get('clickable') else 'not clickable'})"
                for c in cands[:4]
            ]
            msg += " Candidates: " + "; ".join(parts) + "."
        return msg, "error"
    text = str(result.get("text", ""))[:60]
    idx = result.get("index", -1)
    state = "visible" if result.get("visible") else "⚠ NOT visible (hidden/zero-size)"
    if result.get("disabled"):
        state += ", ⚠ disabled (or pointer-events:none)"
    msg = f"✅ FIND success: {label} — matched node #{idx} “{text}” ({state})"
    if result.get("highlighted"):
        r = result.get("rect") or {}
        size = ""
        if r:
            size = (f" at {int(r.get('x', 0))},{int(r.get('y', 0))} "
                    f"{int(r.get('width', 0))}×{int(r.get('height', 0))}px")
        msg += f" — 🟥 red outline drawn{size}"
    elif result.get("visible"):
        msg += " — (highlight off)"
    level = "success" if result.get("visible") else "warn"
    return msg, level


def interpret_click(result, label: str = "element") -> tuple[str, str]:
    """Turn a CLICK-phase result into a (message, level) pair."""
    if not result:
        return f"❌ CLICK failed: no data returned for {label}", "error"
    if result.get("error") and not result.get("clicked"):
        return f"❌ CLICK failed: {label} — {result['error']}", "error"
    target = result.get("target_desc") or "the found element"
    if not result.get("clickable"):
        why = []
        if not result.get("visible"):
            why.append("not visible (hidden/zero-size)")
        if result.get("disabled"):
            why.append("disabled or pointer-events:none")
        reason = ", ".join(why) or "not interactive"
        return (f"❌ CLICK failed: {target} is NOT clickable — {reason}", "error")
    if result.get("clicked"):
        return (f"✅ CLICK success: clicked {target} “"
                f"{str(result.get('text', ''))[:40]}”", "success")
    return (f"⚠ CLICK not dispatched: {target} is clickable but no click was "
            "performed", "warn")


def interpret_click_target(result) -> tuple[str, str]:
    """Message emitted right after the orange outline, before the click."""
    target = result.get("target_desc") or "the found element"
    if result.get("clickable"):
        msg = f"✅ CLICK target is clickable: {target}"
        if result.get("highlighted"):
            msg += " — 🟧 orange outline drawn"
        return msg, "success"
    return f"⚠ CLICK target {target} is not clickable", "warn"
