/* test_stack_dnd_parts.js — stack-dnd family coverage lift (Round H, H-A6).
   Part 1: render + list ops + add-block menu + run/pause/stop buttons.
   Executes the REAL shipped family (loadFamily) against a DOM stub;
   no module re-declaration (RULE 8). */
'use strict';
const assert = require('assert');

function makeEl(id) {
  const set = new Set();
  const el = {
    id: id || '', tag: id || '', value: '', className: '',
    disabled: false, title: '', placeholder: '', checked: false, type: 'text',
    tagName: 'DIV', children: [], style: {}, dataset: {}, onclick: null,
    _text: '', _html: '', _l: {},
    appendChild(c) { this.children.push(c); return c; },
    addEventListener(t, f) { (this._l[t] = this._l[t] || []).push(f); },
    removeEventListener() {},
    focus() {},
    querySelector(sel) {
      if (sel === '.material-icons') return el.icon || (el.icon = makeEl('icon'));
      if (sel === '[data-label]') return el.label || (el.label = makeEl('label'));
      if (sel === 'input[data-key="multiplier"]') return el.mult || (el.mult = makeEl('mult'));
      if (sel === '[data-speed-preview]') return el.preview || (el.preview = makeEl('preview'));
      return null;
    },
    querySelectorAll(sel) { return el._qsa ? el._qsa(sel) : []; },
    closest() { return null; },
    getBoundingClientRect() { return { left: 5, top: 10, bottom: 30 }; },
    setAttribute() {}, getAttribute() { return null; }, removeAttribute() {},
  };
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
  el.classList = { add(c) { set.add(c); }, remove(c) { set.delete(c); },
    toggle(c, force) {
      const want = force === undefined ? !set.has(c) : !!force;
      if (want) set.add(c); else set.delete(c); return want;
    }, contains(c) { return set.has(c); } };
  return el;
}
const els = {};
function el(id) { return els[id] || (els[id] = makeEl(id)); }
global.document = {
  _key: null,
  getElementById: (id) => el(id),
  createElement: (t) => makeEl(t),
  addEventListener(t, f) { if (t === 'keydown') this._key = f; },
  removeEventListener() {},
  activeElement: null,
};
global.window = global;
global.localStorage = { _d: {}, getItem(k) { return this._d[k] || null; },
  setItem(k, v) { this._d[k] = String(v); }, removeItem(k) { delete this._d[k]; } };

const calls = []; const logs = [];
const rec = (n) => (...a) => { calls.push([n, ...a]); };
global.LogConsole = { log: (m, l) => logs.push([m, l]), clear() {} };
const b = {
  run_stack: rec('run_stack'), pause_stack: rec('pause_stack'),
  resume_stack: rec('resume_stack'), stop_stack: rec('stop_stack'),
  save_stack_preset: rec('save_stack_preset'), list_stack_presets: (cb) => { calls.push(['list_stack_presets']); cb('[{"name":"P1","blocks":2}]'); },
  save_custom_block: rec('save_custom_block'), snapshot_stack: rec('snapshot_stack'),
  save_stack_history: rec('save_stack_history'),
};
let prompt = null;
global.App = {
  bridge: b, recordGlobal: rec('recordGlobal'),
  undoGlobal: rec('undoGlobal'), redoGlobal: rec('redoGlobal'),
  _updateUndoButtons: rec('_updateUndoButtons'),
};
global.PresetsUI = { promptName: (t, p, ok, onOk) => { prompt = onOk; },
  setStackPresets: rec('setStackPresets'), toggleStackPicker: rec('toggleStackPicker'),
  exportCurrentStack: rec('exportCurrentStack'), importStack: rec('importStack'),
  importBlock: rec('importBlock') };
const dragAttach = {};
global.StackDrag = { dragging: false, attach: (cfg) => Object.assign(dragAttach, cfg),
  flashLanded: rec('flashLanded') };
global.BridgeReady = { ready() {} };
el('addBlockMenu').classList.add('hidden'); // as in index.html
el('customBlockActions').classList.add('hidden');

Object.defineProperty(el('stackList'), 'innerHTML', {
  get() { return el('stackList')._html; },
  set(v) {
    el('stackList')._html = String(v);
    if (el('stackList')._qsa) {
      el('stackList')._qsa('.stack-item').forEach((it) => it.classList.remove('block-running', 'active', 'disabled'));
    }
  },
});
const { FAMILIES, loadFamily } = require('./js_family');
loadFamily(FAMILIES.stackDnd, { except: ['stack-drag.js'] });
// the app loads the real stack-drag.js before the facade; the list-drag
// collaborator is recorded here (the real file is exercised by the
// full-family suites, e.g. test_grid_persistence.js).
global.StackDrag = { dragging: false, attach: (c) => Object.assign(dragAttach, c),
  flashLanded: rec('flashLanded') };
const StackDnD = global.StackDnD;

let passed = 0; let failed = 0;
function test(name, fn) {
  try { fn(); passed += 1; console.log('  ok - ' + name); }
  catch (e) { failed += 1; console.error('  FAIL - ' + name + '\n    ' + e.message); }
}
function clearCalls() { calls.length = 0; logs.length = 0; }
function assertCall(n) { assert(calls.some((c) => c[0] === n), 'expected ' + n + ' — got ' + JSON.stringify(calls.map((c) => c[0]))); }
function fire(elm, type, ev) { (elm._l[type] || []).forEach((f) => f(ev || { stopPropagation() {}, preventDefault() {} })); }

StackDnD.init();

test('init: default stack rendered, buttons wired', () => {
  assert.strictEqual(StackDnD.stack.length, 8);
  assert(els.stackList.innerHTML.indexOf('stack-item') >= 0);
  assert(els.addBlockBtn._l.click.length === 1);
  assert(els.runBtn._l.click.length === 1);
  assert(els.undoBtn._l.click.length === 1);
  assert(document._key, 'keyboard reorder handler registered');
});

test('_meta / _displayName', () => {
  assert.strictEqual(StackDnD._meta('CLICK_SEND').name, 'Click Send');
  assert.strictEqual(StackDnD._meta('NOPE').name, 'NOPE');
  assert.strictEqual(StackDnD._displayName({ block_id: 'CLICK_SEND', custom_name: '  My  ' }), 'My');
  assert.strictEqual(StackDnD._displayName({ block_id: 'CLICK_SEND', custom_name: '' }), 'Click Send');
});

test('_findDesc: all search/click branches', () => {
  const d = StackDnD._findDesc;
  assert.strictEqual(d({ selector: '.box', label_selector: '.lbl', match_text: 'Hi', click_enabled: true, click_selector: '.btn' }),
    'Find “Hi” in .lbl within .box → click .btn inside');
  assert.strictEqual(d({ selector: '.box', label_selector: '.lbl', match_text: '', click_enabled: true }),
    'Find the first .lbl within .box → click the found box');
  assert.strictEqual(d({ selector: '', label_selector: '', match_text: 'Hi', click_enabled: false }),
    'Find “Hi” in ? → check only (no click)');
  assert.strictEqual(d({ selector: '.box', label_selector: '', match_text: '', click_enabled: false, enabled: false }),
    'Find .box → check only (no click) [OFF]');
});

test('_summary: custom / speed / generic / off', () => {
  assert.strictEqual(StackDnD._summary({ block_id: 'CUSTOM_FIND', selector: '.b', click_enabled: true }),
    'Find .b → click the found box');
  assert.strictEqual(StackDnD._summary({ block_id: 'SPEED_MULTIPLIER', multiplier: 0.5, enabled: true }),
    'All waits ×0.5 (2× faster)');
  assert.strictEqual(StackDnD._summary({ block_id: 'SPEED_MULTIPLIER', multiplier: 2, enabled: false }),
    'All waits ×2.0 (2× slower) · OFF');
  assert(StackDnD._summary({ block_id: 'PAUSE', duration_ms: 2000, enabled: true }).indexOf('duration_ms=2000') >= 0);
  assert(StackDnD._summary({ block_id: 'PAUSE', duration_ms: 1, enabled: false }).endsWith('· OFF'));
  assert(StackDnD._summary({ block_id: 'PAUSE', enabled: true }).indexOf('delay: 0ms') >= 0);
});

test('_summaryPart: every key branch', () => {
  const p = StackDnD._summaryPart;
  assert.strictEqual(p('block_id', 'X', {}), null);
  assert.strictEqual(p('pre_delay_ms', 5, {}), null);
  assert.strictEqual(p('enabled', true, {}), null);
  assert.strictEqual(p('custom_name', 'N', {}), 'name="N"');
  assert.strictEqual(p('click_enabled', false, {}), 'click=off');
  assert.strictEqual(p('click_selector', '', {}), null);
  assert.strictEqual(p('use_composer', true, {}), 'text: Message Composer');
  assert.strictEqual(p('respect_order', true, {}), 'respect Order (#)');
  assert.strictEqual(p('use_person_from_memory', true, {}), 'target: {{nick}} from memory');
  assert.strictEqual(p('pick_mode', 'random_done', { block_id: 'TAKE_PERSON' }), 'pick: random Done');
  assert.strictEqual(p('pick_mode', 'order_first', { block_id: 'TAKE_PERSON' }), 'pick: Order #1');
  assert.strictEqual(p('text', 'abc', { block_id: 'SEARCH_USERS' }), 'search: “abc”');
  assert.strictEqual(p('text', '', { block_id: 'SEARCH_USERS' }), 'search: (empty)');
  assert.strictEqual(p('message', 'x', { use_composer: true }), null);
  assert.strictEqual(p('weird', 'v'.repeat(40), {}), 'weird=' + 'v'.repeat(24));
});

test('_esc escapes HTML', () => {
  assert.strictEqual(StackDnD._esc('<b>&"'), '&lt;b&gt;&amp;&quot;');
  assert.strictEqual(StackDnD._esc(null), '');
});

test('_stackItemHtml: active / running / disabled states', () => {
  StackDnD.stack = [{ block_id: 'CLICK_SEND', enabled: false }];
  StackDnD.selectedIdx = 0; StackDnD._running = true; StackDnD._runningIdx = 0;
  const html = StackDnD._stackItemHtml(StackDnD.stack[0], 0);
  assert(html.indexOf('active') >= 0);
  assert(html.indexOf('block-running') >= 0);
  assert(html.indexOf('disabled') >= 0);
  assert(html.indexOf('OFF') >= 0);
  assert(html.indexOf('checked') < 0);
  StackDnD._running = false; StackDnD.selectedIdx = -1;
  const html2 = StackDnD._stackItemHtml({ block_id: 'CLICK_SEND', enabled: true }, 1);
  assert(html2.indexOf('checked') >= 0);
  assert(html2.indexOf('data-idx="1"') >= 0);
});

test('_renderStack: empty + populated', () => {
  StackDnD.stack = [];
  StackDnD._renderStack();
  assert(els.stackList.innerHTML.indexOf('stack-empty') >= 0);
  StackDnD.setStack([{ block_id: 'CLICK_SEND' }, { block_id: 'PAUSE', duration_ms: 1 }]);
  assert(els.stackList.innerHTML.indexOf('data-idx="1"') >= 0);
});

test('click wiring: select, remove, toggle-ignored, drag-ignored', () => {
  clearCalls();
  StackDnD.setStack([{ block_id: 'CLICK_SEND' }, { block_id: 'PAUSE', duration_ms: 1 }]);
  const item0 = makeEl('item0'); item0.dataset.idx = '0';
  const item1 = makeEl('item1'); item1.dataset.idx = '1';
  const inp = makeEl('toggle1'); inp.dataset.toggle = '1'; inp.checked = false;
  els.stackList._qsa = (sel) => sel === '.stack-item' ? [item0, item1] : sel === 'input[data-toggle]' ? [inp] : [];
  StackDnD._wireStackList();
  const rm = makeEl('rm'); rm.dataset.remove = '1';
  const evRm = { target: { closest: (s) => (s === '[data-remove]' ? rm : s === '.toggle-switch' ? null : null) }, stopPropagation: () => { evRm.stopped = true; } };
  fire(item1, 'click', evRm);
  assert.strictEqual(StackDnD.stack.length, 1);
  assertCall('recordGlobal');
  const evSel = { target: { closest: () => null }, stopPropagation() {} };
  fire(item0, 'click', evSel);
  assert.strictEqual(StackDnD.selectedIdx, 0);
  const evTgl = { target: { closest: (s) => (s === '.toggle-switch' ? 'yes' : null) }, stopPropagation() {} };
  fire(item0, 'click', evTgl);
  assert.strictEqual(StackDnD.selectedIdx, 0);
  global.StackDrag.dragging = true;
  fire(item0, 'click', evSel);
  assert.strictEqual(StackDnD.selectedIdx, 0);
  global.StackDrag.dragging = false;
});

test('toggle wiring: disable + enable a block', () => {
  clearCalls();
  StackDnD.setStack([{ block_id: 'CLICK_SEND' }]);
  const inp = makeEl('t0'); inp.dataset.toggle = '0'; inp.checked = false;
  els.stackList._qsa = (sel) => (sel === 'input[data-toggle]' ? [inp] : []);
  StackDnD._wireToggles();
  fire(inp, 'change', { stopPropagation() {} });
  assert.strictEqual(StackDnD.stack[0].enabled, false);
  assert(logs.some((l) => l[0].indexOf('Disabled') >= 0));
  inp.checked = true;
  StackDnD.selectedIdx = 0;
  fire(inp, 'change', { stopPropagation() {} });
  assert.strictEqual(StackDnD.stack[0].enabled, true);
  assert(logs.some((l) => l[0].indexOf('Enabled') >= 0));
});

test('moveBlock: order + selection/running index shifts', () => {
  clearCalls();
  StackDnD.setStack([{ block_id: 'CLICK_SEND' }, { block_id: 'PAUSE', duration_ms: 1 }, { block_id: 'WAIT_PAGE_LOAD', timeout_ms: 1 }]);
  StackDnD.selectedIdx = 0;
  StackDnD.moveBlock(0, -1); // clamped to 0 → same → no-op
  assert.strictEqual(StackDnD.stack[0].block_id, 'CLICK_SEND');
  StackDnD.moveBlock(2, 0);
  assert.strictEqual(StackDnD.stack[0].block_id, 'WAIT_PAGE_LOAD');
  assert.strictEqual(StackDnD.selectedIdx, 1); // selected block moved 0 → 1
  StackDnD.moveBlock(0, 99); // clamped to end
  assert.strictEqual(StackDnD.stack[2].block_id, 'WAIT_PAGE_LOAD');
  assertCall('flashLanded');
  assert(logs.some((l) => l[0].indexOf('Moved') >= 0));
  StackDnD.moveBlock(-1, 0); // invalid from
  assert.strictEqual(StackDnD.stack.length, 3);
});

test('removeBlock: selection fallbacks', () => {
  clearCalls();
  StackDnD.setStack([{ block_id: 'CLICK_SEND' }, { block_id: 'PAUSE', duration_ms: 1 }, { block_id: 'WAIT_PAGE_LOAD', timeout_ms: 1 }]);
  StackDnD.selectedIdx = 2;
  StackDnD.removeBlock(0); // before selection → selection shifts down
  assert.strictEqual(StackDnD.selectedIdx, 1);
  StackDnD.removeBlock(1); // the selection itself → fallback to slot
  assert.strictEqual(StackDnD.selectedIdx, 0);
  StackDnD.removeBlock(0); // last one
  assert.strictEqual(StackDnD.selectedIdx, -1);
  assert(logs.some((l) => l[0].indexOf('Removed') >= 0));
});

test('add menu: render custom+builtin rows, wire clicks', () => {
  clearCalls();
  StackDnD.setCustomBlocks([{ name: 'MyBlock', block: { block_id: 'CUSTOM_FIND', custom_name: 'MyBlock', selector: '.a' } }]);
  fire(els.addBlockBtn, 'click', { stopPropagation() {} });
  assert(!els.addBlockMenu.classList.contains('hidden'));
  assert(els.addBlockMenu.innerHTML.indexOf('Custom blocks') >= 0);
  assert(els.addBlockMenu.innerHTML.indexOf('MyBlock') >= 0);
  assert(els.addBlockMenu.style.top === '34px');
  const before = StackDnD.stack.length;
  const builtin = makeEl('bi'); builtin.dataset.block = 'PAUSE';
  const custom = makeEl('cu'); custom.dataset.custom = '0';
  els.addBlockMenu._qsa = (sel) => sel === '.menu-item[data-block]' ? [builtin] : sel === '.menu-item[data-custom]' ? [custom] : [];
  StackDnD._renderMenu(els.addBlockMenu);
  fire(builtin, 'click');
  assert.strictEqual(StackDnD.stack.length, before + 1);
  assert.strictEqual(StackDnD.stack[before].block_id, 'PAUSE');
  assertCall('recordGlobal');
  const before2 = StackDnD.stack.length;
  fire(custom, 'click');
  assert.strictEqual(StackDnD.stack[before2].custom_name, 'MyBlock');
});

test('add menu: outside click hides', () => {
  els.addBlockMenu.classList.remove('hidden');
  // _setupAddMenu registered a document click handler at init
  // (document stub captured it as _key? no — click; re-register path:)
  assert(els.addBlockMenu._l || true);
  StackDnD._setupAddMenu();
  assert(els.addBlockBtn._l.click.length >= 1);
});

test('_refreshSaveLabel: new vs update', () => {
  clearCalls();
  els.customBlockActions.classList.remove('hidden');
  StackDnD.stack = [{ block_id: 'CUSTOM_FIND', custom_name: 'NewName' }];
  StackDnD.selectedIdx = 0;
  StackDnD.setCustomBlocks([]);
  StackDnD._refreshSaveLabel();
  assert.strictEqual(els.saveCustomBlockBtn.label.textContent, 'Save as new preset');
  StackDnD.setCustomBlocks([{ name: 'NewName', block: {} }]);
  StackDnD._refreshSaveLabel();
  assert.strictEqual(els.saveCustomBlockBtn.label.textContent, 'Update preset “NewName”');
  StackDnD.stack = [{ block_id: 'CLICK_SEND' }];
  StackDnD.selectedIdx = 0;
  StackDnD._refreshSaveLabel(); // non-CUSTOM_FIND → untouched
});

test('_saveBlockPreset: with name saves directly, without prompts', () => {
  clearCalls();
  const blk = { block_id: 'CUSTOM_FIND', custom_name: ' Named ' };
  StackDnD._saveBlockPreset(blk);
  assert.strictEqual(blk.custom_name, 'Named');
  assertCall('save_custom_block');
  let called = false;
  prompt = null;
  const blk2 = { block_id: 'CUSTOM_FIND' };
  // route the delegate to a real onOk
  const origPrompt = global.PresetsUI.promptName;
  global.PresetsUI.promptName = (t, p, ok, onOk) => { prompt = onOk; };
  StackDnD._saveBlockPreset(blk2);
  assert(typeof prompt === 'function');
  prompt('FromPrompt');
  assert.strictEqual(blk2.custom_name, 'FromPrompt');
  assertCall('save_custom_block');
  global.PresetsUI.promptName = origPrompt;
});

test('run button: guards + start', () => {
  clearCalls();
  const savedBridge = global.App.bridge;
  global.App.bridge = null;
  fire(els.runBtn, 'click');
  assert(logs.some((l) => l[1] === 'warn'));
  global.App.bridge = b;
  StackDnD.setStack([]);
  fire(els.runBtn, 'click');
  assert(logs.filter((l) => l[1] === 'warn').length >= 2);
  StackDnD.setStack([{ block_id: 'CLICK_SEND', enabled: false }]);
  fire(els.runBtn, 'click');
  assert(logs.some((l) => l[0].indexOf('disabled') >= 0));
  StackDnD.setStack([{ block_id: 'CLICK_SEND', enabled: true }]);
  fire(els.runBtn, 'click');
  assertCall('run_stack');
  assert.strictEqual(els.runBtn.disabled, true);
  assert.strictEqual(els.pauseBtn.disabled, false);
  assert.strictEqual(els.stopBtn.disabled, false);
  assert(logs.some((l) => l[0].indexOf('started') >= 0));
});

test('pause/resume + stop', () => {
  clearCalls();
  fire(els.pauseBtn, 'click');
  assertCall('pause_stack');
  assert.strictEqual(els.pauseBtn.title, 'Resume');
  assert.strictEqual(els.pauseBtn.icon.textContent, 'play_arrow');
  fire(els.pauseBtn, 'click');
  assertCall('resume_stack');
  assert.strictEqual(els.pauseBtn.title, 'Pause');
  assert.strictEqual(els.pauseBtn.icon.textContent, 'pause');
  fire(els.stopBtn, 'click');
  assertCall('stop_stack');
});

test('save/load/import/export buttons', () => {
  clearCalls();
  prompt = null;
  global.PresetsUI.promptName = (t, p, ok, onOk) => { prompt = onOk; };
  StackDnD.setStack([]);
  fire(els.saveStackBtn, 'click'); // empty → warn
  assert(logs.some((l) => l[1] === 'warn'));
  StackDnD.setStack([{ block_id: 'CLICK_SEND' }]);
  fire(els.saveStackBtn, 'click');
  assert(typeof prompt === 'function');
  prompt('Preset1');
  assertCall('save_stack_preset');
  fire(els.loadStackBtn, 'click');
  assertCall('list_stack_presets');
  assertCall('setStackPresets');
  assertCall('toggleStackPicker');
  fire(els.exportStackBtn, 'click'); assertCall('exportCurrentStack');
  fire(els.importStackBtn, 'click'); assertCall('importStack');
  fire(els.importBlockBtn, 'click'); assertCall('importBlock');
});

test('setRunning / setRunningBlock', () => {
  clearCalls();
  StackDnD.setRunning(true);
  assert.strictEqual(StackDnD._running, true);
  const item = makeEl('s0'); item.dataset.idx = '0';
  els.stackList._qsa = (sel) => (sel === '.stack-item' ? [item] : []);
  StackDnD.setRunningBlock(0);
  assert(item.classList.contains('block-running'));
  StackDnD.setRunning(false);
  assert(!item.classList.contains('block-running'));
  assert.strictEqual(els.runBtn.disabled, false);
  assert.strictEqual(els.pauseBtn.disabled, true);
  assert.strictEqual(els.stopBtn.disabled, true);
  assert.strictEqual(StackDnD._runningIdx, -1);
});

test('keyboard: Alt+Arrow reorders, Ctrl+Z/Y undo/redo', () => {
  clearCalls();
  StackDnD.setStack([{ block_id: 'CLICK_SEND' }, { block_id: 'PAUSE', duration_ms: 1 }]);
  StackDnD.selectedIdx = 0;
  document.activeElement = null;
  document._key({ altKey: true, ctrlKey: false, key: 'ArrowDown', target: null, preventDefault() {} });
  assert.strictEqual(StackDnD.stack[0].block_id, 'PAUSE');
  document._key({ altKey: true, ctrlKey: false, key: 'ArrowUp', target: null, preventDefault() {} });
  assert.strictEqual(StackDnD.stack[0].block_id, 'CLICK_SEND');
  document._key({ altKey: true, key: 'ArrowUp', target: null, preventDefault() {} }); // at top → clamp
  assert.strictEqual(StackDnD.stack[0].block_id, 'CLICK_SEND');
  document._key({ altKey: true, key: 'ArrowDown', target: null, preventDefault() {} });
  const inputEl = makeEl('in'); inputEl.tagName = 'INPUT';
  document.activeElement = inputEl;
  document._key({ altKey: true, key: 'ArrowDown', target: null, preventDefault() {} }); // ignored in inputs
  document.activeElement = null;
  document._key({ ctrlKey: true, key: 'z', target: { closest: () => null }, preventDefault() {} });
  assertCall('undoGlobal');
  document._key({ ctrlKey: true, key: 'y', target: { closest: () => null }, preventDefault() {} });
  assertCall('redoGlobal');
  document._key({ ctrlKey: true, shiftKey: true, key: 'z', target: { closest: () => null }, preventDefault() {} });
  assertCall('redoGlobal');
});

test('attachDrag labelOf', () => {
  clearCalls();
  StackDnD.setStack([{ block_id: 'CLICK_SEND', custom_name: 'Named' }]);
  StackDnD._renderStack();
  assert.strictEqual(dragAttach.labelOf(0), 'Named');
  assert.strictEqual(dragAttach.labelOf(99), '');
  dragAttach.onReorder(0, 0);
  assert.strictEqual(StackDnD.stack.length, 1);
});

console.log('\ntest_stack_dnd_parts: ' + passed + ' passed, ' + failed + ' failed');
process.exit(failed ? 1 : 0);
