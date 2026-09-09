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
    db_reveal: (p, cb) => {
      calls.push(['db_reveal', p]);
      cb(JSON.stringify({ ok: true, reveal_path: p }));
    },
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
  DbPanel.busy = false;
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

// ── deletion protection / stale responses / independent create ───

t('last archive has a disabled Delete and a direct call warns without calling Python', () => {
  build();
  DbPanel.items = [INFO.items[0]];
  DbPanel.render();
  const del = byId.dbFileList.querySelectorAll('button').find((b) => b.textContent === 'Delete');
  ok(del.disabled);
  DbPanel.remove(INFO.path);
  eq(calls.length, 0);
  eq(confirms.length, 0);
  eq(byId.dbConnStatus.textContent,
     'Cannot delete the last database. Create a new one first.');
});

t('backend capabilities can refuse deletion even if the client list is stale', () => {
  build();
  DbPanel.items[1] = Object.assign({}, INFO.items[1], { can_delete: false });
  DbPanel.remove(INFO.items[1].path);
  eq(calls.length, 0);
  ok(/Cannot delete/.test(byId.dbConnStatus.textContent));
});

t('missing and protected entries never render as ghost rows', () => {
  build();
  DbPanel.items = [INFO.items[0],
    { path: '/app/new.db', exists: false },
    { path: '/app/undo.db', protected: true },
    { path: '/app/other.db', manageable: false }];
  DbPanel.render();
  eq(byId.dbFileList.querySelectorAll('.db-row').length, 1);
  ok(!/missing|new.db|undo.db/.test(byId.dbFileList.textContent));
});

t('create disables mutation controls and repeated calls send only one request', () => {
  build();
  byId.dbNewNameInput.value = 'new';
  const stale = DbPanel._pending;
  DbPanel.create(); DbPanel.create(); DbPanel.load(INFO.items[1].path); DbPanel.clean();
  eq(calls.filter((c) => c[0] !== 'db_info'), [['db_create', 'new']]);
  ok(byId.dbCreateBtn.disabled && byId.dbCleanBtn.disabled);
  byId.dbFileList.querySelectorAll('button').forEach((b) => ok(b.disabled));
  DbPanel.onInfo(stale, JSON.stringify(INFO));
  ok(DbPanel.busy, 'stale info must not finish a mutation');
  ok(byId.dbCreateBtn.disabled);
});

t('create completion keeps the active database and tells the user to Load', () => {
  build();
  DbPanel.onChanged({ ok: true, op: 'create', path: '/app/new.db', active_path: INFO.path });
  eq(DbPanel.activePath, INFO.path);
  ok(/Click Load/.test(byId.dbConnStatus.textContent));
  DbPanel.onInfo(DbPanel._pending, JSON.stringify(INFO));
  ok(/active database is unchanged/.test(byId.dbConnStatus.textContent));
  ok(!calls.some((c) => c[0] === 'db_load'));
});

t('delete completion removes its row immediately and ignores older list responses', () => {
  build();
  const stale = DbPanel._pending;
  DbPanel.remove(INFO.items[1].path);
  DbPanel.onChanged({ ok: true, op: 'delete', path: INFO.items[1].path, active_path: INFO.path });
  eq(byId.dbFileList.querySelectorAll('.db-row').length, 1);
  DbPanel.onInfo(stale, JSON.stringify(INFO));
  eq(byId.dbFileList.querySelectorAll('.db-row').length, 1);
  const del = byId.dbFileList.querySelectorAll('button').find((b) => b.textContent === 'Delete');
  ok(del.disabled, 'the remaining database is protected immediately');
});

t('an unexpected bridge error releases busy controls and keeps the active database', () => {
  build();
  byId.dbNewNameInput.value = 'new';
  DbPanel.create();
  DbPanel.onError('db_create', 'disk unavailable');
  ok(!DbPanel.busy);
  ok(!byId.dbCreateBtn.disabled);
  eq(DbPanel.activePath, INFO.path);
  ok(/disk unavailable/.test(byId.dbConnStatus.textContent));
});

// ── visible file conflicts and native reveal ─────────────────────
const CONFLICT = {
  path: '/app/m.db', name: 'm.db', exists: true, main_exists: true,
  blocking: true, manageable: false, compatible: false, kind: 'file',
  status: 'empty', detail: 'Empty file (0 bytes); not an initialized chat archive.',
  can_load: false, can_delete: false, can_reveal: true, reveal_path: '/app/m.db',
};

t('a real incompatible file remains visible instead of a ghost name conflict', () => {
  build();
  DbPanel.onChanged({ ok: false, error: 'm.db already exists',
    items: [INFO.items[0], CONFLICT] });
  const rows = byId.dbFileList.querySelectorAll('.db-row');
  eq(rows.length, 2);
  ok(/m.db/.test(rows[1].textContent));
  ok(/Empty file/.test(rows[1].textContent));
  eq(rows[1].querySelectorAll('.btn-small').length, 0, 'read-only, not a load/delete target');
  eq(rows[1].querySelector('.db-row-name').tagName, 'BUTTON');
  ok(rows[1].querySelector('.db-row-name').title.includes('/app/m.db'));
});

t('visible diagnostic rows never unlock last-valid deletion or direct Load calls', () => {
  build();
  DbPanel.items = [INFO.items[0], CONFLICT];
  DbPanel.render();
  const del = byId.dbFileList.querySelectorAll('.btn-small').find((b) => b.textContent === 'Delete');
  ok(del.disabled);
  DbPanel.remove(INFO.path);
  DbPanel.load(CONFLICT.path);
  DbPanel.remove(CONFLICT.path);
  eq(calls.length, 0);
  eq(confirms.length, 0);
});

t('sidecars without a main database stay visible and show the actual blocking path', () => {
  build();
  DbPanel.items = [INFO.items[0], Object.assign({}, CONFLICT, {
    exists: false, main_exists: false, status: 'sidecars',
    detail: 'm.db-wal reserves this name; m.db is missing.', reveal_path: '/app/m.db-wal',
  })];
  DbPanel.render();
  const row = byId.dbFileList.querySelectorAll('.db-row')[1];
  ok(row, 'blocking filesystem entries remain visible even with no main file');
  ok(/Sidecar files only/.test(row.textContent));
  ok(row.querySelector('.db-row-name').title.includes('/app/m.db-wal'));
});

t('filename clicks reveal but never Load, reset, confirm deletion or mark a mutation busy', () => {
  build();
  const row = byId.dbFileList.querySelectorAll('.db-row')[1];
  row.querySelector('.db-row-name').click();
  eq(calls, [['db_reveal', INFO.items[1].path]]);
  eq(confirms.length, 0);
  ok(!DbPanel.busy);
  eq(DbPanel.activePath, INFO.path);
  ok(byId.dbConnStatus.textContent.includes(INFO.items[1].path));
});

t('successful Create renders its new row before a stats response arrives', () => {
  build();
  const added = { path: '/app/new.db', name: 'new.db', exists: true,
    manageable: true, can_load: true, can_delete: true };
  DbPanel.onChanged({ ok: true, op: 'create', path: added.path, active_path: INFO.path,
    items: INFO.items.concat([added]) });
  eq(byId.dbFileList.querySelectorAll('.db-row').map((r) => r.querySelector('.db-row-name').textContent),
     ['history.db', 'work.db', 'new.db']);
  ok(/Click Load/.test(byId.dbConnStatus.textContent));
  eq(DbPanel.activePath, INFO.path);
});

t('a duplicate failure snapshot survives pre-mutation replies and a later measurement', () => {
  build();
  const stale = DbPanel._pending;
  const items = [INFO.items[0], CONFLICT];
  DbPanel.onChanged({ ok: false, error: 'm.db already exists', items });
  DbPanel.onInfo(stale, INFO);
  ok(/m.db/.test(byId.dbFileList.textContent));
  DbPanel.onInfo(DbPanel._pending, Object.assign({}, INFO, { items }));
  ok(/m.db already exists/.test(byId.dbConnStatus.textContent));
  ok(/m.db/.test(byId.dbFileList.textContent));
});

t('a stale measurement cannot undo a change even if the bridge has disappeared', () => {
  build();
  const stale = DbPanel._pending;
  const bridge = App.bridge;
  try {
    App.bridge = null;
    DbPanel.onChanged({ ok: false, error: 'm.db already exists', items: [INFO.items[0], CONFLICT] });
    DbPanel.onInfo(stale, INFO);
    ok(/m.db/.test(byId.dbFileList.textContent));
  } finally { App.bridge = bridge; }
});

t('an inventory-read failure retains the last known file rows with an honest error', () => {
  build();
  DbPanel.onInfo(DbPanel._pending, { path: INFO.path, inventory_error: 'folder is unavailable' });
  eq(byId.dbFileList.querySelectorAll('.db-row').length, 2);
  ok(/folder is unavailable/.test(byId.dbConnStatus.textContent));
});

t('late reveal callbacks cannot overwrite a newer mutation notice', () => {
  build();
  const bridge = App.bridge.db_reveal;
  let finish;
  try {
    App.bridge.db_reveal = (_p, cb) => { finish = cb; };
    DbPanel.reveal(INFO.path);
    DbPanel.onChanged({ ok: true, op: 'create', path: '/app/new.db', active_path: INFO.path });
    finish(JSON.stringify({ ok: true, reveal_path: INFO.path }));
    ok(/Created new.db/.test(byId.dbConnStatus.textContent));
  } finally { App.bridge.db_reveal = bridge; }
});

t('diagnostic names and reasons render as literal text, never markup', () => {
  build();
  const text = '<img src=x onerror="throw new Error()">';
  DbPanel.items = [Object.assign({}, CONFLICT, { name: text, detail: text })];
  DbPanel.render();
  eq(byId.dbFileList.querySelector('.db-row-name').textContent, text);
  ok(byId.dbFileList.querySelector('.db-row-detail').textContent.includes(text));
  eq(byId.dbFileList.querySelectorAll('img').length, 0);
});

// ── reporting ────────────────────────────────────────────────────
console.log('db_panel: ' + passed + ' passed, ' + failed + ' failed');
if (failed) process.exit(1);
console.log('OK');
