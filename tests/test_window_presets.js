/* Real SashGrid portable snapshot/apply contract.
   Run: node tests/test_window_presets.js
*/
'use strict';
const fs = require('fs');
const vm = require('vm');
const SashCore = require('../ui/js/sash-core.js');
const PresetAdapt = require('../ui/js/preset-adapt.js');

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
global.PresetAdapt = PresetAdapt;
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
  assert(SashGrid.applyPortablePreset(doc).ok === true);
  assert(SashCore.serialize(SashGrid.root) !== original);
  assert(SashGrid.closedWindows.size === 0);
  assert(SashGrid.minimizedWindows.has('log'));
  assert(SashGrid.winEls.stats.style.display === '', 'stale hidden display cleared');
});

test('structurally corrupt document is rejected without changing the tree', () => {
  const before = SashCore.serialize(SashGrid.root);
  const bad = SashGrid.createPortablePreset('Bad');
  bad.window_states = { closed: ['log'], minimized: ['log'] };
  const result = SashGrid.validatePortablePreset(bad);
  assert(!result.ok && /overlap/.test(result.error), 'overlap refuses');
  const applied = SashGrid.applyPortablePreset(bad);
  assert(applied.ok === false, 'apply returns {ok:false}');
  assert(SashCore.serialize(SashGrid.root) === before, 'tree untouched');
});

test('unknown tree leaf is pruned, its window re-added, and both reported', () => {
  SashGrid.root = SashCore.defaultTree();   // the previous test left layoutC
  const doc = SashGrid.createPortablePreset('Drift');
  doc.grid.tree.children[0].children[0].children[0].id = 'unknown';
  const result = SashGrid.validatePortablePreset(doc);
  assert(result.ok, 'set drift adapts instead of refusing: ' + (result.error || ''));
  const skipped = result.report.skipped.map((r) => r.id);
  assert(skipped.includes('unknown'), 'unknown leaf reported as skipped');
  const added = result.report.added.map((r) => r.id);
  assert(added.includes('stats'), 'the pruned window is re-added by the migrator');
  const leaves = SashCore.leafIds(result.document.grid.tree);
  assert(!leaves.includes('unknown') && leaves.includes('stats'), 'tree repaired');
  const applied = SashGrid.applyPortablePreset(result.document);
  assert(applied.ok === true && Array.isArray(applied.report.applied),
    'apply returns the report');
});

test('a 13-window-era preset restores adaptively (missing window added)', () => {
  const thirteen = SashCore.WINDOWS.slice(0, 13);
  const tree = SashCore.split('col',
    thirteen.map((w) => SashCore.leaf(w.id)),
    SashCore.normalizeSizes(new Array(13).fill(100 / 13)));
  const doc = SashGrid.createPortablePreset('Old desk');
  doc.grid.tree = tree;
  doc.grid.window_count = 13;
  doc.windows = thirteen.map((w, i) => ({
    id: w.id, title: w.title, state: 'open',
    bounds: { x: 0, y: i / 13, width: 1, height: 1 / 13 },
  }));
  const result = SashGrid.validatePortablePreset(doc);
  assert(result.ok, 'old preset restores: ' + (result.error || ''));
  const added = result.report.added.map((r) => r.id);
  assert(added.includes('botprompt'), 'the v4 window is added and explained');
  assert(result.report.applied.length === 13, '13 windows keep their places');
  assert(result.document.windows.length === SashCore.WINDOW_IDS.length,
    'canonical output carries the full current set');
  assert(SashCore.validate(result.document.grid.tree) === null, 'tree valid');
});

test('corrupt bounds of a known window are corrected, not refused', () => {
  const doc = SashGrid.createPortablePreset('Bounds');
  doc.windows[3].bounds.width = 9;
  const result = SashGrid.validatePortablePreset(doc);
  assert(result.ok, 'corrupt bounds adapt');
  const corrected = result.report.corrected.map((r) => r.id);
  assert(corrected.includes(doc.windows[3].id), 'corrected window reported');
});

test('the REASON strings are the shared cross-language contract', () => {
  // Literal on purpose — tests/unit/services/test_preset_adapt.py pins
  // the same five strings for the Python mirror.
  assert(PresetAdapt.REASON.unknown === 'unknown window in this build');
  assert(PresetAdapt.REASON.duplicate === 'duplicate preset entry');
  assert(PresetAdapt.REASON.bounds === 'invalid bounds; default position used');
  assert(PresetAdapt.REASON.state === 'state corrected from window_states');
  assert(PresetAdapt.REASON.added ===
    'not in the preset; added with default placement');
});

test('invalid screen metadata is refused before a preset can be applied', () => {
  const bad = SashGrid.createPortablePreset('Bad screen');
  bad.screen.width = '1400';
  const result = SashGrid.validatePortablePreset(bad);
  assert(!result.ok && result.error === 'screen metadata is invalid');
});

if (failed) process.exit(1);
console.log(`window_presets: ${passed} passed, 0 failed`);
