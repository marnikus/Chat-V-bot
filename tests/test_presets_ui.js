/* test_presets_ui.js — presets-ui.js coverage lift (Round H, H-A6; the
   real shipped file + the real core/ui-helpers.js and core/dialog.js,
   App/StackDnD/Composer/bridge + DOM stubbed). */
'use strict';
const assert = require('assert');
const { loadSingle } = require('./js_family');

function makeEl(id) {
  const set = new Set();
  let _html = '';
  const el = {
    id: id || '', tag: id || '', value: '', textContent: '',
    className: '', title: '', placeholder: '', offsetWidth: 340,
    children: [], style: {}, dataset: {}, onclick: null, onkeydown: null,
    appendChild(c) { this.children.push(c); return c; },
    addEventListener(t, f) { (this._l = this._l || {})[t] = (this._l[t] || []).concat(f); },
    removeEventListener() {},
    focus() {},
    querySelector(sel) {
      if (sel.startsWith('.')) {
        const cls = sel.slice(1);
        return this.children.find((c) => (c.className || '').split(' ').includes(cls)) || null;
      }
      return null;
    },
    querySelectorAll() { return []; },
    getBoundingClientRect() { return { left: 10, top: 40, bottom: 60, right: 90 }; },
    closest(sel) { return sel === '#' + this.id ? this : null; },
  };
  Object.defineProperty(el, 'innerHTML', {
    get() { return _html; },
    set(v) { _html = String(v); if (v === '') el.children.length = 0; },
  });
  el.classList = { add(c) { set.add(c); }, remove(c) { set.delete(c); },
    toggle(c, force) {
      const want = force === undefined ? !set.has(c) : !!force;
      if (want) set.add(c); else set.delete(c); return want;
    }, contains(c) { return set.has(c); } };
  return el;
}
const els = {};
['presetChips', 'presetPicker', 'templateChips', 'templatePicker',
 'customBlockChips', 'loadStackBtn', 'loadTemplateBtn',
 'importPreviewModal', 'importPreviewTitle', 'importPreviewMeta',
 'importPreviewWarnings', 'importPreviewBlocks', 'importPreviewMerge',
 'importPreviewReplace', 'importPreviewAdd', 'importPreviewCancel',
 'nameModal', 'nameModalTitle', 'nameModalInput', 'nameModalOk', 'nameModalCancel',
 'confirmModal', 'confirmModalYes', 'confirmModalNo',
 'confirmModalTitle', 'confirmModalText'].forEach((id) => { els[id] = makeEl(id); });
els.presetPicker.classList.add('hidden');
els.templatePicker.classList.add('hidden');
global.document = {
  _click: null,
  getElementById: (id) => els[id] || null,
  createElement: (t) => makeEl(t),
  addEventListener(t, f) { if (t === 'click') this._click = f; },
  removeEventListener() {},
};
global.window = global;
global.innerWidth = 1200;

const calls = [];
const rec = (name) => (...a) => { calls.push([name, ...a]); };
const logs = [];
global.LogConsole = { log: (m, l) => logs.push([m, l]), clear() {} };
global.StackDnD = { stack: [{ block_id: 'CLICK_SEND' }], pushHistory: rec('StackDnD.pushHistory'),
  setStack: rec('StackDnD.setStack'), addBlockConfig: rec('StackDnD.addBlockConfig') };
global.Composer = { setMessage: rec('Composer.setMessage') };
const cb = (key, name) => (...a) => { calls.push([name, ...a.slice(0, -1)]); els._cb[key] = a[a.length - 1]; };
els._cb = {};
const b = { load_stack_preset: cb('loadStack', 'load_stack_preset'),
  delete_stack_preset: rec('delete_stack_preset'),
  load_template_preset: cb('loadTpl', 'load_template_preset'),
  delete_template_preset: rec('delete_template_preset'),
  list_stack_presets: cb('listStack', 'list_stack_presets'),
  list_template_presets: cb('listTpl', 'list_template_presets'),
  list_custom_blocks: cb('listCb', 'list_custom_blocks'),
  export_stack: cb('exportStack', 'export_stack'),
  export_stack_preset: cb('exportPreset', 'export_stack_preset'),
  export_custom_block: cb('exportBlock', 'export_custom_block'),
  import_file: cb('importFile', 'import_file'),
  apply_imported: cb('applyImported', 'apply_imported'),
  delete_custom_block: rec('delete_custom_block') };
global.App = { bridge: b };

// real shared helpers + dialogs (their own coverage comes from this load)
loadSingle('core/ui-helpers.js');
loadSingle('core/dialog.js');
loadSingle('presets-ui.js', 'PresetsUI');
const PresetsUI = global.PresetsUI;

let passed = 0; let failed = 0;
function test(name, fn) {
  try { fn(); passed += 1; console.log('  ok - ' + name); }
  catch (e) { failed += 1; console.error('  FAIL - ' + name + '\n    ' + e.message); }
}
function clearCalls() { calls.length = 0; logs.length = 0; }
function assertCall(name) {
  assert(calls.some((c) => c[0] === name), 'expected ' + name + ' — got ' + JSON.stringify(calls));
}
const fakeBtns = {};
function fakeButtons(cls, n) {
  const out = [];
  for (let i = 0; i < (n || 2); i += 1) { const btn = makeEl(cls); btn.dataset.name = 'P' + i; out.push(btn); }
  fakeBtns[cls] = out;
  els.presetPicker.querySelectorAll = (sel) => (fakeBtns[sel.slice(1)] || []);
  return out;
}

test('helpers: esc / _date / escText', () => {
  assert.strictEqual(PresetsUI.esc('<b>&"'), '&lt;b&gt;&amp;&quot;');
  assert.strictEqual(PresetsUI._date('2026-01-02T03:04:05'), new Date('2026-01-02T03:04:05').toLocaleString());
  assert.strictEqual(PresetsUI._date(null), '');
  const n = PresetsUI.escText('<x>', 'span');
  assert.strictEqual(n.tag, 'span');
  assert.strictEqual(n.textContent, '<x>');
});

test('stack chips: render, empty state, load, delete', () => {
  clearCalls();
  PresetsUI.setStackPresets('bad json');
  assert(els.presetChips.innerHTML.indexOf('none yet') >= 0);
  PresetsUI.setStackPresets(JSON.stringify([{ name: 'A', blocks: 3 }, { name: 'B', blocks: 1 }]));
  assert.strictEqual(els.presetChips.children.length, 2);
  assert(els.presetChips.children[0].children[0].textContent.indexOf('A') >= 0); // chip-title span
  els.presetChips.children[0]._l.click[0](); // onLoad → loadStack
  assertCall('load_stack_preset');
  els._cb.loadStack('{"ok":1}'.length ? JSON.stringify([{ block_id: 'X' }]) : '[]');
  assertCall('StackDnD.pushHistory'); assertCall('StackDnD.setStack');
  assert(logs.some((l) => l[0].indexOf('restored') >= 0));
  els.presetChips.children[1].querySelector('.chip-x')._l.click[0]({ stopPropagation() {} });
  assert(els.confirmModal.classList.contains('hidden') === false);
  els.confirmModalYes.onclick(); // confirm → delete
  assertCall('delete_stack_preset');
});

test('loadStack guards: no bridge warns, null payload ignored', () => {
  clearCalls();
  const saved = global.App.bridge;
  global.App.bridge = null;
  PresetsUI.loadStack('A');
  assert(logs.some((l) => l[1] === 'warn'));
  global.App.bridge = b;
  b.load_stack_preset('A', (p) => {});
  els._cb.loadStack('null');
  assert(!calls.some((c) => c[0] === 'StackDnD.setStack'));
});

test('stack picker: rows, load/export/delete wiring, empty state', () => {
  clearCalls();
  PresetsUI.setStackPresets(JSON.stringify([{ name: 'A', blocks: 2, updated_at: '2026-01-02T03:04:05' }]));
  const load = fakeButtons('pp-load', 1);
  const exp = fakeButtons('pp-export', 1);
  const del = fakeButtons('pp-del', 1);
  PresetsUI.toggleStackPicker(els.loadStackBtn);
  assert(els.presetPicker.innerHTML.indexOf('A') >= 0);
  assert(els.presetPicker.innerHTML.indexOf('2 blk') >= 0);
  assert(!els.presetPicker.classList.contains('hidden'));
  assert.strictEqual(els.presetPicker.style.top, '64px');
  load[0]._l.click[0]();
  assert(els.presetPicker.classList.contains('hidden'));
  assertCall('load_stack_preset');
  exp[0]._l.click[0]({ stopPropagation() {} });
  assertCall('export_stack_preset');
  del[0]._l.click[0]({ stopPropagation() {} });
  els.confirmModalYes.onclick(); // confirm dialog → delete
  assertCall('delete_stack_preset');
  PresetsUI.setStackPresets('[]');
  PresetsUI.toggleStackPicker(els.loadStackBtn);
  assert(els.presetPicker.innerHTML.indexOf('No saved presets yet') >= 0);
});

test('template chips + picker + load into composer', () => {
  clearCalls();
  PresetsUI.setTemplatePresets('[{"name":"T1","len":12}]');
  assert.strictEqual(els.templateChips.children.length, 1);
  els.templateChips.children[0]._l.click[0]();
  assertCall('load_template_preset');
  els._cb.loadTpl('hello body');
  assert(calls.some((c) => c[0] === 'Composer.setMessage' && c[1] === 'hello body'));
  els.templateChips.children[0].querySelector('.chip-x')._l.click[0]({ stopPropagation() {} });
  els.confirmModalYes.onclick();
  assertCall('delete_template_preset');
  PresetsUI.setTemplatePresets('[]');
  PresetsUI.toggleTemplatePicker(els.loadTemplateBtn);
  assert(els.templatePicker.innerHTML.indexOf('No saved templates yet') >= 0);
});

test('custom blocks: set/copy, json, chips, add, delete', () => {
  clearCalls();
  const src = [{ name: 'CB', block: { block_id: 'CUSTOM_FIND', selector: '.a' } }];
  PresetsUI.setCustomBlocks(src);
  src[0].block.selector = '.mutated';
  assert.strictEqual(PresetsUI.customBlocks[0].block.selector, '.a'); // deep-copied
  assert.strictEqual(els.customBlockChips.children.length, 1);
  els.customBlockChips.children[0]._l.click[0]();
  assertCall('StackDnD.addBlockConfig');
  els.customBlockChips.children[0].querySelector('.chip-x')._l.click[0]({ stopPropagation() {} });
  els.confirmModalYes.onclick();
  assertCall('delete_custom_block');
  PresetsUI.setCustomBlocksJson('[{"name":"C2","block":{}}]');
  assert.strictEqual(PresetsUI.customBlocks.length, 1);
  PresetsUI.setCustomBlocksJson('nope');
  assert.strictEqual(PresetsUI.customBlocks.length, 0);
});

test('refreshAll pulls every list', () => {
  clearCalls();
  PresetsUI.refreshAll();
  assertCall('list_stack_presets'); assertCall('list_template_presets');
  assertCall('list_custom_blocks');
  els._cb.listStack('[{"name":"S","blocks":1}]');
  els._cb.listTpl('[]');
  els._cb.listCb('[]');
  assert.strictEqual(PresetsUI.stackPresets.length, 1);
});

test('export: guards + ok/canceled/error results', () => {
  clearCalls();
  const saved = global.App.bridge;
  global.App.bridge = null;
  PresetsUI.exportCurrentStack();
  assert(logs.some((l) => l[1] === 'warn'));
  global.App.bridge = b;
  global.StackDnD.stack = [];
  PresetsUI.exportCurrentStack();
  assert(logs.filter((l) => l[1] === 'warn').length === 2);
  global.StackDnD.stack = [{ block_id: 'X' }];
  PresetsUI.exportCurrentStack();
  els._cb.exportStack(JSON.stringify({ ok: true, path: '/tmp/x.json' }));
  assert(logs.some((l) => l[0].indexOf('/tmp/x.json') >= 0));
  PresetsUI.exportPreset('P');
  els._cb.exportPreset(JSON.stringify({ canceled: true }));
  assert(logs.some((l) => l[0].indexOf('cancelled') >= 0));
  PresetsUI.exportBlock('B');
  els._cb.exportBlock(JSON.stringify({ error: 'boom' }));
  assert(logs.some((l) => l[0].indexOf('boom') >= 0));
  els._cb.exportBlock('not json');
  assert(logs.some((l) => l[1] === 'error'));
  global.App.bridge = saved;
});

test('import preview: canceled / error / ok (stack)', () => {
  clearCalls();
  PresetsUI.importStack();
  assertCall('import_file');
  els._cb.importFile(JSON.stringify({ canceled: true }));
  assert(logs.some((l) => l[0].indexOf('cancelled') >= 0));
  els._cb.importFile(JSON.stringify({ error: 'no file' }));
  assert(logs.some((l) => l[1] === 'error'));
  els._cb.importFile(JSON.stringify({ ok: true, kind: 'stack', name: 'IMP',
    exported_at: '2026-01-01', app_version: '1.0',
    stack: [{ block_id: 'CLICK_SEND', selector: '.s', match_text: 'm', enabled: false },
            { block_id: 'TYPE_MESSAGE', text: 'long text'.repeat(10) }],
    custom_blocks: [{ name: 'CB' }], warnings: ['w1'] }));
  assert(!els.importPreviewModal.classList.contains('hidden'));
  assert.strictEqual(els.importPreviewTitle.textContent, 'Import stack “IMP”');
  assert(els.importPreviewMeta.textContent.indexOf('2 step(s)') >= 0);
  assert.strictEqual(els.importPreviewBlocks.children.length, 2);
  const row1meta = els.importPreviewBlocks.children[0].children[2].textContent;
  assert(row1meta.indexOf('.s') >= 0);
  assert(row1meta.indexOf('disabled') >= 0);
  assert(els.importPreviewBlocks.children[0].children[1].textContent === 'CLICK_SEND');
  const row2meta = els.importPreviewBlocks.children[1].children[2].textContent;
  assert.strictEqual(row2meta.length, 60); // long text is truncated in the preview
  assert(!els.importPreviewWarnings.classList.contains('hidden'));
  assert(!els.importPreviewMerge.classList.contains('hidden'));
  assert(els.importPreviewAdd.classList.contains('hidden'));
});

test('import preview: block kind shows Add only', () => {
  els._cb.importFile && PresetsUI.importBlock();
  els._cb.importFile(JSON.stringify({ ok: true, kind: 'block', name: 'BLK',
    block: { block_id: 'CUSTOM_FIND', custom_name: 'My block' } }));
  assert(els.importPreviewAdd.classList.contains('hidden') === false);
  assert(els.importPreviewMerge.classList.contains('hidden'));
  // the block preview row shows the block's name (preview.name)
  assert.strictEqual(els.importPreviewBlocks.children[0].children[1].textContent, 'BLK');
});

test('import: cancel + Escape close', () => {
  clearCalls();
  els.importPreviewCancel.onclick();
  assert(els.importPreviewModal.classList.contains('hidden'));
  assert(logs.some((l) => l[1] === 'warn'));
  // capture keydown registrations, re-open, close via Escape
  global.document.addEventListener = (t, f) => { if (t === 'keydown') global.document._key = f; };
  els._cb.importFile(JSON.stringify({ ok: true, kind: 'stack', name: 'S2', stack: [] }));
  assert(PresetsUI._importKeyHandler);
  global.document._key({ key: 'Escape' });
  assert(els.importPreviewModal.classList.contains('hidden'));
  assert.strictEqual(PresetsUI._importKeyHandler, null);
});

test('applyImported: stack merge → history + setStack + note', () => {
  clearCalls();
  els._cb.importFile(JSON.stringify({ ok: true, kind: 'stack', name: 'S3',
    stack: [{ block_id: 'A' }, { block_id: 'B' }] }));
  els.importPreviewMerge.onclick();
  assertCall('StackDnD.pushHistory');
  assertCall('apply_imported');
  els._cb.applyImported(JSON.stringify({ ok: true, stack: [{ block_id: 'A' }, { block_id: 'B' }],
    blocks_added: 1, blocks_replaced: 0, preset_saved: 'S3 copy' }));
  assertCall('StackDnD.setStack');
  assert(logs.some((l) => l[0].indexOf('S3 copy') >= 0));
});

test('applyImported: block add + failure path', () => {
  clearCalls();
  els._cb.importFile(JSON.stringify({ ok: true, kind: 'block', name: 'BL2',
    block: { block_id: 'CUSTOM_FIND' } }));
  els.importPreviewAdd.onclick();
  els._cb.applyImported(JSON.stringify({ ok: true, name: 'BL2' }));
  assert(logs.some((l) => l[0].indexOf('BL2') >= 0 && l[1] === 'success'));
  els._cb.importFile(JSON.stringify({ ok: true, kind: 'stack', name: 'S4', stack: [{}] }));
  els.importPreviewReplace.onclick();
  els._cb.applyImported(JSON.stringify({ ok: false, error: 'locked' }));
  assert(logs.some((l) => l[0].indexOf('locked') >= 0));
});

test('promptName delegates to Dialog (empty refused, ok, Escape)', () => {
  clearCalls();
  let got = null;
  PresetsUI.promptName('Save stack as preset', 'e.g. X', 'Save', (n) => { got = n; });
  els.nameModalOk.onclick(); // empty → refused
  assert.strictEqual(got, null);
  els.nameModalInput.value = '  My Name ';
  els.nameModalOk.onclick();
  assert.strictEqual(got, 'My Name');
  PresetsUI.promptName('t', 'p', 'Save', () => {});
  els.nameModalInput.onkeydown({ key: 'Escape' });
  assert(els.nameModal.classList.contains('hidden'));
});

test('confirmDelete delegates to Dialog (yes / no / Enter / Escape)', () => {
  clearCalls();
  let yes = 0;
  PresetsUI.confirmDelete('preset', 'A', () => { yes += 1; });
  assert.strictEqual(els.confirmModalTitle.textContent, 'Delete preset?');
  assert(els.confirmModalText.textContent.indexOf('“A”') >= 0);
  els.confirmModalYes.onclick();
  assert.strictEqual(yes, 1);
  PresetsUI.confirmDelete('preset', 'B', () => { yes += 1; });
  els.confirmModalNo.onclick();
  assert.strictEqual(yes, 1);
  // capture the dialog's keydown handler, then fire Enter and Escape
  global.document.addEventListener = (t, f) => { if (t === 'keydown') global.document._key = f; };
  PresetsUI.confirmDelete('preset', 'C', () => { yes += 1; });
  global.document._key({ key: 'Enter', preventDefault() {} });
  assert.strictEqual(yes, 2);
  PresetsUI.confirmDelete('preset', 'D', () => { yes += 1; });
  global.document._key({ key: 'Escape', preventDefault() {} });
  assert.strictEqual(yes, 2);
});

test('outside click hides pickers (anchor click keeps them)', () => {
  els.presetPicker.classList.add('hidden'); // start closed (prior test left it open)
  PresetsUI.setStackPresets('[{"name":"A","blocks":1}]');
  fakeButtons('pp-load');
  PresetsUI.toggleStackPicker(els.loadStackBtn);
  assert(!els.presetPicker.classList.contains('hidden'));
  global.document._click({ target: els.presetPicker }); // inside picker
  assert(!els.presetPicker.classList.contains('hidden'));
  global.document._click({ target: makeEl('other') });
  assert(els.presetPicker.classList.contains('hidden'));
});

console.log('\ntest_presets_ui: ' + passed + ' passed, ' + failed + ' failed');
process.exit(failed ? 1 : 0);
