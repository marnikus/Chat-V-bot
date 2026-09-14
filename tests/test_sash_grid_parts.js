/* test_sash_grid_parts.js — sash-grid family coverage lift (Round H, H-A6).
   Drag lifecycle, drop specs, sash resize, window persistence/ops, windows
   + layout menus, minimize dock. Executes the REAL shipped family
   (loadFamily) against a DOM stub (RULE 8). */
'use strict';
const assert = require('assert');

function matchFirst(root, sel) {
  if (sel.startsWith(':scope > ')) sel = sel.slice(9);
  let cls = null; let attr = null;
  const m = sel.match(/^\.[a-z-]+\[[a-z-]+="[^"]*"\]$/);
  if (m) {
    const p = sel.match(/^\.(.+)\[(.+?)="(.+?)"\]$/);
    cls = p[1]; attr = [p[2], p[3]];
  } else if (sel.startsWith('.')) cls = sel.slice(1);
  if (!cls) return null;
  const key = attr ? (attr[0].startsWith('data-') ? attr[0].slice(5) : attr[0]) : null;
  let found = null;
  (function rec(n) {
    if (found) return;
    n.children.forEach((c) => {
      if (found) return;
      if (c.classList && c.classList.contains(cls)
          && (!attr || (c.dataset ? c.dataset[key] : null) === attr[1])) found = c;
      rec(c);
    });
  })(root);
  return found;
}
function matchAll(root, sel) {
  if (sel === '*') {
    const out = [];
    (function rec(n) { n.children.forEach((c) => { out.push(c); rec(c); }); })(root);
    return out;
  }
  const cls = sel.startsWith('.') ? sel.slice(1) : null;
  const out = [];
  (function rec(n) {
    n.children.forEach((c) => {
      if (!cls || (c.classList && c.classList.contains(cls))) out.push(c);
      rec(c);
    });
  })(root);
  return out;
}

function makeEl(id, replaceListeners) {
  const set = new Set();
  const el = {
    id: id || '', tag: id || '', value: '', title: '', _cls: '',
    children: [], style: {}, dataset: {}, onclick: null, _text: '', _html: '',
    ow: 0, oh: 0, parent: null, _l: {},
    appendChild(c) { this.children.push(c); c.parent = this; return c; },
    insertBefore(c) { this.children.push(c); c.parent = this; return c; },
    replaceChildren(...kids) { this.children.length = 0; kids.forEach((k) => this.appendChild(k)); },
    removeChild(c) { const i = this.children.indexOf(c); if (i >= 0) this.children.splice(i, 1); },
    remove() { if (this.parent) this.parent.removeChild(this); },
    addEventListener(t, f) {
      if (replaceListeners) { this._l[t] = f; }
      else { (this._l[t] = this._l[t] || []).push(f); }
    },
    removeEventListener() {}, focus() {},
    setPointerCapture() { this._cap = true; },
    releasePointerCapture() { this._cap = false; },
    cloneNode() { const c = makeEl(); c.className = this.className; c.dataset = { ...this.dataset }; return c; },
    contains(n) { for (let p = n; p; p = p.parent) { if (p === this) return true; } return false; },
    getBoundingClientRect() { return el.rect || { left: 0, top: 0, right: 0, bottom: 0, width: 0, height: 0 }; },
    closest(sel) {
      const parts = String(sel).split(',').map((s) => s.trim());
      for (let n = this; n; n = n.parent) {
        if (parts.some((p) => {
          if (p.startsWith('.')) return n.classList && n.classList.contains(p.slice(1));
          if (p.startsWith('#')) return n.id === p.slice(1);
          return (n.tag || '').toUpperCase() === p.toUpperCase();
        })) return n;
      }
      return null;
    },
  };
  Object.defineProperty(el, 'isConnected', { get() { return !!el.parent; } });
  Object.defineProperty(el, 'parentElement', { get() { return el.parent; } });
  Object.defineProperty(el, 'parentNode', { get() { return el.parent; } });
  Object.defineProperty(el, 'offsetWidth', { get() { return el.ow; } });
  Object.defineProperty(el, 'offsetHeight', { get() { return el.oh; } });
  el.classList = { add(c) { set.add(c); }, remove(...c) { c.forEach((x) => set.delete(x)); },
    toggle(c, force) {
      const want = force === undefined ? !set.has(c) : !!force;
      if (want) set.add(c); else set.delete(c); return want;
    }, contains(c) { return set.has(c); } };
  Object.defineProperty(el, 'textContent', {
    get() { return el._text; },
    set(v) { el._text = v; },
  });
  Object.defineProperty(el, 'className', {
    get() { return el._cls; },
    set(v) {
      el._cls = String(v);
      set.clear();
      el._cls.split(/\s+/).filter(Boolean).forEach((c) => set.add(c));
    },
  });
  Object.defineProperty(el, 'innerHTML', {
    get() { return el._html; },
    set(v) { el._html = String(v); if (v === '') el.children.length = 0; },
    configurable: true,
  });
  el.fire = (type, ev) => (Array.isArray(el._l[type]) ? el._l[type].slice() : el._l[type] ? [el._l[type]] : []).forEach((f) => f(ev || {}));
  el.querySelector = (sel) => (el._qs ? el._qs(sel) : matchFirst(el, sel));
  el.querySelectorAll = (sel) => (el._qsa ? el._qsa(sel) : matchAll(el, sel));
  return el;
}

const els = {};
['sashGrid', 'windowsMenuBtn', 'windowsMenu', 'windowsShowAllBtn',
 'windowsHideAllBtn', 'windowsMenuList', 'layoutMenuBtn', 'layoutMenu',
 'resetLayoutBtn'].forEach((id) => { els[id] = makeEl(id); });
els.windowsMenu.classList.add('hidden');
els.layoutMenu.classList.add('hidden');

function panelEl(domId) {
  const p = makeEl(domId);
  p.id = domId;
  p.className = 'panel';
  const title = makeEl('win-title');
  title.className = 'win-title';
  const name = makeEl('win-name');
  name.className = 'win-name';
  title.appendChild(name);
  p.appendChild(title);
  return p;
}
const panels = {
  stats: panelEl('winStats'), stack: panelEl('winStack'), composer: panelEl('winComposer'),
};
const byId = {};
Object.assign(byId, els);
Object.entries(panels).forEach(([k, v]) => { byId[v.id] = v; });

const lb = makeEl('la', true); lb.dataset.layout = 'b';
els.layoutMenu._qsa = (sel) => (sel === 'button[data-layout]' ? [lb] : []);

const wmItems = [makeEl('i1', true), makeEl('i2', true)];
wmItems[0].dataset.win = 'composer';
wmItems[1].dataset.win = 'stats';
const wmBtns = [makeEl('b1', true), makeEl('b2', true), makeEl('b3', true)];
wmBtns[0].dataset = { win: 'stats', action: 'minimize' };
wmBtns[1].dataset = { win: 'composer', action: 'open' };
wmBtns[2].dataset = { win: 'stack', action: 'close' };
els.windowsMenuList._qsa = (sel) => (sel === '.wm-item' ? wmItems : sel === '.wm-mini-btn' ? wmBtns : []);

const container = makeEl('container');
container.appendChild(els.sashGrid);

global.document = {
  _h: {},
  body: makeEl('body'),
  getElementById: (id) => byId[id] || null,
  createElement: (t) => makeEl(t),
  addEventListener(t, f) { (this._h[t] = this._h[t] || []).push(f); },
  removeEventListener(t, f) {
    const a = this._h[t] || [];
    const i = a.indexOf(f);
    if (i >= 0) a.splice(i, 1);
  },
  activeElement: null,
};
function fireDoc(t, ev) { (document._h[t] || []).slice().forEach((f) => f(ev || {})); }
global.window = global;
global.innerWidth = 1200;
global.MutationObserver = class { constructor() {} observe() {} disconnect() {} };
global.localStorage = { _d: {}, getItem(k) { return this._d[k] || null; },
  setItem(k, v) { this._d[k] = String(v); }, removeItem(k) { delete this._d[k]; } };

const calls = []; const logs = [];
const rec = (n) => (...a) => { calls.push([n, ...a]); };
global.LogConsole = { log: (m, l) => logs.push([m, l]), clear() {} };
global.App = { bridge: null, recordGlobal: rec('recordGlobal') };
global.WindowPresets = { render: rec('WP.render'), refresh: rec('WP.refresh') };
global.BridgeReady = { ready() {} };

// The real DOM-free model, via its CommonJS export path (the same code the
// Python sash-core tests execute); exposed as the global the parts read.
const SashCore = require('../ui/js/sash-core.js');
global.SashCore = SashCore;

const { FAMILIES, loadFamily } = require('./js_family');
loadFamily(FAMILIES.sashGrid);
const SashGrid = global.SashGrid;

let passed = 0; let failed = 0;
function test(name, fn) {
  try { fn(); passed += 1; console.log('  ok - ' + name); }
  catch (e) { failed += 1; console.error('  FAIL - ' + name + '\n    ' + e.message); }
}
function clearCalls() { calls.length = 0; logs.length = 0; }
function assertCall(n) { assert(calls.some((c) => c[0] === n), 'expected ' + n + ' — got ' + JSON.stringify(calls.map((c) => c[0]))); }
function setRect(el, left, top, width, height) {
  el.rect = { left, top, width, height, right: left + width, bottom: top + height };
  el.ow = width; el.oh = height;
}
function evOpts(x, y) { return { clientX: x, clientY: y, pointerId: 1, button: 0,
  preventDefault() {}, stopPropagation() {} }; }
function winElOf(id) { return els.sashGrid.querySelector('.sash-window[data-win="' + id + '"]'); }
function fullTree(first) {
  const firstId = first || 'stats';
  const rest = SashCore.WINDOW_IDS.filter((id) => id !== firstId);
  return SashCore.split('row',
    [SashCore.leaf(firstId),
     SashCore.split('col', rest.map((id) => SashCore.leaf(id)),
       rest.map(() => 100 / rest.length))],
    [50, 50]);
}
function buildTestTree() {
  SashGrid.closedWindows = new Set();
  SashGrid.minimizedWindows = new Set();
  Object.values(SashGrid.winEls).forEach((p) => {
    if (p) { p.classList.remove('hidden'); p.style.display = ''; }
  });
  SashGrid.root = SashCore.split('row',
    [SashCore.leaf('stats'),
     SashCore.split('col', [SashCore.leaf('stack'), SashCore.leaf('composer')], [50, 50])],
    [60, 40]);
  SashGrid.render();
  setRect(winElOf('stats').parent, 0, 0, 1000, 400); // root row split
  setRect(winElOf('stats'), 0, 0, 594, 400);
  setRect(winElOf('stack'), 600, 0, 400, 194);
  setRect(winElOf('composer'), 600, 200, 400, 200);
  setRect(winElOf('stack').parent, 600, 0, 400, 400); // col split
  els.sashGrid.querySelectorAll('.sash').forEach((s, i) => {
    if (i === 0) setRect(s, 594, 0, 6, 400); else setRect(s, 600, 194, 400, 6);
  });
}

SashGrid.init();

test('init: panels collected, grid rendered, menus wired', () => {
  assert.strictEqual(Object.keys(SashGrid.winEls).length, 3);
  assert(els.sashGrid._l.pointerdown.length === 1);
  assert(els.sashGrid._l.dblclick.length === 1);
  assert(SashGrid.dockEl, 'dock created by _ensureDock');
  assert(container.children.includes(SashGrid.dockEl));
  assert(els.windowsMenuBtn._l.click.length === 1);
  assert(els.layoutMenuBtn._l.click.length === 1);
});

// ── persistence store ──────────────────────────────────────────
test('_loadTree: stored / corrupt / empty', () => {
  localStorage.setItem(SashGrid.STORAGE_KEY, SashCore.serialize(fullTree()));
  const t = SashGrid._loadTree();
  assert(t);
  assert.strictEqual(SashCore.leafIds(t).length, SashCore.WINDOW_IDS.length);
  localStorage.setItem(SashGrid.STORAGE_KEY, '{broken');
  assert.strictEqual(SashGrid._loadTree(), null);
  localStorage.removeItem(SashGrid.STORAGE_KEY);
  assert.strictEqual(SashGrid._loadTree(), null);
});

test('_loadWindowStates: closed + minimized, bogus filtered', () => {
  localStorage.setItem(SashGrid.STORAGE_CLOSED, JSON.stringify(['stats', 'bogus']));
  localStorage.setItem(SashGrid.STORAGE_MINIMIZED, JSON.stringify(['stack', 'stats']));
  SashGrid.closedWindows = new Set(); SashGrid.minimizedWindows = new Set();
  SashGrid._loadWindowStates();
  assert(SashGrid.closedWindows.has('stats'));
  assert(!SashGrid.closedWindows.has('bogus'));
  assert(SashGrid.minimizedWindows.has('stack'));
  assert(!SashGrid.minimizedWindows.has('stats')); // closed wins
});

test('_save / _saveWindowStates with and without bridge', () => {
  clearCalls();
  buildTestTree();
  SashGrid._save();
  assert(localStorage.getItem(SashGrid.STORAGE_KEY));
  assertCall('recordGlobal'); // no bridge → local record
  global.App.bridge = { save_grid_layout: () => true, save_window_states: rec('save_window_states') };
  SashGrid._save();
  assertCall('recordGlobal'); // accepted → also recorded
  global.App.bridge.save_grid_layout = () => false;
  calls.length = 0;
  SashGrid._save();
  assert(!calls.some((c) => c[0] === 'recordGlobal')); // rejected → no double record
  SashGrid._saveWindowStates();
  assertCall('save_window_states');
  global.App.bridge = null;
});

test('_loadFromBackend: layout + window states callbacks', () => {
  clearCalls();
  buildTestTree();
  const other = fullTree('stack');
  global.App.bridge = {
    get_grid_layout: (cb) => {
      cb(null); // no layout
      cb(SashCore.serialize(SashGrid.root)); // identical → ignored
      cb(SashCore.serialize(other)); // different → applied
    },
    get_window_states: (cb) => {
      cb(null);
      cb('not json');
      cb(JSON.stringify({ closed: ['composer', 'bogus'], minimized: ['stack'], maximized: 'stats' }));
    },
  };
  SashGrid._loadFromBackend();
  assert.strictEqual(SashCore.firstLeafId(SashGrid.root), 'stack'); // applied
  assert(SashGrid.closedWindows.has('composer'));
  assert(SashGrid.minimizedWindows.has('stack'));
  global.App.bridge = null;
});

test('_applySerialized: null / bad / ok + showAll', () => {
  SashGrid.closeWindow('stats');
  const tree = fullTree('composer');
  assert.strictEqual(SashGrid._applySerialized('null', false), false);
  assert.strictEqual(SashGrid._applySerialized('{bad', false), false);
  assert.strictEqual(SashGrid._applySerialized(SashCore.serialize(tree), true), true);
  assert.strictEqual(SashCore.firstLeafId(SashGrid.root), 'composer');
  assert(!SashGrid.closedWindows.has('stats')); // showAll reopened
});

// ── window ops ─────────────────────────────────────────────────
test('close/open/show/toggle window', () => {
  clearCalls();
  buildTestTree();
  assert.strictEqual(SashGrid.closeWindow('nope'), false);
  assert.strictEqual(SashGrid.closeWindow('stats'), true);
  assert(panels.stats.classList.contains('hidden'));
  assert(SashGrid.closedWindows.has('stats'));
  assert.strictEqual(SashGrid.closeWindow('stats'), false); // already closed
  assert.strictEqual(SashGrid.openWindow('stats'), true);
  assert(!panels.stats.classList.contains('hidden'));
  assert(!SashGrid.closedWindows.has('stats'));
  assert.strictEqual(SashGrid.openWindow('stats'), false); // not closed
  SashGrid.minimizeWindow('stack');
  assert.strictEqual(SashGrid.showWindow('stack'), true); // restore minimized
  assert(!SashGrid.minimizedWindows.has('stack'));
  SashGrid.closeWindow('composer');
  assert.strictEqual(SashGrid.showWindow('composer'), true); // open closed
  SashGrid.closeWindow('stats');
  assert.strictEqual(SashGrid.toggleWindow('stats'), true); // open branch
  SashGrid.closeWindow('stats');
  assert.strictEqual(SashGrid.toggleWindow('stats'), true); // close branch
  assert.strictEqual(SashGrid.toggleWindow('nope'), false);
  assert(logs.some((l) => l[0].indexOf('Closed Stats') >= 0));
});

test('minimize/restore/toggleMinimize + showAllWindows', () => {
  clearCalls();
  buildTestTree();
  assert.strictEqual(SashGrid.minimizeWindow('nope'), false);
  SashGrid.closeWindow('stats');
  assert.strictEqual(SashGrid.minimizeWindow('stats'), false); // closed → refuse
  assert.strictEqual(SashGrid.minimizeWindow('stats'), false);
  assert.strictEqual(SashGrid.minimizeWindow('stack'), true);
  assert(SashGrid.minimizedWindows.has('stack'));
  assert.strictEqual(SashGrid.minimizeWindow('stack'), false); // already
  assert.strictEqual(SashGrid.restoreMinimized('nope'), false);
  assert.strictEqual(SashGrid.restoreMinimized('stack'), true);
  assert.strictEqual(SashGrid.toggleMinimize('composer'), true); // minimize
  assert.strictEqual(SashGrid.toggleMinimize('composer'), true); // restore
  panels.stats.style.display = 'none';
  SashGrid.showAllWindows();
  assert.strictEqual(panels.stats.style.display, '');
  assert.strictEqual(SashGrid.closedWindows.size, 0);
  assert.strictEqual(SashGrid.minimizedWindows.size, 0);
});

test('resetToDefault + setLayout', () => {
  clearCalls();
  buildTestTree();
  SashGrid.resetToDefault();
  assert(SashGrid.root);
  assert(logs.some((l) => l[0].indexOf('reset') >= 0));
  global.App.bridge = { reset_grid_layout: (cb) => cb(SashCore.serialize(SashCore.defaultTree())) };
  SashGrid.closeWindow('stats');
  SashGrid.resetToDefault();
  assertCall('recordGlobal');
  global.App.bridge = null;
  assert.strictEqual(SashGrid.setLayout('nope'), false);
  assert.strictEqual(SashGrid.setLayout('a'), true);
  assert(logs.some((l) => l[0].indexOf('Layout') >= 0));
});

// ── windows menu + dock ────────────────────────────────────────
test('windows menu: render rows + wire actions', () => {
  clearCalls();
  buildTestTree();
  SashGrid.closeWindow('composer');
  const items = wmItems;
  const btns = wmBtns;
  els.windowsMenuBtn.rect = { left: 700, right: 780, bottom: 30, width: 80, height: 24 };
  const click = { stopPropagation() {} };
  els.windowsMenuBtn._l.click[0](click);
  assert(!els.windowsMenu.classList.contains('hidden'));
  assert(els.windowsMenu.style.top === '36px');
  assert(els.windowsMenuList.innerHTML.indexOf('Message Composer') >= 0);
  assert(els.windowsMenuList.innerHTML.indexOf('Closed') >= 0);
  // row click on a closed window → open
  items[0].fire('click', { target: { closest: () => null }, stopPropagation() {} });
  assert(!SashGrid.closedWindows.has('composer'));
  // mini buttons
  btns[0].fire('click', { target: { closest: () => 'yes' }, stopPropagation() {} });
  assert(SashGrid.minimizedWindows.has('stats'));
  btns[1].fire('click', { target: { closest: () => 'yes' }, stopPropagation() {} });
  btns[2].fire('click', { target: { closest: () => 'yes' }, stopPropagation() {} });
  assert(SashGrid.closedWindows.has('stack'));
  // show all / hide all
  els.windowsShowAllBtn.fire('click', click);
  assert.strictEqual(SashGrid.closedWindows.size, 0);
  assert(logs.some((l) => l[0].indexOf('All windows shown') >= 0));
  els.windowsHideAllBtn.fire('click', click);
  assert(SashGrid.closedWindows.has('stats'));
  assert(els.windowsMenu.classList.contains('hidden'));
});

test('dock: chip render, restore/close/chip-click', () => {
  clearCalls();
  buildTestTree();
  assert(SashGrid.dockEl.classList.contains('hidden'));
  SashGrid.minimizeWindow('stats');
  SashGrid._renderDock();
  assert(!SashGrid.dockEl.classList.contains('hidden'));
  const chip = SashGrid.dockEl.children[0];
  assert.strictEqual(chip.dataset.win, 'stats');
  assert.strictEqual(chip.children[0].textContent, 'Stats');
  const restoreBtn = chip.querySelector('.win-toggle');
  const closeBtn = chip.querySelector('.win-close');
  chip._l.click[0]({ target: { closest: () => null } }); // chip body → restore
  assert(!SashGrid.minimizedWindows.has('stats'));
  SashGrid.minimizeWindow('stats');
  restoreBtn._l.click[0]({ stopPropagation() {} });
  assert(!SashGrid.minimizedWindows.has('stats'));
  SashGrid.minimizeWindow('stats');
  closeBtn._l.click[0]({ stopPropagation() {} });
  assert(SashGrid.closedWindows.has('stats'));
});

test('layout menu: open + WindowPresets + layout buttons + reset', () => {
  clearCalls();
  els.layoutMenuBtn.rect = { left: 100, right: 200, bottom: 30, width: 100, height: 24 };
  els.layoutMenu.ow = 560;
  els.layoutMenuBtn.fire('click', { stopPropagation() {} });
  assert(!els.layoutMenu.classList.contains('hidden'));
  assertCall('WP.render');
  assertCall('WP.refresh');
  lb.fire('click', {});
  assert(els.layoutMenu.classList.contains('hidden'));
  assert(logs.some((l) => l[0].indexOf('B — split top row') >= 0));
  els.resetLayoutBtn._l.click[0]({});
  assert(els.layoutMenu.classList.contains('hidden'));
  assert(logs.some((l) => l[0].indexOf('reset') >= 0));
});

// ── drag lifecycle ─────────────────────────────────────────────
test('pointerdown guards: button / sash / hidden / control target', () => {
  buildTestTree();
  SashGrid._pointerDown({ button: 1, target: panels.stats.children[0] });
  assert.strictEqual(SashGrid._drag, null);
  const sash = els.sashGrid.querySelectorAll('.sash')[0];
  SashGrid._pointerDown(Object.assign(evOpts(600, 100), { target: sash }));
  assert(SashGrid._resize, 'sash target starts a resize');
  SashGrid._cancelResize(true);
  assert.strictEqual(SashGrid._resize, null);
  winElOf('stats').classList.add('sash-win-closed');
  SashGrid._pointerDown(Object.assign(evOpts(300, 100), { target: panels.stats.children[0] }));
  assert.strictEqual(SashGrid._drag, null);
  winElOf('stats').classList.remove('sash-win-closed');
  const btn = winElOf('stats').querySelector('.win-btn');
  SashGrid._pointerDown(Object.assign(evOpts(300, 100), { target: btn }));
  assert.strictEqual(SashGrid._drag, null);
});

test('drag: threshold, begin, spec follows pointer, drop applies', () => {
  clearCalls();
  buildTestTree();
  const before = JSON.stringify(SashCore.leafPaths(SashGrid.root));
  SashGrid._pointerDown(Object.assign(evOpts(300, 200), { target: panels.stats.children[0] }));
  assert(SashGrid._drag && !SashGrid._drag.active);
  fireDoc('pointermove', Object.assign(evOpts(301, 201), { preventDefault() {} })); // within THRESHOLD
  assert(!SashGrid._drag.active);
  fireDoc('pointermove', Object.assign(evOpts(330, 240), { preventDefault() {} })); // begins
  assert(SashGrid._drag.active);
  assert(document.body.classList.contains('sash-dragging'));
  assert(winElOf('stats').classList.contains('sash-drag-source'));
  assert(document.body.children.some((c) => c.classList && c.classList.contains('sash-drag-clone')));
  assert(document.body.children.some((c) => c.classList && c.classList.contains('sash-drag-badge')));
  // over stack center-left → sibling before
  fireDoc('pointermove', Object.assign(evOpts(650, 50), { preventDefault() {} }));
  assert(SashGrid._drag.lastSpec.kind === 'sibling');
  assert.strictEqual(SashGrid._drag.lastSpec.side, 'before');
  assert(document.body.children.some((c) => c.classList && c.classList.contains('sash-drop-indicator')));
  assert(winElOf('stack').classList.contains('sash-drag-target'));
  // over the vertical sash gap → sash spec
  fireDoc('pointermove', Object.assign(evOpts(597, 300), { preventDefault() {} }));
  assert.strictEqual(SashGrid._drag.lastSpec.kind, 'sash');
  // over the edge zone of composer → edge spec
  fireDoc('pointermove', Object.assign(evOpts(620, 380), { preventDefault() {} }));
  assert.strictEqual(SashGrid._drag.lastSpec.kind, 'edge');
  assert.strictEqual(SashGrid._drag.lastSpec.target, 'composer');
  // drop on stack-before
  fireDoc('pointermove', Object.assign(evOpts(650, 50), { preventDefault() {} }));
  fireDoc('pointerup', {});
  assert.strictEqual(SashGrid._drag, null);
  assert(!document.body.classList.contains('sash-dragging'));
  assert(!winElOf('stats').classList.contains('sash-drag-source'));
  const after = JSON.stringify(SashCore.leafPaths(SashGrid.root));
  assert.notStrictEqual(after, before);
  assertCall('recordGlobal');
  assert(logs.some((l) => l[0].indexOf('Stats → top of Action Stack') >= 0));
});

test('drag: no spec → cancel log; Escape cancels; pointercancel cleans up', () => {
  clearCalls();
  buildTestTree();
  SashGrid._pointerDown(Object.assign(evOpts(300, 200), { target: panels.stats.children[0] }));
  fireDoc('pointermove', Object.assign(evOpts(330, 240), { preventDefault() {} }));
  fireDoc('pointerup', {}); // moved but released over empty space (spec from last move over stats? → move outside all rects)
  SashGrid._pointerDown(Object.assign(evOpts(300, 200), { target: panels.stats.children[0] }));
  fireDoc('pointermove', Object.assign(evOpts(330, 240), { preventDefault() {} }));
  fireDoc('pointermove', Object.assign(evOpts(50, 500), { preventDefault() {} })); // outside everything → spec null
  fireDoc('pointerup', {});
  assert(logs.some((l) => l[0].indexOf('drag cancelled') >= 0));
  SashGrid._pointerDown(Object.assign(evOpts(300, 200), { target: panels.stats.children[0] }));
  fireDoc('pointermove', Object.assign(evOpts(330, 240), { preventDefault() {} }));
  fireDoc('keydown', { key: 'Escape' });
  assert.strictEqual(SashGrid._drag, null);
  assert(logs.some((l) => l[0].indexOf('drag cancelled') >= 0));
  SashGrid._pointerDown(Object.assign(evOpts(300, 200), { target: panels.stats.children[0] }));
  fireDoc('pointermove', Object.assign(evOpts(330, 240), { preventDefault() {} }));
  fireDoc('pointercancel', {});
  assert.strictEqual(SashGrid._drag, null);
  assert.strictEqual(SashGrid._resize, null);
});

test('simulateDrop: all zones + bad zone throws', () => {
  buildTestTree();
  assert.throws(() => SashGrid.simulateDrop('stats', 'stack', 'sideways'));
  const t1 = SashGrid.simulateDrop('stats', 'stack', 'before');
  assert(t1);
  SashGrid.simulateDrop('stats', 'stack', 'after');
  SashGrid.simulateDrop('stats', 'stack', 'left');
  SashGrid.simulateDrop('stats', 'stack', 'right');
  SashGrid.simulateDrop('stats', 'stack', 'top');
  SashGrid.simulateDrop('stats', 'stack', 'bottom');
  assertCall('recordGlobal');
});

// ── resize ─────────────────────────────────────────────────────
test('resize: move allocates pixels, up commits percent sizes', () => {
  clearCalls();
  buildTestTree();
  SashGrid._cancelResize(true);
  const sash = els.sashGrid.querySelectorAll('.sash')[0]; // vertical, row split
  SashGrid._pointerDown(Object.assign(evOpts(600, 200), { target: sash }));
  assert(SashGrid._resize);
  assert(sash.classList.contains('sash-active'));
  assert(document.body.classList.contains('sash-resizing-row'));
  assert(sash._cap === true); // pointer captured
  fireDoc('pointermove', Object.assign(evOpts(300, 200), { preventDefault() {} }));
  const statsWin = winElOf('stats');
  assert.strictEqual(statsWin.style.flex, '0 0 300px');
  assert.strictEqual(winElOf('stats').parent.children[2].style.flex, '0 0 694px');
  fireDoc('pointerup', {});
  assert.strictEqual(SashGrid._resize, null);
  const s0 = SashGrid.root.sizes[0];
  assert(s0 > 55 && s0 < 65, 'sizes[0] ≈ 60.4, got ' + s0);
  assertCall('recordGlobal');
  assert(logs.some((l) => l[0].indexOf('resized') >= 0));
});

test('resize: impossible span refuses; Escape restores flex', () => {
  buildTestTree();
  SashGrid._cancelResize(true);
  const sash = els.sashGrid.querySelectorAll('.sash')[0];
  SashGrid._pointerDown(Object.assign(evOpts(600, 200), { target: sash }));
  const z = SashGrid._resize;
  // crush both children below MIN_PX → null allocation
  assert.strictEqual(SashGrid._resizePixelAllocation(
    { isRow: true, sIdx: 0, childSizes: [40, 40, 700], sashSizes: [6], otherWidths: { 2: 700 } },
    100, { left: 0, top: 0, width: 500, height: 400 }), null);
  fireDoc('keydown', { key: 'Escape', preventDefault() {} });
  assert.strictEqual(SashGrid._resize, null);
  assert(!sash.classList.contains('sash-active'));
  assert(!document.body.classList.contains('sash-resizing-row'));
  assert(sash._cap === false); // pointer released
});

test('dblclick resets the split to even sizes', () => {
  clearCalls();
  buildTestTree();
  SashGrid.root.sizes = [80, 20];
  SashGrid.render();
  const sash = els.sashGrid.querySelectorAll('.sash')[0];
  SashGrid._onDblClick({ target: sash });
  assert.deepStrictEqual(SashGrid.root.sizes, [50, 50]);
  assert(logs.some((l) => l[0].indexOf('even sizes') >= 0));
});

test('simulateResize: clamps first child, rescales the rest', () => {
  buildTestTree();
  SashGrid.root = SashCore.split('row',
    [SashCore.leaf('stats'), SashCore.leaf('stack'), SashCore.leaf('composer')], [40, 30, 30]);
  SashGrid.render();
  const t = SashGrid.simulateResize('', 70);
  assert.strictEqual(SashGrid.root.sizes[0], 70);
  assert(Math.abs(SashGrid.root.sizes[1] - 15) < 0.01);
  assert(Math.abs(SashGrid.root.sizes[2] - 15) < 0.01);
  assert(t);
  SashGrid.simulateResize('', 2); // below MIN_SIZE → clamped to 4
  assert.strictEqual(SashGrid.root.sizes[0], 4);
  assert.throws(() => SashGrid.simulateResize('9-9-9', 50));
});

test('drag ghost path: heavy panel (>350 nodes) gets a ghost badge', () => {
  buildTestTree();
  const heavy = winElOf('stack');
  for (let i = 0; i < 400; i += 1) heavy.appendChild(makeEl('n' + i));
  SashGrid._pointerDown(Object.assign(evOpts(800, 100), { target: panels.stack.children[0] }));
  fireDoc('pointermove', Object.assign(evOpts(830, 130), { preventDefault() {} }));
  const ghost = document.body.children.find((c) => c.classList && c.classList.contains('sash-drag-ghost'));
  assert(ghost, 'ghost created for heavy panel');
  fireDoc('pointermove', Object.assign(evOpts(840, 140), { preventDefault() {} })); // ghost follows cursor
  assert(ghost.style.transform.indexOf('854') >= 0);
  fireDoc('pointerup', {});
  assert.strictEqual(SashGrid._drag, null);
});

console.log('\ntest_sash_grid_parts: ' + passed + ' passed, ' + failed + ' failed');
process.exit(failed ? 1 : 0);
