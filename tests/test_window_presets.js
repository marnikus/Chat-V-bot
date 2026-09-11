/* Real SashGrid portable snapshot/apply contract.
   Run: node tests/test_window_presets.js
*/
'use strict';
const fs = require('fs');
const vm = require('vm');
const SashCore = require('../ui/js/sash-core.js');

let passed = 0, failed = 0;
function test(name, fn) {
  try { fn(); passed++; }
  catch (e) { failed++; console.error('FAIL', name, e && e.message); }
}
function assert(condition, message) { if (!condition) throw new Error(message || 'assert'); }

function panel(id) {
  return {
    dataset: { win: id },
    classList: { contains() { return false; }, add() {}, remove() {}, toggle() {} },
    style: { display: id === 'stats' ? 'none' : '' },
    querySelector() { return null; },
    getBoundingClientRect() {
      const n = SashCore.WINDOW_IDS.indexOf(id);
      return { left: 10 + n, top: 20 + n, width: 100, height: 80 };
    },
  };
}

const grid = {
  getBoundingClientRect() { return { left: 10, top: 20, width: 1200, height: 700 }; },
  querySelectorAll(selector) {
    if (selector === '.sash-window') return SashCore.WINDOW_IDS.map(panel);
    return [];
  },
};

global.window = global;
global.document = {
  addEventListener() {},
  getElementById() { return null; },
  createElement() { return { classList: { add() {}, remove() {}, toggle() {} } }; },
};
global.localStorage = { setItem() {}, getItem() { return null; } };
global.BridgeReady = { ready() {} };
global.SashCore = SashCore;
vm.runInThisContext(fs.readFileSync('ui/js/sash-grid.js', 'utf8') +
  '\nglobalThis.__SashGrid = SashGrid;');
const SashGrid = global.__SashGrid;
SashGrid.gridEl = grid;
SashGrid.root = SashCore.defaultTree();
SashGrid.closedWindows = new Set();
SashGrid.minimizedWindows = new Set();
SashGrid.winEls = Object.fromEntries(SashCore.WINDOW_IDS.map((id) => [id, panel(id)]));
SashGrid.render = () => {};
SashGrid._save = () => {};
SashGrid._saveWindowStates = () => {};
SashGrid._applyStates = () => {};

test('portable snapshot includes the tree, count, bounds, states, and screen', () => {
  const doc = SashGrid.createPortablePreset('Desk');
  assert(doc.format === 'chat-v-bot.window-preset');
  assert(doc.grid.type === 'sash-tree');
  assert(doc.grid.window_count === SashCore.WINDOW_IDS.length);
  assert(doc.windows.length === SashCore.WINDOW_IDS.length);
  assert(doc.windows[0].bounds.width > 0);
  assert(doc.window_states.closed.includes('stats'));
  assert(doc.windows.find((item) => item.id === 'stats').state === 'closed');
  assert(doc.screen.width === 1200 && doc.screen.height === 700);
});

test('valid portable document applies exact tree and window states', () => {
  const original = SashCore.serialize(SashGrid.root);
  const doc = SashGrid.createPortablePreset('Desk');
  doc.grid.tree = SashCore.layoutC();
  doc.window_states = { closed: [], minimized: ['log'] };
  doc.windows.forEach((entry) => { entry.state = entry.id === 'log' ? 'minimized' : 'open'; });
  assert(SashGrid.applyPortablePreset(doc));
  assert(SashCore.serialize(SashGrid.root) !== original);
  assert(SashGrid.closedWindows.size === 0);
  assert(SashGrid.minimizedWindows.has('log'));
  assert(SashGrid.winEls.stats.style.display === '', 'stale hidden display cleared');
});

test('invalid portable document is rejected without changing the tree', () => {
  const before = SashCore.serialize(SashGrid.root);
  const bad = SashGrid.createPortablePreset('Bad');
  bad.grid.tree.children[0].children[0].children[0].id = 'unknown';
  const result = SashGrid.validatePortablePreset(bad);
  assert(!result.ok && /window|id|leaf/.test(result.error));
  assert(!SashGrid.applyPortablePreset(bad));
  assert(SashCore.serialize(SashGrid.root) === before);
});

test('invalid screen metadata is refused before a preset can be applied', () => {
  const bad = SashGrid.createPortablePreset('Bad screen');
  bad.screen.width = '1400';
  const result = SashGrid.validatePortablePreset(bad);
  assert(!result.ok && result.error === 'screen metadata is invalid');
});

if (failed) process.exit(1);
console.log(`window_presets: ${passed} passed, 0 failed`);
