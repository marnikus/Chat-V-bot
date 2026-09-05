/* Regression test for the final WebEngine close-time grid flush. */
'use strict';

const fs = require('fs');
const vm = require('vm');

global.document = { addEventListener() {} };
global.localStorage = {
  values: {},
  setItem(key, value) { this.values[key] = value; },
};
global.SashCore = {
  serialize(tree) { return JSON.stringify({ v: 1, tree }); },
};
vm.runInThisContext(
  fs.readFileSync('ui/js/sash-grid.js', 'utf8') +
  '\nglobalThis.__SashGridForCloseTests = SashGrid;'
);
const SashGrid = global.__SashGridForCloseTests;

let passed = 0;
let failed = 0;
function test(name, fn) {
  try { fn(); passed++; }
  catch (error) {
    failed++;
    console.error('FAIL ' + name + '\n  ' + (error.stack || error));
  }
}
function ok(value, message) {
  if (!value) throw new Error(message || 'expected truthy value');
}

SashGrid.root = { t: 'split', dir: 'col', children: [
  { t: 'leaf', id: 'composer' },
  { t: 'leaf', id: 'people' },
], sizes: [60, 40] };

let savedPayload = null;
global.App = {
  bridge: {
    save_grid_layout(payload) { savedPayload = payload; },
  },
};

test('flushPersistence sends the complete current tree to the backend', () => {
  const expectsAck = SashGrid.flushPersistence();
  ok(expectsAck, 'backend acknowledgment should be expected');
  ok(savedPayload, 'payload should be sent');
  const parsed = JSON.parse(savedPayload);
  ok(parsed.tree.children[0].id === 'composer', 'window order is included');
  ok(parsed.tree.sizes[0] === 60 && parsed.tree.sizes[1] === 40,
    'current split dimensions are included');
  ok(global.localStorage.values[SashGrid.STORAGE_KEY] === savedPayload,
    'local fallback is updated too');
});

test('flushPersistence remains safe without a backend', () => {
  let localHistory = null;
  global.App = { recordGlobal(_kind, payload) { localHistory = payload; } };
  const expectsAck = SashGrid.flushPersistence();
  ok(!expectsAck, 'no backend means no acknowledgment is expected');
  ok(localHistory, 'local history receives the final tree');
});

console.log(`grid_close_autosave: ${passed} passed, ${failed} failed`);
if (failed) process.exitCode = 1;
