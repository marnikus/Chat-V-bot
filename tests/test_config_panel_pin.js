/* Tests for the Block Config pin / keep-open feature.

   A pinned Block Config (Tune) panel must remain visible even when no
   Action Block is selected, showing its empty-state hint instead of closing;
   unpinning restores the default close-on-deselect behaviour.

   Per AGENT_RULES RULE 8 this executes the REAL shipped module
   (ui/js/stack-dnd.js) in a real runtime (Node), against a tiny DOM stub,
   and also checks the real shipped ui/index.html for the pin button.

   Run:  node tests/test_config_panel_pin.js
   Exits 0 + prints "OK" when every test passes.
*/
'use strict';
const fs = require('fs');
const path = require('path');

// ── minimal DOM / global stubs (same shape as the other stack-dnd tests) ──
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
    setAttribute(k, v) { (this._attrs = this._attrs || {})[k] = v; },
    getAttribute(k) { return (this._attrs || {})[k]; },
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
const storage = {};
function clearStorage() { Object.keys(storage).forEach((k) => delete storage[k]); }
global.localStorage = {
  getItem(k) { return storage[k] === undefined ? null : storage[k]; },
  setItem(k, v) { storage[k] = String(v); },
  removeItem(k) { delete storage[k]; },
  clear() { clearStorage(); },
};
global.window = global;
global.App = { bridge: null };
global.LogConsole = { log() {} };
global.PresetsUI = { promptName() {} };
global.StackDrag = { attach() {}, dragging: false };

// Load the real shipped module.
const src = fs.readFileSync(
  path.join(__dirname, '..', 'ui', 'js', 'stack-dnd.js'), 'utf8');
const StackDnD = new Function(src + '\nreturn StackDnD;')();
StackDnD.init();

const html = fs.readFileSync(
  path.join(__dirname, '..', 'ui', 'index.html'), 'utf8');

// ── tiny assertion kit ──────────────────────────────────────────────
let passed = 0, failed = 0;
function t(name, fn) {
  try { fn(); passed++; }
  catch (e) { failed++; console.error('FAIL ' + name + '\n   ' + (e && e.stack || e)); }
}
function ok(cond, msg) { if (!cond) throw new Error(msg || 'ok'); }

const block = { block_id: 'CLICK_MAIN_TAB', enabled: true, pre_delay_ms: 500 };
const panel = () => el('blockConfigPanel');
const pinBtn = () => el('pinConfigBtn');
const form = () => el('blockConfigForm');

function openWithBlock() {
  StackDnD.setStack([block], { silent: true });
  StackDnD.selectBlock(0);
}

// ── markup / wiring ─────────────────────────────────────────────────

t('pin button exists in the Block Config title bar', () => {
  ok(html.indexOf('id="pinConfigBtn"') !== -1,
     'index.html must contain #pinConfigBtn');
  ok(html.indexOf('push_pin') !== -1, 'pin button uses the push_pin icon');
  ok(html.indexOf('aria-pressed="false"') !== -1,
     'pin button starts unpinned (aria-pressed=false)');
});

t('pin button starts unpinned and reflects that state', () => {
  ok(StackDnD.configPinned === false, 'configPinned defaults false');
  ok(pinBtn().classList.contains('pin-active') === false,
     'button must not show the active pin style');
  ok(pinBtn().getAttribute('aria-pressed') === 'false',
     'button announces unpinned state');
});

t('clicking the real pin button toggles and updates aria-pressed', () => {
  StackDnD.configPinned = false;
  StackDnD._updateConfigPinButton();
  const click = pinBtn().onclick;
  ok(typeof click === 'function', 'pin button has a click handler');
  click({ stopPropagation() {}, preventDefault() {} });
  ok(StackDnD.configPinned === true, 'click pins the panel');
  ok(pinBtn().getAttribute('aria-pressed') === 'true', 'aria-pressed true');
  click({ stopPropagation() {}, preventDefault() {} });
  ok(StackDnD.configPinned === false, 'second click unpins');
  ok(pinBtn().getAttribute('aria-pressed') === 'false', 'aria-pressed false');
});

// ── default (unpinned) close-on-deselect ────────────────────────────

t('unpinned panel opens for a selected block', () => {
  openWithBlock();
  ok(!panel().classList.contains('hidden'), 'panel visible with a block');
  ok(panel().classList.contains('has-block'), 'panel marked as populated');
  ok(form().innerHTML.indexOf('data-key="pre_delay_ms"') !== -1,
     'config form is rendered');
});

t('unpinned panel closes when the stack resets (deselect)', () => {
  StackDnD.configPinned = false;
  StackDnD._updateConfigPinButton();
  openWithBlock();
  StackDnD.setStack([], { silent: true });
  ok(StackDnD.selectedIdx === -1, 'deselected after stack reset');
  ok(panel().classList.contains('hidden'), 'unpinned panel closes on deselect');
  ok(!panel().classList.contains('has-block'), 'empty state stays shown-because-hidden');
  ok(form().innerHTML === '', 'form is cleared when no block is selected');
});

t('deselectBlock respects the pin (open empty vs close)', () => {
  StackDnD.configPinned = false;
  StackDnD._updateConfigPinButton();
  openWithBlock();
  StackDnD.deselectBlock();
  ok(panel().classList.contains('hidden'), 'unpinned deselect closes the panel');

  StackDnD.configPinned = true;
  StackDnD._updateConfigPinButton();
  openWithBlock();
  StackDnD.deselectBlock();
  ok(!panel().classList.contains('hidden'), 'pinned deselect keeps the panel open');
  ok(!panel().classList.contains('has-block'), 'pinned deselect shows the empty state');
});

// ── pin keeps the empty panel open ──────────────────────────────────

t('pinning keeps the panel open with the empty state after deselect', () => {
  StackDnD.configPinned = false;
  StackDnD._updateConfigPinButton();
  openWithBlock();
  StackDnD._toggleConfigPin();                    // pin
  ok(StackDnD.configPinned === true, 'toggle pins the panel');
  ok(pinBtn().classList.contains('pin-active'), 'pin button becomes active');

  StackDnD.setStack([], { silent: true });        // deselect
  ok(StackDnD.selectedIdx === -1, 'stack reset deselects the block');
  ok(!panel().classList.contains('hidden'), 'pinned panel stays open empty');
  ok(!panel().classList.contains('has-block'), 'empty state is shown, not a stale block');
  ok(form().innerHTML === '', 'form is cleared in the pinned empty state');
});

t('pinned empty panel still accepts a later block selection', () => {
  StackDnD.configPinned = false;
  StackDnD._updateConfigPinButton();
  StackDnD.setStack([], { silent: true });
  StackDnD._toggleConfigPin();                    // pin while empty
  StackDnD.setStack([block], { silent: true });   // stack refresh
  ok(!panel().classList.contains('hidden'), 'pinned panel remains open after refresh');
  ok(!panel().classList.contains('has-block'),
     'stack refresh without selecting a block keeps the empty state');
  StackDnD.selectBlock(0);
  ok(panel().classList.contains('has-block'),
     'selecting a block re-populates the pinned panel');
  ok(form().innerHTML.indexOf('data-key="pre_delay_ms"') !== -1,
     'config form populated after selection');
});

// ── pin persistence across restarts ─────────────────────────────────

t('pin toggle persists to localStorage', () => {
  clearStorage();
  StackDnD.configPinned = false;
  StackDnD._updateConfigPinButton();
  StackDnD._toggleConfigPin();                    // pin -> persists '1'
  ok(storage[StackDnD.CONFIG_PIN_STORAGE_KEY] === '1',
     'pinning writes 1 to localStorage');
  StackDnD._toggleConfigPin();                    // unpin -> persists '0'
  ok(storage[StackDnD.CONFIG_PIN_STORAGE_KEY] === '0',
     'unpinning writes 0 to localStorage');
});

t('pin toggle notifies the desktop bridge so config.json persists it', () => {
  clearStorage();
  const saved = [];
  global.App.bridge = { set_block_config_pinned(v) { saved.push(!!v); } };
  try {
    StackDnD.configPinned = false;
    StackDnD._updateConfigPinButton();
    StackDnD._toggleConfigPin();
    StackDnD._toggleConfigPin();
  } finally {
    global.App.bridge = null;
  }
  ok(saved.length === 2, 'bridge pin slot called on each toggle');
  ok(saved[0] === true, 'pin toggle sends true');
  ok(saved[1] === false, 'unpin toggle sends false');
});

t('load restores a pinned state and reopens the panel empty after restart', () => {
  clearStorage();
  StackDnD.configPinned = false;
  StackDnD._updateConfigPinButton();
  StackDnD._toggleConfigPin();                    // pin (persists true)
  ok(storage[StackDnD.CONFIG_PIN_STORAGE_KEY] === '1', 'storage holds pinned');
  // Simulate a fresh session: StackDnD starts unpinned, then reads storage.
  StackDnD.configPinned = false;
  StackDnD._loadConfigPin();
  ok(StackDnD.configPinned === true, 'load reads the persisted pin');
  StackDnD.setStack([], { silent: true });        // "reload" with no selection
  ok(!panel().classList.contains('hidden'),
     'pinned panel is visible after reload with no block selected');
  ok(!panel().classList.contains('has-block'),
     'reloaded pinned panel is empty, not stale');
});

t('backend session state overrides the local pin on restore', () => {
  clearStorage();
  StackDnD.configPinned = false;
  StackDnD._persistConfigPin();                   // storage = '0'
  StackDnD._applyConfigPin(true);                 // backend says pinned
  ok(StackDnD.configPinned === true, 'backend pinned state wins');
  StackDnD._applyConfigPin(false);                // backend says unpinned
  ok(StackDnD.configPinned === false, 'backend unpinned state wins');
  ok(storage[StackDnD.CONFIG_PIN_STORAGE_KEY] === '0',
     'local storage still defaults to unpinned for a fresh browser');
});

t('applyConfigPin after a stack restore reopens a pinned empty panel', () => {
  clearStorage();
  StackDnD.configPinned = false;
  StackDnD._updateConfigPinButton();
  StackDnD.setStack([block], { silent: true });
  StackDnD.setStack([], { silent: true });        // deselect -> closed
  ok(panel().classList.contains('hidden'), 'panel closed before restore');
  StackDnD._applyConfigPin(true);                 // restore says pinned
  ok(!panel().classList.contains('hidden'),
     'later restore still reopens the pinned empty panel');
});

t('public applyConfigPin exists and is what session restore calls', () => {
  clearStorage();
  ok(typeof StackDnD.applyConfigPin === 'function',
     'session restore must find a public applyConfigPin = undefined');
  if (typeof StackDnD.applyConfigPin === 'function') {
    ok(StackDnD.applyConfigPin === StackDnD._applyConfigPin ||
       (() => { // either direct alias or delegated wrapper
         StackDnD.configPinned = false;
         StackDnD._updateConfigPinButton();
         StackDnD.applyConfigPin(true);
         return StackDnD.configPinned === true;
       })(),
       'public applyConfigPin delegates to the internal restore');
  }
});

t('restoring true after setStack([]) makes the panel visible (exact bug)', () => {
  clearStorage();
  StackDnD.configPinned = false;
  StackDnD._updateConfigPinButton();
  // The app restore sequence: setStack clears selection, then applyConfigPin
  // reopens it if it was pinned.
  StackDnD.setStack([], { silent: true });
  if (typeof StackDnD.applyConfigPin === 'function') {
    StackDnD.applyConfigPin(true);
  } else {
    StackDnD._applyConfigPin(true);
  }
  ok(!panel().classList.contains('hidden'),
     'restored pinned panel must become visible after startup');
  ok(pinBtn().classList.contains('pin-active'),
     'restored pin button must be active after startup');
});

t('flushPersistence saves the pin state (local + backend)', () => {
  clearStorage();
  const saved = [];
  global.App.bridge = { set_block_config_pinned(v) { saved.push(!!v); } };
  try {
    StackDnD.configPinned = false;
    StackDnD._updateConfigPinButton();
    StackDnD.configPinned = true;                 // toggle logic missed the bridge
    StackDnD.flushPersistence();
  } finally {
    global.App.bridge = null;
  }
  ok(storage[StackDnD.CONFIG_PIN_STORAGE_KEY] === '1',
     'close flush writes the final pin to localStorage');
  ok(saved.length === 1 && saved[0] === true,
     'close flush writes the final pin to the backend');
});

// ── unpin restores the default behaviour ────────────────────────────

t('unpinning an empty pinned panel closes it', () => {
  StackDnD.configPinned = false;
  StackDnD._updateConfigPinButton();
  openWithBlock();
  StackDnD._toggleConfigPin();                    // pin
  StackDnD.setStack([], { silent: true });        // deselect -> pinned empty
  ok(!panel().classList.contains('hidden'), 'pinned empty panel open before unpin');
  StackDnD._toggleConfigPin();                    // unpin
  ok(StackDnD.configPinned === false, 'toggle unpins the panel');
  ok(!pinBtn().classList.contains('pin-active'), 'pin button inactive after unpin');
  ok(panel().classList.contains('hidden'), 'unpinned empty panel closes immediately');
});

t('close button unpins and closes even when pinned', () => {
  StackDnD.configPinned = false;
  StackDnD._updateConfigPinButton();
  openWithBlock();
  StackDnD._toggleConfigPin();                    // pin
  el('closeConfigBtn').onclick();                  // explicit close
  ok(StackDnD.configPinned === false, 'explicit close unpins');
  ok(panel().classList.contains('hidden'), 'explicit close hides the panel');
  ok(!panel().classList.contains('has-block'), 'close clears the populated mark');
});

t('close button works on a pinned empty panel with no block ever selected', () => {
  StackDnD.configPinned = false;
  StackDnD._updateConfigPinButton();
  StackDnD.setStack([], { silent: true });         // starts hidden
  StackDnD._toggleConfigPin();                     // pin empty
  ok(!panel().classList.contains('hidden'), 'pinned empty panel is open');
  el('closeConfigBtn').onclick();                  // close without a block
  ok(StackDnD.configPinned === false, 'closing an empty pinned panel unpins');
  ok(panel().classList.contains('hidden'), 'empty panel closes even though no block was ever selected');
});

// ── removeBlock keeps the selection / config panel consistent ──────

t('removing a block before the selected one keeps that block selected', () => {
  StackDnD.configPinned = false;
  StackDnD._updateConfigPinButton();
  StackDnD.setStack(
    [{ block_id: 'CLICK_MAIN_TAB' }, { block_id: 'PAUSE' }, { block_id: 'CLICK_SEND' }],
    { silent: true });
  StackDnD.selectBlock(2);
  StackDnD.removeBlock(0);
  ok(StackDnD.selectedIdx === 1,
     'selection shifts down after removing an earlier block');
  ok(StackDnD.stack[StackDnD.selectedIdx].block_id === 'CLICK_SEND',
     'the originally selected block stays selected');
  ok(panel().classList.contains('has-block'), 'config panel still populated');
});

// ── pin interacts with removeBlock deselect paths ───────────────────

t('pinned panel stays open empty when the last selected block is removed', () => {
  StackDnD.configPinned = false;
  StackDnD._updateConfigPinButton();
  StackDnD.setStack([block], { silent: true });
  StackDnD.selectBlock(0);
  StackDnD._toggleConfigPin();                    // pin
  StackDnD.removeBlock(0);
  ok(StackDnD.selectedIdx === -1, 'last selected block removal deselects');
  ok(!panel().classList.contains('hidden'), 'pinned panel stays open after removal');
  ok(!panel().classList.contains('has-block'), 'removal leaves the empty state');
  ok(form().innerHTML === '', 'removal clears the form');
});

t('unpinned panel closes when the last selected block is removed', () => {
  StackDnD.configPinned = false;
  StackDnD._updateConfigPinButton();
  StackDnD.setStack([block], { silent: true });
  StackDnD.selectBlock(0);
  StackDnD.removeBlock(0);
  ok(panel().classList.contains('hidden'), 'unpinned panel closes on removal');
  ok(StackDnD.selectedIdx === -1, 'no selected block remains');
});

console.log('config-panel pin: ' + passed + ' passed, ' + failed + ' failed');
if (failed) process.exit(1);
console.log('OK');
