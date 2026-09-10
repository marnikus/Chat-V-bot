/* Tests for the portable export/import UI in ui/js/presets-ui.js
   (+ the onExport chip option in ui/js/core/ui-helpers.js).

Per AGENT_RULES RULE 8 this executes the REAL shipped modules in a real
runtime (Node) against a tiny DOM stub — the same pattern as
tests/test_stack_dnd_migration.js. The backend is stubbed behind
App.bridge; the test pins what the UI sends and what it renders:

  * export/import results become honest log lines (ok / cancelled / error);
  * an import preview populates the modal (title, meta, warnings, block
    rows) and shows the right action buttons per file kind;
  * Merge/Replace/Add hand the PREVIEW JSON (including the raw file
    text the backend re-validates) + the current stack to the bridge,
    push history first (RULE 12), and apply the result via setStack;
  * a cancelled / failed apply touches no state.

Run:  node tests/test_preset_io_ui.js
Exits 0 + prints "OK" when every test passes.
*/
'use strict';
const fs = require('fs');
const path = require('path');

// ── minimal DOM / global stubs ───────────────────────────────────
function makeEl(id) {
  const listeners = {};
  return {
    id: id,
    _children: [],
    _listeners: listeners,
    innerHTML: '',
    textContent: '',
    value: '',
    title: '',
    style: {},
    dataset: {},
    disabled: false,
    onclick: null,
    classList: {
      _set: new Set(),
      add(...c) { c.forEach((x) => this._set.add(x)); },
      remove(...c) { c.forEach((x) => this._set.delete(x)); },
      toggle(c, on) {
        const want = (on === undefined) ? !this._set.has(c) : !!on;
        if (want) this._set.add(c); else this._set.delete(c);
        return want;
      },
      contains(c) { return this._set.has(c); },
    },
    appendChild(child) { this._children.push(child); return child; },
    addEventListener(type, fn) { (listeners[type] = listeners[type] || []).push(fn); },
    removeEventListener(type, fn) {
      listeners[type] = (listeners[type] || []).filter((f) => f !== fn);
    },
    querySelectorAll() { return []; },
    querySelector(sel) {
      return this._children.find((c) => c.className === sel.slice(1)) || null;
    },
    focus() {},
    getBoundingClientRect() { return { left: 0, bottom: 0, width: 0 }; },
  };
}

const elements = {};
global.window = global;
global.document = {
  _listeners: {},
  getElementById(id) { return elements[id] || (elements[id] = makeEl(id)); },
  createElement(tag) {
    const el = makeEl(null);
    el.tagName = tag;
    el.className = '';
    return el;
  },
  addEventListener(type, fn) {
    (this._listeners[type] = this._listeners[type] || []).push(fn);
  },
  removeEventListener(type, fn) {
    this._listeners[type] =
      (this._listeners[type] || []).filter((f) => f !== fn);
  },
};

const logs = [];
global.LogConsole = { log(msg, level) { logs.push({ msg, level }); } };
global.App = { bridge: null };
global.StackDnD = { stack: [] };

// load the REAL shipped modules
require(path.join(__dirname, '..', 'ui', 'js', 'core', 'ui-helpers.js'));
const PresetsUI = new Function(
  fs.readFileSync(path.join(__dirname, '..', 'ui', 'js', 'presets-ui.js'),
                  'utf8') + '\nreturn PresetsUI;')();

// ── tiny assertion kit ───────────────────────────────────────────
let passed = 0, failed = 0;
function t(name, fn) {
  try { fn(); passed++; }
  catch (e) { failed++; console.error('FAIL ' + name + '\n   ' + (e && e.stack || e)); }
}
function ok(cond, msg) { if (!cond) throw new Error(msg || 'ok'); }
function eq(a, b, msg) {
  const ja = JSON.stringify(a), jb = JSON.stringify(b);
  if (ja !== jb) throw new Error((msg || 'eq') + '\n  got:  ' + ja + '\n  want: ' + jb);
}
function lastLog() { return logs[logs.length - 1]; }
function reset() {
  logs.length = 0;
  Object.keys(elements).forEach((k) => delete elements[k]);
  PresetsUI.closeImportPreview();
  global.StackDnD = { stack: [] };
}
function bridgeStub(handlers) {
  const calls = [];
  const bridge = {};
  Object.keys(handlers).forEach((name) => {
    bridge[name] = (...args) => {
      calls.push({ name, args });
      handlers[name](...args);
    };
  });
  App.bridge = bridge;
  return calls;
}

// ── onFileResult: honest feedback for every export outcome ──────
t('export success logs the path', () => {
  reset();
  bridgeStub({ export_stack: (stackJson, cb) =>
    cb(JSON.stringify({ ok: true, path: '/home/u/stack.json' })) });
  PresetsUI.onFileResult(JSON.stringify({ ok: true, path: '/home/u/stack.json' }));
  eq(lastLog().level, 'success');
  ok(lastLog().msg.includes('/home/u/stack.json'), 'path in log');
});

t('export cancelled is not an error', () => {
  reset();
  bridgeStub({});
  PresetsUI.onFileResult(JSON.stringify({ ok: false, canceled: true }));
  eq(lastLog().level, 'info');
});

t('export failure logs the backend error', () => {
  reset();
  bridgeStub({});
  PresetsUI.onFileResult(JSON.stringify({ ok: false, error: 'disk full' }));
  eq(lastLog().level, 'error');
  ok(lastLog().msg.includes('disk full'));
});

t('garbage bridge result degrades to one error line, no crash', () => {
  reset();
  bridgeStub({});
  PresetsUI.onFileResult('not json');
  eq(lastLog().level, 'error');
});

// ── onImportPreview: the preview modal ──────────────────────────
const STACK_PREVIEW = {
  ok: true, kind: 'stack', name: 'My Campaign',
  format_version: 1, app_version: '1.0.0',
  exported_at: '2026-09-10T12:00:00',
  stack: [
    { block_id: 'SCROLL_PARSE', enabled: true },
    { block_id: 'CUSTOM_FIND', custom_name: 'open menu',
      selector: '#menu', match_text: '{{nick}}', enabled: true },
  ],
  custom_blocks: [{ name: 'open menu', block: { block_id: 'CUSTOM_FIND' } }],
  warnings: ['block #3 uses unknown type “GHOST” — it will be skipped on import'],
  text: '{"format":"chat-v-bot/stack-preset"}',
};
const BLOCK_PREVIEW = {
  ok: true, kind: 'block', name: 'open menu',
  format_version: 1, app_version: '1.0.0', exported_at: '2026-09-10T12:00:00',
  stack: [], custom_blocks: [],
  block: { block_id: 'CUSTOM_FIND', custom_name: 'open menu', selector: '#menu' },
  warnings: [], text: '{"format":"chat-v-bot/action-block"}',
};

t('stack preview fills the modal and shows Merge/Replace only', () => {
  reset();
  bridgeStub({});
  PresetsUI.onImportPreview(JSON.stringify(STACK_PREVIEW));
  const modal = elements['importPreviewModal'];
  ok(!modal.classList.contains('hidden'), 'modal visible');
  ok(elements['importPreviewTitle'].textContent.includes('My Campaign'));
  ok(elements['importPreviewMeta'].textContent.includes('2 step(s)'));
  ok(elements['importPreviewMeta'].textContent.includes('app 1.0.0'));
  const warn = elements['importPreviewWarnings'];
  ok(!warn.classList.contains('hidden'), 'warnings visible');
  eq(warn._children.length, 1, 'one warning row');
  eq(elements['importPreviewBlocks']._children.length, 2, 'two block rows');
  ok(elements['importPreviewMerge'].classList.contains('hidden') === false);
  ok(elements['importPreviewReplace'].classList.contains('hidden') === false);
  ok(elements['importPreviewAdd'].classList.contains('hidden') === true,
     'block import button hidden for stack files');
});

t('block preview shows only the Import Block action', () => {
  reset();
  bridgeStub({});
  PresetsUI.onImportPreview(JSON.stringify(BLOCK_PREVIEW));
  ok(!elements['importPreviewAdd'].classList.contains('hidden'));
  ok(elements['importPreviewMerge'].classList.contains('hidden'));
  ok(elements['importPreviewReplace'].classList.contains('hidden'));
  eq(elements['importPreviewBlocks']._children.length, 1);
  ok(elements['importPreviewWarnings'].classList.contains('hidden'),
     'no warnings -> warnings box hidden');
});

t('failed import shows an error line and no modal', () => {
  reset();
  bridgeStub({});
  PresetsUI.onImportPreview(JSON.stringify({ ok: false,
    error: 'the file is not valid JSON' }));
  eq(lastLog().level, 'error');
  ok(elements['importPreviewModal'].classList.contains('hidden'));
});

t('cancelled import is an info line, not an error', () => {
  reset();
  bridgeStub({});
  PresetsUI.onImportPreview(JSON.stringify({ ok: false, canceled: true }));
  eq(lastLog().level, 'info');
  ok(elements['importPreviewModal'].classList.contains('hidden'));
});

// ── applyImported: what crosses the bridge ──────────────────────
t('replace pushes history first, sends preview+stack, applies result', () => {
  reset();
  global.StackDnD = {
    stack: [{ block_id: 'PAUSE', enabled: true }],
    pushHistory(stack) { this.pushedWith = JSON.parse(JSON.stringify(stack)); },
    setStack(blocks) { this.applied = JSON.parse(JSON.stringify(blocks)); },
  };
  const calls = bridgeStub({
    apply_imported: (previewJson, mode, stackJson, cb) => {
      cb(JSON.stringify({ ok: true,
        stack: [{ block_id: 'SCROLL_PARSE' }, { block_id: 'CUSTOM_FIND' }],
        blocks_added: 1, blocks_replaced: 0 }));
    },
  });
  PresetsUI.onImportPreview(JSON.stringify(STACK_PREVIEW));
  PresetsUI.applyImported('replace');

  eq(calls.length, 1);
  eq(calls[0].name, 'apply_imported');
  eq(calls[0].args[1], 'replace', 'mode');
  const preview = JSON.parse(calls[0].args[0]);
  eq(preview.kind, 'stack');
  ok(preview.text, 'the raw file text crosses the wire (backend re-validates)');
  eq(JSON.parse(calls[0].args[2]), [{ block_id: 'PAUSE', enabled: true }],
     'current stack is sent');
  ok(global.StackDnD.pushedWith, 'history pushed BEFORE the bridge call');
  eq(global.StackDnD.applied.length, 2, 'result stack applied via setStack');
  ok(elements['importPreviewModal'].classList.contains('hidden'),
     'modal closed after applying');
  eq(lastLog().level, 'success');
  ok(lastLog().msg.includes('1 custom block(s) added')
     || lastLog().msg.includes('added'), 'counts in the success line');
});

t('merge mode is forwarded and the appended stack is applied', () => {
  reset();
  global.StackDnD = {
    stack: [{ block_id: 'PAUSE' }],
    pushHistory() {}, setStack(b) { this.applied = b; },
  };
  const calls = bridgeStub({
    apply_imported: (pj, mode, sj, cb) => {
      cb(JSON.stringify({ ok: true,
        stack: [{ block_id: 'PAUSE' }, { block_id: 'CUSTOM_FIND' }],
        blocks_added: 0, blocks_replaced: 0 }));
    },
  });
  PresetsUI.onImportPreview(JSON.stringify(STACK_PREVIEW));
  PresetsUI.applyImported('merge');
  eq(calls[0].args[1], 'merge');
  eq(global.StackDnD.applied.length, 2);
});

t('failed apply logs the error and applies nothing', () => {
  reset();
  global.StackDnD = {
    stack: [{ block_id: 'PAUSE' }],
    pushHistory() {}, setStack(b) { this.applied = b; },
  };
  bridgeStub({
    apply_imported: (pj, mode, sj, cb) =>
      cb(JSON.stringify({ ok: false, error: 're-validation failed' })),
  });
  PresetsUI.onImportPreview(JSON.stringify(STACK_PREVIEW));
  PresetsUI.applyImported('replace');
  eq(lastLog().level, 'error');
  ok(!('applied' in global.StackDnD), 'setStack must not run');
});

t('block import (mode add) never touches the stack', () => {
  reset();
  global.StackDnD = {
    stack: [{ block_id: 'PAUSE' }],
    pushHistory() { this.pushed = true; }, setStack(b) { this.applied = b; },
  };
  bridgeStub({
    apply_imported: (pj, mode, sj, cb) =>
      cb(JSON.stringify({ ok: true, name: 'open menu' })),
  });
  PresetsUI.onImportPreview(JSON.stringify(BLOCK_PREVIEW));
  PresetsUI.applyImported('add');
  ok(!('applied' in global.StackDnD), 'no setStack for block imports');
  ok(!global.StackDnD.pushed, 'no stack history entry for block imports');
  ok(lastLog().msg.includes('Custom Blocks library'));
});

t('cancel closes the modal and logs, nothing is sent', () => {
  reset();
  let sent = 0;
  bridgeStub({ apply_imported: () => { sent++; } });
  PresetsUI.onImportPreview(JSON.stringify(STACK_PREVIEW));
  elements['importPreviewCancel'].onclick();
  ok(elements['importPreviewModal'].classList.contains('hidden'));
  eq(sent, 0);
  eq(lastLog().level, 'warn');
});

// ── ui-helpers chip: the onExport option ─────────────────────────
t('chip with onExport exports on ⬇ click, not on load/delete', () => {
  const calls = [];
  const chip = window.UIHelpers.chip({
    title: '🔎 open menu',
    onLoad: () => calls.push('load'),
    onDelete: () => calls.push('delete'),
    onExport: () => calls.push('export'),
  });
  ok(chip.querySelector('.chip-export'), 'export affordance exists');
  chip.querySelector('.chip-export')._listeners.click
    .forEach((fn) => fn({ stopPropagation() {} }));
  eq(calls, ['export']);
  chip._listeners.click.forEach((fn) => fn({ stopPropagation() {} }));
  eq(calls, ['export', 'load'], 'plain chip click still loads');
});

t('chip without onExport keeps the historical shape', () => {
  const calls = [];
  const chip = window.UIHelpers.chip({
    title: 'x', onLoad: () => calls.push('load'),
    onDelete: () => calls.push('delete'),
  });
  ok(!chip.querySelector('.chip-export'), 'no export affordance');
});

// ── summary ──────────────────────────────────────────────────────
console.log(`\n${passed} passed, ${failed} failed`);
if (failed) process.exit(1);
console.log('OK');
