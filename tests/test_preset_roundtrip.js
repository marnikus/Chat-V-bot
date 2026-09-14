/* save -> restart -> import round trip, with NO desktop bridge (K3, issue 2).

   The ticket asks for exactly this journey: save a layout to a file, restart
   the app, load the file back, and get the same layout. It used to break in
   two places:

     * export refused outright without the bridge ("Export requires the
       desktop bridge to choose a folder"), so there was no file to reload;
     * a file from a build with a different window set passed the import
       preview and was then rejected by _persistDocument on the way to disk.

   "Restart" is modelled the way it actually matters: the document is
   serialised to text, every module is re-instantiated from source in a fresh
   global, and the text is re-read with no bridge, no localStorage carryover
   and no in-memory state from the first run.

   Executes the REAL shipped modules (sash-core, sash-grid, preset-validate,
   preset-reconcile, window-presets) in node, per AGENT_RULES RULE 6.

   Run:  node tests/test_preset_roundtrip.js
*/
'use strict';
const fs = require('fs');
const vm = require('vm');
const path = require('path');

let passed = 0, failed = 0;
function t(name, fn) {
  try { fn(); passed++; }
  catch (e) { failed++; console.error('FAIL ' + name + '\n   ' + (e && e.stack || e)); }
}
function eq(a, b, msg) {
  const x = JSON.stringify(a), y = JSON.stringify(b);
  if (x !== y) throw new Error((msg || 'not equal') + '\n   got  ' + x + '\n   want ' + y);
}
function ok(v, msg) { if (!v) throw new Error(msg || 'expected truthy'); }

const root = path.join(__dirname, '..');
const read = (p) => fs.readFileSync(path.join(root, p), 'utf8');

/* ── one complete app session, isolated from every other ──────────── */
function boot(options) {
  const opts = options || {};
  const downloads = [];
  const messages = [];
  const store = {};

  const el = () => ({
    id: '', children: [], style: {}, dataset: {}, className: '',
    textContent: '', disabled: false, href: '', download: '',
    classList: { add() {}, remove() {}, contains() { return false; },
                 toggle() {} },
    appendChild(c) { this.children.push(c); return c; },
    append() {}, replaceChildren(...c) { this.children = c; },
    addEventListener() {}, removeEventListener() {},
    getBoundingClientRect() { return { left: 0, top: 0, width: 1200, height: 700 }; },
    querySelector() { return null; }, querySelectorAll() { return []; },
    click() { downloads.push({ name: this.download, href: this.href }); },
    remove() {}, focus() {},
  });

  const sandbox = {};
  sandbox.self = sandbox;
  sandbox.globalThis = sandbox;
  sandbox.console = console;
  sandbox.setTimeout = () => 0;
  sandbox.JSON = JSON;
  sandbox.Math = Math;
  sandbox.Number = Number;
  sandbox.Set = Set;
  sandbox.Map = Map;
  sandbox.Array = Array;
  sandbox.Object = Object;
  sandbox.String = String;
  sandbox.Date = Date;
  sandbox.Error = Error;
  sandbox.RegExp = RegExp;
  sandbox.isNaN = isNaN;
  // a "browser" with Blob/URL but no desktop bridge
  sandbox.Blob = function Blob(parts) { this.parts = parts; };
  sandbox.URL = { createObjectURL: () => 'blob:preset', revokeObjectURL() {} };
  sandbox.localStorage = {
    getItem: (k) => (k in store ? store[k] : null),
    setItem: (k, v) => { store[k] = String(v); },
    removeItem: (k) => { delete store[k]; },
  };
  sandbox.document = {
    body: el(),
    getElementById: () => el(),
    createElement: () => el(),
    addEventListener() {},
  };
  sandbox.window = sandbox;
  sandbox.BridgeReady = { ready() {} };
  sandbox.LogConsole = { log(text) { messages.push(String(text)); } };
  sandbox.Dialog = {};
  sandbox.App = { bridge: opts.bridge || null };   // NO bridge by default

  vm.createContext(sandbox);
  // `const SashGrid = {...}` does not attach to the sandbox global the way a
  // <script> tag's top-level const does, so publish each module explicitly.
  const modules = [
    ['ui/js/sash-core.js', null],
    ['ui/js/core/sash-resize-math.js', null],
    ['ui/js/core/preset-reconcile.js', null],
    ['ui/js/core/preset-validate.js', null],
    ['ui/js/sash-grid.js', 'SashGrid'],
    ['ui/js/window-presets.js', 'WindowPresets'],
  ];
  modules.forEach(([f, name]) => {
    const src = read(f) + (name ? '\nthis.' + name + ' = ' + name + ';' : '');
    vm.runInContext(src, sandbox, { filename: f });
  });

  const SashCore = sandbox.SashCore;
  const SashGrid = sandbox.SashGrid;
  const panel = (id) => {
    const n = SashCore.WINDOW_IDS.indexOf(id);
    const p = el();
    p.dataset = { win: id };
    p.getBoundingClientRect = () => ({ left: 10 + n, top: 20 + n,
                                       width: 100, height: 80 });
    return p;
  };
  SashGrid.gridEl = el();
  SashGrid.root = opts.tree || SashCore.defaultTree();
  SashGrid.closedWindows = new Set(opts.closed || []);
  SashGrid.minimizedWindows = new Set(opts.minimized || []);
  SashGrid.winEls = Object.fromEntries(
    SashCore.WINDOW_IDS.map((id) => [id, panel(id)]));
  SashGrid.render = () => {};
  SashGrid._save = () => {};
  SashGrid._saveWindowStates = () => {};
  SashGrid._applyStates = () => {};

  sandbox.WindowPresets.init();
  return { sandbox, SashCore, SashGrid, presets: sandbox.WindowPresets,
           downloads, messages, store };
}

/* ── the journey the ticket describes ─────────────────────────────── */

t('a layout saved to a file comes back identical after a restart', () => {
  // session 1: arrange, save
  const first = boot();
  const arranged = first.SashCore.moveWindow(
    first.SashGrid.root, 'log',
    { kind: 'edge', target: 'composer', dir: 'row', newFirst: true });
  first.SashGrid.root = arranged;
  const saved = JSON.stringify(
    first.SashGrid.createPortablePreset('Research desk'));

  // session 2: a brand new app, default layout, no bridge, no shared state
  const second = boot();
  ok(second.SashCore.serialize(second.SashGrid.root) !==
     second.SashCore.serialize(arranged), 'fresh session must start different');

  const result = second.SashGrid.validatePortablePreset(saved);
  ok(result.ok, 'the saved file must import: ' + result.error);
  ok(second.SashGrid.applyPortablePreset(saved), 'apply must succeed');
  eq(second.SashCore.serialize(second.SashGrid.root),
     second.SashCore.serialize(arranged),
     'the restored tree must be the one that was saved');
});

t('window open/closed/minimized states survive the round trip', () => {
  const first = boot({ closed: ['stats'], minimized: ['log'] });
  const saved = JSON.stringify(first.SashGrid.createPortablePreset('States'));

  const second = boot();
  ok(second.SashGrid.applyPortablePreset(saved), 'apply must succeed');
  ok(second.SashGrid.closedWindows.has('stats'), 'closed state lost');
  ok(second.SashGrid.minimizedWindows.has('log'), 'minimized state lost');
});

t('the round trip is stable when repeated', () => {
  const first = boot();
  const once = JSON.stringify(first.SashGrid.createPortablePreset('Stable'));
  const second = boot();
  second.SashGrid.applyPortablePreset(once);
  const twice = JSON.stringify(second.SashGrid.createPortablePreset('Stable'));
  eq(JSON.parse(twice).grid.tree, JSON.parse(once).grid.tree,
     'a re-export must describe the same tree');
});

/* ── export without a desktop bridge ──────────────────────────────── */

t('export without a bridge produces a file instead of an error', () => {
  const s = boot();
  const doc = s.SashGrid.createPortablePreset('Desk');
  s.presets._persistDocument(doc);           // saves locally, no bridge
  s.presets.export('Desk');
  eq(s.downloads.length, 1, 'expected exactly one download');
  ok(/\.json$/.test(s.downloads[0].name),
     'bad download name: ' + s.downloads[0].name);
});

t('the exported filename is filesystem-safe', () => {
  const s = boot();
  eq(s.presets._exportFileName('Research desk'),
     'Research-desk.window-preset.json');
  eq(s.presets._exportFileName('a/b\\c:d*?"<>|'), 'a-b-c-d.window-preset.json');
  eq(s.presets._exportFileName(''), 'preset.window-preset.json');
  eq(s.presets._exportFileName('  '), 'preset.window-preset.json');
  ok(s.presets._exportFileName('x'.repeat(200)).length < 100, 'must be capped');
});

t('the native picker is still used when the bridge is present', () => {
  const calls = [];
  const s = boot({ bridge: {
    export_window_preset(name, done) { calls.push(name);
      done(JSON.stringify({ ok: true, path: '/tmp/Desk.json' })); },
  } });
  s.presets.export('Desk');
  eq(calls, ['Desk'], 'the bridge must be preferred when available');
  eq(s.downloads.length, 0, 'must not also download');
});

/* ── the late-rejection bug ───────────────────────────────────────── */

t('an accepted import is not rejected on the way to disk', () => {
  // a file from a build that had a window this one does not
  const first = boot();
  const doc = first.SashGrid.createPortablePreset('Foreign');
  const victim = doc.grid.tree.children[0].children[0].children[0];
  const retired = victim.id;
  victim.id = 'retired-window';
  doc.windows.find((w) => w.id === retired).id = 'retired-window';

  const second = boot();
  // the preview accepts it...
  const preview = second.SashGrid.validatePortablePreset(doc);
  ok(preview.ok, 'preview rejected the file: ' + preview.error);
  // ...so saving it must accept it too
  second.presets._persistDocument(doc, true);
  const complaint = second.messages.concat(
    Object.values(second.store)).join(' ');
  ok(!/not saved/.test(complaint),
     'the file was accepted at preview then refused at save: ' + complaint);
  const stored = JSON.parse(second.store['chatbot.windowPresets.v1'] || '[]');
  ok(stored.length === 1, 'the preset must actually be stored');
});

t('a structurally broken file is still refused at save', () => {
  const s = boot();
  const doc = s.SashGrid.createPortablePreset('Broken');
  doc.format = 'not-a-preset';
  s.presets._persistDocument(doc);
  ok(!JSON.parse(s.store['chatbot.windowPresets.v1'] || '[]').length,
     'garbage must not be stored');
});

console.log('preset roundtrip: ' + passed + ' passed, ' + failed + ' failed');
if (failed) process.exit(1);
console.log('OK');
