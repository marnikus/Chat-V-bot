/* Boot test for the three archive windows (ui/js/history-store.js,
   history-db.js, collector-panel.js).

   The unit tests cover the model and the renderer in isolation; this one
   wires the REAL shipped modules to the REAL element ids in
   ui/index.html and drives them the way the QWebChannel bridge does:
   a slot is called with a request id, the answer arrives on a signal.

   It fails if a module reaches for an element that the page does not
   have (the classic silent-no-op bug), if a bridge slot is called with
   the wrong shape, or if an answer does not reach the DOM.

   Run:  node tests/test_history_panels_boot.js
*/
'use strict';
const fs = require('fs');
const path = require('path');

const readUi = (f) => fs.readFileSync(path.join(__dirname, '..', 'ui', f),
                                      'utf8');
const html = readUi('index.html');

// ── DOM stub ─────────────────────────────────────────────────────

function mkEl(tag) {
  const listeners = {};
  const el = {
    tagName: String(tag || 'div').toUpperCase(),
    _text: '',
    children: [],
    parentNode: null,
    style: {},
    dataset: {},
    attrs: {},
    title: '',
    value: '',
    checked: false,
    scrollTop: 0,
    scrollHeight: 1000,
    clientHeight: 500,
    listeners,
    classList: {
      _set: new Set(),
      add(...c) { c.forEach((x) => this._set.add(x)); },
      remove(...c) { c.forEach((x) => this._set.delete(x)); },
      toggle(c, on) { on ? this._set.add(c) : this._set.delete(c); },
      contains(c) { return this._set.has(c); },
    },
    get className() { return [...el.classList._set].join(' '); },
    set className(v) {
      el.classList._set = new Set(String(v).split(/\s+/).filter(Boolean));
    },
    get textContent() {
      return el._text + el.children.map((c) => c.textContent).join('');
    },
    set textContent(v) { el._text = String(v); el.children = []; },
    set innerHTML(v) { throw new Error('markup assignment is forbidden'); },
    appendChild(c) { el.children.push(c); c.parentNode = el; return c; },
    append(...cs) {
      cs.forEach((c) => el.appendChild(typeof c === 'string' ? mkText(c) : c));
    },
    replaceChildren(...cs) { el.children = []; el.append(...cs); },
    setAttribute(k, v) { el.attrs[k] = String(v); },
    getAttribute(k) { return k in el.attrs ? el.attrs[k] : null; },
    addEventListener(ev, fn) { (listeners[ev] = listeners[ev] || []).push(fn); },
    removeEventListener() {},
    getBoundingClientRect() { return { top: 0, left: 0, width: 10, height: 10 }; },
    scrollIntoView() {},
    focus() {},
    blur() {},
    closest(sel) {
      let node = el;
      while (node) {
        if (matches(node, sel)) return node;
        node = node.parentNode;
      }
      return null;
    },
    querySelector(sel) { return findAll(el, sel)[0] || null; },
    querySelectorAll(sel) { return findAll(el, sel); },
    fire(ev, extra) {
      (listeners[ev] || []).forEach((fn) => fn(Object.assign(
        { target: el, button: 0, preventDefault() {}, stopPropagation() {} },
        extra || {})));
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
      const name = /([\w-]+)/.exec(parts[1])[1].replace(/-(\w)/g,
        (m, c) => c.toUpperCase());
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
  createElement: mkEl,
  createTextNode: mkText,
  getElementById(id) {
    if (!(id in byId)) byId[id] = html.includes('id="' + id + '"')
      ? mkEl('div') : null;
    return byId[id];
  },
  querySelector: () => null,
  querySelectorAll: () => [],
  addEventListener() {},
  activeElement: null,
};
global.window = global;
global.getSelection = () => '';

// ── bridge stub (records every call, replays the answers) ────────

const calls = [];
function slot(name) {
  return function (...args) {
    calls.push({ name, args });
    const last = args[args.length - 1];
    if (typeof last === 'function') last('');    // property-getter style
  };
}
global.App = {
  bridge: {
    history_open: slot('history_open'),
    history_page: slot('history_page'),
    history_search: slot('history_search'),
    userdb_page: slot('userdb_page'),
    userdb_stats: slot('userdb_stats'),
    history_delete_person: slot('history_delete_person'),
    copy_media: slot('copy_media'),
    copy_text: slot('copy_text'),
    collector_command: slot('collector_command'),
    collector_set: slot('collector_set'),
    collector_state: slot('collector_state'),
    set_my_nick: slot('set_my_nick'),
    get_my_nick: (cb) => { calls.push({ name: 'get_my_nick', args: [] }); cb('Me'); },
    save_history_settings: slot('save_history_settings'),
  },
};
global.LogConsole = { log() {} };

// ── load the real modules ────────────────────────────────────────

// Everything the modules need (document, App, LogConsole, and each other)
// lives on the global object, exactly like the <script> tags in the page.
const load = (file, name) =>
  new Function(readUi(file) + '\nreturn ' + name + ';')();

const modelMod = { exports: {} };
new Function('module', 'exports', readUi('js/history-model.js'))(
  modelMod, modelMod.exports);
global.HistoryModel = modelMod.exports;
global.HistoryView = load('js/history-view.js', 'HistoryView');
global.HistoryStore = load('js/history-store.js', 'HistoryStore');
global.HistoryDb = load('js/history-db.js', 'HistoryDb');
global.CollectorPanel = load('js/collector-panel.js', 'CollectorPanel');

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
const named = (name) => calls.filter((c) => c.name === name);

// ── every id the modules use must exist in index.html ────────────

t('the panels only address elements the page really has', () => {
  for (const file of ['js/history-store.js', 'js/history-db.js',
                      'js/collector-panel.js']) {
    const src = readUi(file);
    const ids = new Set();
    const re = /\$\('([\w-]+)'\)|getElementById\('([\w-]+)'\)/g;
    let m;
    while ((m = re.exec(src))) ids.add(m[1] || m[2]);
    for (const id of ids)
      ok(html.includes('id="' + id + '"'), file + ' wants #' + id);
  }
});

// ── boot ─────────────────────────────────────────────────────────

t('the three windows boot without a DOM error', () => {
  HistoryStore.init();
  HistoryDb.init();
  CollectorPanel.init();
  eq(HistoryStore.myNick, 'Me', 'the persisted nick is loaded on start');
  ok(named('userdb_page').length === 1, 'the database asks for its first page');
});

// ── Person History ───────────────────────────────────────────────

const rows = (from, to) => {
  const out = [];
  for (let o = from; o <= to; o++)
    out.push({ ord: o, fp: 'fp' + o, dir: o % 2 ? 'out' : 'in',
               from: o % 2 ? 'Me' : 'Nick', kind: 'text', text: 'line ' + o,
               media: null, time: '17:3' + (o % 10), day: '2026-09-06' });
  return out;
};

t('clicking a nick asks Python for that conversation', () => {
  HistoryStore.openPerson('Nick');
  const call = named('history_open').pop();
  ok(call, 'history_open was called');
  eq(call.args[1], 'Nick', 'the person travels as its own argument');
  const request = JSON.parse(call.args[2]);
  eq(request.nick, 'Nick');
  ok(request.limit > 0, 'a page size is requested');
});

t('the answer is rendered, newest last, with both nicks in the header', () => {
  const req = named('history_open').pop().args[0];
  HistoryStore.onPage(req, JSON.stringify({
    nick: 'Nick', items: rows(1, 20), total: 20, has_more: false,
    has_newer: false, gaps: [], missing: false,
    stats: { messages: 20, first_day: '2026-09-01', last_day: '2026-09-06' },
  }));
  const list = document.getElementById('historyList');
  eq(list.querySelectorAll('.msg').length, 20);
  const header = document.getElementById('historyHeader').textContent;
  ok(header.includes('Nick') && header.includes('Me'), header);
});

t('an answer for another person is ignored', () => {
  HistoryStore.onPage('stale', JSON.stringify({
    nick: 'Someone Else', items: rows(1, 5), total: 5, has_more: false,
    has_newer: false, gaps: [], missing: false }));
  eq(document.getElementById('historyList').querySelectorAll('.msg').length, 20);
});

t('a live append from the collector lands in the open conversation', () => {
  HistoryStore.onLiveAppend(JSON.stringify(
    { nick: 'Nick', added: 1, total: 21, items: rows(21, 21) }));
  eq(document.getElementById('historyList').querySelectorAll('.msg').length, 21);
});

t('a live append for a different person does not', () => {
  HistoryStore.onLiveAppend(JSON.stringify(
    { nick: 'Other', added: 1, total: 1, items: rows(22, 22) }));
  eq(document.getElementById('historyList').querySelectorAll('.msg').length, 21);
});

t('a left click on media asks the bridge to copy it', () => {
  HistoryStore.onPage(named('history_open').pop().args[0], JSON.stringify({
    nick: 'Nick', total: 1, has_more: false, has_newer: false, gaps: [],
    missing: false,
    items: [{ ord: 30, fp: 'g', dir: 'in', from: 'Nick', kind: 'gif',
              text: '', time: '18:00', day: '2026-09-06',
              media: { id: 7, url: 'https://x/y.gif', kind: 'gif' } }],
  }));
  document.getElementById('historyList').querySelector('.msg-media')
    .fire('click', { button: 0 });
  eq(named('copy_media').pop().args, ['7']);
});

t('typing in the search box searches this conversation', () => {
  const box = document.getElementById('historySearchInput');
  box.value = 'line';
  box.fire('input');
  HistoryStore.runSearch();
  const call = named('history_search').pop();
  const request = JSON.parse(call.args[1]);
  eq(request.scope, 'person');
  eq(request.nick, 'Nick');
  eq(request.q, 'line');
});

t('global results are grouped per person', () => {
  HistoryStore.scope = 'global';
  HistoryStore.onSearch('x', JSON.stringify({ scope: 'global', groups: [
    { nick: 'Nick', items: [{ ord: 1, snippet: 'hello' }] },
    { nick: 'Other', items: [{ ord: 2, snippet: 'hi' }] },
  ] }));
  const list = document.getElementById('historyList');
  eq(list.querySelectorAll('.search-group').length, 2);
  HistoryStore.scope = 'person';
});

// ── My Nick ──────────────────────────────────────────────────────

t('editing My Nick persists it through the bridge', () => {
  const input = document.getElementById('myNickInput');
  input.value = '  HiHoney  ';
  input.fire('change');
  eq(named('set_my_nick').pop().args, ['HiHoney']);
});

t('a nick change coming back from Python updates the field', () => {
  HistoryStore.setMyNick('Другой');
  eq(document.getElementById('myNickInput').value, 'Другой');
  ok(document.getElementById('historyHeader').textContent.includes('Другой'));
});

// ── Full User Database ───────────────────────────────────────────

t('the database lists people merged by nick', () => {
  HistoryDb.onPage('u1', JSON.stringify({ items: [
    { nick: 'Nick', message_count: 20, media_count: 2,
      first_seen: '2026-09-01 10:00:00', last_seen: '2026-09-06 18:00:00',
      my_nicks: ['Me'] },
    { nick: 'Other', message_count: 3, media_count: 0,
      first_seen: '2026-09-02 10:00:00', last_seen: '2026-09-02 11:00:00',
      my_nicks: ['Me', 'HiHoney'] },
  ], total: 2, has_more: false, offset: 0 }));
  const body = document.getElementById('userdbBody');
  eq(body.querySelectorAll('.userdb-row').length, 2);
  ok(body.textContent.includes('Nick') && body.textContent.includes('Other'));
  ok(body.textContent.includes('2026-09-01'), 'dates are shown as days');
});

t('clicking a row opens that person in Person History', () => {
  const body = document.getElementById('userdbBody');
  const row = body.querySelectorAll('.userdb-row')[1];
  body.fire('click', { target: row });   // delegated, as a real click bubbles
  eq(named('history_open').pop().args[1], 'Other');
});

t('the footer summarises the whole archive', () => {
  HistoryDb.onPage('s1', JSON.stringify(
    { persons: 12, messages: 3400, media: 40, bytes: 5242880 }));
  const foot = document.getElementById('userdbFoot').textContent;
  ok(/12 people/.test(foot) && /3400 messages/.test(foot), foot);
  ok(/5\.0 MB/.test(foot), foot);
});

t('searching the database reloads it with the query', () => {
  const box = document.getElementById('userdbSearch');
  box.value = 'ang';
  HistoryDb.query = 'ang';
  HistoryDb.reload();
  const request = JSON.parse(named('userdb_page').pop().args[1]);
  eq(request.q, 'ang');
  eq(request.offset, 0);
});

// ── the collector window ─────────────────────────────────────────

t('the status badge has one class per state', () => {
  const badge = document.getElementById('collectorStatus');
  CollectorPanel.onStatus(JSON.stringify(
    { state: 'collecting', text: 'Collecting', nick: 'Nick', total: 21,
      settings: { enabled: true, download_media: true, heartbeat_ms: 1500 } }));
  ok(badge.classList.contains('state-collecting'), badge.className);
  eq(badge.textContent, 'Collecting');
  CollectorPanel.onStatus(JSON.stringify(
    { state: 'not_private', text: 'Not in private tab now', settings: {} }));
  ok(badge.classList.contains('state-idle'), badge.className);
  eq(badge.textContent, 'Not in private tab now');
  CollectorPanel.onStatus(JSON.stringify(
    { state: 'error', text: 'Error', error: 'boom', settings: {} }));
  ok(badge.classList.contains('state-error'), badge.className);
});

t('the window names the partner and my nick', () => {
  CollectorPanel.onStatus(JSON.stringify(
    { state: 'collected', text: 'Collected', nick: 'Ангелина', total: 120,
      settings: { my_nick: 'HiHoney' } }));
  const text = document.getElementById('collectorRows').textContent;
  ok(text.includes('Ангелина'), text);
  ok(text.includes('HiHoney') || text.includes('Другой'), text);
});

t('pause / resume and collect-now reach the backend', () => {
  const pause = document.getElementById('collectorPauseBtn');
  pause.fire('click');
  eq(named('collector_command').pop().args, ['pause']);
  CollectorPanel.onStatus(JSON.stringify(
    { state: 'paused', text: 'Paused', paused: true, settings: {} }));
  pause.fire('click');
  eq(named('collector_command').pop().args, ['resume']);
  document.getElementById('collectorNowBtn').fire('click');
  eq(named('collector_command').pop().args, ['tick']);
});

t('the settings toggles are sent as a patch', () => {
  const media = document.getElementById('collectorMediaToggle');
  media.checked = false;
  media.fire('change');
  eq(JSON.parse(named('collector_set').pop().args[0]), { download_media: false });
  const beat = document.getElementById('collectorHeartbeat');
  beat.value = '2222';
  beat.fire('change');
  eq(JSON.parse(named('collector_set').pop().args[0]), { heartbeat_ms: 2222 });
});

// ── reporting ────────────────────────────────────────────────────

console.log('history_panels_boot: ' + passed + ' passed, ' + failed + ' failed');
if (failed) process.exit(1);
console.log('OK');
