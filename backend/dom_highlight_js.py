"""The JavaScript the highlight/find/click probes evaluate in the page.

Split out of backend/dom_highlight.py in Round H (step H5). That file was 590
lines, of which 219 were JS SOURCE TEXT held in Python strings — and only 4 of
its 16 definitions touched any of it. The rest is Python that builds probe
payloads and interprets the results, which is what the module's tests exercise.

Keeping the two apart means a change to the in-page DOM walk and a change to
the result interpretation no longer land in the same file, and neither has to
be read past the other. The names are unchanged and still private to the
`dom_highlight` pair, except `CANDIDATE_LABEL_JS`, which
`backend/dom_probe.py` also needs and therefore is public.
"""

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

def _splice(body: str, **fragments) -> str:
    """Put the shared JS fragments back into a body's ``__MARKER__`` lines.

    A fragment loses its own blank margins on the way in, so a body made of
    pieces reads exactly like one written out in full — which is what keeps
    the script the page runs byte-identical to the hand-written one.
    """
    for name, fragment in fragments.items():
        body = body.replace(f"__{name.upper()}__", fragment.strip("\n"))
    return body


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


#: The wrapper every probe shares: the diagnostic object, the helper
#: functions, one try/catch that turns a thrown JS error into ``out.error``
#: (so a broken page can never raise across CDP), and the JSON reply.
#:
#: ``build_clear_probe()`` is the one probe that deliberately skips the
#: chassis: it answers ``{cleared: n}`` and must do so even on a page with no
#: overlay, no helper and no diagnostic object at all.
_PROBE_JS = """
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


# ── JS fragments more than one probe needs ──────────────────────────────
#: How the FIND and HIGHLIGHT probes read their arguments. In one place on
#: purpose: a new argument used to mean editing two bodies, and missing one
#: left the two probes matching against different text.
_QUERY_VARS = """
    var sel = %(selector)s;
    var childSel = %(label_selector)s;
    var matchText = %(match_text)s;
    var exact = %(exact)s;
"""


#: The label of one candidate node: the root's own text, or the inner element
#: the caller named with ``label_selector``.
#:
#: PUBLIC because `backend/dom_probe.py` walks candidates the same way. It was
#: written out a second time there, and pylint's R0801 flagged the pair: two
#: copies of "what counts as this node's text" can drift, and then the probe
#: that reports a match and the probe that highlights it disagree about which
#: node matched. One definition, two callers.
CANDIDATE_LABEL_JS = """
      var node = nodes[i];
      var el = node;
      var label = (node.textContent || '').trim().replace(/\\s+/g, ' ');
      if (childSel) {
        var c = node.querySelector(childSel);
        if (c) { el = c; label = (c.textContent || '').trim().replace(/\\s+/g, ' '); }
      }"""


#: The exact/contains filter. "Anna must never match Annabelle" is one rule
#: the two matching probes may not implement twice.
_MATCH_JS = """
      if (matchText !== null && matchText !== undefined && matchText !== '') {
        if (exact) { if (label !== matchText) { continue; } }
        else { if (label.indexOf(matchText) < 0) { continue; } }
      }
"""


#: Phase 1: locate the node, report what was found, draw the RED outline,
#: and stash the element for the click phase.
_FIND_BODY = _splice("""
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
""", query=_QUERY_VARS, label=CANDIDATE_LABEL_JS, match=_MATCH_JS)


#: Visual confirmation only: highlight the first match. Never clicks, never
#: scrolls, never touches the click stash — the scroll parser marks every
#: person who matched the filter with this probe, one row at a time.
_HIGHLIGHT_BODY = _splice("""
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
""", query=_QUERY_VARS, label=CANDIDATE_LABEL_JS, match=_MATCH_JS)


#: Phase 2: re-check the stashed element, draw the ORANGE outline on the
#: click target, then click it. It works from ``window.__cfStash`` rather
#: than a query, so it shares none of the fragments above.
_CLICK_BODY = """
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
