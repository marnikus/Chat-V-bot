/* Regression tests for the window controls bugfix:
   minimize = release the grid slot + dock a title strip at the bottom edge,
   restore (maximize) = bring it back, no full-grid maximize state.

   Runs the REAL shipped modules (ui/js/sash-core.js + ui/js/sash-grid.js)
   in Node against a tiny DOM stub that executes the actual render pipeline
   (buildNode → ensureWindowControls → applyStates) — AGENT_RULES RULE 6.

   The DOM stub deliberately implements only the surface sash-grid.js uses:
   createElement/appendChild/replaceChildren/insertBefore, classList, dataset,
   style, innerHTML (content string), getElementById and a small selector
   engine (:scope >, .class, #id, [data-win="v"], :not(...)). If sash-grid.js
   ever reaches for a new DOM feature, these tests break — which is the point.

   Run:  node tests/test_sash_grid_window_controls.js
   Exits 0 + prints "OK" when every test passes.
*/
'use strict';

const fs = require('fs');
const path = require('path');

// ── load the real modules ──────────────────────────────────────────
const coreSrc = fs.readFileSync(path.join(__dirname, '..', 'ui', 'js', 'sash-core.js'), 'utf8');
const coreModule = { exports: {} };
new Function('module', 'exports', coreSrc)(coreModule, coreModule.exports);
global.SashCore = coreModule.exports;

// ── minimal DOM stub ───────────────────────────────────────────────
let ID_SEQ = 0;
function mkEl(tag, className) {
  const el = {
    tagName: String(tag || 'div').toUpperCase(),
    className: className || '',
    id: '',
    textContent: '',
    title: '',
    _innerHTML: '',
    _attrs: {},
    children: [],
    parentNode: null,
    dataset: {},
    style: {},
    offsetWidth: 100,
    offsetHeight: 100,
    _listeners: {},
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
    removeEventListener() {},
    setPointerCapture() {},
    releasePointerCapture() {},
    closest() { return null; },
    click() {},
  };
  Object.defineProperty(el, 'innerHTML', {
    get() { return this._innerHTML; },
    set(v) {
      this._innerHTML = String(v);
      // The stub does not parse arbitrary HTML; children are created through
      // createElement/appendChild. Setting '' clears the node.
      if (String(v) === '') { this.children.forEach((c) => { c.parentNode = null; }); this.children = []; }
    },
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
    node.parentNode = el;
    el.children.push(node);
    return node;
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
    if (ref === null || ref === undefined) { el.children.push(node); return node; }
    const ri = el.children.indexOf(ref);
    if (ri < 0) throw new Error('insertBefore: missing reference node');
    el.children.splice(ri, 0, node);
    return node;
  };
  el.querySelector = (sel) => queryAll(el, sel)[0] || null;
  el.querySelectorAll = (sel) => queryAll(el, sel);
  return el;
}

// tiny selector engine: compound selectors joined by spaces (descendant)
// or '>' (child). Compound = tag?, #id, .class, [attr="v"], :not(.class),
// :scope. Matches the surface sash-grid.js actually queries.
function tokenize(sel) {
  const toks = [];
  let cur = '';
  let inBracket = 0, inParen = 0;
  const push = () => {
    const s = cur.trim();
    if (!s) return;
    if (s === '>') toks.push({ comb: 'child' });
    else toks.push({ comp: parseCompound(s) });
    cur = '';
  };
  for (const ch of String(sel)) {
    if (ch === '[') inBracket++;
    if (ch === ']') inBracket--;
    if (ch === '(') inParen++;
    if (ch === ')') inParen--;
    if (ch === ' ' && !inBracket && !inParen) { push(); continue; }
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
    if (ch === '.') {
      let j = i + 1;
      while (j < part.length && /[\w-]/.test(part[j])) j++;
      if (j > i + 1) c.classes.push(part.slice(i + 1, j));
      i = j;
    } else if (ch === '#') {
      let j = i + 1;
      while (j < part.length && /[\w-]/.test(part[j])) j++;
      c.id = part.slice(i + 1, j);
      i = j;
    } else if (part.startsWith(':not(', i)) {
      const close = part.indexOf(')', i);
      const inner = part.slice(i + 5, close < 0 ? part.length : close);
      if (inner[0] === '.') c.notClasses.push(inner.slice(1));
      i = (close < 0 ? part.length : close + 1);
    } else if (part.startsWith(':scope', i)) {
      c.scope = true;
      i += 6;
    } else if (ch === '[') {
      const close = part.indexOf(']', i);
      const body = part.slice(i + 1, close < 0 ? part.length : close);
      const eq = body.indexOf('=');
      let name = body, val = null;
      if (eq >= 0) {
        name = body.slice(0, eq);
        val = body.slice(eq + 1).replace(/^"/, '').replace(/"$/, '');
      }
      c.attrs.push([name, val]);
      i = (close < 0 ? part.length : close + 1);
    } else if (/[a-zA-Z]/.test(ch)) {
      let j = i + 1;
      while (j < part.length && /[\w-]/.test(part[j])) j++;
      c.tag = part.slice(i, j).toLowerCase();
      i = j;
    } else {
      i++;
    }
  }
  return c;
}

function matchCompound(el, c) {
  if (!el || !el.classList) return false;
  if (c.tag && el.tagName.toLowerCase() !== c.tag) return false;
  if (c.id && el.id !== c.id) return false;
  const have = el.classList._set;
  const classNames = String(el.className || '').split(/\s+/).filter(Boolean);
  const hasCls = (x) => have.has(x) || classNames.indexOf(x) !== -1;
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

function descendantsOf(el, includeSelf) {
  const out = [];
  if (includeSelf) out.push(el);
  const stack = [el];
  while (stack.length) {
    const node = stack.pop();
    for (const child of node.children || []) { out.push(child); stack.push(child); }
  }
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
    // determine combinator linking previous compound to this one
    let direct = false;
    let j = i - 1;
    while (j >= 0 && toks[j].comb) { if (toks[j].comb === 'child') direct = true; j--; }
    const next = [];
    for (const el of set) {
      if (direct) {
        for (const ch of el.children || []) if (matchCompound(ch, toks[i].comp)) next.push(ch);
      } else {
        for (const d of descendantsOf(el)) if (matchCompound(d, toks[i].comp)) next.push(d);
      }
    }
    set = next;
    i++;
  }
  return set;
}

// ── document / window / storage globals ───────────────────────────
const byId = {};
function register(id, el) { el.id = id; byId[id] = el; return el; }

const gridEl = register('sashGrid', mkEl('main', 'sash-grid'));
const appLayout = mkEl('div', 'app-layout');
appLayout.appendChild(gridEl);

const byIdPanels = {};
function makePanel(id) {
  const p = mkEl('div', 'panel');
  const h3 = mkEl('h3', 'win-title');
  const grip = mkEl('span', 'win-grip');
  grip.textContent = '≡';
  h3.appendChild(grip);
  p.appendChild(h3);
  const reg = register(id, p);
  byIdPanels[id] = reg;
  return reg;
}
// window id -> html panel element id (mirrors SashGrid.init winElIds)
const PANEL_IDS = {
  stats: 'winStats', filters: 'winFilters', stack: 'winStack',
  config: 'blockConfigPanel', composer: 'winComposer',
  people: 'winPeople', log: 'winLog',
  history: 'winHistory', userdb: 'winUserDb', collector: 'winCollector',
  labels: 'winLabels', dbconn: 'winDbconn',
};

const windowsMenu = register('windowsMenu', mkEl('div', 'layout-menu windows-menu hidden'));
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
  while (stack.length) {
    const node = stack.pop();
    if (node.id === id) return node;
    for (const child of node.children || []) stack.push(child);
  }
  return null;
}
global.document = {
  _byId: byId,
  getElementById(id) { return byId[id] || findById(appLayout, id); },
  createElement(tag) { return mkEl(tag); },
  addEventListener() {},
};
global.window = global;
global.localStorage = (() => {
  const m = {};
  return {
    getItem(k) { return k in m ? m[k] : null; },
    setItem(k, v) { m[k] = String(v); },
    removeItem(k) { delete m[k]; },
    clear() { for (const k of Object.keys(m)) delete m[k]; },
    _map: m,
  };
})();
global.LogConsole = { log() {} };
global.App = { bridge: null, recordGlobal() {} };
global.MutationObserver = class { constructor() {} observe() {} disconnect() {} };
global.getComputedStyle = () => ({ display: '' });

// ── load the real shipped sash-grid.js ────────────────────────────
const gridSrc = fs.readFileSync(path.join(__dirname, '..', 'ui', 'js', 'sash-grid.js'), 'utf8');
const SashGrid = new Function('return (function() {\n' + gridSrc + '\nreturn SashGrid;\n})();')();

// panels exist in the DOM before init (like ui/index.html)
for (const w of SashCore.WINDOWS) makePanel(PANEL_IDS[w.id]);

SashGrid.init();

// ── helpers ────────────────────────────────────────────────────────
const winElOf = (id) => gridEl.querySelector('.sash-window[data-win="' + id + '"]');
const dockEl = () => document.getElementById('sashMinDock');
const chips = () => (dockEl() ? dockEl().querySelectorAll('.sash-min-chip') : []);
const chipOf = (id) => dockEl() && dockEl().querySelector('.sash-min-chip[data-win="' + id + '"]');
const toggleIn = (id) => winElOf(id).querySelector(':scope > .panel > .win-title .win-toggle');
const closeIn = (id) => winElOf(id).querySelector(':scope > .panel > .win-title .win-close');

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

// reset between tests
function freshState() {
  SashGrid.showAllWindows();
  global.localStorage.clear();
  SashGrid._loadWindowStates();
  SashGrid.render();
}

// ══════════════════════════════════════════════════════════════════

t('every window renders the two standard controls (─ + ✕) with tooltips', () => {
  freshState();
  for (const w of SashCore.WINDOWS) {
    const win = winElOf(w.id);
    ok(win, 'wrapper exists for ' + w.id);
    const toggle = toggleIn(w.id);
    const close = closeIn(w.id);
    ok(toggle && close, 'controls exist for ' + w.id);
    ok(toggle.textContent === '─', 'toggle shows ─ while open (' + w.id + ')');
    ok(toggle.title === 'Minimize ' + w.title, 'toggle tooltip is "Minimize <title>"');
    ok(close.textContent === '✕', 'close shows ✕');
    ok(close.title === 'Close ' + w.title, 'close tooltip is "Close <title>"');
  }
});

t('minimize hides the wrapper, keeps the panel "open", and docks a strip', () => {
  freshState();
  const before = winElOf('people');
  ok(!before.classList.contains('sash-win-hidden'), 'people starts visible');
  ok(SashGrid.minimizeWindow('people') === true, 'minimizeWindow accepts');
  const after = winElOf('people');
  ok(after.classList.contains('sash-win-hidden'), 'wrapper marked sash-win-hidden (grid slot released)');
  ok(!after.classList.contains('sash-win-closed'), 'minimized ≠ closed');
  const panel = after.querySelector(':scope > .panel');
  ok(!panel.classList.contains('hidden'), 'panel itself stays open (no .hidden class)');
  ok(SashGrid.isMinimized('people') && !SashGrid.isClosed('people'), 'state set: minimized not closed');
  ok(!dockEl().classList.contains('hidden'), 'dock visible when something is minimized');
  const chip = chipOf('people');
  ok(chip, 'dock contains a chip for the minimized window');
  ok(chip.title === 'Restore User Memory', 'chip tooltip says Restore');
  ok(chip.querySelector('.smc-label').textContent === 'User Memory', 'chip label shows the window title');
  const restore = chip.querySelector('.win-toggle');
  const close = chip.querySelector('.win-close');
  ok(restore && restore.textContent === '□' && restore.title === 'Restore User Memory',
    'dock chip has a □ Restore button');
  ok(close && close.textContent === '✕' && close.title === 'Close User Memory',
    'dock chip has a ✕ Close button');
  const saved = JSON.parse(global.localStorage.getItem(SashGrid.STORAGE_MINIMIZED));
  ok(saved.includes('people'), 'minimized list persisted');
});

t('minimizing again is a no-op; closed windows cannot be minimized', () => {
  freshState();
  ok(SashGrid.minimizeWindow('people') === true, 'first minimize ok');
  ok(SashGrid.minimizeWindow('people') === false, 'second minimize refused');
  SashGrid.closeWindow('log');
  ok(SashGrid.minimizeWindow('log') === false, 'closed window cannot be minimized');
});

t('restore (maximize) brings the window back and empties the dock', () => {
  freshState();
  SashGrid.minimizeWindow('people');
  ok(SashGrid.restoreMinimized('people') === true, 'restoreMinimized ok');
  const win = winElOf('people');
  ok(!win.classList.contains('sash-win-hidden'), 'wrapper visible again after restore');
  ok(SashGrid.isMinimized('people') === false, 'minimized set cleared');
  ok(dockEl().classList.contains('hidden'), 'dock hides when nothing is minimized');
  ok(chipOf('people') === null, 'dock chip removed');
  const saved = JSON.parse(global.localStorage.getItem(SashGrid.STORAGE_MINIMIZED));
  ok(!saved.includes('people'), 'persisted minimized list cleared');
});

t('dock strip click restores; dock ✕ closes the window', () => {
  freshState();
  SashGrid.minimizeWindow('log');
  const chip = chipOf('log');
  // click the chip body (label)
  chip.querySelector('.smc-label').addEventListener('click', function (e) {
    // simulate: click bubbles to the chip; e.target = label
    chip._listeners.click.forEach((fn) => fn.call(chip, { target: chip.querySelector('.smc-label'), stopPropagation() {} }));
  });
  // simpler: call the chip's own click listener directly with a non-button target
  const ev = { target: chip.querySelector('.smc-label'), stopPropagation() {} };
  for (const fn of chip._listeners.click || []) fn.call(chip, ev);
  ok(!SashGrid.isMinimized('log'), 'chip body click restored the window');

  freshState();
  SashGrid.minimizeWindow('log');
  const chip2 = chipOf('log');
  for (const fn of chip2.querySelector('.win-close')._listeners.click || []) {
    fn({ stopPropagation() {} });
  }
  ok(SashGrid.isClosed('log'), 'dock ✕ closed the window');
  ok(!SashGrid.isMinimized('log'), 'closing a minimized window clears minimized');
  ok(chipOf('log') === null, 'chip removed after close');
});

t('title-bar toggle click minimizes; second click (via restore) brings back', () => {
  freshState();
  const toggle = toggleIn('composer');
  for (const fn of toggle._listeners.click || []) fn({ stopPropagation() {} });
  ok(SashGrid.isMinimized('composer'), 'clicking ─ minimizes');
  ok(winElOf('composer').classList.contains('sash-win-hidden'), 'composer released its slot');
  // title bar is inside the hidden wrapper now — the □ restore lives on the chip
  const chip = chipOf('composer');
  ok(chip, 'chip present');
  for (const fn of chip.querySelector('.win-toggle')._listeners.click || []) fn({ stopPropagation() {} });
  ok(!SashGrid.isMinimized('composer'), 'chip □ restores');
});

t('close/open still work and redistribute space through the same hidden path', () => {
  freshState();
  SashGrid.closeWindow('history');
  ok(SashGrid.isClosed('history'), 'window closed');
  ok(winElOf('history').classList.contains('sash-win-closed'), 'sash-win-closed set');
  ok(SashGrid.openWindow('history') === true, 'reopen works');
  ok(!SashGrid.isClosed('history'), 'open clears closed');
});

t('windows menu reflects open / minimized / closed states', () => {
  freshState();
  SashGrid._renderWindowsMenu();
  let html = document.getElementById('windowsMenuList').innerHTML;
  ok(html.includes('data-win="stats"') && html.includes('>Open<'), 'stats listed Open');
  SashGrid.minimizeWindow('filters');
  SashGrid.closeWindow('config');
  SashGrid._renderWindowsMenu();
  html = document.getElementById('windowsMenuList').innerHTML;
  ok(html.includes('data-win="filters"') && html.includes('>Minimized<'), 'filters listed Minimized');
  ok(html.includes('data-win="config"') && html.includes('>Closed<'), 'config listed Closed');
  ok(html.indexOf('❐') === -1, 'no ❐ maximize glyph anywhere in the menu');
  ok(html.includes('data-action="open"') && html.includes('data-action="close"'),
    'closed rows offer Open; open/minimized rows offer Close');
});

t('window control toggle glyph follows state via _updateWindowControlIcons', () => {
  freshState();
  SashGrid.minimizeWindow('dbconn');
  // hidden window's title is gone from the grid, but icons function must still reflect
  // the minimized state (used by the dock chip too)
  const chip = chipOf('dbconn');
  ok(chip.querySelector('.win-toggle').textContent === '□', 'dock toggle is □');
});

t('legacy maximized localStorage value is ignored on load', () => {
  freshState();
  global.localStorage.setItem('chatbot.sashWindows.maximized.v1', '"log"');
  global.localStorage.setItem(SashGrid.STORAGE_MINIMIZED, JSON.stringify(['people']));
  SashGrid._loadWindowStates();
  ok(SashGrid.isMinimized('people'), 'minimized still loaded');
  ok(!SashGrid.isMinimized('log') && !SashGrid.isClosed('log'), 'maximized value ignored');
  ok(SashGrid.getWindowStates().maximized === undefined, 'no maximized key in getWindowStates');
  eq(SashGrid.getWindowStates(), { closed: [], minimized: ['people'] }, 'state shape is closed+minimized');
});

t('save payload sent to the backend contains no maximized key', () => {
  freshState();
  let sent = null;
  global.App = { bridge: { save_window_states(p) { sent = p; } } };
  SashGrid.minimizeWindow('stack');
  const parsed = JSON.parse(sent);
  eq(Object.keys(parsed).sort(), ['closed', 'minimized'], 'backend payload keys');
  ok(parsed.minimized.includes('stack'), 'stack minimized in payload');
});

t('showAllWindows clears minimized + closed and empties the dock', () => {
  freshState();
  SashGrid.minimizeWindow('people');
  SashGrid.minimizeWindow('log');
  SashGrid.closeWindow('history');
  SashGrid.showAllWindows();
  ok(SashGrid.minimizedWindows.size === 0 && SashGrid.closedWindows.size === 0, 'sets cleared');
  ok(dockEl().classList.contains('hidden'), 'dock hidden');
  ok(!winElOf('people').classList.contains('sash-win-hidden'), 'people visible again');
  ok(!winElOf('log').classList.contains('sash-win-hidden'), 'log visible again');
  ok(!winElOf('history').classList.contains('sash-win-closed'), 'history open again');
});

t('all-minimized shows the minimized empty hint', () => {
  freshState();
  SashCore.WINDOWS.forEach((w) => SashGrid.minimizeWindow(w.id));
  const empty = gridEl.querySelector('.sash-grid-empty');
  ok(empty, 'empty hint rendered');
  ok(empty.innerHTML.indexOf('All windows are minimized') !== -1, 'hint mentions minimized');
  ok(!dockEl().classList.contains('hidden'), 'dock still visible with all minimized');
});

// ── static contract: shipped CSS / HTML match the JS classes ──────
const css = fs.readFileSync(path.join(__dirname, '..', 'ui', 'css', 'sash-layout.css'), 'utf8');
const html = fs.readFileSync(path.join(__dirname, '..', 'ui', 'index.html'), 'utf8');

t('css: sash-win-hidden releases space and obsolete minimize/maximize rules are gone', () => {
  ok(/\.sash-window\.sash-win-hidden\s*\{\s*display:\s*none/.test(css),
    'sash-win-hidden must hide the wrapper (shared by closed + minimized)');
  ok(css.indexOf('.sash-win-minimized') === -1, 'obsolete in-place minimize CSS removed');
  ok(css.indexOf('.sash-window-maximized') === -1 && css.indexOf('.sash-grid-maximized') === -1,
    'obsolete full-grid maximize CSS removed');
});

t('css: dock + icon styles exist and use the dark-theme tokens', () => {
  ok(css.indexOf('.sash-min-dock') !== -1, '.sash-min-dock styled');
  ok(css.indexOf('.sash-min-chip') !== -1, '.sash-min-chip styled');
  ok(css.indexOf('.win-controls .win-btn') !== -1, 'win-btn base style present');
  ok(css.indexOf('--bg-header') !== -1 && css.indexOf('--border') !== -1,
    'dock uses the theme tokens');
});

t('html: windows menu captions describe open/minimized/closed', () => {
  ok(html.indexOf('id="windowsMenuBtn"') !== -1, 'windows menu button present');
  ok(html.indexOf('minimize and restore') !== -1, 'menu button tooltip updated');
  ok(html.indexOf('id="windowsMenuList"') !== -1, 'menu list container present');
});

// ══════════════════════════════════════════════════════════════════
console.log(`sash_grid_window_controls: ${passed} passed, ${failed} failed`);
if (failed) process.exitCode = 1;
else console.log('OK');
