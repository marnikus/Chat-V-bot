/* test_history_store.js — history-store.js coverage lift (Round H, H-A6).
   Drives the REAL shipped history-store.js (plus the real HistoryModel,
   HistoryView, Dialog) the way the QWebChannel bridge does: a slot is
   called with a request id, the answer arrives on a signal. RULE 8. */
'use strict';
const assert = require('assert');
const fs = require('fs');
const path = require('path');

const readUi = (f) => fs.readFileSync(path.join(__dirname, '..', 'ui', f), 'utf8');
const html = readUi('index.html');

// ── DOM stub (same contract as test_history_panels_boot.js) ─────
function mkEl(tag) {
  const listeners = {};
  const el = {
    tagName: String(tag || 'div').toUpperCase(),
    _text: '', children: [], parentNode: null, style: {}, dataset: {},
    attrs: {}, title: '', value: '', checked: false,
    scrollTop: 0, scrollHeight: 1000, clientHeight: 500,
    listeners,
    classList: {
      _set: new Set(),
      add(...c) { c.forEach((x) => this._set.add(x)); },
      remove(...c) { c.forEach((x) => this._set.delete(x)); },
      toggle(c, on) { on ? this._set.add(c) : this._set.delete(c); },
      contains(c) { return this._set.has(c); },
    },
    get className() { return [...el.classList._set].join(' '); },
    set className(v) { el.classList._set = new Set(String(v).split(/\s+/).filter(Boolean)); },
    get textContent() { return el._text + el.children.map((c) => c.textContent).join(''); },
    set textContent(v) { el._text = String(v); el.children = []; },
    set innerHTML(v) { throw new Error('markup assignment is forbidden'); },
    get innerHTML() { return ''; },
    appendChild(c) { el.children.push(c); c.parentNode = el; return c; },
    append(...cs) { cs.forEach((c) => el.appendChild(typeof c === 'string' ? mkText(c) : c)); },
    replaceChildren(...cs) { el.children = []; el.append(...cs); },
    removeChild(c) {
      const i = el.children.indexOf(c);
      if (i >= 0) el.children.splice(i, 1);
      c.parentNode = null;
      return c;
    },
    remove() { if (el.parentNode) el.parentNode.removeChild(el); },
    setAttribute(k, v) { el.attrs[k] = String(v); },
    getAttribute(k) { return k in el.attrs ? el.attrs[k] : null; },
    addEventListener(ev, fn) { (listeners[ev] = listeners[ev] || []).push(fn); },
    removeEventListener() {},
    getBoundingClientRect() { return { top: 0, left: 0, width: 10, height: 10 }; },
    scrollIntoView() { el._scrolled = true; },
    focus() {}, blur() {},
    closest(sel) {
      let node = el;
      while (node) { if (matches(node, sel)) return node; node = node.parentNode; }
      return null;
    },
    querySelector(sel) { return findAll(el, sel)[0] || null; },
    querySelectorAll(sel) { return findAll(el, sel); },
    fire(ev, extra) {
      (listeners[ev] || []).forEach((fn) => fn(Object.assign(
        { target: el, button: 0, preventDefault() {}, stopPropagation() {} }, extra || {})));
    },
  };
  return el;
}
function mkText(s) { const n = mkEl('#text'); n._text = s; return n; }
function matches(node, sel) {
  const s = String(sel).trim();
  if (s.startsWith('.')) {
    const parts = s.slice(1).split('[');
    if (!node.classList.contains(parts[0])) return false;
    if (parts[1]) {
      const name = /([\w-]+)/.exec(parts[1])[1].replace(/-(\w)/g, (m, c) => c.toUpperCase());
      return node.dataset[name] !== undefined;
    }
    return true;
  }
  if (s.startsWith('[')) {
    const m = /\[data-([\w-]+)/.exec(s);
    if (m) {
      const key = m[1].replace(/-(\w)/g, (x, c) => c.toUpperCase());
      return node.dataset[key] !== undefined;
    }
    return false;
  }
  return node.tagName === s.toUpperCase();
}
function walk(el, out) {
  out = out || [];
  el.children.forEach((c) => { out.push(c); walk(c, out); });
  return out;
}
function findAll(el, sel) {
  const last = String(sel).trim().split(/\s+/).pop();
  return walk(el).filter((n) => matches(n, last));
}

const byId = {};
global.document = {
  body: mkEl('body'),
  createElement: mkEl,
  createTextNode: mkText,
  getElementById(id) {
    if (!(id in byId)) byId[id] = html.includes('id="' + id + '"') ? mkEl('div') : null;
    return byId[id];
  },
  querySelector: () => null,
  querySelectorAll: () => [],
  addEventListener() {},
  removeEventListener() {},
  activeElement: null,
};
global.window = global;
global.getSelection = () => 'selected text';

// ── bridge stub ──────────────────────────────────────────────────
const calls = []; const logs = [];
function slot(name) {
  return (...args) => { calls.push({ name, args }); };
}
global.App = { bridge: null };
global.LogConsole = { log: (m, l) => logs.push([m, l]), clear() {} };
const confirmations = [];
global.Dialog = { confirm: (t, x, ok, onYes) => { confirmations.push([t, ok]); global.Dialog._yes = onYes; } };
global.BotChat = { nick: 'Other', openPerson: (...a) => { calls.push({ name: 'BotChat.openPerson', args: a }); global.BotChat.nick = a[0]; } };
global.CollectorPanel = { setMyNick: (...a) => { calls.push({ name: 'CollectorPanel.setMyNick', args: a }); } };
global.Labels = { forNick: () => [], pill: () => mkText('pill'), unassign() {} };

// ── load the real modules ─────────────────────────────────────────
new Function(readUi('js/core/ui-helpers.js'))();
const modelMod = { exports: {} };
new Function('module', 'exports', readUi('js/history-model.js'))(modelMod, modelMod.exports);
global.HistoryModel = modelMod.exports;
global.HistoryView = new Function(readUi('js/history-view.js') + '\nreturn HistoryView;')();
global.HistoryStore = new Function(readUi('js/history-store.js') + '\nreturn HistoryStore;')();
const Store = global.HistoryStore;
const els = {
  list: document.getElementById('historyList'),
  search: document.getElementById('historySearchInput'),
  global: document.getElementById('historySearchGlobalBtn'),
  images: document.getElementById('historyImagesToggle'),
  folder: document.getElementById('historyFolderBtn'),
  clear: document.getElementById('historyClearBtn'),
  removePerson: document.getElementById('historyDeletePersonBtn'),
  latest: document.getElementById('historyLatestBtn'),
  myNick: document.getElementById('myNickInput'),
  header: document.getElementById('historyHeader'),
  panel: document.getElementById('winHistory'),
};
assertAllEls();
function assertAllEls() {
  Object.entries(els).forEach(([k, v]) => {
    if (!v) throw new Error('missing page element for ' + k);
  });
}

let passed = 0; let failed = 0;
function test(name, fn) {
  try { fn(); passed += 1; console.log('  ok - ' + name); }
  catch (e) { failed += 1; console.error('  FAIL - ' + name + '\n    ' + e.message); }
}
function clearCalls() { calls.length = 0; logs.length = 0; confirmations.length = 0; }
function assertCall(n) {
  assert(calls.some((c) => c.name === n), 'expected ' + n + ' — got ' + JSON.stringify(calls.map((c) => c.name)));
}
function setBridge() {
  global.App.bridge = {
    history_open: slot('history_open'), history_page: slot('history_page'),
    history_search: slot('history_search'), history_stats: slot('history_stats'),
    history_delete_person: slot('history_delete_person'),
    history_clear_person: slot('history_clear_person'),
    history_delete_message: slot('history_delete_message'),
    open_media_folder: slot('open_media_folder'),
    media_restore: slot('media_restore'), media_path: slot('media_path'),
    copy_media: slot('copy_media'), copy_text: slot('copy_text'),
    set_my_nick: slot('set_my_nick'),
    get_my_nick: (cb) => { calls.push({ name: 'get_my_nick', args: [] }); cb('Me'); },
    save_history_settings: slot('save_history_settings'),
  };
}
const page = (items, extra) => JSON.stringify(Object.assign({ nick: 'Ангелина' }, extra || {}, { items }));
const row = (ord, extra) => Object.assign({ ord, type: 'msg', nick: 'Ангелина',
  text: 'msg ' + ord, ts: '2026-01-01T10:00:0' + (ord % 10) }, extra || {});

setBridge();
Store.init();

test('init: model + listeners + empty state + my_nick', () => {
  assert(Store.model && typeof Store.model.requestInitial === 'function');
  assert(els.list.listeners.scroll.length === 1);
  assert(els.search.listeners.input.length === 1);
  assert(els.global.listeners.click.length === 1);
  assert(els.images.listeners.change.length === 1);
  assert(els.latest.listeners.click.length === 1);
  assert(els.folder.listeners.click.length === 1);
  assert(els.clear.listeners.click.length === 1);
  assert(els.removePerson.listeners.click.length === 1);
  assert(Store.myNick === 'Me');
  assert(els.list.textContent.indexOf('Click a nick') >= 0);
});

test('myNick: commit on change / Enter, no-op when unchanged', () => {
  clearCalls();
  els.myNick.value = 'Me';
  els.myNick.fire('change');
  assert(!calls.some((c) => c.name === 'set_my_nick'));
  els.myNick.value = 'NewNick';
  els.myNick.fire('change');
  assertCall('set_my_nick');
  assert(Store.myNick === 'NewNick');
  els.myNick.classList.add('saved');
  els.myNick.value = 'EnterNick';
  els.myNick.fire('keydown', { key: 'Enter' });
  assertCall('set_my_nick');
});

test('setMyNick: updates input, model, CollectorPanel', () => {
  clearCalls();
  Store.setMyNick('Someone');
  assert.strictEqual(els.myNick.value, 'Someone');
  assertCall('CollectorPanel.setMyNick');
  Store.setMyNick('');
  assert.strictEqual(Store.myNick, '');
});

test('applySettings + saveSettings', () => {
  clearCalls();
  Store.applySettings({ preview: { preload_rows: 10, page_size: 25, show_images: false } });
  assert.strictEqual(Store.preloadRows, 10);
  assert.strictEqual(Store.pageSize, 25);
  assert.strictEqual(Store.showImages, false);
  assert.strictEqual(els.images.checked, false);
  assert.strictEqual(Store.model.pageSize, 25);
  Store.saveSettings();
  assertCall('save_history_settings');
  const payload = JSON.parse(calls.find((c) => c.name === 'save_history_settings').args[0]);
  assert.strictEqual(payload.preview.page_size, 25);
});

test('openPerson: reset, header, bot follow, around option', () => {
  clearCalls();
  Store.openPerson(''); // refused
  assert.strictEqual(Store.nick, '');
  Store.openPerson('Ангелина');
  assert.strictEqual(Store.nick, 'Ангелина');
  assert(els.search.value === '');
  assertCall('history_open');
  const call = calls.find((c) => c.name === 'history_open');
  assert(call.args[1] === 'Ангелина');
  assert(call.args[0].indexOf('h') === 0);
  assert(els.list.textContent.indexOf('Loading') >= 0);
  assert(els.panel._scrolled);
  Store.openPerson('Второй', { around: 42 });
  const lastOpen = calls.filter((c) => c.name === 'history_open').pop();
  const req = JSON.parse(lastOpen.args[2]);
  assert.strictEqual(req.around, 42);
  assert.strictEqual(lastOpen.args[1], 'Второй');
  Store.reloadCurrent();
  assertCall('history_open');
});

test('_send: slot shapes + missing bridge', () => {
  clearCalls();
  const id1 = Store._send('history_stats', { nick: 'X' });
  assertCall('history_stats');
  assert(calls.find((c) => c.name === 'history_stats').args.length === 2);
  const id2 = Store._send('history_open', { nick: 'X' });
  assert(calls.find((c) => c.name === 'history_open').args.length === 3);
  global.App.bridge = null;
  const id3 = Store._send('history_stats', { nick: 'X' });
  assert(id3); // still returns a request id
  setBridge();
});

test('onPage: initial + stale + stats/preview/my_nick', () => {
  clearCalls();
  Store.openPerson('Ангелина');
  Store.myNick = ''; els.myNick.value = ''; // so page.my_nick applies
  const openId = calls.find((c) => c.name === 'history_open').args[0];
  Store.onPage(openId, 'bad json');
  Store.onPage(openId, JSON.stringify({ nick: 'Некто', items: [] })); // stale
  Store.onPage(openId, page([row(1), row(2)], { has_more: true, total: 2,
    preview: { page_size: 30 }, my_nick: 'PersistedMe' }));
  assert.strictEqual(Store.model.items.length, 2);
  assert.strictEqual(Store.model.hasOlder, true);
  assert.strictEqual(Store.model.total, 2);
  assert.strictEqual(Store.pageSize, 30);
  assert.strictEqual(Store.myNick, 'PersistedMe');
  assert(els.list.children.length > 0);
  Store.onPage('h-other', page([row(9)], {})); // not the initial request
  assert(Store.model.items.some((i) => i.ord === 9));
});

test('onSearch: person items / global groups / empty', () => {
  clearCalls();
  Store.nick = 'Ангелина';
  Store.query = 'hi';
  Store.onSearch('h1', 'not json');
  Store.onSearch('h1', JSON.stringify({ items: [row(5, { text: 'hit' })] }));
  assert(els.list.textContent.indexOf('hit') >= 0);
  Store.scope = 'global';
  Store.onSearch('h2', JSON.stringify({ scope: 'global',
    groups: [{ nick: 'Ангелина', count: 3, ord: 7 }] }));
  Store.scope = 'person';
  Store.onSearch('h3', JSON.stringify({ items: [] }));
  assert(els.list.textContent.indexOf('Nothing found') >= 0);
  Store.query = '';
});

test('onLiveAppend: merged at the tail / buffered away from the tail', () => {
  clearCalls();
  Store.openPerson('Ангелина');
  const openId = calls.find((c) => c.name === 'history_open').args[0];
  Store.onPage(openId, page([row(1), row(2)], { total: 2 }));
  els.list.scrollTop = els.list.scrollHeight; // at the live end
  Store.onLiveAppend('bad');
  Store.onLiveAppend(JSON.stringify({ nick: 'Некто', items: [row(3)] }));
  Store.onLiveAppend(JSON.stringify({ nick: 'Ангелина', items: [row(3)], total: 3 }));
  assert(Store.model.items.some((i) => i.ord === 3));
  assert.strictEqual(Store.model.total, 3);
  assertCall('history_stats');
  // away from the tail (hasNewer) → buffered, button offered
  Store.openPerson('Ангелина');
  const openId2 = calls.find((c) => c.name === 'history_open').args[0];
  Store.onPage(openId2, page([row(1)], { has_newer: true, total: 1 }));
  assert(Store.model.hasNewer);
  Store.onLiveAppend(JSON.stringify({ nick: 'Ангелина', items: [row(10)] }));
  assert(Store.model.pendingLive > 0);
  assert(els.latest.textContent.indexOf('Jump to latest') >= 0);
  assert(els.latest.textContent.indexOf('1 new') >= 0);
});

test('onStats: mismatch ignored, count applied', () => {
  const before = Store.model.total;
  Store.nick = 'Ангелина';
  Store.onStats('s1', JSON.stringify({ nick: 'Некто', message_count: 99 }));
  assert.strictEqual(Store.model.total, before);
  Store.onStats('s1', JSON.stringify({ nick: 'Ангелина', message_count: 42 }));
  assert.strictEqual(Store.model.total, 42);
  Store.onStats('s1', 'bad');
});

test('openFolder: guard + bridge', () => {
  clearCalls();
  Store.nick = '';
  Store.openFolder();
  assert(logs.some((l) => l[1] === 'info'));
  Store.nick = 'Ангелина';
  Store.openFolder();
  assertCall('open_media_folder');
});

test('onMediaReady: model hit / view path / error warn', () => {
  clearCalls();
  Store.openPerson('Ангелина');
  const openId = calls.find((c) => c.name === 'history_open').args[0];
  Store.onPage(openId, page([row(1, { media: { id: 77, state: 'missing' } })], {}));
  Store.onMediaReady('r1', 'bad');
  Store.onMediaReady('r1', JSON.stringify({ id: 77, path: '/media/77.jpg' }));
  assert.strictEqual(Store.model.items[0].media.path, '/media/77.jpg');
  Store.onMediaReady('r1', JSON.stringify({ id: 999, path: '/media/999.jpg' }));
  // no model hit → HistoryView.applyMediaPath (no-op on the stub DOM)
  Store.onMediaReady('r1', JSON.stringify({ error: 'expired', state: 'gone' }));
  assert(logs.some((l) => l[0].indexOf('expired') >= 0));
});

test('restoreMedia: media_restore + media_path fallback', () => {
  clearCalls();
  Store.restoreMedia(77);
  assertCall('media_restore');
  global.App.bridge.media_restore = undefined;
  Store.restoreMedia(78);
  assertCall('media_path');
  setBridge();
});

test('onError: history scopes only', () => {
  Store.onError('other_thing', 'x');
  Store.onError('history_open', 'boom');
  assert(els.list.textContent.indexOf('boom') >= 0);
});

test('_onScroll: older prefetch + newer prefetch + query guard', () => {
  clearCalls();
  Store.openPerson('Ангелина');
  const openId = calls.find((c) => c.name === 'history_open').args[0];
  Store.onPage(openId, page([row(1), row(2), row(3)], { has_more: true, has_newer: true }));
  Store.query = 'locked';
  els.list.scrollTop = 0;
  Store._onScroll(); // query guard
  assert(!calls.some((c) => c.name === 'history_page'));
  Store.query = '';
  els.list.scrollTop = 10;
  Store._onScroll(); // near the top → older
  assertCall('history_page');
  clearCalls();
  Store.model.loading = false; // the older request set it
  els.list.scrollTop = els.list.scrollHeight - els.list.clientHeight + 10;
  Store._onScroll(); // at the bottom → newer
  assertCall('history_page');
});

test('jumpToLatest + runSearch + debounce', () => {
  clearCalls();
  Store.jumpToLatest();
  assertCall('history_open');
  Store.query = 'abc';
  Store.runSearch();
  assertCall('history_search');
  Store.query = '';
  Store.runSearch(); // renders, no slot
  const origSetTimeout = global.setTimeout;
  let timerFn = null;
  global.setTimeout = (fn) => { timerFn = fn; return 1; };
  Store.query = 'deb';
  Store._debounceSearch();
  assert(timerFn);
  timerFn();
  assertCall('history_search');
  global.setTimeout = origSetTimeout;
  Store.query = '';
});

test('search input + global toggle wiring', () => {
  clearCalls();
  els.search.value = 'zz';
  els.search.fire('input');
  assert.strictEqual(Store.query, 'zz');
  els.global.fire('click');
  assert.strictEqual(Store.scope, 'global');
  assert(els.global.classList.contains('active'));
  els.global.fire('click');
  assert.strictEqual(Store.scope, 'person');
  els.search.value = '';
  els.search.fire('input');
});

test('images toggle: setting + save + render', () => {
  clearCalls();
  els.images.checked = false;
  els.images.fire('change');
  assert.strictEqual(Store.showImages, false);
  assertCall('save_history_settings');
});

test('deleteMessage: guard + bridge', () => {
  clearCalls();
  Store.deleteMessage(null);
  global.App.bridge = null;
  Store.deleteMessage(5);
  assert(logs.some((l) => l[1] === 'warn'));
  setBridge();
  Store.deleteMessage(5);
  assertCall('history_delete_message');
});

test('clearHistory / deletePerson: confirm → bridge', () => {
  clearCalls();
  Store.nick = '';
  Store.clearHistory();
  Store.deletePerson();
  assert.strictEqual(confirmations.length, 0);
  Store.nick = 'Ангелина';
  Store.clearHistory();
  assert(confirmations.length === 1);
  global.Dialog._yes();
  assertCall('history_clear_person');
  Store.deletePerson();
  global.Dialog._yes();
  assertCall('history_delete_person');
});

test('render: empty states + rows + latest button', () => {
  Store.model.reset({ nick: 'Ангелина' });
  Store.model.missing = true;
  Store.render();
  assert(els.list.textContent.indexOf('Nothing archived') >= 0);
  Store.model.missing = false;
  Store.render();
  assert(els.list.textContent.indexOf('No messages to show') >= 0);
  Store.openPerson('Ангелина');
  const openId = calls.find((c) => c.name === 'history_open').args[0];
  Store.onPage(openId, page([row(1), row(2)], { total: 2 }));
  assert(els.latest.classList.contains('hidden'));
  Store.model.hasNewer = true;
  Store._updateLatestButton();
  assert(!els.latest.classList.contains('hidden'));
  Store.model.pendingLive = 2;
  Store._updateLatestButton();
  assert(els.latest.textContent.indexOf('2 new') >= 0);
  Store.model.pendingLive = 0;
  els.latest.fire('click'); // jumpToLatest
  assertCall('history_open');
});

test('copyMedia / copySelection', () => {
  clearCalls();
  Store.copyMedia(77);
  assertCall('copy_media');
  assert(logs.some((l) => l[0].indexOf('Copying media') >= 0));
  const sel = Store.copySelection();
  assert.strictEqual(sel, 'selected text');
  assertCall('copy_text');
  const orig = global.getSelection;
  global.getSelection = () => '';
  assert.strictEqual(Store.copySelection(), '');
  global.getSelection = orig;
});

console.log('\ntest_history_store: ' + passed + ' passed, ' + failed + ' failed');
process.exit(failed ? 1 : 0);
