/* test_stack_history_form.js — stack-dnd family coverage lift (Round H,
   H-A6). Part 2: migration + history state machine + history buttons +
   config form (row-builder table) + speed multiplier controls.
   Executes the REAL shipped family against a DOM stub (RULE 8). */
'use strict';
const assert = require('assert');

function makeEl(id) {
  const set = new Set();
  const el = {
    id: id || '', tag: id || '', value: '', _cls: '', disabled: false,
    title: '', placeholder: '', checked: false, type: 'text', tagName: 'DIV',
    children: [], style: {}, dataset: {}, onclick: null, _text: '', _html: '', _l: {},
    appendChild(c) { this.children.push(c); return c; },
    addEventListener(t, f) { (this._l[t] = this._l[t] || []).push(f); },
    removeEventListener() {}, focus() {},
    querySelector() { return null; },
    querySelectorAll(sel) { return el._qsa ? el._qsa(sel) : []; },
    closest() { return null; },
    setAttribute() {}, getAttribute() { return null; }, removeAttribute() {},
  };
  el.classList = { add(c) { set.add(c); }, remove(c) { set.delete(c); },
    toggle(c, force) {
      const want = force === undefined ? !set.has(c) : !!force;
      if (want) set.add(c); else set.delete(c); return want;
    }, contains(c) { return set.has(c); } };
  Object.defineProperty(el, 'textContent', {
    get() { return el._text; },
    set(v) {
      el._text = v;
      el._html = (v === null || v === undefined) ? ''
        : String(v).replace(/&/g, '&amp;').replace(/</g, '&lt;')
          .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    },
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
    set(v) { el._html = String(v); },
    configurable: true,
  });
  return el;
}
const els = {};
function el(id) { return els[id] || (els[id] = makeEl(id)); }
global.document = {
  getElementById: (id) => el(id),
  createElement: (t) => makeEl(t),
  addEventListener() {}, removeEventListener() {},
  activeElement: null,
};
global.window = global;
global.localStorage = { _d: {}, getItem(k) { return this._d[k] || null; },
  setItem(k, v) { this._d[k] = String(v); }, removeItem(k) { delete this._d[k]; } };

const calls = []; const logs = [];
const rec = (n) => (...a) => { calls.push([n, ...a]); };
global.LogConsole = { log: (m, l) => logs.push([m, l]), clear() {} };
const b = {
  snapshot_stack: rec('snapshot_stack'), save_stack_history: rec('save_stack_history'),
  save_custom_block: rec('save_custom_block'),
};
function appUndo() { calls.push(['undoGlobal']); return 'app-undo'; }
function appRedo() { calls.push(['redoGlobal']); return 'app-redo'; }
global.App = { bridge: b, recordGlobal: rec('recordGlobal'),
  undoGlobal: appUndo, redoGlobal: appRedo,
  _updateUndoButtons: rec('_updateUndoButtons') };
global.PresetsUI = { promptName: (t, p, ok, onOk) => { onOk('Prompted'); } };
global.StackDrag = { dragging: false, attach() {}, flashLanded() {} };
global.BridgeReady = { ready() {} };

const { FAMILIES, loadFamily } = require('./js_family');
loadFamily(FAMILIES.stackDnd, { except: ['stack-drag.js'] });
const StackDnD = global.StackDnD;

let passed = 0; let failed = 0;
function test(name, fn) {
  try { fn(); passed += 1; console.log('  ok - ' + name); }
  catch (e) { failed += 1; console.error('  FAIL - ' + name + '\n    ' + e.message); }
}
function clearCalls() { calls.length = 0; logs.length = 0; }
function assertCall(n) { assert(calls.some((c) => c[0] === n), 'expected ' + n); }
function fire(elm, type, ev) { (elm._l[type] || []).forEach((f) => f(ev || {})); }

// ── migration ──────────────────────────────────────────────────
test('_deepCopy: object / array / circular fallback', () => {
  const o = { a: [1, 2], b: { c: 3 } };
  const c = StackDnD._deepCopy(o);
  c.b.c = 9;
  assert.strictEqual(o.b.c, 3);
  const arr = [{ x: 1 }];
  const ca = StackDnD._deepCopy(arr);
  ca[0].x = 2;
  assert.strictEqual(arr[0].x, 1);
  const circ = { n: 'circ' }; circ.self = circ;
  const cc = StackDnD._deepCopy(circ); // JSON throws → shallow fallback
  assert.strictEqual(cc.n, 'circ');
  assert.strictEqual(StackDnD._deepCopy(42), 42);
});

test('_migrateBlock / _normalizeBlock: retired keys, defaults, enabled', () => {
  const m = StackDnD._migrateBlock({ block_id: 'CLICK_SEND', use_panel_filters: true,
    skip_if_backlog: true, backlog_threshold: 5, enabled: null });
  assert(!('use_panel_filters' in m));
  assert(!('skip_if_backlog' in m));
  assert.strictEqual(m.fallback_selector, 'button:has(mat-icon)'); // back-filled
  assert.strictEqual(m.enabled, true); // null → true
  const m2 = StackDnD._migrateBlock({ block_id: 'CLICK_SEND', enabled: 1, pre_delay_ms: 'no' });
  assert.strictEqual(m2.enabled, true);
  assert.strictEqual(m2.pre_delay_ms, 500); // non-number → default
  assert.strictEqual(StackDnD._migrateBlock(null), null);
  assert.strictEqual(StackDnD._migrateBlock([]), null);
  const unknown = StackDnD._migrateBlock({ block_id: 'MY_CUSTOM', foo: 'bar', enabled: false });
  assert.strictEqual(unknown.foo, 'bar'); // unknown block keeps its keys
  assert.strictEqual(StackDnD._normalizeBlock(m).block_id, 'CLICK_SEND');
  assert.deepStrictEqual(StackDnD._normalizeStack('nope'), []);
  assert.strictEqual(StackDnD._normalizeStack([null, { block_id: 'PAUSE', duration_ms: 5 }]).length, 1);
});

test('_stacksEqual', () => {
  assert(StackDnD._stacksEqual([{ a: 1 }], [{ a: 1 }]));
  assert(!StackDnD._stacksEqual([{ a: 1 }], [{ a: 2 }]));
  const bad = { x: {} }; bad.self = bad;
  assert(!StackDnD._stacksEqual(bad, bad));
});

test('_initDefaultStack: 8 blocks, fully back-filled', () => {
  StackDnD._initDefaultStack();
  assert.strictEqual(StackDnD.stack.length, 8);
  const scroll = StackDnD.stack.find((x) => x.block_id === 'SCROLL_PARSE');
  assert.strictEqual(scroll.scroll_only, false); // added after old stacks
  assert.strictEqual(scroll.purge_rejected, true);
  assert.strictEqual(scroll.filter_female, 'yes');
  assert(StackDnD.stack.every((x) => typeof x.enabled === 'boolean'));
});

test('_getCurrentHistoryStack: in / out of range', () => {
  StackDnD.history = [[{ a: 1 }], [{ a: 2 }]];
  StackDnD.historyIndex = 1;
  assert.deepStrictEqual(StackDnD._getCurrentHistoryStack(), [{ a: 2 }]);
  StackDnD.historyIndex = 5;
  assert.strictEqual(StackDnD._getCurrentHistoryStack(), null);
  StackDnD.historyIndex = -1;
  assert.strictEqual(StackDnD._getCurrentHistoryStack(), null);
});

// ── history state machine ──────────────────────────────────────
test('pushHistory: push, dedup, force, guards, future truncate', () => {
  clearCalls();
  StackDnD.history = []; StackDnD.historyIndex = -1;
  StackDnD.setStack([{ block_id: 'CLICK_SEND' }], { forceHistory: true });
  assert.strictEqual(StackDnD.history.length, 1);
  assertCall('recordGlobal');
  const len = StackDnD.history.length;
  StackDnD.pushHistory(); // same tip → dedup
  assert.strictEqual(StackDnD.history.length, len);
  StackDnD.stack.push({ block_id: 'PAUSE', duration_ms: 1 });
  StackDnD.pushHistory();
  assert.strictEqual(StackDnD.history.length, len + 1);
  // undo once, then a new push truncates the future
  StackDnD.historyIndex--;
  StackDnD.stack = [{ block_id: 'CLICK_SEND' }, { block_id: 'WAIT_PAGE_LOAD', timeout_ms: 1 }];
  StackDnD.pushHistory(StackDnD.stack, { force: true });
  assert.strictEqual(StackDnD.history.length, 2); // future truncated
  StackDnD._isRestoringHistory = true;
  StackDnD.pushHistory(StackDnD.stack, { force: true }); // blocked while restoring
  assert.strictEqual(StackDnD.history.length, 2);
  StackDnD._isRestoringHistory = false;
  StackDnD._running = true;
  StackDnD.pushHistory(StackDnD.stack, { force: true }); // blocked while running
  assert.strictEqual(StackDnD.history.length, 2);
  StackDnD._running = false;
});

test('pushHistory: MAX_HISTORY enforcement', () => {
  StackDnD.history = []; StackDnD.historyIndex = -1;
  StackDnD.MAX_HISTORY = 3;
  for (let i = 0; i < 5; i += 1) {
    StackDnD.pushHistory([{ block_id: 'PAUSE', duration_ms: i }], { force: true });
  }
  assert.strictEqual(StackDnD.history.length, 3);
  assert.strictEqual(StackDnD.historyIndex, 2);
  assert.strictEqual(StackDnD.history[2][0].duration_ms, 4);
  StackDnD.MAX_HISTORY = 100;
});

test('canUndo / canRedo', () => {
  StackDnD.history = [{ a: 1 }, { a: 2 }, { a: 3 }];
  StackDnD.historyIndex = 0;
  assert.strictEqual(StackDnD.canUndo(), false);
  assert.strictEqual(StackDnD.canRedo(), true);
  StackDnD.historyIndex = 2;
  assert.strictEqual(StackDnD.canUndo(), true);
  assert.strictEqual(StackDnD.canRedo(), false);
  StackDnD.historyIndex = -1;
  assert.strictEqual(StackDnD.canRedo(), false);
});

test('undo/redo delegate to App when available', () => {
  clearCalls();
  assert.strictEqual(StackDnD.undo(), 'app-undo');
  assertCall('undoGlobal');
  assert.strictEqual(StackDnD.redo(), 'app-redo');
  assertCall('redoGlobal');
  assert(!calls.some((c) => c[0] === 'save_stack_history'));
});

test('undo/redo legacy path (no App timeline)', () => {
  clearCalls();
  delete global.App.undoGlobal;
  delete global.App.redoGlobal;
  StackDnD.history = []; StackDnD.historyIndex = -1;
  StackDnD.setStack([{ block_id: 'CLICK_SEND' }], { forceHistory: true });
  StackDnD.stack.push({ block_id: 'PAUSE', duration_ms: 1 });
  StackDnD.pushHistory();
  assert.strictEqual(StackDnD.history.length, 2);
  const ok = StackDnD.undo();
  assert.strictEqual(ok, true);
  assert.strictEqual(StackDnD.historyIndex, 0);
  assert.strictEqual(StackDnD.stack.length, 1);
  assertCall('save_stack_history');
  assertCall('snapshot_stack');
  assert(logs.some((l) => l[0].indexOf('Undo') >= 0));
  const ok2 = StackDnD.redo();
  assert.strictEqual(ok2, true);
  assert.strictEqual(StackDnD.historyIndex, 1);
  assert.strictEqual(StackDnD.stack.length, 2);
  assert(logs.some((l) => l[0].indexOf('Redo') >= 0));
  assert.strictEqual(StackDnD.undo(), true); // back to the bottom
  assert.strictEqual(StackDnD.undo(), false); // now truly at the bottom
  assert(logs.some((l) => l[0].indexOf('Nothing to undo') >= 0));
  assert.strictEqual(StackDnD.redo(), true);
  assert.strictEqual(StackDnD.redo(), false); // top
  assert(logs.some((l) => l[0].indexOf('Nothing to redo') >= 0));
  global.App.undoGlobal = appUndo;
  global.App.redoGlobal = appRedo;
});

test('updateHistoryButtons: delegate + legacy paint', () => {
  clearCalls();
  StackDnD.updateHistoryButtons();
  assertCall('_updateUndoButtons');
  delete global.App._updateUndoButtons;
  StackDnD.history = [{ a: 1 }]; StackDnD.historyIndex = 0;
  StackDnD.updateHistoryButtons();
  assert.strictEqual(el('undoBtn').disabled, true);
  assert.strictEqual(el('undoBtn').title, 'Nothing to undo');
  assert.strictEqual(el('redoBtn').disabled, true);
  assert.strictEqual(el('redoBtn').title, 'Nothing to redo');
  StackDnD.history.push({ a: 2 }); StackDnD.historyIndex = 0;
  StackDnD.updateHistoryButtons();
  assert.strictEqual(el('undoBtn').disabled, true);
  assert.strictEqual(el('redoBtn').disabled, false);
  assert(el('redoBtn').title.indexOf('Redo (Ctrl+Y)') === 0);
  global.App._updateUndoButtons = rec('_updateUndoButtons');
});

test('loadHistoryFromState: list + clamps + last_stack seed', () => {
  clearCalls();
  StackDnD.loadHistoryFromState({
    stack_history: [[{ block_id: 'CLICK_SEND' }], [{ block_id: 'PAUSE', duration_ms: 5 }]],
    stack_history_index: 10, // clamped
  });
  assert.strictEqual(StackDnD.history.length, 2);
  assert.strictEqual(StackDnD.historyIndex, 1);
  StackDnD.loadHistoryFromState({
    stack_history: [[{ block_id: 'PAUSE', duration_ms: 5 }]],
    stack_history_index: -4, // clamped up
  });
  assert.strictEqual(StackDnD.historyIndex, 0);
  StackDnD.history = []; StackDnD.historyIndex = -1;
  StackDnD.loadHistoryFromState({ last_stack: [{ block_id: 'PAUSE', duration_ms: 7 }] });
  assert.strictEqual(StackDnD.history.length, 1);
  assert.strictEqual(StackDnD.history[0][0].duration_ms, 7);
  StackDnD.loadHistoryFromState(null); // no-op
  StackDnD.loadHistoryFromState({}); // no history, no last_stack → untouched
});

test('_setupHistoryButtons wires undo/redo', () => {
  clearCalls();
  StackDnD._setupHistoryButtons();
  fire(el('undoBtn'), 'click');
  fire(el('redoBtn'), 'click');
  assertCall('undoGlobal');
  assertCall('redoGlobal');
});

// ── config form ────────────────────────────────────────────────
test('_configKeys: meta default order first, extras after', () => {
  const meta = { defaults: { b: 1, a: 2 }, labels: {} };
  assert.deepStrictEqual(StackDnD._configKeys({ a: 2, b: 1, z: 9, block_id: 'X' }, meta), ['b', 'a', 'z']);
  assert.deepStrictEqual(StackDnD._configKeys({ x: 1 }, {}), ['x']);
});

test('_configBodyHtml: head, hint, retired skip, zebra', () => {
  const cf = { block_id: 'CUSTOM_FIND', custom_name: 'N', selector: '.a', enabled: true,
    use_panel_filters: true, pre_delay_ms: 1 };
  const html = StackDnD._configBodyHtml(cf, StackDnD._meta('CUSTOM_FIND'));
  assert(html.indexOf('Block') >= 0);
  assert(html.indexOf('constructor') >= 0);
  assert(html.indexOf('use_panel_filters') < 0); // retired never rendered
  const cu = { block_id: 'CLICK_USER', selector: '.u', tab_pause_ms: 800, enabled: true, pre_delay_ms: 1 };
  const html2 = StackDnD._configBodyHtml(cu, StackDnD._meta('CLICK_USER'));
  assert(html2.indexOf('zebra-0') >= 0);
  assert(html2.indexOf('zebra-1') >= 0);
});

test('_configRowHtml dispatch: checkbox/select/radio/input/speed/message', () => {
  const meta = StackDnD._meta('TAKE_PERSON');
  const block = { block_id: 'TAKE_PERSON', pick_mode: 'random_new', enabled: true, pre_delay_ms: 1 };
  assert(StackDnD._configRowHtml('pick_mode', 'random_new', block, meta, 0).indexOf('radio-group') >= 0);
  assert(StackDnD._configRowHtml('enabled', true, block, meta, 0).indexOf('form-row-enabled') >= 0);
  const tm = { block_id: 'TYPE_MESSAGE', message: 'hi', use_composer: false, enabled: true, pre_delay_ms: 1 };
  assert(StackDnD._configRowHtml('message', 'hi', tm, StackDnD._meta('TYPE_MESSAGE'), 1).indexOf('textarea') >= 0);
  const sm = { block_id: 'SPEED_MULTIPLIER', multiplier: 1, enabled: true };
  assert(StackDnD._configRowHtml('multiplier', 1, sm, StackDnD._meta('SPEED_MULTIPLIER'), 0).indexOf('speed-presets') >= 0);
  const sc = StackDnD._meta('SCROLL_PARSE');
  assert(StackDnD._configRowHtml('filter_female', 'yes', { block_id: 'SCROLL_PARSE', filter_female: 'yes' }, sc, 0).indexOf('<select') >= 0);
  assert(StackDnD._configRowHtml('max_scrolls', 50, { block_id: 'SCROLL_PARSE', max_scrolls: 50 }, sc, 0).indexOf('type="number"') >= 0);
  assert(StackDnD._configRowHtml('person_selector', '.p', { block_id: 'SCROLL_PARSE', person_selector: '.p' }, sc, 0).indexOf('type="text"') >= 0);
});

test('row builders: radio labels, select selected, message disabled', () => {
  const meta = StackDnD._meta('TAKE_PERSON');
  const r = StackDnD._radioRowHtml('pick_mode', 'Pick', 'random_done', meta.radios.pick_mode, meta, 1);
  assert(r.indexOf('random_done') >= 0);
  assert(r.indexOf('checked') >= 0);
  assert(r.indexOf('Any random already-messaged') >= 0);
  const s = StackDnD._selectRowHtml('mode', 'Mode', 'full', ['incremental', 'full'], 0);
  assert(s.indexOf('value="full" selected') >= 0);
  const m1 = StackDnD._messageRowHtml('Message', 'text', { use_composer: false }, 0);
  assert(m1.indexOf('disabled') < 0);
  const m2 = StackDnD._messageRowHtml('Message', 'text', { use_composer: true }, 0);
  assert(m2.indexOf('disabled') >= 0);
  assert(m2.indexOf('Message Composer') >= 0);
});

test('_showConfig: no block / block / close handler', () => {
  StackDnD.stack = [];
  StackDnD.selectedIdx = -1;
  StackDnD._showConfig(-1);
  assert.strictEqual(el('blockConfigForm').innerHTML, '');
  const closeClicked = [];
  el('closeConfigBtn').onclick = () => closeClicked.push(1);
  StackDnD.setStack([{ block_id: 'PAUSE', duration_ms: 1 }], { forceHistory: true });
  el('blockConfigForm')._qsa = () => [];
  StackDnD._showConfig(0);
  assert(el('blockConfigForm').innerHTML.indexOf('Duration') >= 0);
  assert(typeof el('closeConfigBtn').onclick === 'function');
  assert(el('customBlockActions').classList.contains('hidden')); // not CUSTOM_FIND
});

test('_wireCustomBlockActions: shows + saves for CUSTOM_FIND', () => {
  clearCalls();
  StackDnD.setStack([{ block_id: 'CUSTOM_FIND', custom_name: 'CF' }], { forceHistory: true });
  el('blockConfigForm')._qsa = () => [];
  StackDnD._showConfig(0);
  assert(!el('customBlockActions').classList.contains('hidden'));
  el('saveCustomBlockBtn').onclick();
  assertCall('save_custom_block');
});

test('_wireConfigForm: select / checkbox / number / text + logs', () => {
  clearCalls();
  const block = { block_id: 'SCROLL_PARSE', filter_female: 'yes', max_scrolls: 50,
    purge_rejected: true, enabled: true, pre_delay_ms: 1 };
  const sel = makeEl('sel'); sel.tagName = 'SELECT'; sel.dataset.key = 'filter_female'; sel.value = 'no';
  const chk = makeEl('chk'); chk.type = 'checkbox'; chk.dataset.key = 'purge_rejected'; chk.checked = false;
  const num = makeEl('num'); num.type = 'number'; num.dataset.key = 'max_scrolls'; num.value = '7';
  const en = makeEl('en'); en.type = 'checkbox'; en.dataset.key = 'enabled'; en.checked = false;
  el('blockConfigForm')._qsa = () => [sel, chk, num, en];
  StackDnD.setStack([block], { forceHistory: true });
  StackDnD.selectedIdx = 0;
  StackDnD._showConfig(0); // wires the change handlers onto the fakes
  const live = StackDnD.stack[0]; // setStack migrates a copy
  fire(sel, 'change');
  assert.strictEqual(live.filter_female, 'no');
  fire(chk, 'change');
  assert.strictEqual(live.purge_rejected, false);
  fire(num, 'change');
  assert.strictEqual(live.max_scrolls, 7);
  fire(en, 'change');
  assert.strictEqual(live.enabled, false);
  assert(logs.some((l) => l[0].indexOf('Disabled') >= 0));
  assertCall('recordGlobal');
});

test('_wireConfigForm: TYPE_MESSAGE use_composer re-renders', () => {
  clearCalls();
  const block = { block_id: 'TYPE_MESSAGE', message: 'm', use_composer: false, enabled: true, pre_delay_ms: 1 };
  const uc = makeEl('uc'); uc.type = 'checkbox'; uc.dataset.key = 'use_composer'; uc.checked = true;
  el('blockConfigForm')._qsa = () => [uc];
  StackDnD.setStack([block], { forceHistory: true });
  StackDnD.selectedIdx = 0;
  StackDnD._showConfig(0);
  const before = el('blockConfigForm').innerHTML;
  fire(uc, 'change');
  assert.strictEqual(StackDnD.stack[0].use_composer, true);
  assert.notStrictEqual(el('blockConfigForm').innerHTML, before); // re-rendered
});

// ── speed multiplier ───────────────────────────────────────────
test('_speedValue / _speedCoef / _speedDesc', () => {
  assert.strictEqual(StackDnD._speedValue('junk'), 1);
  assert.strictEqual(StackDnD._speedValue(0), 1);
  assert.strictEqual(StackDnD._speedValue(-3), 1);
  assert.strictEqual(StackDnD._speedValue(0.001), 0.1);
  assert.strictEqual(StackDnD._speedValue(99), 10);
  assert.strictEqual(StackDnD._speedValue(2.5), 2.5);
  assert.strictEqual(StackDnD._speedCoef(2), '2.0');
  assert.strictEqual(StackDnD._speedCoef(1.25), '1.25');
  assert.strictEqual(StackDnD._speedCoef(1.004), '1');
  assert.strictEqual(StackDnD._speedDesc(1), '×1.0 (normal speed)');
  assert.strictEqual(StackDnD._speedDesc(0.5), '×0.5 (2× faster)');
  assert.strictEqual(StackDnD._speedDesc(2), '×2.0 (2× slower)');
});

test('_speedPreviewHtml marks', () => {
  assert(StackDnD._speedPreviewHtml(0.5).indexOf('🐇') >= 0);
  assert(StackDnD._speedPreviewHtml(2).indexOf('🐢') >= 0);
  assert(StackDnD._speedPreviewHtml(1).indexOf('➖') >= 0);
});

test('_wireSpeedControls: preset click + input + change', () => {
  clearCalls();
  const block = { block_id: 'SPEED_MULTIPLIER', multiplier: 1, enabled: true };
  const mult = makeEl('mult'); mult.value = '1';
  const preview = makeEl('preview');
  const btn2 = makeEl('b2'); btn2.dataset.speed = '2';
  el('blockConfigForm').querySelector = (s) => s === 'input[data-key="multiplier"]' ? mult
    : s === '[data-speed-preview]' ? preview : null;
  el('blockConfigForm')._qsa = (s) => (s === '[data-speed]' ? [btn2] : []);
  StackDnD.setStack([block], { forceHistory: true });
  StackDnD.selectedIdx = 0;
  el('blockConfigForm')._qsa = (s) => (s === '[data-speed]' ? [btn2] : s.indexOf('input') >= 0 ? [] : []);
  StackDnD._wireSpeedControls(el('blockConfigForm'), block);
  fire(btn2, 'click', { preventDefault() {} });
  assert.strictEqual(block.multiplier, 2);
  assert.strictEqual(mult.value, 2);
  assert(preview.innerHTML.indexOf('slower') >= 0);
  assertCall('recordGlobal');
  mult.value = '0.5';
  fire(mult, 'input');
  assert.strictEqual(block.multiplier, 0.5);
  assert(preview.innerHTML.indexOf('faster') >= 0);
  fire(mult, 'change');
  assert(preview.innerHTML.length > 0);
});

test('_showConfig wires speed for SPEED_MULTIPLIER', () => {
  clearCalls();
  const block = { block_id: 'SPEED_MULTIPLIER', multiplier: 1, enabled: true };
  const mult = makeEl('mult'); mult.value = '1';
  const preview = makeEl('preview');
  const btn3 = makeEl('b3'); btn3.dataset.speed = '0.5';
  const form = el('blockConfigForm');
  form.querySelector = (s) => s === 'input[data-key="multiplier"]' ? mult
    : s === '[data-speed-preview]' ? preview : null;
  form._qsa = (s) => (s === '[data-speed]' ? [btn3] : []);
  StackDnD.setStack([block], { forceHistory: true });
  StackDnD.selectedIdx = 0;
  StackDnD._showConfig(0);
  assert(form.innerHTML.indexOf('speed-presets') >= 0);
  fire(btn3, 'click', { preventDefault() {} });
  assert.strictEqual(StackDnD.stack[0].multiplier, 0.5);
  assert(preview.innerHTML.indexOf('faster') >= 0);
});

console.log('\ntest_stack_history_form: ' + passed + ' passed, ' + failed + ' failed');
process.exit(failed ? 1 : 0);
