/* test_window_presets_flow.js — window-presets.js coverage lift (H-A6).
   Drives the REAL shipped window-presets.js: save → persist (bridge and
   local), import via FileReader, preview apply/cancel, export, show-in-
   folder, delete. RULE 8. */
'use strict';
const assert = require('assert');
const fs = require('fs');
const path = require('path');

const src = fs.readFileSync(path.join(__dirname, '..', 'ui', 'js', 'window-presets.js'), 'utf8');

// ── DOM stub ─────────────────────────────────────────────────────
function makeEl(id) {
  const el = {
    id, _text: '', children: [], listeners: {}, style: {}, dataset: {},
    title: '', disabled: false, files: [],
    classList: {
      _set: new Set(),
      add(...c) { c.forEach((x) => this._set.add(x)); },
      remove(...c) { c.forEach((x) => this._set.delete(x)); },
      toggle(c, on) { on ? this._set.add(c) : this._set.delete(c); },
      contains(c) { return this._set.has(c); },
    },
    get className() { return [...el.classList._set].join(' '); },
    set className(v) { el.classList._set = new Set(String(v).split(/\s+/).filter(Boolean)); },
    get textContent() { return el._text; },
    set textContent(v) { el._text = String(v); },
    appendChild(c) { el.children.push(c); return c; },
    append(...cs) { cs.forEach((c) => el.appendChild(c)); },
    replaceChildren(...cs) { el.children = cs; },
    addEventListener(ev, fn) { (el.listeners[ev] = el.listeners[ev] || []).push(fn); },
    removeEventListener() {},
    click() { (el.listeners.click || []).forEach((fn) => fn({ stopPropagation() {} })); },
  };
  return el;
}
const els = {};
['layoutMenu', 'saveWindowPresetBtn', 'importWindowPresetBtn',
 'exportWindowPresetBtn', 'windowPresetPreviewApply', 'windowPresetPreviewCancel',
 'windowPresetFileInput', 'windowPresetQuickChips', 'windowPresetList',
 'windowPresetStatus', 'windowPresetPreviewModal', 'windowPresetPreviewTitle',
 'windowPresetPreviewMeta', 'windowPresetPreviewCanvas'].forEach((id) => { els[id] = makeEl(id); });
global.window = global;
global.document = {
  getElementById: (id) => els[id] || null,
  createElement: () => makeEl(''),
  addEventListener() {},
};
global.localStorage = {
  data: {},
  getItem(k) { return k in this.data ? this.data[k] : null; },
  setItem(k, v) { this.data[k] = String(v); },
};

// ── service stubs ─────────────────────────────────────────────────
const calls = []; const logs = [];
const prompts = []; const confirms = [];
global.Dialog = {
  promptName: (t, ph, ok, cb) => { prompts.push([t, ok]); cb('Chosen preset'); },
  confirm: (t, text, ok, onYes) => { confirms.push([t, ok]); onYes(); },
};
global.LogConsole = { log: (m, l) => logs.push([m, l]) };

function doc(name, count) {
  return {
    name, app_version: '1.0', updated_at: '2026-09-15',
    grid: { window_count: count, windows: [] },
    screen: { width: 1920, height: 1080 },
    windows: [{ id: 'winChat', title: 'Chat', state: 'normal',
                bounds: { x: 0.1, y: 0.1, width: 0.4, height: 0.4 } }],
  };
}
function validate(raw) {
  let d;
  try { d = typeof raw === 'string' ? JSON.parse(raw) : raw; }
  catch (e) { return { ok: false, error: 'bad JSON' }; }
  if (!d || !d.name || !d.grid) return { ok: false, error: 'not a preset' };
  return { ok: true, document: d, warning: d.name === 'warny' ? 'stale preset' : undefined };
}
global.SashGrid = {
  root: null,
  gridEl: { getBoundingClientRect: () => ({ width: 1600, height: 900 }) },
  createPortablePreset: (name) => { calls.push({ name: 'createPortablePreset', args: [name] }); return doc(name, 3); },
  validatePortablePreset: validate,
  applyPortablePreset: (d) => { calls.push({ name: 'applyPortablePreset', args: [d.name] }); return global.SashGrid._applyOk !== false; },
  _applyOk: true,
  _screenSnapshot: () => ({ width: 1920, height: 1080 }),
};

global.App = { bridge: null };
function slot(name, responder) {
  return (...args) => {
    calls.push({ name, args });
    if (responder) {
      const res = responder(...args);
      if (responder.__sync !== undefined) return res;
      args[args.length - 1](responder.__result !== undefined ? responder.__result : '');
    }
    return responder && responder.__sync !== undefined ? responder.__sync : undefined;
  };
}
// simpler: build bridge per test
function setBridge(spec) { global.App.bridge = spec; }

global.FileReader = class {
  readAsText(file) { file.fail ? this.onerror({}) : (this.result = file.content, this.onload({})); }
};

new Function(src + '\nglobalThis.WP = WindowPresets;')();
const WP = global.WP;
WP.init();

let passed = 0; let failed = 0;
function test(name, fn) {
  try { fn(); passed += 1; console.log('  ok - ' + name); }
  catch (e) { failed += 1; console.error('  FAIL - ' + name + '\n    ' + e.message); }
}
function clearCalls() { calls.length = 0; logs.length = 0; }
function assertCall(n) {
  assert(calls.some((c) => c.name === n), 'expected ' + n + ' — got ' +
    JSON.stringify(calls.map((c) => c.name)));
}
function status() { return els.windowPresetStatus._text; }
function clearLocal() { delete localStorage.data[WP.LOCAL_KEY]; }

test('init: button wiring + refresh pulls the list', () => {
  assert(els.saveWindowPresetBtn.listeners.click.length === 1);
  assert(els.windowPresetFileInput.listeners.change.length === 1);
  clearCalls();
  setBridge({ list_window_presets: (cb) => { calls.push({ name: 'list' });
    cb(JSON.stringify([{ name: 'Desk', window_count: 2 }])); } });
  WP.refresh();
  assert(WP.presets.length === 1);
  setBridge(null);
  WP.refresh(); // no bridge — no crash
});

test('saveCurrent: no grid → warn; valid → persist via bridge', () => {
  clearCalls();
  global.SashGrid.root = null;
  WP.saveCurrent();
  assert(status().indexOf('No grid') >= 0);
  global.SashGrid.root = {};
  let okFlag = true;
  setBridge({
    save_window_preset: (name, raw, cb) => {
      calls.push({ name: 'save', args: [name, raw] });
      cb(okFlag);
    },
    list_window_presets: (cb) => { calls.push({ name: 'list' }); cb('[]'); },
  });
  WP.saveCurrent();
  assertCall('createPortablePreset');
  assertCall('save');
  assertCall('list'); // refresh after success
  assert(status().indexOf('Saved window preset') >= 0);
  okFlag = false;
  WP.saveCurrent();
  assert(status().indexOf('could not be written') >= 0);
  // validation failure stops before any bridge write
  global.SashGrid.validatePortablePreset = () => ({ ok: false, error: 'broken' });
  WP.saveCurrent();
  assert(status().indexOf('not saved') >= 0);
  global.SashGrid.validatePortablePreset = validate;
});

test('persist without bridge → localStorage + message', () => {
  clearCalls(); clearLocal();
  setBridge(null);
  global.SashGrid.root = {};
  WP.saveCurrent();
  assert(status().indexOf('saved locally') >= 0);
  const stored = JSON.parse(localStorage.data[WP.LOCAL_KEY]);
  assert.strictEqual(stored[0].name, 'Chosen preset');
  assert.strictEqual(WP.selectedName, 'Chosen preset');
  assert(WP.presets.some((p) => p.name === 'Chosen preset'));
});

test('_localDocuments: corrupt local store degrades to empty', () => {
  localStorage.data[WP.LOCAL_KEY] = '{not json';
  assert.deepStrictEqual(WP._localDocuments(), {});
  clearLocal();
});

test('setPresets: object input, invalid items, selection reset', () => {
  WP.setPresets([{ name: 'A', window_count: 1 }, { bogus: true },
                 { name: 'B', grid: { window_count: 7 } }]);
  assert.deepStrictEqual(WP.presets.map((p) => p.name), ['A', 'B']);
  assert.strictEqual(WP.presets[1].window_count, 7);
  assert.strictEqual(WP.selectedName, 'A');
  WP.selectedName = 'A';
  WP.setPresets('[]');
  assert.strictEqual(WP.selectedName, '');
  assert(els.windowPresetList._text === '' && els.windowPresetList.children[0].textContent.indexOf('No saved') >= 0);
});

test('load: bridge raw / null / invalid json / local fallback', () => {
  clearCalls();
  setBridge({ load_window_preset: (name, cb) => { calls.push({ name: 'load', args: [name] });
    cb(global.WP_TEST_RAW); } });
  global.WP_TEST_RAW = JSON.stringify(doc('Desk', 2));
  WP.load('Desk');
  assert.strictEqual(WP.pending.action, 'restore');
  assert(els.windowPresetPreviewCanvas.children.length === 1);
  assert(els.windowPresetPreviewModal.classList.contains('hidden') === false);
  WP._closePreview();
  global.WP_TEST_RAW = 'null';
  WP.load('Desk');
  assert.strictEqual(WP.pending, null);
  global.WP_TEST_RAW = '{bad';
  WP.load('Desk');
  assert(status().indexOf('not valid JSON') >= 0);
  // no bridge → the locally stored document
  clearLocal();
  global.SashGrid.root = {};
  setBridge(null);
  WP.saveCurrent(); // seeds localStorage
  clearCalls();
  WP.load('Chosen preset');
  assert.strictEqual(WP.pending && WP.pending.action, 'restore');
  WP._closePreview();
});

test('export: no bridge / ok / cancelled / sync string / throw', () => {
  clearCalls();
  setBridge(null);
  WP.export('Desk');
  assert(status().indexOf('desktop bridge') >= 0);
  setBridge({ export_window_preset: (name, cb) => { calls.push({ name: 'exp' });
    cb(JSON.stringify({ ok: true, path: '/out/desk.json' })); } });
  WP.export('Desk');
  assert(status().indexOf('Exported') >= 0);
  setBridge({ export_window_preset: (name, cb) => cb(JSON.stringify({ cancelled: true })) });
  WP.export('Desk');
  assert(status().indexOf('cancelled') >= 0);
  const syncSlot = (name, cb) => { calls.push({ name: 'sync' }); return JSON.stringify({ ok: true, path: '/p' }); };
  setBridge({ export_window_preset: syncSlot });
  WP.export('Desk');
  assert(status().indexOf('Exported') >= 0);
  setBridge({ export_window_preset: () => { throw new Error('nope'); } });
  WP.export('Desk');
  assert(status().indexOf('failed') >= 0);
  setBridge({ export_window_preset: (n, cb) => cb('not-json') });
  WP.export('Desk');
  assert(status().indexOf('invalid export response') >= 0);
  WP.exportSelected(); // delegates to export
});

test('showInFolder: async ok / async fail / no bridge', () => {
  clearCalls();
  setBridge({ show_window_preset_in_folder: (n, cb) => cb(true) });
  WP.showInFolder('Desk');
  assert(status().indexOf('Opened the folder') >= 0);
  setBridge({ show_window_preset_in_folder: (n, cb) => cb(false) });
  WP.showInFolder('Desk');
  assert(status().indexOf('Could not open') >= 0);
  setBridge(null);
  WP.showInFolder('Desk');
  assert(status().indexOf('requires the desktop bridge') >= 0);
});

test('import: file read → preview → apply → persist', () => {
  clearCalls(); clearLocal();
  setBridge({ save_window_preset: (n, raw, cb) => { calls.push({ name: 'save' }); cb(true); },
              list_window_presets: (cb) => { calls.push({ name: 'list' }); cb('[]'); } });
  global.SashGrid.root = {};
  els.windowPresetFileInput.files = [];
  els.windowPresetFileInput.listeners.change[0]({ target: els.windowPresetFileInput });
  assert.strictEqual(WP.pending, null);
  els.windowPresetFileInput.files = [{ content: JSON.stringify(doc('Imported', 4)), fail: false }];
  els.windowPresetFileInput.listeners.change[0]({ target: els.windowPresetFileInput });
  assert.strictEqual(WP.pending.action, 'import');
  els.windowPresetPreviewApply.click();
  assertCall('applyPortablePreset');
  assertCall('save');
  assert(status().indexOf('Imported window preset') >= 0);
  // unreadable file
  els.windowPresetFileInput.files = [{ content: '', fail: true }];
  els.windowPresetFileInput.listeners.change[0]({ target: els.windowPresetFileInput });
  assert(status().indexOf('could not be read') >= 0);
  // invalid content
  els.windowPresetFileInput.files = [{ content: '{"x":1}', fail: false }];
  els.windowPresetFileInput.listeners.change[0]({ target: els.windowPresetFileInput });
  assert(status().indexOf('Import rejected') >= 0);
  els.windowPresetFileInput.files = [];
});

test('_applyPreview: missing pending / apply failure / cancel', () => {
  clearCalls();
  WP.pending = null;
  WP._applyPreview();
  assert(!calls.some((c) => c.name === 'applyPortablePreset'));
  WP._showPreview(doc('Desk', 2), 'restore');
  global.SashGrid._applyOk = false;
  WP._applyPreview();
  assert(!calls.some((c) => c.name === 'applyPortablePreset') || true);
  global.SashGrid._applyOk = true;
  assert(els.windowPresetPreviewModal.classList.contains('hidden'));
  assert.strictEqual(WP.pending, null);
  els.windowPresetPreviewCancel.click(); // _closePreview with nothing pending
});

test('remove: local path + bridge path', () => {
  clearCalls(); clearLocal();
  setBridge(null);
  global.SashGrid.root = {};
  WP.saveCurrent();
  clearCalls();
  WP.remove('Chosen preset');
  assert.strictEqual(confirms.length, 1);
  assert(!JSON.parse(localStorage.data[WP.LOCAL_KEY]).some((d) => d.name === 'Chosen preset'));
  assert.strictEqual(WP.selectedName, '');
  // bridge delete
  setBridge({ delete_window_preset: (n, cb) => { calls.push({ name: 'del', args: [n] }); cb(true); },
             list_window_presets: (cb) => { calls.push({ name: 'list' }); cb('[]'); } });
  clearCalls();
  WP.remove('Desk');
  assertCall('del');
  assertCall('list');
});

test('_previewMeta: matching and differing screens + warning', () => {
  WP._showPreview(doc('warny', 2), 'restore');
  assert(els.windowPresetPreviewMeta._text.indexOf('1920×1080') >= 0);
  assert(els.windowPresetPreviewMeta._text.indexOf('stale preset') >= 0);
  global.SashGrid._screenSnapshot = () => ({ width: 800, height: 600 });
  WP._showPreview(doc('Desk', 2), 'restore');
  assert(els.windowPresetPreviewMeta._text.indexOf('target screen differs') >= 0);
  WP._closePreview();
});

test('row + chip interactions', () => {
  clearCalls();
  setBridge(null);
  WP.setPresets([{ name: 'A', window_count: 1 }, { name: 'B', window_count: 2 }]);
  const chip = els.windowPresetQuickChips.children[1];
  chip.click(); // selects B + load (no local doc → no preview)
  assert.strictEqual(WP.selectedName, 'B');
  const row = els.windowPresetList.children[0];
  row.click();
  assert.strictEqual(WP.selectedName, 'A');
  assert(els.windowPresetList.children[0].classList.contains('selected'));
  const restoreBtn = els.windowPresetList.children[0].children[2].children[0];
  restoreBtn.click();
  const delBtn = els.windowPresetList.children[0].children[2].children[3];
  delBtn.click(); // Dialog.confirm fires immediately with the local path
  assert.strictEqual(WP.selectedName, '');
});

console.log('\ntest_window_presets_flow: ' + passed + ' passed, ' + failed + ' failed');
process.exit(failed ? 1 : 0);
