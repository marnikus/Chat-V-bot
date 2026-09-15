"""The JS payloads the visual probes inject into the page.

Part of the `dom_highlight` family (builder: `backend/dom_highlight.py`,
Round J step J-4). Five payloads and their shared fragments live here as
module constants instead of sitting inside the builder's control flow:

* `HELPERS_JS` — `probeVisible` / `describe` / `outline`, injected at the top
  of every probe (69 lines);
* `PROBE_CHASSIS_JS` — the wrapper each probe is formatted into: the
  diagnostic object, the helpers, one `try/catch` that turns a thrown JS
  error into `out.error` (a broken page must never raise across CDP), and
  the JSON reply;
* `base_out_js()` — the empty diagnostic object both phases share;
* `QUERY_VARS` / `LABEL_JS` / `MATCH_JS` — the fragments more than one body
  needs. In one place on purpose: a new argument used to mean editing two
  bodies, and missing one left the two probes matching different text;
* `FIND_BODY` / `HIGHLIGHT_BODY` / `CLICK_BODY` — the three probe bodies, the
  first two already spliced from those fragments.

`HIGHLIGHT_ATTR` and `STASH_KEY` live here too, because the payloads are what
interpolate them; `backend.dom_highlight` re-exports both, which is where the
probes' callers and the contract tests have always read them from.

`ideal-size:` this module exists so that payload *length* never forces a split
of the builder (RULE 16 §16.1.5's stated exception): the literal below is 69
lines and the three bodies are 35 / 21 / 62, and none of them is behaviour.
The Python side keeps its own CC/nesting budget, and the JS is byte-identical
to what it was when it lived inline — the contract tests compare probe *text*
(STASH_KEY, HIGHLIGHT_ATTR, the JSON reply), so a payload that drifted would
fail them.
"""

#: Attribute marking every overlay node so they can be bulk-removed.
HIGHLIGHT_ATTR = "data-cf-highlight"

#: Key on ``window`` where the matched element is stashed between phases.
STASH_KEY = "__cfStash"

HELPERS_JS = """
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


def base_out_js() -> str:
    """The empty diagnostic object shared by both phases."""
    return """
  var out = {
    phase: null, query: null, total: 0, found: false, index: -1, text: '',
    visible: false, disabled: false, clickable: false, clicked: false,
    clicked_target: null, target_desc: null, highlighted: false,
    rect: null, candidates: [], note: null, error: null
  };
"""


PROBE_CHASSIS_JS = """
(function(){
%(out)s
%(helpers)s
  try {
%(body)s
  } catch (err) {
    out.error = String(err && err.message || err);
  }
  return JSON.stringify(out);
})()
"""

def splice(body: str, **fragments) -> str:
    """Put the shared JS fragments back into a body's ``__MARKER__`` lines.

    A fragment loses its own blank margins on the way in, so a body made of
    pieces reads exactly like one written out in full — which is what keeps
    the script the page runs byte-identical to the hand-written one.
    """
    for name, fragment in fragments.items():
        body = body.replace(f"__{name.upper()}__", fragment.strip("\n"))
    return body


# ── JS fragments more than one probe needs ──────────────────────────────
#: How the FIND and HIGHLIGHT probes read their arguments. In one place on
#: purpose: a new argument used to mean editing two bodies, and missing one
#: left the two probes matching against different text.
QUERY_VARS = """
    var sel = %(selector)s;
    var childSel = %(label_selector)s;
    var matchText = %(match_text)s;
    var exact = %(exact)s;
"""

LABEL_JS = """
      var node = nodes[i];
      var el = node;
      var label = (node.textContent || '').trim().replace(/\\s+/g, ' ');
      if (childSel) {
        var c = node.querySelector(childSel);
        if (c) { el = c; label = (c.textContent || '').trim().replace(/\\s+/g, ' '); }
      }"""

MATCH_JS = """
      if (matchText !== null && matchText !== undefined && matchText !== '') {
        if (exact) { if (label !== matchText) { continue; } }
        else { if (label.indexOf(matchText) < 0) { continue; } }
      }
"""

FIND_BODY = splice("""
    out.phase = 'find';
__QUERY__
    var doHighlight = %(highlight)s;
    out.query = sel;
    clearHighlights();
    try { window.%(stash)s = null; } catch(e) {}
    var nodes = Array.prototype.slice.call(document.querySelectorAll(sel));
    out.total = nodes.length;
    var cands = [];
    for (var i = 0; i < nodes.length; i++) {
__LABEL__
      if (label.length > 120) label = label.slice(0, 120) + '\\u2026';
__MATCH__
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
""", query=QUERY_VARS, label=LABEL_JS, match=MATCH_JS)

HIGHLIGHT_BODY = splice("""
    out.phase = 'highlight';
__QUERY__
    out.query = sel;
    if (%(clear)s) clearHighlights();
    var nodes = Array.prototype.slice.call(document.querySelectorAll(sel));
    out.total = nodes.length;
    for (var i = 0; i < nodes.length; i++) {
__LABEL__
__MATCH__
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
""", query=QUERY_VARS, label=LABEL_JS, match=MATCH_JS)

CLICK_BODY = """
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
"""
