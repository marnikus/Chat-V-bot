/* test_composer.js — composer.js (Round H: first Node harness for this
   file, RULE 8: the real shipped file, DOM + bridge + PresetsUI stubbed). */
'use strict';
const assert = require('assert');
const { loadSingle } = require('./js_family');

function makeEl(id) {
  const set = new Set();
  const el = {
    id: id || '', tag: id || '', value: '', textContent: '', innerHTML: '',
    className: '', style: {}, children: [],
    selectionStart: 0, selectionEnd: 0, dataset: {},
    appendChild(c) { this.children.push(c); return c; },
    addEventListener(t, f) { (this._l = this._l || {})[t] = (this._l[t] || []).concat(f); },
    dispatchEvent(ev) { ((this._l || {})[ev.type] || []).forEach((f) => f(ev)); },
    focus() { this._focused = true; },
    getBoundingClientRect() { return { top: 600, left: 50 }; },
    querySelectorAll() { return []; },
  };
  el.classList = { add(c) { set.add(c); }, remove(c) { set.delete(c); },
    toggle(c) { set.has(c) ? set.delete(c) : set.add(c); },
    contains(c) { return set.has(c); } };
  return el;
}
const els = {};
['messageInput', 'charCount', 'varMenu', 'insertVarBtn', 'saveTemplateBtn',
 'loadTemplateBtn'].forEach((id) => { els[id] = makeEl(id); });
const varItem = makeEl('var-item'); varItem.dataset.var = '{{nick}}';
els.varMenu.querySelectorAll = (sel) => (sel === '.var-item' ? [varItem] : []);
const docClicks = [];
global.document = { getElementById: (id) => els[id] || null,
  createElement: (t) => makeEl(t),
  addEventListener(t, f) { if (t === 'click') docClicks.push(f); } };
global.window = global;
global.innerHeight = 800;
global.Event = class { constructor(type) { this.type = type; }
  stopPropagation() { this._stopped = true; } };

const calls = [];
const rec = (name) => (...a) => { calls.push([name, ...a]); };
global.PresetsUI = {
  promptName(title, _ph, _btn, cb) { calls.push(['promptName', title]); cb('MyName'); },
  setTemplatePresets: rec('setTemplatePresets'),
  toggleTemplatePicker: rec('toggleTemplatePicker'),
};
global.LogConsole = { log: rec('log'), clear() {} };
const b = {};
b.save_message = rec('save_message');
b.save_template_preset = rec('save_template_preset');
b.list_template_presets = (cb) => { calls.push(['list_template_presets']); b._tplCb = cb; };
global.App = { bridge: b };

global.BridgeReady = { _cb: null, ready(fn) { this._cb = fn; } };
loadSingle('composer.js', 'Composer');
global.BridgeReady._cb(); // Composer.init()

let passed = 0; let failed = 0;
function test(name, fn) {
  try { fn(); passed += 1; console.log('  ok - ' + name); }
  catch (e) { failed += 1; console.error('  FAIL - ' + name + '\n    ' + e.message); }
}
function clearCalls() { calls.length = 0; }
function assertCall(name) {
  assert(calls.some((c) => c[0] === name), 'expected ' + name + ' — got ' + JSON.stringify(calls));
}

test('init: wired without crash', () => {
  assert(Array.isArray(els.messageInput._l.input));
  assert(Array.isArray(els.insertVarBtn._l.click));
  assert.strictEqual(docClicks.length, 1);
});

test('input event: counter + autosave', () => {
  clearCalls();
  els.messageInput.value = 'hello';
  els.messageInput.dispatchEvent(new Event('input'));
  assert.strictEqual(els.charCount.textContent, '5 / 1000');
  assert.strictEqual(els.charCount.className, '');
  assertCall('save_message');
});

test('counter classes: near-limit > 800, at-limit > 950', () => {
  els.messageInput.value = 'x'.repeat(900);
  els.messageInput.dispatchEvent(new Event('input'));
  assert.strictEqual(els.charCount.className, 'near-limit');
  els.messageInput.value = 'x'.repeat(960);
  els.messageInput.dispatchEvent(new Event('input'));
  assert.strictEqual(els.charCount.className, 'at-limit');
});

test('insertBtn: toggles menu, pins it above the button', () => {
  els.insertVarBtn._l.click[0](new Event('click'));
  assert(els.varMenu.classList.contains('hidden'));
  assert.strictEqual(els.varMenu.style.position, 'fixed');
  assert.strictEqual(els.varMenu.style.bottom, '204px'); // 800 - 600 + 4
  assert.strictEqual(els.varMenu.style.left, '50px');
});

test('var-item click: inserts at caret, re-saves, hides menu', () => {
  clearCalls();
  els.varMenu.classList.remove('hidden');
  els.messageInput.value = 'AB';
  els.messageInput.selectionStart = 1; els.messageInput.selectionEnd = 1;
  varItem._l.click[0]();
  assert.strictEqual(els.messageInput.value, 'A{{nick}}B');
  assert.strictEqual(els.messageInput.selectionStart, 9);
  assert.strictEqual(els.messageInput.selectionEnd, 9);
  assert(els.messageInput._focused);
  assert(els.varMenu.classList.contains('hidden'));
  assert(calls.some((c) => c[0] === 'save_message' && c[1] === 'A{{nick}}B'));
});

test('document click hides the variable menu', () => {
  els.varMenu.classList.remove('hidden');
  docClicks[0]();
  assert(els.varMenu.classList.contains('hidden'));
});

test('saveTemplateBtn: no bridge / empty text warn; else persist', () => {
  clearCalls();
  const saved = global.App.bridge;
  global.App.bridge = null;
  els.saveTemplateBtn._l.click[0]();
  assert(calls.some((c) => c[0] === 'log' && c[2] === 'warn'));
  global.App.bridge = b;
  els.messageInput.value = '   ';
  els.saveTemplateBtn._l.click[0]();
  assert(calls.filter((c) => c[0] === 'log').length === 2);
  els.messageInput.value = 'hi there';
  els.saveTemplateBtn._l.click[0]();
  assert(calls.some((c) => c[0] === 'promptName'));
  assert(calls.some((c) => c[0] === 'save_template_preset' && c[1] === 'MyName'
    && c[2] === 'hi there'));
  global.App.bridge = saved;
});

test('loadTemplateBtn: no bridge warns; else list + open picker', () => {
  clearCalls();
  const saved = global.App.bridge;
  global.App.bridge = null;
  els.loadTemplateBtn._l.click[0]();
  assert(calls.some((c) => c[0] === 'log' && c[2] === 'warn'));
  global.App.bridge = b;
  els.loadTemplateBtn._l.click[0]();
  assertCall('list_template_presets');
  b._tplCb('["tpl1"]');
  assert(calls.some((c) => c[0] === 'setTemplatePresets' && c[1] === '["tpl1"]'));
  assert(calls.some((c) => c[0] === 'toggleTemplatePicker' && c[1] === els.loadTemplateBtn));
  global.App.bridge = saved;
});

console.log('\ntest_composer: ' + passed + ' passed, ' + failed + ' failed');
process.exit(failed ? 1 : 0);
