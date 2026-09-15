/* test_log_console.js — log-console.js (Round H: first Node harness for this
   file, RULE 8: the real shipped file, DOM stubbed). */
'use strict';
const assert = require('assert');
const { loadSingle } = require('./js_family');

function makeConsoleEl() {
  const el = {
    children: [], innerHTML: '', scrollTop: 0, scrollHeight: 100,
    appendChild(c) { this.children.push(c); this.scrollHeight = this.children.length * 20; return c; },
    removeChild(c) { const i = this.children.indexOf(c); if (i >= 0) this.children.splice(i, 1); },
    get firstChild() { return this.children[0] || null; },
  };
  return el;
}
const consoleEl = makeConsoleEl();
const created = [];
global.document = {
  getElementById: (id) => (id === 'logConsole' ? consoleEl : null),
  createElement: (tag) => { const e = { tag, className: '', textContent: '' }; created.push(e); return e; },
  addEventListener() {},
};
global.window = global;

global.BridgeReady = { _cb: null, ready(fn) { this._cb = fn; } };
loadSingle('log-console.js', 'LogConsole');
const LogConsole = global.LogConsole;
global.BridgeReady._cb(); // LogConsole.init()

let passed = 0; let failed = 0;
function test(name, fn) {
  try { fn(); passed += 1; console.log('  ok - ' + name); }
  catch (e) { failed += 1; console.error('  FAIL - ' + name + '\n    ' + e.message); }
}

test('init binds the console element', () => {
  assert.strictEqual(LogConsole._el, consoleEl);
});

test('log: timestamped entry, level class, auto-scroll', () => {
  LogConsole.log('hello world');
  assert.strictEqual(consoleEl.children.length, 1);
  const entry = consoleEl.children[0];
  assert.strictEqual(entry.className, 'log-entry info');
  assert.match(entry.textContent, /^\[\d{2}:\d{2}:\d{2}\] hello world$/);
  assert.strictEqual(consoleEl.scrollTop, consoleEl.scrollHeight);
});

test('log: custom level class', () => {
  LogConsole.log('boom', 'error');
  assert.strictEqual(consoleEl.children[1].className, 'log-entry error');
});

test('log: trims to maxEntries, dropping the oldest', () => {
  LogConsole._maxEntries = 3;
  for (let i = 1; i <= 5; i += 1) LogConsole.log('m' + i);
  assert.strictEqual(consoleEl.children.length, 3);
  assert(consoleEl.children[0].textContent.includes('m3'));
  assert(consoleEl.children[2].textContent.includes('m5'));
  LogConsole._maxEntries = 500;
});

test('clear: empties the console', () => {
  LogConsole.clear();
  assert.strictEqual(consoleEl.innerHTML, '');
});

test('log without init: lazily re-fetches the element', () => {
  LogConsole._el = null;
  LogConsole.log('late entry');
  assert.strictEqual(LogConsole._el, consoleEl);
  assert(consoleEl.children.length >= 1);
});

test('log with no element: no throw', () => {
  const saved = global.document.getElementById;
  global.document.getElementById = () => null;
  LogConsole._el = null;
  assert.doesNotThrow(() => LogConsole.log('nowhere'));
  global.document.getElementById = saved;
});

console.log('\ntest_log_console: ' + passed + ' passed, ' + failed + ' failed');
process.exit(failed ? 1 : 0);
