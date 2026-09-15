/* Tests for the Speed Multiplier block UI (feature: global wait speed).

   Per AGENT_RULES RULE 8 this executes the REAL shipped module
   (ui/js/stack-dnd.js) in a real runtime (Node), against a tiny DOM stub:
   the BUILTIN_BLOCKS entry, the preview wording, the stack summary and
   the config rows (coefficient input + quick presets + live preview).

   Run:  node tests/test_speed_multiplier.js
   Exits 0 + prints "OK" when every test passes.
*/
'use strict';
const fs = require('fs');
const path = require('path');

// ── minimal DOM / global stubs (just enough for init() + _showConfig) ──
function makeEl() {
  const listeners = {};
  return {
    innerHTML: '',
    textContent: '',
    value: '',
    disabled: false,
    classList: {
      _set: new Set(),
      add(...c) { c.forEach((x) => this._set.add(x)); },
      remove(...c) { c.forEach((x) => this._set.delete(x)); },
      toggle(c, on) { on ? this._set.add(c) : this._set.delete(c); },
      contains(c) { return this._set.has(c); },
    },
    style: {},
    _listeners: listeners,
    addEventListener(ev, fn) { (listeners[ev] = listeners[ev] || []).push(fn); },
    querySelector() { return makeEl(); },
    querySelectorAll() { return []; },
    closest() { return null; },
    setAttribute() {},
    appendChild() {},
  };
}
const elements = {};
function el(id) { return elements[id] || (elements[id] = makeEl()); }

global.document = {
  addEventListener() {},
  createElement() { return makeEl(); },
  getElementById(id) { return el(id); },
  querySelector() { return makeEl(); },
  querySelectorAll() { return []; },
};
global.window = global;
global.App = { bridge: null };
global.LogConsole = { log() {} };
global.PresetsUI = { promptName() {} };
global.StackDrag = { attach() {}, dragging: false };

// Load the real shipped module.
const { FAMILIES, loadFamily } = require('./js_family');
loadFamily(FAMILIES.stackDnd, { except: ['stack-drag.js'] });
const StackDnD = global.StackDnD;
const BUILTIN_BLOCKS = global.BUILTIN_BLOCKS;
StackDnD.init();

// ── tiny assertion kit ──────────────────────────────────────────────
let passed = 0, failed = 0;
function t(name, fn) {
  try { fn(); passed++; }
  catch (e) { failed++; console.error('FAIL ' + name + '\n   ' + (e && e.stack || e)); }
}
function ok(cond, msg) { if (!cond) throw new Error(msg || 'ok'); }
function speedBlock(multiplier) {
  return { block_id: 'SPEED_MULTIPLIER', multiplier, enabled: true };
}
function renderPanel(block) {
  StackDnD.setStack([block], { silent: true });
  StackDnD._showConfig(0);
  return el('blockConfigForm').innerHTML;
}

// ── registry entry ──────────────────────────────────────────────────
t('BUILTIN_BLOCKS carries the Speed Multiplier with a 1.0 default', () => {
  const meta = BUILTIN_BLOCKS.find((b) => b.block_id === 'SPEED_MULTIPLIER');
  ok(meta, 'entry present');
  ok(meta.defaults.multiplier === 1.0, 'default multiplier is 1.0');
  ok(meta.defaults.enabled === true, 'enabled by default');
  ok(/1\.0/.test(meta.labels.multiplier), 'label names normal speed');
});

// ── preview wording (mirrors actions/speed.py describe()) ───────────
t('preview: normal speed', () => {
  ok(StackDnD._speedDesc(1.0) === '×1.0 (normal speed)', StackDnD._speedDesc(1));
});
t('preview: faster', () => {
  ok(StackDnD._speedDesc(0.5) === '×0.5 (2× faster)', StackDnD._speedDesc(0.5));
  ok(StackDnD._speedDesc(0.1) === '×0.1 (10× faster)', StackDnD._speedDesc(0.1));
});
t('preview: slower', () => {
  ok(StackDnD._speedDesc(2) === '×2.0 (2× slower)', StackDnD._speedDesc(2));
  ok(StackDnD._speedDesc(3) === '×3.0 (3× slower)', StackDnD._speedDesc(3));
});
t('preview: garbage fails open to normal speed', () => {
  ok(StackDnD._speedDesc('fast') === '×1.0 (normal speed)');
  ok(StackDnD._speedDesc(0) === '×1.0 (normal speed)');
  ok(StackDnD._speedDesc(undefined) === '×1.0 (normal speed)');
});

// ── stack summary ───────────────────────────────────────────────────
t('stack row summarises the effect', () => {
  const s = StackDnD._summary(speedBlock(0.5));
  ok(s === 'All waits ×0.5 (2× faster)', s);
});

t('stack row marks a disabled block OFF', () => {
  const s = StackDnD._summary(
    { block_id: 'SPEED_MULTIPLIER', multiplier: 0.5, enabled: false });
  ok(s === 'All waits ×0.5 (2× faster) · OFF', s);
});

// ── config panel rows ───────────────────────────────────────────────
t('panel: coefficient input with step bounds', () => {
  const html = renderPanel(speedBlock(0.5));
  ok(html.indexOf('data-key="multiplier"') !== -1, 'coefficient input');
  ok(html.indexOf('type="number"') !== -1, 'number input');
  ok(html.indexOf('step="0.1"') !== -1, '0.1 step');
});

t('panel: quick presets for 0.5 / 1 / 2 / 3', () => {
  const html = renderPanel(speedBlock(1.0));
  ['0.5', '1', '2', '3'].forEach((v) => {
    ok(html.indexOf('data-speed="' + v + '"') !== -1, 'preset ' + v);
  });
});

t('panel: live preview names the effect', () => {
  const fast = renderPanel(speedBlock(0.5));
  ok(fast.indexOf('All waits ×0.5 (2× faster)') !== -1, 'fast preview');
  ok(fast.indexOf('🐇') !== -1, 'faster indicator');
  const slow = renderPanel(speedBlock(2));
  ok(slow.indexOf('All waits ×2.0 (2× slower)') !== -1, 'slow preview');
  ok(slow.indexOf('🐢') !== -1, 'slower indicator');
  const normal = renderPanel(speedBlock(1.0));
  ok(normal.indexOf('×1.0 (normal speed)') !== -1, 'normal preview');
});

t('migration back-fills the coefficient on bare blocks', () => {
  const nb = StackDnD._migrateBlock({ block_id: 'SPEED_MULTIPLIER' });
  ok(nb.multiplier === 1.0, 'default back-filled, got ' + nb.multiplier);
  ok(nb.enabled === true, 'enabled back-filled');
});

console.log('speed multiplier UI: ' + passed + ' passed, ' + failed + ' failed');
if (failed) process.exit(1);
console.log('OK');
