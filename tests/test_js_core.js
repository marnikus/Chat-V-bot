/* Tests for ui/js/core/ — the shared frontend modules extracted in the
   2026-09-09 refactor.

   Per AGENT_RULES RULE 8 these execute the REAL shipped modules
   (ui/js/core/bridge-ready.js, dialog.js, ui-helpers.js) against a DOM
   stub, and assert the compatibility contracts the panels rely on:

     · UIHelpers.esc() neutralises markup in user text
     · UIHelpers.chip() is the ONE chip: title + meta + ×, the delete
       click never triggers the load click
     · UIHelpers.sortArrow() renders ▲▼ / ▲ / ▼
     · Dialog.confirm()/promptName() drive the real modal ids
     · BridgeReady queues boots until the channel exists, then runs
       them exactly once, and keeps App.bridge assigned for app.js

   Run:  node tests/test_js_core.js
*/
'use strict';

const fs = require('fs');
const path = require('path');

const readUi = (f) =>
  fs.readFileSync(path.join(__dirname, '..', 'ui', f), 'utf8');

// ── minimal DOM stub ─────────────────────────────────────────────
function mkEl(tag) {
  const listeners = {};
  return {
    tagName: String(tag).toUpperCase(),
    className: '',
    _text: '',
    children: [],
    parentNode: null,
    style: {},
    dataset: {},
    title: '',
    get textContent() {
      return this._text;
    },
    set textContent(v) { this._text = String(v); },
    classList: {
      _set: new Set(),
      add(c) { this._set.add(c); },
      remove(c) { this._set.delete(c); },
      toggle(c, on) {
        if (on === undefined) on = !this._set.has(c);
        on ? this._set.add(c) : this._set.delete(c);
      },
      contains(c) { return this._set.has(c); },
    },
    setAttribute(k, v) { (this._attrs = this._attrs || {})[k] = v; },
    appendChild(c) { this.children.push(c); c.parentNode = this; return c; },
    focus() {},
    addEventListener(ev, fn) { (listeners[ev] = listeners[ev] || []).push(fn); },
    removeEventListener(ev, fn) {
      listeners[ev] = (listeners[ev] || []).filter((f) => f !== fn);
    },
    dispatch(ev, e) { (listeners[ev] || []).forEach((fn) => fn(e)); },
    click() { this.dispatch('click', { stopPropagation() {} }); },
  };
}

const modalIds = ['nameModal', 'nameModalInput', 'nameModalOk',
                  'nameModalTitle', 'nameModalCancel',
                  'confirmModal', 'confirmModalYes', 'confirmModalNo',
                  'confirmModalTitle', 'confirmModalText'];
const byId = {};
modalIds.forEach((id) => { byId[id] = mkEl('div'); });

const domListeners = {};
global.document = {
  getElementById(id) { return byId[id] || null; },
  createElement: mkEl,
  addEventListener(ev, fn) { (domListeners[ev] = domListeners[ev] || []).push(fn); },
  removeEventListener(ev, fn) {
    domListeners[ev] = (domListeners[ev] || []).filter((f) => f !== fn);
  },
  dispatch(ev, e) { (domListeners[ev] || []).forEach((fn) => fn(e)); },
};
global.window = global;

// ── assertion kit ────────────────────────────────────────────────
let passed = 0, failed = 0;
function t(name, fn) {
  try { fn(); passed++; }
  catch (e) { failed++; console.error('FAIL ' + name + '\n   ' + (e && e.stack || e)); }
}
function eq(a, b, msg) {
  const ja = JSON.stringify(a), jb = JSON.stringify(b);
  if (ja !== jb) throw new Error((msg || 'eq') + '\n  got:  ' + ja + '\n  want: ' + jb);
}
function ok(cond, msg) { if (!cond) throw new Error(msg || 'ok'); }

const load = (file, name) =>
  new Function('window', 'document', readUi(file) + '\nreturn ' + name + ';')(
    global.window, global.document);

// ═════════════════════════════════════════════════════════════════
// UIHelpers (loaded first — no dependencies)
// ═════════════════════════════════════════════════════════════════
const UIHelpers = load('js/core/ui-helpers.js', 'UIHelpers');

t('esc neutralises the five dangerous characters', () => {
  eq(UIHelpers.esc('<img src=x onerror=alert(1)>'),
     '&lt;img src=x onerror=alert(1)&gt;');
  eq(UIHelpers.esc('a & "b" \'c\''), 'a &amp; &quot;b&quot; &#39;c&#39;');
  eq(UIHelpers.esc(null), '');
  eq(UIHelpers.esc(undefined), '');
  eq(UIHelpers.esc(42), '42');
});

t('chip builds the standard removable chip', () => {
  let loaded = 0, deleted = 0;
  const chip = UIHelpers.chip({
    title: '🔗 chat', meta: 'meta text', tooltip: 'tip', selected: true,
    onLoad: () => loaded++,
    onDelete: () => deleted++,
  });
  eq(chip.className, 'chip chip-selected');
  eq(chip.title, 'tip');
  eq(chip.children.length, 3);
  eq(chip.children[0].className, 'chip-title');
  eq(chip.children[0].textContent, '🔗 chat');
  eq(chip.children[1].className, 'chip-meta');
  eq(chip.children[1].textContent, 'meta text');
  eq(chip.children[2].className, 'chip-x');
  eq(chip.children[2].textContent, '×');
  chip.click();
  eq(loaded, 1, 'chip click loads');
  chip.children[2].click();
  eq(deleted, 1, '× click deletes');
});

t('chip delete stops propagation and never fires the load handler', () => {
  let loaded = 0;
  let stopped = false;
  const chip = UIHelpers.chip({ title: 'x', onLoad: () => loaded++,
                                onDelete: () => {} });
  chip.children[chip.children.length - 1].dispatch('click', {
    stopPropagation() { stopped = true; },
  });
  ok(stopped, 'the × handler must stop propagation');
  eq(loaded, 0, 'the load handler must not fire');
});

t('chip without meta omits the meta span', () => {
  const chip = UIHelpers.chip({ title: 'x' });
  eq(chip.children.length, 2);
  eq(chip.children[1].className, 'chip-x');
});

t('sortArrow renders the three states', () => {
  eq(UIHelpers.sortArrow(false, 1), '▲▼');
  eq(UIHelpers.sortArrow(true, 1), '▲');
  eq(UIHelpers.sortArrow(true, -1), '▼');
});

// ═════════════════════════════════════════════════════════════════
// Dialog
// ═════════════════════════════════════════════════════════════════
const Dialog = load('js/core/dialog.js', 'Dialog');

t('confirm drives the real modal and Yes runs onYes', () => {
  byId.confirmModal.classList.add('hidden');
  let yes = 0;
  Dialog.confirm('Delete?', '“x” will be removed.', 'Delete', () => yes++);
  eq(byId.confirmModalTitle.textContent, 'Delete?');
  eq(byId.confirmModalText.textContent, '“x” will be removed.');
  eq(byId.confirmModalYes.textContent, 'Delete');
  ok(!byId.confirmModal.classList.contains('hidden'), 'modal shown');
  byId.confirmModalYes.onclick();
  eq(yes, 1);
  ok(byId.confirmModal.classList.contains('hidden'), 'modal hidden again');
});

t('confirm No cancels without running onYes', () => {
  let yes = 0;
  Dialog.confirm('?', '', 'OK', () => yes++);
  byId.confirmModalNo.onclick();
  eq(yes, 0);
  ok(byId.confirmModal.classList.contains('hidden'));
});

t('confirm Enter confirms, Escape cancels (keyboard)', () => {
  const keys = [];
  const origDispatch = global.document.dispatch;
  global.document.dispatch = (ev, e) => keys.push([ev, e.key]);
  // capture the capture-phase listener Dialog registered
  const keydownFns = domListeners['keydown'] || [];
  ok(keydownFns.length >= 0);
  global.document.dispatch = origDispatch;
  let yes = 0;
  Dialog.confirm('?', '', 'OK', () => yes++);
  // simulate Escape via the registered listener
  const fn = domListeners['keydown'][domListeners['keydown'].length - 1];
  fn({ key: 'Escape', preventDefault() {} });
  eq(yes, 0, 'Escape cancels');
  ok(byId.confirmModal.classList.contains('hidden'));
  let yes2 = 0;
  Dialog.confirm('?', '', 'OK', () => yes2++);
  const fn2 = domListeners['keydown'][domListeners['keydown'].length - 1];
  fn2({ key: 'Enter', preventDefault() {} });
  eq(yes2, 1, 'Enter confirms');
});

t('promptName refuses an empty name, accepts a typed one', () => {
  let got = null;
  Dialog.promptName('Preset name', 'Enter a name…', 'Save', (n) => got = n);
  eq(byId.nameModalTitle.textContent, 'Preset name');
  eq(byId.nameModalOk.textContent, 'Save');
  byId.nameModalInput.value = '   ';
  byId.nameModalOk.onclick();
  eq(got, null, 'empty is refused, modal stays open');
  ok(!byId.nameModal.classList.contains('hidden'));
  byId.nameModalInput.value = ' my preset ';
  byId.nameModalOk.onclick();
  eq(got, 'my preset', 'trimmed name accepted');
  ok(byId.nameModal.classList.contains('hidden'));
});

// ═════════════════════════════════════════════════════════════════
// BridgeReady — queue, single handshake, App.bridge compat
// ═════════════════════════════════════════════════════════════════

function freshBridgeReady(withChannel) {
  delete global.BridgeReady;
  delete global.QWebChannel;
  delete global.qt;
  delete global.App;
  const doml = {};
  global.document = {
    getElementById: (id) => byId[id] || null,
    createElement: mkEl,
    addEventListener(ev, fn) { (doml[ev] = doml[ev] || []).push(fn); },
    removeEventListener() {},
  };
  global.window = global;
  let channelCb = null;
  if (withChannel) {
    global.QWebChannel = function (transport, cb) { channelCb = cb; };
    global.qt = { webChannelTransport: {} };
  }
  new Function('window', 'document', 'QWebChannel', 'qt',
               readUi('js/core/bridge-ready.js'))(
    global.window, global.document,
    global.QWebChannel, global.qt);
  return {
    fireDomReady: () => (doml['DOMContentLoaded'] || []).forEach((fn) => fn()),
    connect: (bridge) => channelCb({ objects: { bridge } }),
  };
}

t('standalone mode (no QWebChannel): queued boots run on DOM ready', () => {
  const br = freshBridgeReady(false);
  const ran = [];
  global.BridgeReady.ready((bridge) => ran.push(bridge));
  eq(ran.length, 0, 'not before DOM ready');
  br.fireDomReady();
  eq(ran.length, 1);
  eq(ran[0], null, 'no bridge in standalone mode');
});

t('with a channel: boots run once the bridge exists, exactly once', () => {
  const br = freshBridgeReady(true);
  global.App = { bridge: null, ready: false };
  const ran = [];
  global.BridgeReady.ready((bridge) => ran.push(bridge));
  br.fireDomReady();
  eq(ran.length, 0, 'still queued while the channel connects');
  const fakeBridge = { get_tabs() {} };
  br.connect(fakeBridge);
  eq(ran.length, 1);
  eq(ran[0], fakeBridge);
  eq(global.App.bridge, fakeBridge, 'App.bridge stays assigned for app.js');
  ok(global.App.ready, 'App.ready set');
  // late subscribers run immediately with the live bridge
  let late = null;
  global.BridgeReady.ready((bridge) => late = bridge);
  eq(late, fakeBridge);
});

t('a handler that throws never blocks the rest of the queue', () => {
  const br = freshBridgeReady(false);
  const ran = [];
  global.BridgeReady.ready(() => { throw new Error('boom'); });
  global.BridgeReady.ready(() => ran.push(1));
  br.fireDomReady();
  eq(ran, [1]);
});

// ── THE 2026-09-09 INCIDENT, pinned forever ──────────────────────
// In the real page app.js declares `const App = {...}` — a classic
// script's top-level const lives in the global LEXICAL scope, not on
// window. bridge-ready.js originally assigned via `window.App` (always
// undefined in the page) → App.bridge was never set → the app ran in
// standalone mode: no session restore, no DB window, no presets — it
// looked like every database had been destroyed. This test simulates
// the REAL condition: App resolvable by name, but NOT a window
// property.
t('App is handed the bridge even when it is a lexical const (the incident)', () => {
  // App passed as a FUNCTION PARAMETER = a binding the code can resolve
  // by name, while window carries no App at all — exactly the browser.
  const doml = {};
  const win = { addEventListener() {}, removeEventListener() {} };  // no App!
  const sentinel = { bridge: null, ready: false };
  let channelCb = null;
  const QWebChannel = function (transport, cb) { channelCb = cb; };
  const qt = { webChannelTransport: {} };
  const doc = {
    getElementById: (id) => byId[id] || null,
    createElement: mkEl,
    addEventListener(ev, fn) { (doml[ev] = doml[ev] || []).push(fn); },
    removeEventListener() {},
  };
  new Function('App', 'window', 'document', 'QWebChannel', 'qt',
               readUi('js/core/bridge-ready.js'))(
    sentinel, win, doc, QWebChannel, qt);
  (doml['DOMContentLoaded'] || []).forEach((fn) => fn());
  const fakeBridge = { get_tabs() {}, db_create() {} };
  channelCb({ objects: { bridge: fakeBridge } });
  eq(sentinel.bridge, fakeBridge,
     'App.bridge MUST be assigned when App is a lexical binding');
  ok(sentinel.ready, 'App.ready set');
  eq(win.App, undefined, 'window.App stays untouched (it does not exist)');
});

// The whole page, in the exact order index.html loads it, evaluated
// against the REAL global object like a browser does (UMD modules
// attach to self/window; panels address each other through it).
t('every script in index.html evaluates cleanly in page order', () => {
  const html = readUi('index.html');
  const srcs = [];
  const re = /<script src="([^"]+)"><\/script>/g;
  let m;
  while ((m = re.exec(html))) srcs.push(m[1]);
  ok(srcs.length >= 20, 'found the script tags (' + srcs.length + ')');
  const local = srcs.filter((s) => !s.startsWith('qrc:'));
  ok(local[0].includes('core/bridge-ready.js'),
     'the handshake module loads before every panel');
  const combined = local.map((s) => readUi(s)).join('\n;\n');

  // a browser-ish global environment
  const prevWindow = global.window, prevSelf = global.self,
        prevDocument = global.document;
  const doml = {};
  global.document = {
    getElementById: (id) => byId[id] || null,
    createElement: mkEl,
    querySelectorAll: () => [],
    addEventListener(ev, fn) { (doml[ev] = doml[ev] || []).push(fn); },
    removeEventListener() {},
    documentElement: mkEl('html'),
  };
  global.window = global;
  global.self = global;
  try {
    // one shared scope, no module/exports/QWebChannel/qt in reach.
    // `const App` inside the function is a LEXICAL binding — reachable
    // by name from every later "script" in the same scope, never a
    // window property: exactly the browser condition of the incident.
    new Function('module', 'exports', 'QWebChannel', 'qt',
                 combined + '\n;globalThis.__pageApp = App;')(
      undefined, undefined, undefined, undefined);
    ok(global.BridgeReady, 'core/bridge-ready.js published BridgeReady');
    ok(global.Dialog, 'core/dialog.js published Dialog');
    ok(global.UIHelpers, 'core/ui-helpers.js published UIHelpers');
    ok(global.SashCore, 'sash-core.js published SashCore (UMD self path)');
    // nothing connected yet: the page is simply waiting for the channel
    eq(global.__pageApp.bridge, null);
    eq(global.__pageApp.ready, false);
  } finally {
    global.window = prevWindow;
    global.self = prevSelf;
    global.document = prevDocument;
    ['BridgeReady', 'Dialog', 'UIHelpers', 'SashCore', '__pageApp']
      .forEach((k) => { try { delete global[k]; } catch (e) {} });
  }
});

// ═════════════════════════════════════════════════════════════════
// wiring: index.html loads the core modules before every panel
// ═════════════════════════════════════════════════════════════════
t('index.html loads the core modules first', () => {
  const html = readUi('index.html');
  const coreAt = html.indexOf('js/core/bridge-ready.js');
  const firstPanel = html.indexOf('js/sash-core.js');
  ok(coreAt !== -1 && coreAt < firstPanel,
     'bridge-ready.js must load before the panels');
  ['js/core/dialog.js', 'js/core/ui-helpers.js'].forEach((src) =>
    ok(html.includes(src), src + ' must be loaded'));
});

console.log(`js_core: ${passed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
