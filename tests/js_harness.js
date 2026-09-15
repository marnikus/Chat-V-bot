/* Minimal DOM stub good enough to execute the generated probe expressions.
   Reads {expr, html} JSON on stdin, prints the probe's JSON result plus the
   observable side effects (clicks dispatched, overlays created). */
'use strict';

let chunks = '';
process.stdin.on('data', (d) => { chunks += d; });
process.stdin.on('end', () => {
  const { exprs, nodes } = JSON.parse(chunks);
  const effects = { clicks: [], overlays: [], scrolled: [] };
  let idSeq = 0;

  function mkEl(spec) {
    spec = spec || {};
    const el = {
      tagName: (spec.tag || 'DIV').toUpperCase(),
      className: spec.className || '',
      textContent: spec.text || '',
      disabled: !!spec.disabled,
      isConnected: spec.detached ? false : true,
      offsetWidth: spec.hidden ? 0 : (spec.width === undefined ? 100 : spec.width),
      offsetHeight: spec.hidden ? 0 : (spec.height === undefined ? 20 : spec.height),
      style: { cssText: '' },
      children: [],
      _id: idSeq++,
      _spec: spec,
      getClientRects() { return (this.offsetWidth || this.offsetHeight) ? [{}] : []; },
      getBoundingClientRect() {
        return { left: spec.x || 0, top: spec.y || 0,
                 x: spec.x || 0, y: spec.y || 0,
                 width: this.offsetWidth, height: this.offsetHeight };
      },
      matches(sel) { return matches(this, sel); },
      querySelector(sel) {
        for (const c of this.children) if (matches(c, sel)) return c;
        return null;
      },
      appendChild(c) { this.children.push(c); c.parentNode = this; return c; },
      removeChild(c) {
        const i = this.children.indexOf(c);
        if (i >= 0) this.children.splice(i, 1);
        c.parentNode = null; return c;
      },
      setAttribute(k, v) { (this._attrs = this._attrs || {})[k] = v; },
      scrollIntoView() { effects.scrolled.push(describe(this)); },
      click() {
        if (spec.throwOnClick) throw new Error('click blew up');
        effects.clicks.push(describe(this));
      },
    };
    (spec.children || []).forEach((c) => el.appendChild(mkEl(c)));
    return el;
  }

  function describe(el) {
    const cls = el.className ? '.' + String(el.className).trim().split(/\s+/).join('.') : '';
    return el.tagName.toLowerCase() + cls;
  }

  // Small selector matcher: tag, .cls, [attr='v'] and combinations thereof,
  // e.g. "div[role='tab'].tab-item" or "p.chat-title".
  function matches(el, sel) {
    sel = String(sel).trim();
    const m = /^([a-zA-Z-]+)?((?:\[[^\]]+\]|\.[\w-]+)*)$/.exec(sel);
    if (!m) return (el._spec.sel || '') === sel;
    const [, tag, rest] = m;
    if (tag && el.tagName.toLowerCase() !== tag.toLowerCase()) return false;
    const have = String(el.className || '').split(/\s+/).filter(Boolean);
    const parts = rest ? rest.match(/\[[^\]]+\]|\.[\w-]+/g) || [] : [];
    for (const p of parts) {
      if (p[0] === '.') {
        if (!have.includes(p.slice(1))) return false;
      } else {
        const am = /^\[([\w-]+)(?:([~|^$*]?=)['"]?([^'"\]]*)['"]?)?\]$/.exec(p);
        if (!am) return false;
        const [, name, op, want] = am;
        const attrs = el._spec.attrs || {};
        const got = attrs[name];
        if (got === undefined) return false;
        if (op && String(got) !== want) return false;
      }
    }
    return true;
  }

  const roots = (nodes || []).map(mkEl);
  const overlayHost = mkEl({ tag: 'BODY' });

  const document = {
    body: overlayHost,
    documentElement: overlayHost,
    querySelectorAll(sel) {
      if (String(sel).startsWith('[')) {          // overlay cleanup query
        return overlayHost.children.filter((c) => c._attrs && c._attrs['data-cf-highlight']);
      }
      const out = [];
      const walk = (el) => { if (matches(el, sel)) out.push(el); el.children.forEach(walk); };
      roots.forEach(walk);
      return out;
    },
    createElement(tag) {
      const el = mkEl({ tag });
      if (tag === 'div') el._maybeOverlay = true;
      return el;
    },
  };

  const timers = [];
  const window = {
    getComputedStyle(el) {
      return { display: el._spec.hidden ? 'none' : 'block',
               visibility: el._spec.invisible ? 'hidden' : 'visible',
               pointerEvents: el._spec.pointerEventsNone ? 'none' : 'auto' };
    },
  };
  const setTimeout_ = (fn, ms) => { timers.push({ fn, ms }); return timers.length; };

  // Run every phase against the SAME window/document so window.__cfStash
  // carries the found element from the find phase into the click phase,
  // exactly as it does in a real page.
  const results = [];
  const overlaysPerPhase = [];
  for (const expr of exprs) {
    // NB: trim — a leading newline after `return` triggers ASI.
    const run = new Function('window', 'document', 'setTimeout', 'return (' + String(expr).trim() + ');');
    let out;
    try { out = JSON.parse(run(window, document, setTimeout_)); }
    catch (e) { out = { harness_error: String((e && e.message) || e) }; }
    results.push(out);
    overlaysPerPhase.push(overlayHost.children
      .filter((c) => c._attrs && c._attrs['data-cf-highlight'])
      .map((c) => ({ css: c.style.cssText,
                     caption: c.children.length ? c.children[0].textContent : null })));
  }
  effects.overlays = overlaysPerPhase;
  effects.timers = timers.map((t) => t.ms);
  process.stdout.write(JSON.stringify({ results, effects }));
});
