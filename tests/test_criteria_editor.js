/* test_criteria_editor.js — criteria-editor.js (Round H: first Node harness
   for this file, RULE 8: the real shipped file, DOM + bridge stubbed). */
'use strict';
const assert = require('assert');
const { loadSingle } = require('./js_family');

function makeEl(id) {
  const set = new Set();
  const el = {
    id: id || '', tag: id || '', value: '', textContent: '', innerHTML: '',
    className: '', dataset: {}, checked: false, onclick: null,
    appendChild(c) { this.children.push(c); return c; },
    addEventListener(t, f) { (this._l = this._l || {})[t] = (this._l[t] || []).concat(f); },
    querySelectorAll() { return []; },
  };
  el.classList = { add(c) { set.add(c); }, remove(c) { set.delete(c); },
    toggle(c) { set.has(c) ? set.delete(c) : set.add(c); },
    contains(c) { return set.has(c); } };
  return el;
}
const els = {};
['criteriaDisplay', 'editCriteriaBtn', 'criteriaModal', 'criteriaEditor',
 'criteriaSaveBtn', 'criteriaCancelBtn'].forEach((id) => { els[id] = makeEl(id); });
els.criteriaModal.classList.add('hidden');
global.document = { getElementById: (id) => els[id] || null,
  createElement: (t) => makeEl(t), addEventListener() {} };
global.window = global;

const calls = [];
const rec = (name) => (...a) => { calls.push([name, ...a]); };
const b = { save_criteria: rec('save_criteria') };
global.App = { bridge: b };

loadSingle('criteria-editor.js', 'CriteriaEditor');
const CriteriaEditor = global.CriteriaEditor;

let passed = 0; let failed = 0;
function test(name, fn) {
  try { fn(); passed += 1; console.log('  ok - ' + name); }
  catch (e) { failed += 1; console.error('  FAIL - ' + name + '\n    ' + e.message); }
}
function clearCalls() { calls.length = 0; }
function assertCall(name) {
  assert(calls.some((c) => c[0] === name), 'expected ' + name + ' — got ' + JSON.stringify(calls));
}

test('loadFromJson: valid list + garbage fallback', () => {
  CriteriaEditor.loadFromJson('bad json');
  assert.deepStrictEqual(CriteriaEditor.criteria, []);
  CriteriaEditor.loadFromJson('[{"label":"L1","enabled":true,"selector":".a",' +
    '"class_name":"c","check_type":"MUST_HAVE_CLASS"},' +
    '{"label":"L2","enabled":false,"selector":".b","class_name":"","check_type":"MUST_NOT_HAVE_CLASS"}]');
  assert.strictEqual(CriteriaEditor.criteria.length, 2);
});

test('renderDisplay: enabled/disabled rows + edit wiring', () => {
  CriteriaEditor.renderDisplay();
  assert(els.criteriaDisplay.innerHTML.indexOf('filter-row enabled') >= 0);
  assert(els.criteriaDisplay.innerHTML.indexOf('filter-row disabled') >= 0);
  assert(els.criteriaDisplay.innerHTML.indexOf('check_circle') >= 0);
  assert(els.criteriaDisplay.innerHTML.indexOf('cancel') >= 0);
  assert.strictEqual(typeof els.editCriteriaBtn.onclick, 'function');
});

test('openEditor: unhide modal, render form rows + add button', () => {
  els.editCriteriaBtn.onclick();
  assert(!els.criteriaModal.classList.contains('hidden'));
  assert(els.criteriaEditor.innerHTML.indexOf('data-idx="0"') >= 0);
  assert(els.criteriaEditor.innerHTML.indexOf('data-idx="1"') >= 0);
  assert(els.criteriaEditor.innerHTML.indexOf('+ Add Criterion') >= 0);
  assert(els.criteriaEditor.innerHTML.indexOf('checked') >= 0); // L1 enabled
  assert.strictEqual(typeof els.criteriaSaveBtn.onclick, 'function');
  assert.strictEqual(typeof els.criteriaCancelBtn.onclick, 'function');
});

test('addCriterion: default row appended, form re-rendered', () => {
  CriteriaEditor.addCriterion();
  assert.strictEqual(CriteriaEditor.criteria.length, 3);
  assert.deepStrictEqual(CriteriaEditor.criteria[2], {
    label: 'New criterion', enabled: false, selector: '.avatar-wrapper',
    class_name: '', check_type: 'MUST_HAVE_CLASS' });
  assert(els.criteriaEditor.innerHTML.indexOf('data-idx="2"') >= 0);
});

test('removeCriterion: splice + re-render', () => {
  CriteriaEditor.removeCriterion(0);
  assert.strictEqual(CriteriaEditor.criteria.length, 2);
  assert.strictEqual(CriteriaEditor.criteria[0].label, 'L2');
  assert(!els.criteriaEditor.innerHTML.includes('data-idx="2"'));
});

test('_collectFromForm: form values write back into criteria', () => {
  els.criteriaEditor.querySelectorAll = (sel) => (sel === '[data-idx]' ? [
    { dataset: { idx: '0', field: 'enabled' }, checked: true },
    { dataset: { idx: '0', field: 'label' }, value: 'L2-edit' },
    { dataset: { idx: '0', field: 'selector' }, value: '.new' },
    { dataset: { idx: '0', field: 'class_name' }, value: 'cn' },
    { dataset: { idx: '0', field: 'check_type' }, value: 'MUST_NOT_HAVE_CLASS' },
    { dataset: { idx: '9', field: 'label' }, value: 'ghost' }, // no such idx
  ] : []);
  CriteriaEditor._collectFromForm();
  assert.strictEqual(CriteriaEditor.criteria[0].enabled, true);
  assert.strictEqual(CriteriaEditor.criteria[0].label, 'L2-edit');
  assert.strictEqual(CriteriaEditor.criteria[0].selector, '.new');
  assert.strictEqual(CriteriaEditor.criteria[0].class_name, 'cn');
  assert.strictEqual(CriteriaEditor.criteria[0].check_type, 'MUST_NOT_HAVE_CLASS');
  assert.strictEqual(CriteriaEditor.criteria.length, 2); // ghost ignored
});

test('save: collect + persist JSON + re-render + hide modal', () => {
  clearCalls();
  els.criteriaSaveBtn.onclick();
  assertCall('save_criteria');
  const payload = JSON.parse(calls.find((c) => c[0] === 'save_criteria')[1]);
  assert.strictEqual(payload[0].label, 'L2-edit');
  assert(els.criteriaDisplay.innerHTML.indexOf('L2-edit') >= 0);
  assert(els.criteriaModal.classList.contains('hidden'));
});

test('cancel: hides the modal only', () => {
  els.criteriaModal.classList.remove('hidden');
  els.criteriaCancelBtn.onclick();
  assert(els.criteriaModal.classList.contains('hidden'));
});

console.log('\ntest_criteria_editor: ' + passed + ' passed, ' + failed + ' failed');
process.exit(failed ? 1 : 0);
