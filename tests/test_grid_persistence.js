/* Contract tests for close-time grid persistence.
   MainWindow JS snippet requires:
     window.StackDnD.flushPersistence
     window.SashGrid.flushPersistence → boolean (true only if backend save queued)

   Run: node tests/test_grid_persistence.js
*/
'use strict';
const fs = require('fs');
const vm = require('vm');

let passed = 0, failed = 0;
function test(name, fn) {
  try { fn(); passed++; }
  catch (e) { failed++; console.error('FAIL', name, e && e.message); }
}
function assert(c, m) { if (!c) throw new Error(m || 'assert'); }

global.window = global;
global.document = {
  addEventListener() {},
  getElementById() { return null; },
  createElement() {
    return {
      classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
      style: {}, appendChild() {},
      querySelector() { return null; },
      querySelectorAll() { return []; },
    };
  },
};
global.localStorage = {
  _d: {},
  getItem(k) { return Object.prototype.hasOwnProperty.call(this._d, k) ? this._d[k] : null; },
  setItem(k, v) { this._d[k] = String(v); },
};
global.SashCore = {
  serialize(tree) { return JSON.stringify({ v: 1, tree }); },
  deserialize(s) {
    try { return { ok: true, tree: JSON.parse(s).tree }; }
    catch (e) { return { ok: false, error: String(e) }; }
  },
  defaultTree() { return { t: 'leaf', id: 'stats' }; },
  WINDOWS: [{ id: 'stats', title: 'Stats' }],
  WINDOW_IDS: ['stats'],
  WINDOW_TITLES: { stats: 'Stats' },
  isLeaf(n) { return n && n.t === 'leaf'; },
  clone(t) { return JSON.parse(JSON.stringify(t)); },
};
global.App = { bridge: null, recordGlobal() {} };
global.BridgeReady = { ready() {} };

vm.runInThisContext(
  fs.readFileSync('ui/js/sash-grid.js', 'utf8') +
  '\nglobalThis.__SashGrid = SashGrid;'
);
vm.runInThisContext(
  fs.readFileSync('ui/js/stack-dnd.js', 'utf8') +
  '\nglobalThis.__StackDnD = StackDnD;'
);
const SashGrid = global.__SashGrid;
const StackDnD = global.__StackDnD;

test('SashGrid.flushPersistence is a function', () => {
  assert(typeof SashGrid.flushPersistence === 'function');
});

test('no root → flush returns false (main.py treats as no ack)', () => {
  SashGrid.root = null;
  assert(SashGrid.flushPersistence() === false);
});

test('root but no bridge.save_grid_layout → false', () => {
  SashGrid.root = { t: 'leaf', id: 'stats' };
  global.App.bridge = {};
  assert(SashGrid.flushPersistence() === false);
  assert(!!global.localStorage.getItem(SashGrid.STORAGE_KEY), 'must still write localStorage');
});

test('bridge.save_grid_layout present → true (expects ack)', () => {
  let got = null;
  SashGrid.root = { t: 'leaf', id: 'stats' };
  global.App.bridge = { save_grid_layout(p) { got = p; } };
  assert(SashGrid.flushPersistence() === true);
  assert(typeof got === 'string' && got.length > 0);
});

test('StackDnD.flushPersistence exists and does not throw', () => {
  assert(typeof StackDnD.flushPersistence === 'function');
  StackDnD.flushPersistence();
});

test('corrupt localStorage tree does not throw on _loadTree', () => {
  global.localStorage.setItem(SashGrid.STORAGE_KEY, '{not json');
  const orig = global.SashCore.deserialize;
  global.SashCore.deserialize = () => { throw new Error('boom'); };
  try {
    const t = SashGrid._loadTree();
    assert(t === null);
  } finally {
    global.SashCore.deserialize = orig;
  }
});

if (failed) {
  console.error(`grid_persistence: ${passed} passed, ${failed} failed`);
  process.exit(1);
}
console.log(`grid_persistence: ${passed} passed, 0 failed`);
console.log('OK');
