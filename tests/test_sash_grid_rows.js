/* Row creation by drag & drop + minimum-size reflow (Issue 4 / bug 5).
 *
 * Runs the REAL shipped modules (sash-core.js, preset-adapt.js,
 * sash-grid.js) in Node against the same tiny DOM stub pattern as
 * test_sash_grid_window_controls.js — the stub executes the real render
 * pipeline (AGENT_RULES RULE 6). Pinned behaviours:
 *
 *   • a row can be created ABOVE the first window, BELOW the last one and
 *     BETWEEN two existing rows (sibling insert + horizontal-sash insert);
 *   • the drop preview for a row is a FULL-WIDTH horizontal bar;
 *   • after any drop every window keeps its minimum height at a feasible
 *     viewport (the bug-5 regression: a 50/50 split of a short slot used
 *     to overflow and cover the neighbouring sashes);
 *   • the rendered DOM carries one horizontal sash per stacked boundary;
 *   • undo (_applySerialized) restores the previous arrangement EXACTLY —
 *     the minimum-size pass must not touch the restore path;
 *   • installing a preset layout re-fits the minimums, while an explicit
 *     resize commit stays exact (the pinned resize contract).
 *
 * Run:  node tests/test_sash_grid_rows.js      → exits 0, prints OK.
 */
'use strict';


// ── minimal DOM stub (window-controls pattern) ──────────────────
function mkEl(tag, className) {
  const el = {
    tagName: String(tag || 'div').toUpperCase(),
    className: className || '',
    id: '', textContent: '', title: '', _innerHTML: '', _attrs: {},
    children: [], parentNode: null, dataset: {}, style: {},
    offsetWidth: 100, offsetHeight: 100, _listeners: {},
    classList: {
      _set: new Set((className || '').split(/\s+/).filter(Boolean)),
      add(...cs) { cs.forEach((c) => this._set.add(c)); },
      remove(...cs) { cs.forEach((c) => this._set.delete(c)); },
      contains(c) { return this._set.has(c); },
      toggle(c, on) { if (on === undefined) on = !this._set.has(c); on ? this._set.add(c) : this._set.delete(c); },
    },
    setAttribute(k, v) { this._attrs[k] = v; },
    getAttribute(k) { return this._attrs[k]; },
    addEventListener(ev, fn) { (this._listeners[ev] = this._listeners[ev] || []).push(fn); },
    removeEventListener() {}, setPointerCapture() {}, releasePointerCapture() {},
    closest() { return null; }, click() {},
  };
  Object.defineProperty(el, 'innerHTML', {
    get() { return this._innerHTML; },
    set(v) { this._innerHTML = String(v);
      if (String(v) === '') { this.children.forEach((c) => { c.parentNode = null; }); this.children = []; } },
  });
  Object.defineProperty(el, 'nextSibling', {
    get() {
      if (!this.parentNode) return null;
      const kids = this.parentNode.children;
      const i = kids.indexOf(this);
      return i >= 0 && i + 1 < kids.length ? kids[i + 1] : null;
    },
  });
  el.appendChild = (node) => {
    if (!node) return node;
    if (node.parentNode) {
      const sib = node.parentNode.children;
      const i = sib.indexOf(node);
      if (i >= 0) sib.splice(i, 1);
    }
    node.parentNode = el; el.children.push(node); return node;
  };
  el.removeChild = (node) => {
    const i = el.children.indexOf(node);
    if (i >= 0) { el.children.splice(i, 1); node.parentNode = null; }
    return node;
  };
  el.replaceChildren = (...nodes) => {
    el.children.forEach((c) => { c.parentNode = null; });
    el.children = [];
    nodes.forEach((n) => { if (n) { n.parentNode = el; el.children.push(n); } });
  };
  el.insertBefore = (node, ref) => {
    if (node.parentNode) {
      const sib = node.parentNode.children;
      const i = sib.indexOf(node);
      if (i >= 0) sib.splice(i, 1);
    }
    node.parentNode = el;
    if (ref == null) { el.children.push(node); return node; }
    const ri = el.children.indexOf(ref);
    if (ri < 0) throw new Error('insertBefore: missing reference node');
    el.children.splice(ri, 0, node); return node;
  };
  el.querySelector = (sel) => queryAll(el, sel)[0] || null;
  el.querySelectorAll = (sel) => queryAll(el, sel);
  return el;
}

function tokenize(sel) {
  const toks = []; let cur = ''; let inB = 0, inP = 0;
  const push = () => { const s = cur.trim(); if (!s) return;
    if (s === '>') toks.push({ comb: 'child' }); else toks.push({ comp: parseCompound(s) }); cur = ''; };
  for (const ch of String(sel)) {
    if (ch === '[') inB++;
    if (ch === ']') inB--;
    if (ch === '(') inP++;
    if (ch === ')') inP--;
    if (ch === ' ' && !inB && !inP) { push(); continue; }
    cur += ch;
  }
  push();
  return toks;
}
function parseCompound(part) {
  const c = { tag: null, id: null, classes: [], attrs: [], notClasses: [], scope: false };
  if (String(part).trim() === ':scope') { c.scope = true; return c; }
  let i = 0;
  while (i < part.length) {
    const ch = part[i];
    if (ch === '.') { let j = i + 1; while (j < part.length && /[\w-]/.test(part[j])) j++;
      if (j > i + 1) c.classes.push(part.slice(i + 1, j)); i = j; }
    else if (ch === '#') { let j = i + 1; while (j < part.length && /[\w-]/.test(part[j])) j++;
      c.id = part.slice(i + 1, j); i = j; }
    else if (part.startsWith(':not(', i)) { const close = part.indexOf(')', i);
      const inner = part.slice(i + 5, close < 0 ? part.length : close);
      if (inner[0] === '.') c.notClasses.push(inner.slice(1));
      i = (close < 0 ? part.length : close + 1); }
    else if (part.startsWith(':scope', i)) { c.scope = true; i += 6; }
    else if (ch === '[') { const close = part.indexOf(']', i);
      const body = part.slice(i + 1, close < 0 ? part.length : close);
      const eq = body.indexOf('=');
      let name = body, val = null;
      if (eq >= 0) { name = body.slice(0, eq); val = eq + 1 < body.length ? body.slice(eq + 1).replace(/^"/, '').replace(/"$/, '') : ''; }
      c.attrs.push([name, val]); i = (close < 0 ? part.length : close + 1); }
    else if (/[a-zA-Z]/.test(ch)) { let j = i + 1; while (j < part.length && /[\w-]/.test(part[j])) j++;
      c.tag = part.slice(i, j).toLowerCase(); i = j; }
    else i++;
  }
  return c;
}
function matchCompound(el, c) {
  if (!el || !el.classList) return false;
  if (c.tag && el.tagName.toLowerCase() !== c.tag) return false;
  if (c.id && el.id !== c.id) return false;
  const have = el.classList._set;
  const names = String(el.className || '').split(/\s+/).filter(Boolean);
  const hasCls = (x) => have.has(x) || names.indexOf(x) !== -1;
  for (const cls of c.classes) if (!hasCls(cls)) return false;
  for (const cls of c.notClasses) if (hasCls(cls)) return false;
  for (const [name, val] of c.attrs) {
    const dsKey = name.indexOf('data-') === 0 ? name.slice(5) : name;
    const got = el._attrs[name] !== undefined ? el._attrs[name] : el.dataset[dsKey];
    if (got === undefined || got === null) return false;
    if (val !== null && String(got) !== val) return false;
  }
  return true;
}
function descendantsOf(el) {
  const out = []; const stack = [el];
  while (stack.length) { const n = stack.pop();
    for (const c of n.children || []) { out.push(c); stack.push(c); } }
  return out;
}
function queryAll(root, sel) {
  const toks = tokenize(sel);
  if (!toks.length) return [];
  let set;
  if (toks[0].comp && toks[0].comp.scope) set = [root];
  else if (toks[0].comp) set = descendantsOf(root).filter((el) => matchCompound(el, toks[0].comp));
  else return [];
  let i = 1;
  while (i < toks.length) {
    if (toks[i].comb) { i++; continue; }
    let direct = false;
    let j = i - 1;
    while (j >= 0 && toks[j].comb) { if (toks[j].comb === 'child') direct = true; j--; }
    const next = [];
    for (const el of set) {
      if (direct) { for (const ch of el.children || []) if (matchCompound(ch, toks[i].comp)) next.push(ch); }
      else { for (const d of descendantsOf(el)) if (matchCompound(d, toks[i].comp)) next.push(d); }
    }
    set = next; i++;
  }
  return set;
}

// ── page globals ─────────────────────────────────────────────────
const byId = {};
function register(id, el) { el.id = id; byId[id] = el; return el; }
// 1400×1000: the three-move accumulation scenario needs 888 px of stacked
// minimums (two nested pairs) — a feasible viewport keeps the assertion
// "nothing under the minimum" honest instead of best-effort.
const VIEW = { width: 1400, height: 1000 };
const gridEl = register('sashGrid', mkEl('main', 'sash-grid'));
gridEl.getBoundingClientRect = () => ({ left: 0, top: 0, width: VIEW.width, height: VIEW.height });
const appLayout = mkEl('div', 'app-layout');
appLayout.appendChild(gridEl);

const PANEL_IDS = {
  stats: 'winStats', filters: 'winFilters', stack: 'winStack',
  config: 'blockConfigPanel', composer: 'winComposer',
  people: 'winPeople', log: 'winLog',
  history: 'winHistory', userdb: 'winUserDb', collector: 'winCollector',
  labels: 'winLabels', dbconn: 'winDbconn',
  botchat: 'winBotChat', botprompt: 'winBotPrompt',
};
function makePanel(id) {
  const p = mkEl('div', 'panel');
  const h3 = mkEl('h3', 'win-title');
  const grip = mkEl('span', 'win-grip');
  grip.textContent = '≡';
  h3.appendChild(grip);
  p.appendChild(h3);
  p.getBoundingClientRect = () => ({ left: 0, top: 0, width: 100, height: 60 });
  return register(id, p);
}
register('windowsMenu', mkEl('div', 'layout-menu windows-menu hidden'));
register('windowsMenuList', mkEl('div'));
register('windowsMenuBtn', mkEl('button'));
register('windowsShowAllBtn', mkEl('button'));
register('windowsHideAllBtn', mkEl('button'));
register('layoutMenu', mkEl('div', 'layout-menu hidden'));
register('layoutMenuBtn', mkEl('button'));
register('resetLayoutBtn', mkEl('button'));
function findById(root, id) {
  if (!root) return null;
  const stack = [root];
  while (stack.length) { const n = stack.pop();
    if (n.id === id) return n;
    for (const c of n.children || []) stack.push(c); }
  return null;
}
global.document = {
  getElementById(id) { return byId[id] || findById(appLayout, id); },
  createElement(tag) { return mkEl(tag); },
  addEventListener() {},
};
global.window = global;
global.localStorage = (() => { const m = {};
  return { getItem: (k) => (k in m ? m[k] : null), setItem: (k, v) => { m[k] = String(v); },
    removeItem: (k) => { delete m[k]; }, clear() { for (const k of Object.keys(m)) delete m[k]; } }; })();
global.LogConsole = { log() {} };
global.App = { bridge: null, recordGlobal() {} };
global.MutationObserver = class { constructor() {} observe() {} disconnect() {} };
global.getComputedStyle = () => ({ display: '' });

// the REAL shipped family, loaded like index.html does (Round H, H-A3:
// facade + four parts + the DOM-free model + the adaptive-restore mirror)
const { FAMILIES, loadFamily } = require('./js_family');
loadFamily(FAMILIES.sashGrid);
const SashCore = global.SashCore;
const SashGrid = global.SashGrid;
for (const w of SashCore.WINDOWS) makePanel(PANEL_IDS[w.id]);
SashGrid.init();

// ── helpers ──────────────────────────────────────────────────────
let passed = 0, failed = 0;
function t(name, fn) {
  try { fn(); passed++; }
  catch (e) { failed++; console.error('FAIL ' + name + '\n   ' + (e && e.stack || e)); }
}
function ok(cond, msg) { if (!cond) throw new Error(msg || 'expected truthy'); }
function eq(a, b, msg) {
  if (JSON.stringify(a) !== JSON.stringify(b))
    throw new Error((msg || 'eq') + ': got ' + JSON.stringify(a) + ' want ' + JSON.stringify(b));
}
function fresh() {
  SashGrid.root = SashCore.defaultTree();
  SashGrid.closedWindows = new Set();
  SashGrid.minimizedWindows = new Set();
  SashGrid.render();
}
/** Every leaf's rendered height, walking the tree with the sash gaps. */
function leafHeights(tree, h) {
  const out = [];
  const walk = (node, height) => {
    if (SashCore.isLeaf(node)) { out.push(height); return; }
    const gap = SashGrid.SASH_W * (node.children.length - 1);
    node.children.forEach((c, i) => walk(c,
      node.dir === 'col' ? (height - gap) * node.sizes[i] / 100 : height));
  };
  walk(tree, h);
  return out;
}
function stackedBoundaries(node) {
  if (SashCore.isLeaf(node)) return 0;
  return (node.dir === 'col' ? node.children.length - 1 : 0) +
    node.children.reduce((a, c) => a + stackedBoundaries(c), 0);
}

// ══════════════════════════════════════════════════════════════════

t('a drop on the TOP edge creates a row above the target', () => {
  fresh();
  SashGrid.simulateDrop('log', 'stats', 'top');
  const f = SashCore.findNode(SashGrid.root, 'log');
  ok(f.parent && f.parent.dir === 'col', 'log sits in a stacked split');
  eq(f.parent.children.map((c) => c.id), ['log', 'stats'], 'log is the row ABOVE stats');
  ok(SashCore.validate(SashGrid.root) === null, 'tree valid');
});

t('a drop on the BOTTOM edge creates a row below the target', () => {
  fresh();
  SashGrid.simulateDrop('log', 'botprompt', 'bottom');
  const f = SashCore.findNode(SashGrid.root, 'log');
  ok(f.parent && f.parent.dir === 'col', 'log sits in a stacked split');
  eq(f.parent.children.map((c) => c.id), ['botprompt', 'log'], 'log is the row BELOW botprompt');
});

t('a sibling drop inserts a MIDDLE row between two existing rows', () => {
  fresh();
  SashGrid.simulateDrop('log', 'composer', 'before');
  const ids = SashGrid.root.children.map((c) => (c.t === 'leaf' ? c.id : 'group'));
  // moving log also vacates the people row, which collapses to a leaf
  eq(ids, ['group', 'log', 'composer', 'people', 'group', 'group', 'group'],
    'log became its own root row between row 1 and composer');
  ok(SashCore.validate(SashGrid.root) === null, 'tree valid');
});

t('a horizontal-sash drop inserts a middle row (model contract)', () => {
  const tree = SashCore.moveWindow(SashCore.defaultTree(), 'log',
    { kind: 'sash', left: 'composer', right: 'people' });
  const ids = tree.children.map((c) => (c.t === 'leaf' ? c.id : 'group'));
  eq(ids, ['group', 'composer', 'log', 'people', 'group', 'group', 'group'],
    'log landed between the composer and people rows');
  ok(SashCore.validate(tree) === null, 'tree valid');
});

t('the row drop preview is a FULL-WIDTH horizontal bar', () => {
  fresh();
  const indicator = mkEl('div', 'sash-drop-indicator');
  const badge = mkEl('div', 'sash-drag-badge');
  SashGrid._drag = {
    id: 'log', rects: { composer: { left: 100, top: 300, width: 1200, height: 120 } },
    sashes: [], indicator, badge, targetEl: null, lastX: 400, lastY: 320,
  };
  SashGrid._showSpec({ kind: 'edge', target: 'composer', zone: 'top', dir: 'col', newFirst: true });
  eq(indicator.style.width, '1200px', 'the bar spans the whole target width');
  eq(indicator.style.height, '3px', 'a thin horizontal line');
  ok(badge.textContent.includes('top of Message Composer'), 'badge names the row position');
  SashGrid._drag = null;
});

t('after a row-creating drop every window keeps its minimum height (bug 5)', () => {
  fresh();
  SashGrid.simulateDrop('log', 'composer', 'bottom');   // the 52-px repro
  const heights = leafHeights(SashGrid.root, VIEW.height);
  const under = heights.filter((h) => h < 96 - 0.001).length;
  eq(under, 0, 'no leaf under the 96px minimum at a feasible viewport');
  const f = SashCore.findNode(SashGrid.root, 'log');
  ok(f.parent.dir === 'col', 'the new row still exists');
});

t('the repeated-move accumulation scenario stays minimum-clean', () => {
  fresh();
  SashGrid.simulateDrop('log', 'composer', 'bottom');
  SashGrid.simulateDrop('people', 'stats', 'bottom');
  SashGrid.simulateDrop('userdb', 'filters', 'top');
  const under = leafHeights(SashGrid.root, VIEW.height).filter((h) => h < 96 - 0.001).length;
  eq(under, 0, 'three row-creating moves leave nothing under the minimum');
  ok(SashCore.validate(SashGrid.root) === null, 'tree valid');
});

t('the rendered DOM carries one horizontal sash per stacked boundary', () => {
  fresh();
  SashGrid.simulateDrop('log', 'composer', 'bottom');
  const sashes = gridEl.querySelectorAll('.sash-h');
  eq(sashes.length, stackedBoundaries(SashGrid.root),
    'no horizontal sash went missing after the move');
  ok(sashes.every((s) => !s.classList.contains('sash-hidden')),
    'with every window open no sash is hidden');
});

t('undo restores the previous arrangement byte-for-byte', () => {
  fresh();
  const before = SashCore.serialize(SashGrid.root);
  SashGrid.simulateDrop('log', 'composer', 'bottom');
  ok(SashCore.serialize(SashGrid.root) !== before, 'the drop changed the tree');
  SashGrid._applySerialized(before, false);   // the global-undo grid path
  eq(SashCore.serialize(SashGrid.root), before, 'undo restores the exact tree');
});

t('installing a preset layout re-fits the minimums', () => {
  fresh();
  SashGrid.setLayout('a');   // 14 stacked rows cannot fit 900px — degrade fairly
  const sizes = SashGrid.root.sizes;
  const spread = Math.max(...sizes) - Math.min(...sizes);
  ok(spread < 1, 'fair degradation: rows end up equal, got spread ' + spread.toFixed(2));
  ok(SashCore.validate(SashGrid.root) === null, 'tree valid');
  SashGrid.setLayout('default');
});

t('an explicit resize commit stays EXACT (no enforcement behind the drag)', () => {
  fresh();
  SashGrid.simulateResize('0', 30);   // first row's split: left group → 30 %
  const first = SashCore.nodeAtPath(SashGrid.root, [0]).sizes[0];
  ok(Math.abs(first - 30) < 0.5, 'committed size is the requested one, got ' + first);
});

console.log('sash_grid_rows: ' + passed + ' passed, ' + failed + ' failed');
if (failed) process.exit(1);
console.log('OK');
