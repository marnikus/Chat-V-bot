/* Tests for the DB Connection window (ui/js/db-panel.js).

   The window must answer three questions at a glance — how big is the
   database, how big is the text, how big is the images folder — and must
   never let the user destroy data without a way back: delete and clean go
   through the in-app confirmation and say that db_trash keeps a copy.

   Per AGENT_RULES RULE 8 this executes the REAL shipped module against a
   DOM stub that throws if a markup setter is touched (a database file name
   is user text).

   Run:  node tests/test_db_panel_js.js
*/
'use strict';
const fs = require('fs');
const path = require('path');

// ── DOM stub ─────────────────────────────────────────────────────
const byId = {};
function mkEl(tag) {
  const listeners = {};
  const el = {
    tagName: String(tag).toUpperCase(),
    _text: '', children: [], parentNode: null,
    style: {}, dataset: {}, attrs: {}, title: '', type: '', value: '',
    disabled: false, listeners,
    classList: {
      _set: new Set(),
      add(...c) { c.forEach((x) => this._set.add(x)); },
      remove(...c) { c.forEach((x) => this._set.delete(x)); },
      toggle(c, on) { if (on) this._set.add(c); else this._set.delete(c); },
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
    set innerHTML(v) { throw new Error('innerHTML is forbidden here'); },
    appendChild(c) { el.children.push(c); c.parentNode = el; return c; },
    replaceChildren(...cs) { el.children = []; cs.forEach((c) => el.appendChild(c)); },
    setAttribute(k, v) { el.attrs[k] = String(v); },
    getAttribute(k) { return k in el.attrs ? el.attrs[k] : null; },
    addEventListener(ev, fn) { (listeners[ev] = listeners[ev] || []).push(fn); },
    removeEventListener() {},
    querySelectorAll(sel) { return findAll(el, sel); },
    querySelector(sel) { return findAll(el, sel)[0] || null; },
    fire(ev, extra) {
      (listeners[ev] || []).forEach((fn) => fn(Object.assign(
        { target: el, preventDefault() {}, stopPropagation() {} }, extra || {})));
    },
    click() { el.fire('click'); },
    focus() {},
  };
  return el;
}
function walk(el, out) {
  out = out || [];
  el.children.forEach((c) => { out.push(c); walk(c, out); });
  return out;
}
function findAll(el, sel) {
  const last = String(sel).trim().split(/\s+/).pop();
  return walk(el).filter((n) => last.startsWith('.')
    ? n.classList.contains(last.slice(1))
    : n.tagName === last.toUpperCase());
}
global.document = {
  body: mkEl('body'),
  createElement: mkEl,
  createTextNode: (s) => { const n = mkEl('#text'); n._text = s; return n; },
  getElementById: (id) => byId[id] || null,
  addEventListener() {}, removeEventListener() {},
};
global.window = { addEventListener() {}, removeEventListener() {} };

// ── the real module ──────────────────────────────────────────────
const readUi = (f) => fs.readFileSync(path.join(__dirname, '..', 'ui', f), 'utf8');
const mod = { exports: {} };
new Function('module', 'exports', 'window', 'document',
             readUi('js/db-panel.js'))(mod, mod.exports, global.window,
                                       global.document);
const DbPanel = mod.exports;

const calls = [];
const confirms = [];
global.PresetsUI = {
  confirm(title, text, okLabel, onYes) {
    confirms.push({ title, text, okLabel });
    onYes();                       // the user says yes
  },
};
global.App = {
  bridge: {
    db_info: (id) => calls.push(['db_info', id]),
    db_create: (name) => calls.push(['db_create', name]),
    db_load: (p) => calls.push(['db_load', p]),
    db_delete: (p) => calls.push(['db_delete', p]),
    db_clean: () => calls.push(['db_clean']),
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

const INFO = {
  req_id: 'db-1',
  path: '/app/history.db', name: 'history.db', connected: true,
  db_bytes: 5 * 1024 * 1024, text_bytes: 900 * 1024,
  media_dir: '/app/saved_media', media_bytes: 12 * 1024 * 1024, media_files: 34,
  persons: 12, messages: 4211, messages_hidden: 7,
  total_bytes: 17 * 1024 * 1024,
  items: [
    { path: '/app/history.db', name: 'history.db', bytes: 5 * 1024 * 1024,
      exists: true, active: true },
    { path: '/app/work.db', name: 'work.db', bytes: 2048, exists: true,
      active: false },
  ],
};

function build() {
  Object.keys(byId).forEach((k) => delete byId[k]);
  ['winDbconn', 'dbActivePath', 'dbStatsGrid', 'dbFileList', 'dbCreateBtn',
   'dbCleanBtn', 'dbRefreshBtn', 'dbConnStatus',
  ].forEach((id) => { byId[id] = mkEl('div'); });
  byId.dbNewNameInput = mkEl('input');
  DbPanel._wired = false;
  DbPanel.info = null;
  DbPanel.items = [];
  DbPanel.activePath = '';
  calls.length = 0;
  confirms.length = 0;
  DbPanel.init();
  DbPanel.onInfo(DbPanel._pending, JSON.stringify(
    Object.assign({}, INFO, { req_id: DbPanel._pending })));
  calls.length = 0;
}

// ── sizes ────────────────────────────────────────────────────────
t('bytes are shown in units a human reads', () => {
  eq(DbPanel.bytes(0), '0 B');
  eq(DbPanel.bytes(999), '999 B');
  eq(DbPanel.bytes(1536), '1.5 KB');
  eq(DbPanel.bytes(5 * 1024 * 1024), '5.0 MB');
  eq(DbPanel.bytes(3 * 1024 * 1024 * 1024), '3.0 GB');
  eq(DbPanel.bytes(17 * 1024 * 1024), '17 MB', 'no needless decimals');
});

t('the window shows the full size, the text size and the images folder', () => {
  build();
  const text = byId.dbStatsGrid.textContent;
  ok(/Full DB size/.test(text), text);
  ok(/17 MB/.test(text), 'the total is shown: ' + text);
  ok(/Text size/.test(text), text);
  ok(/900 KB/.test(text), 'the text size is shown: ' + text);
  ok(/Images folder/.test(text), text);
  ok(/12 MB/.test(text), 'the images folder size is shown: ' + text);
  ok(/34 file/.test(text), 'and how many files: ' + text);
});

t('the connected database is named with a live dot', () => {
  build();
  ok(/history\.db/.test(byId.dbActivePath.textContent));
  ok(byId.dbActivePath.querySelector('.db-dot').classList.contains('on'));
});

t('hidden messages are reported so an undo is discoverable', () => {
  build();
  ok(/Hidden/.test(byId.dbStatsGrid.textContent));
  ok(/Hidden7/.test(byId.dbStatsGrid.textContent.replace(/\s+/g, '')),
     'the count sits next to the label');
});

// ── the list ─────────────────────────────────────────────────────
t('every database file is listed, the active one marked', () => {
  build();
  const rows = byId.dbFileList.querySelectorAll('.db-row');
  eq(rows.length, 2);
  ok(rows[0].classList.contains('active'));
  ok(/connected/.test(rows[0].textContent), rows[0].textContent);
});

t('the connected database cannot be loaded again', () => {
  build();
  const rows = byId.dbFileList.querySelectorAll('.db-row');
  eq(rows[0].querySelectorAll('.btn-small').filter(
    (b) => b.textContent === 'Load').length, 0);
});

t('another database can be loaded with one click', () => {
  build();
  const rows = byId.dbFileList.querySelectorAll('.db-row');
  rows[1].querySelectorAll('.btn-small')
    .filter((b) => b.textContent === 'Load')[0].click();
  eq(calls[0], ['db_load', '/app/work.db']);
});

t('an empty folder says so instead of showing nothing', () => {
  build();
  DbPanel.items = [];
  DbPanel.render();
  ok(/No other database/i.test(byId.dbFileList.textContent),
     byId.dbFileList.textContent);
});

// ── the actions ──────────────────────────────────────────────────
t('creating needs a name and sends it once', () => {
  build();
  byId.dbNewNameInput.value = '  work  ';
  byId.dbCreateBtn.click();
  eq(calls[0], ['db_create', 'work']);
  eq(byId.dbNewNameInput.value, '');
});

t('creating without a name explains instead of failing silently', () => {
  build();
  byId.dbNewNameInput.value = '';
  byId.dbCreateBtn.click();
  eq(calls.length, 0);
  ok(/name/i.test(byId.dbConnStatus.textContent), byId.dbConnStatus.textContent);
});

t('deleting is confirmed and promises the trash + undo', () => {
  build();
  const rows = byId.dbFileList.querySelectorAll('.db-row');
  rows[1].querySelectorAll('.btn-small')
    .filter((b) => b.textContent === 'Delete')[0].click();
  eq(confirms.length, 1);
  ok(/db_trash/.test(confirms[0].text), confirms[0].text);
  ok(/Ctrl\+Z/.test(confirms[0].text), confirms[0].text);
  eq(calls[0], ['db_delete', '/app/work.db']);
});

t('cleaning is confirmed and says a backup is kept', () => {
  build();
  byId.dbCleanBtn.click();
  eq(confirms.length, 1);
  ok(/backup/i.test(confirms[0].text), confirms[0].text);
  ok(/Ctrl\+Z/.test(confirms[0].text), confirms[0].text);
  eq(calls[0], ['db_clean']);
});

t('a stale answer for an old request is ignored', () => {
  build();
  DbPanel.onInfo('db-999', JSON.stringify({ total_bytes: 1, items: [] }));
  ok(/17 MB/.test(byId.dbStatsGrid.textContent),
     'the current read-out must survive a late reply');
});

t('an error from the backend is shown, not swallowed', () => {
  build();
  DbPanel.onChanged(JSON.stringify({ ok: false, error: 'file is in use' }));
  ok(/file is in use/.test(byId.dbConnStatus.textContent),
     byId.dbConnStatus.textContent);
});

t('a change triggers a fresh measurement', () => {
  build();
  DbPanel.onChanged('{}');
  ok(calls.some((c) => c[0] === 'db_info'), 'the sizes are re-read');
});

t('without a bridge nothing explodes', () => {
  build();
  const keep = global.App.bridge;
  global.App.bridge = null;
  DbPanel.refresh();
  byId.dbCleanBtn.click();
  global.App.bridge = keep;
});

// ── reporting ────────────────────────────────────────────────────
console.log('db_panel: ' + passed + ' passed, ' + failed + ' failed');
if (failed) process.exit(1);
console.log('OK');
