/* Real WindowPresets rendering contract with a small DOM implementation. */
'use strict';
const fs = require('fs');
const vm = require('vm');

let passed = 0, failed = 0;
function test(name, fn) { try { fn(); passed++; } catch (e) { failed++; console.error('FAIL', name, e.message); } }
function assert(value, message) { if (!value) throw new Error(message || 'assert'); }

class Element {
  constructor(id = '') {
    this.id = id; this.children = []; this.listeners = {}; this.dataset = {};
    this.className = ''; this.classList = { add: (c) => { this.className += ' ' + c; },
      remove: () => {}, contains: () => false, toggle: () => {} };
    this.style = {}; this.disabled = false; this.textContent = '';
  }
  appendChild(child) { this.children.push(child); return child; }
  append(...children) { children.forEach((child) => this.appendChild(child)); }
  replaceChildren(...children) { this.children = children; }
  addEventListener(type, fn) { this.listeners[type] = fn; }
  getBoundingClientRect() { return { left: 0, right: 100, bottom: 30 }; }
}

const ids = ['layoutMenu', 'saveWindowPresetBtn', 'importWindowPresetBtn',
  'exportWindowPresetBtn', 'windowPresetPreviewApply',
  'windowPresetPreviewCancel', 'windowPresetFileInput', 'windowPresetPanel',
  'windowPresetQuickChips', 'windowPresetList', 'windowPresetStatus',
  'windowPresetPreviewModal', 'windowPresetPreviewTitle',
  'windowPresetPreviewMeta', 'windowPresetPreviewCanvas'];
const elements = Object.fromEntries(ids.map((id) => [id, new Element(id)]));

global.window = global;
global.document = {
  getElementById(id) { return elements[id] || null; },
  createElement() { return new Element(); },
  addEventListener() {},
};
global.localStorage = { data: {}, getItem(k) { return this.data[k] || null; }, setItem(k, v) { this.data[k] = String(v); } };
global.Dialog = {};
global.LogConsole = { log() {} };
global.App = { bridge: null };
vm.runInThisContext(fs.readFileSync('ui/js/window-presets.js', 'utf8') +
  '\nglobalThis.__WindowPresets = WindowPresets;');
const presets = global.__WindowPresets;
presets.init();

test('saved presets render as visible quick buttons and panel rows', () => {
  presets.setPresets(JSON.stringify([
    { name: 'Desk', window_count: 12, updated_at: 'now' },
    { name: 'Writing', window_count: 12, updated_at: 'later' },
  ]));
  assert(elements.windowPresetQuickChips.children.length === 2, 'quick chips');
  assert(elements.windowPresetList.children.length === 2, 'panel rows');
  assert(elements.windowPresetList.children[0].children[0].textContent === 'Desk', 'row name');
  assert(elements.windowPresetList.children[0].children[2].children.length === 4, 'row actions');
  assert(!elements.exportWindowPresetBtn.disabled, 'export enabled');
});

test('empty list renders an explicit empty state', () => {
  presets.setPresets('[]');
  assert(elements.windowPresetQuickChips.children.length === 1, 'quick empty state');
  assert(elements.windowPresetList.children.length === 1, 'panel empty state');
  assert(elements.exportWindowPresetBtn.disabled, 'export disabled');
});

test('valid restore data creates a visual preview without applying it', () => {
  global.SashGrid = {
    validatePortablePreset(value) {
      if (value === 'bad') return { ok: false, error: 'bad JSON' };
      return { ok: true, document: value, warning: '' };
    },
    _screenSnapshot() { return { width: 1400, height: 900 }; },
    gridEl: null,
  };
  const document = {
    name: 'Desk', grid: { window_count: 1 },
    screen: { width: 1400, height: 900 },
    windows: [{ id: 'stats', title: 'Stats', state: 'open',
      bounds: { x: 0, y: 0, width: 1, height: 1 } }],
  };
  presets._showPreview(document, 'restore');
  assert(presets.pending && presets.pending.action === 'restore', 'pending preview');
  assert(elements.layoutMenu.className.includes('hidden'), 'grid menu closes for preview');
  assert(elements.windowPresetPreviewCanvas.children.length === 1, 'preview tile');
  assert(elements.windowPresetPreviewCanvas.children[0].textContent === 'Stats', 'tile label');
});

test('invalid imported file reports an error and does not open a preview', () => {
  global.FileReader = class {
    readAsText() { this.result = 'bad'; this.onload(); }
  };
  presets._readFile({ target: { files: [{}], value: 'chosen.json' } });
  assert(elements.windowPresetStatus.textContent.includes('Import rejected'), 'import error');
  assert(presets.pending.action === 'restore', 'pending preview unchanged');
});

test('export uses the native folder response and show-in-folder bridge action', () => {
  global.App.bridge = {
    export_window_preset(name, callback) {
      callback(JSON.stringify({ ok: true, name, path: '/exports/window-preset-Desk.json' }));
    },
    show_window_preset_in_folder(name, callback) {
      callback(name === 'Desk');
    },
  };
  presets.export('Desk');
  assert(elements.windowPresetStatus.textContent.includes('/exports/'), 'export path');
  presets.showInFolder('Desk');
  assert(elements.windowPresetStatus.textContent.includes('Opened the folder'), 'show folder');
  global.App.bridge.export_window_preset = (_name, callback) =>
    callback(JSON.stringify({ ok: false, cancelled: true }));
  presets.export('Desk');
  assert(elements.windowPresetStatus.textContent.includes('cancelled'), 'cancelled export');
});

if (failed) process.exit(1);
console.log(`window_preset_ui: ${passed} passed, 0 failed`);
