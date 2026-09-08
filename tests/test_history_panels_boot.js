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
    removeChild(c) {
      el.children = el.children.filter((n) => n !== c);
      c.parentNode = null;
      return c;
    },
    remove() { if (el.parentNode) el.parentNode.removeChild(el); },
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
  // the floating colour picker attaches itself to the page body
  body: mkEl('body'),
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
  removeEventListener() {},
  activeElement: null,
};
global.window = global;
global.getSelection = () => '';

// ── bridge stub (records every call, replays the answers) ────────

const calls = [];
const LABEL_STATE = {
  defs: [{ id: 'lbl_1', name: 'Rude', color: '#ff3b30' },
         { id: 'lbl_2', name: 'VIP', color: '#34c759' }],
  assign: { 'Ангелина': ['lbl_1'] },
  filter: { include: [], exclude: [] },
};
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
    history_clear_person: slot('history_clear_person'),
    history_delete_message: slot('history_delete_message'),
    get_labels: (cb) => { calls.push({ name: 'get_labels', args: [] });
                          cb(JSON.stringify(LABEL_STATE)); },
    label_create: slot('label_create'),
    label_delete: slot('label_delete'),
    label_assign: slot('label_assign'),
    label_unassign: slot('label_unassign'),
    label_set_for: slot('label_set_for'),
    label_set_filter: slot('label_set_filter'),
    label_clear_filter: slot('label_clear_filter'),
    db_info: slot('db_info'),
    db_create: slot('db_create'),
    db_load: slot('db_load'),
    db_delete: slot('db_delete'),
    db_clean: slot('db_clean'),
    copy_media: slot('copy_media'),
    media_restore: slot('media_restore'),
    media_path: slot('media_path'),
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
global.ColorPicker = load('js/color-picker.js', 'ColorPicker');
global.Labels = load('js/labels.js', 'Labels');
global.DbPanel = load('js/db-panel.js', 'DbPanel');
global.PresetsUI = {
  confirm(title, text, okLabel, onYes) {
    calls.push({ name: 'confirm', args: [title, text] });
    onYes();
  },
};

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

t('a live append appears immediately and bumps the header count', () => {
  HistoryStore.openPerson('Nick');
  HistoryStore.onPage(named('history_open').pop().args[0], JSON.stringify({
    nick: 'Nick', items: rows(1, 3), total: 3, has_more: false,
    has_newer: false, gaps: [], missing: false,
    stats: { messages: 3, first_day: '2026-09-06', last_day: '2026-09-06' },
  }));
  const list = document.getElementById('historyList');
  ok(document.getElementById('historyHeader').textContent
    .includes('3 messages'), 'header shows the count before the append');
  HistoryStore.onLiveAppend(JSON.stringify({
    nick: 'Nick', added: 1, total: 4,
    items: [{ ord: 4, fp: 'fp4', dir: 'in', from: 'Nick', kind: 'text',
              text: 'fresh', media: null, time: '17:34', day: '2026-09-06' }],
  }));
  eq(list.querySelectorAll('.msg').length, 4, 'the new row is rendered');
  ok(document.getElementById('historyHeader').textContent
    .includes('4 messages'), 'the header count is updated');

  // restore the state the following tests assume
  HistoryStore.openPerson('Nick');
  HistoryStore.onPage(named('history_open').pop().args[0], JSON.stringify({
    nick: 'Nick', items: rows(1, 20), total: 20, has_more: false,
    has_newer: false, gaps: [], missing: false,
    stats: { messages: 20, first_day: '2026-09-01', last_day: '2026-09-06' },
  }));
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
              media: { id: 7, url: 'https://x/y.gif', kind: 'gif',
                       state: 'cached',
                       path: '/home/user/saved_media/Nick/gifs/x.gif' } }],
  }));
  document.getElementById('historyList').querySelector('.msg-media')
    .fire('click', { button: 0 });
  eq(named('copy_media').pop().args, ['7']);
});

t('a failed media row offers a restore marker and asks the bridge', () => {
  HistoryStore.openPerson('Nick');
  HistoryStore.onPage(named('history_open').pop().args[0], JSON.stringify({
    nick: 'Nick', total: 1, has_more: false, has_newer: false, gaps: [],
    missing: false,
    items: [{ ord: 31, fp: 'g2', dir: 'in', from: 'Nick', kind: 'gif',
              text: '', time: '18:01', day: '2026-09-06',
              media: { id: 8, url: 'https://x/y.gif', kind: 'gif',
                       state: 'failed', path: '' } }],
  }));
  const marker =
    document.getElementById('historyList').querySelector('.msg-media-restore');
  ok(marker, 'the marker is drawn instead of a broken img');
  marker.fire('click', { button: 0 });
  const call = named('media_restore').pop();
  ok(call.args[0].indexOf('r') === 0, 'a request id is sent');
  eq(call.args[1], '8', 'the media id travels as the second argument');
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

t('the partner name is a clickable link to its history', () => {
  CollectorPanel.onStatus(JSON.stringify(
    { state: 'collected', text: 'Collected', nick: 'Ангелина', total: 120,
      settings: {} }));
  const link = document.getElementById('collectorRows')
    .querySelector('.collector-nick-link');
  ok(link, 'the partner row must expose a clickable nick');
  eq(link.dataset.nick, 'Ангелина');
  const shown = [];
  global.SashGrid = { showWindow: (id) => shown.push(id) };
  try {
    // Real clicks bubble through the rows host, so simulate that exactly
    // (the stub's .fire() only invokes listeners on the target itself).
    document.getElementById('collectorRows').fire('click', { target: link });
    ok(shown.includes('history') && shown.includes('userdb'),
       'both archive windows are brought into view');
    const open = named('history_open').pop();
    ok(open && open.args[1] === 'Ангелина',
       'the person is opened in Person History');
    const db = named('userdb_page').pop();
    eq(JSON.parse(db.args[1]).q, 'Ангелина',
       'the database is filtered to that nick');
  } finally {
    global.SashGrid = undefined;
  }
});

t('the collector keeps its own parsing log in this window', () => {
  const log = document.getElementById('collectorLog');
  const clear = document.getElementById('collectorClearLogBtn');
  ok(log && clear, 'the collector log area and its Clear button exist');
  CollectorPanel.onLog(JSON.stringify(
    { ts: '12:00:01', level: 'info', nick: 'Ангелина',
      message: 'No new messages (unchanged, page count 7)' }));
  CollectorPanel.onLog(JSON.stringify(
    { ts: '12:00:02', level: 'warn', nick: '',
      message: 'Refused: 17 participants, not a private chat' }));
  ok(log.textContent.includes('Ангелина'), log.textContent);
  ok(log.textContent.includes('No new messages'), log.textContent);
  ok(log.textContent.includes('Refused'), log.textContent);
  clear.fire('click');
  eq(log.children.length, 0, 'Clear empties the collector log');
});

t('the highlighted person is flashed in the database row', () => {
  const req = named('userdb_page').pop().args[0];
  HistoryDb.onPage(req, JSON.stringify({
    items: [{ nick: 'Ангелина', message_count: 120, media_count: 2,
              first_seen: '2026-09-01 10:00:00',
              last_seen: '2026-09-07 12:00:00', my_nicks: ['Хорошо Все'] }],
    total: 1, has_more: false, offset: 0 }));
  const row = document.getElementById('userdbBody').querySelector('.userdb-row');
  ok(row, 'the filter result is rendered');
  ok(row.classList.contains('row-flash'),
     'the clicked partner is highlighted in the database');
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

// ═════════════════════════════════════════════════════════════════
// the Label Manager and DB Connection windows boot against the page
// ═════════════════════════════════════════════════════════════════

t('the Label Manager finds every element it needs and loads the labels', () => {
  Labels.init();
  eq(named('get_labels').length, 1, 'the state is requested on boot');
  const active = document.getElementById('labelActiveList');
  ok(active.textContent.includes('Rude'), active.textContent);
  ok(active.textContent.includes('VIP'), active.textContent);
});

t('the DB Connection window asks for the sizes on boot', () => {
  DbPanel.init();
  eq(named('db_info').length, 1);
  const req = named('db_info').pop().args[0];
  DbPanel.onInfo(req, JSON.stringify({
    req_id: req, path: '/app/history.db', connected: true,
    db_bytes: 2048, text_bytes: 1024, media_bytes: 4096, media_files: 2,
    persons: 3, messages: 40, messages_hidden: 0, total_bytes: 6144,
    items: [{ path: '/app/history.db', name: 'history.db', bytes: 2048,
              exists: true, active: true }] }));
  const stats = document.getElementById('dbStatsGrid');
  ok(stats.textContent.includes('Full DB size'), stats.textContent);
  ok(document.getElementById('dbActivePath').textContent.includes('history.db'));
});

t('a label pill with its ✕ shows next to the nick in the database table', () => {
  const req = named('userdb_page').pop().args[0];
  HistoryDb.onPage(req, JSON.stringify({
    items: [{ nick: 'Ангелина', message_count: 3, media_count: 0,
              first_seen: '2026-09-01 10:00:00',
              last_seen: '2026-09-07 12:00:00', my_nicks: ['Me'] }],
    total: 1, has_more: false, offset: 0 }));
  const row = document.getElementById('userdbBody').querySelector('.userdb-row');
  ok(row.textContent.includes('Rude'), 'the pill is drawn: ' + row.textContent);
  const x = row.querySelector('.label-pill-x');
  ok(x, 'the pill carries an ✕');
  x.fire('click');
  eq(named('label_unassign').pop().args, ['Ангелина', 'lbl_1'],
     'the ✕ only detaches the label from this person');
});

t('the database row can clear a chat or remove the person', () => {
  const row = document.getElementById('userdbBody').querySelector('.userdb-row');
  const buttons = row.querySelectorAll('.btn-row');
  ok(buttons.length >= 3, 'label / clear / delete');
  const body = document.getElementById('userdbBody');
  const fireOn = (action) => {
    const btn = buttons.filter((b) => b.dataset.action === action)[0];
    ok(btn, 'a button for ' + action);
    body.fire('click', { target: btn });
  };
  fireOn('clear');
  eq(named('history_clear_person').pop().args, ['Ангелина']);
  fireOn('delete');
  eq(named('history_delete_person').pop().args, ['Ангелина', false]);
});

t('clicking a nick points the Label Manager at that person', () => {
  const body = document.getElementById('userdbBody');
  const row = body.querySelector('.userdb-row');
  body.fire('click', { target: row });
  eq(Labels.person, 'Ангелина');
  const hint = document.getElementById('labelAssignHint');
  ok(hint.textContent.includes('Ангелина'), hint.textContent);
});

t('a single message can be removed from the open conversation', () => {
  HistoryStore.openPerson('Ангелина');
  const req = named('history_open').pop().args[0];
  HistoryStore.onPage(req, JSON.stringify({
    nick: 'Ангелина', my_nick: 'Me',
    items: [{ id: 41, ord: 1, dir: 'in', from: 'Ангелина', text: 'hi',
              time: '10:00', day: '2026-09-07' },
            { id: 42, ord: 2, dir: 'out', from: 'Me', text: 'hello',
              time: '10:01', day: '2026-09-07' }],
    has_older: false, has_newer: false, stats: { messages: 2 } }));
  const list = document.getElementById('historyList');
  const dels = list.querySelectorAll('.msg-del');
  eq(dels.length, 2, 'every message offers a delete');
  dels[1].fire('click');
  eq(named('history_delete_message').pop().args, ['Ангелина', '42']);
});

t('the toolbar can clear the chat or remove the person, with a confirmation', () => {
  document.getElementById('historyClearBtn').fire('click');
  ok(named('confirm').length >= 1, 'the user is asked first');
  eq(named('history_clear_person').pop().args, ['Ангелина']);
  document.getElementById('historyDeletePersonBtn').fire('click');
  eq(named('history_delete_person').pop().args, ['Ангелина', false]);
});

t('creating a label from the manager reaches the backend', () => {
  const input = document.getElementById('labelNameInput');
  input.value = 'Ignoring';
  document.getElementById('labelAddBtn').fire('click');
  const call = named('label_create').pop();
  eq(call.args[0], 'Ignoring');
  ok(/^#[0-9a-f]{6}$/i.test(call.args[1]), 'a colour travels with it');
});

t('the colour button opens the movable picker', () => {
  document.getElementById('labelColorBtn').fire('click');
  ok(ColorPicker.isOpen, 'the picker is open');
  ColorPicker.cancel();
  ok(!ColorPicker.isOpen);
});

t('the filter buttons send an include/exclude rule', () => {
  Labels.selected = new Set(['lbl_1']);
  document.getElementById('labelExcludeBtn').fire('click');
  eq(JSON.parse(named('label_set_filter').pop().args[0]),
     { include: [], exclude: ['lbl_1'] });
  document.getElementById('labelClearFilterBtn').fire('click');
  eq(named('label_clear_filter').length, 1);
});

t('a repair-only live event reloads existing bubbles instead of adding duplicates', () => {
  HistoryStore.openPerson('Nick');
  const initial = named('history_open').pop().args[0];
  HistoryStore.onPage(initial, JSON.stringify({ nick: 'Nick', items: rows(1, 3), total: 3 }));
  const before = named('history_open').length;
  HistoryStore.onLiveAppend(JSON.stringify({ nick: 'Nick', added: 0, total: 3, refresh: true }));
  eq(named('history_open').length, before + 1);
  ok(named('history_open').pop().args[0] !== initial, 'old replies have been invalidated');
});

t('pending capture has a warning status and shows structured read diagnostics', () => {
  CollectorPanel.onStatus(JSON.stringify({
    state: 'capture_pending', text: 'Capture pending — 1 unreadable; retrying',
    agent: 11, nick: 'Nick', total: 0, added: 0, capture_missing: 1, capture_errors: 0,
    capture_diagnostics: [{ from: 0, to: 1, returned: 1, ready: 0,
      reason: 'payload_pending', sources: { 'message-content': 1 } }],
  }));
  const status = document.getElementById('collectorStatus');
  ok(status.classList.contains('state-capture-pending'));
  ok(!/No new messages/.test(status.textContent));
  const rows = document.getElementById('collectorRows').textContent;
  ok(rows.includes('awaiting retry 1'));
  ok(rows.includes('v11'));
  ok(rows.includes('payload_pending'));
  ok(rows.includes('message-content'));
});

t('a failed browser read is shown as an error, not a no-new success', () => {
  CollectorPanel.onStatus(JSON.stringify({
    state: 'error', text: 'Message read failed', nick: 'Nick', total: 0,
    capture_errors: 1, error: 'DOM 0:2: invalid response',
    capture_diagnostics: [{ from: 0, to: 2, returned: 0, ready: 0,
      reason: 'invalid_response', error: 'invalid response' }],
  }));
  ok(document.getElementById('collectorStatus').classList.contains('state-error'));
  ok(document.getElementById('collectorRows').textContent.includes('read errors 1'));
  ok(document.getElementById('collectorRows').textContent.includes('DOM 0:2: invalid response'));
});

// ── reporting ────────────────────────────────────────────────────

console.log('history_panels_boot: ' + passed + ' passed, ' + failed + ' failed');
if (failed) process.exit(1);
console.log('OK');
