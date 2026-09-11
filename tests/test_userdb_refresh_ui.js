/* Tests for the Full User Database window in ui/js/history-db.js
   (bug report "Person DB: Undo Fails to Restore Deleted Person",
   2026-09-11) + its wiring in ui/js/app.js.

Per AGENT_RULES RULE 8 this executes the REAL shipped module in a real
runtime (Node) against a tiny DOM stub — the same pattern as
tests/test_preset_io_ui.js. The backend is stubbed behind App.bridge;
the tests pin what the UI does when pages and change events race:

  * a late STALE page response (an older reload generation) must never
    overwrite a newer view — the exact race that froze the DB list on
    the pre-undo state even though the database had the person back;
  * a change event while a page is in flight must be remembered and the
    reload must happen as soon as the in-flight request settles (never
    dropped by the `loading` guard);
  * onChanged() coalesces an event burst into one reload (250 ms);
  * deletePerson asks the in-app confirm dialog first and only touches
    the bridge after the user confirms;
  * app.js feeds the DB view from users_updated (new person / any people
    change) and from labels_changed, so the list auto-refreshes.

Run:  node tests/test_userdb_refresh_ui.js
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
    title: '',
    value: '',
    scrollTop: 0,
    scrollHeight: 0,
    clientHeight: 0,
    style: {},
    dataset: {},
    className: '',
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
    replaceChildren(...nodes) { this._children = nodes; },
    addEventListener(type, fn) {
      (listeners[type] = listeners[type] || []).push(fn);
    },
    removeEventListener(type, fn) {
      listeners[type] = (listeners[type] || []).filter((f) => f !== fn);
    },
    setAttribute() {},
    querySelectorAll() { return []; },
    focus() {},
  };
}

const elements = {};
global.window = global;
global.document = {
  getElementById(id) { return elements[id] || (elements[id] = makeEl(id)); },
  createElement(tag) {
    const el = makeEl(null);
    el.tagName = tag;
    return el;
  },
  createTextNode(text) { return { textContent: text }; },
  addEventListener() {},
  removeEventListener() {},
};

global.App = { bridge: null };
// the in-app confirm modal — captured, not auto-answered
const dialogAsks = [];
global.Dialog = {
  confirm(title, text, okLabel, onYes) {
    dialogAsks.push({ title, text, okLabel, onYes });
  },
};

// load the REAL shipped module (fresh per test)
function loadHistoryDb() {
  const src = fs.readFileSync(
    path.join(__dirname, '..', 'ui', 'js', 'history-db.js'), 'utf8');
  const fresh = new Function(src + '\nreturn HistoryDb;')();
  global.window.HistoryDb = fresh;
  return fresh;
}

// ── fake bridge: records calls, the test answers pages manually ──
function makeBridge() {
  const calls = { page: [], stats: [], del: [], clear: [] };
  const bridge = {
    userdb_page(id, json) {
      calls.page.push({ id, opts: JSON.parse(json) });
    },
    userdb_stats(id) { calls.stats.push(id); },
    history_delete_person(nick, hard) { calls.del.push([nick, !!hard]); },
    history_clear_person(nick) { calls.clear.push(nick); },
  };
  global.App.bridge = bridge;
  return calls;
}

const pageOf = (nicks, offset) => JSON.stringify({
  items: nicks.map((n) => ({ nick: n, message_count: 1, media_count: 0 })),
  total: nicks.length, has_more: false, offset: offset || 0, limit: 50,
});

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const pageIds = (calls) => calls.page.map((c) => c.id);

// ── tiny assertion kit (async) ───────────────────────────────────
let passed = 0, failed = 0;
const tests = [];
function t(name, fn) { tests.push({ name, fn }); }
function ok(cond, msg) { if (!cond) throw new Error(msg || 'ok'); }
function eq(a, b, msg) {
  const ja = JSON.stringify(a), jb = JSON.stringify(b);
  if (ja !== jb) throw new Error((msg || 'eq') +
    '\n  got:  ' + ja + '\n  want: ' + jb);
}
const nicksOf = (db) => db.rows.map((r) => r.nick);

function reset() {
  dialogAsks.length = 0;
  Object.keys(elements).forEach((k) => delete elements[k]);
}

t('a late stale page response cannot overwrite a newer view', async () => {
  reset();
  const db = loadHistoryDb();
  const calls = makeBridge();
  db.init();                                   // reload #1 (gen 1)
  const first = pageIds(calls)[0];
  db.onPage(first, pageOf(['A', 'B', 'C'], 0));
  eq(nicksOf(db), ['A', 'B', 'C'], 'initial page rendered');

  // two change events in a row: the second one lands while #2 is in flight
  db.reload();                                 // gen 2 — in flight
  const second = pageIds(calls)[1];
  db.reload();                                 // gen 3 — issued right away
  eq(calls.page.length, 3,
     'a reload is never deferred behind an in-flight page');

  // the STALE page (no Mloni) arrives first
  db.onPage(second, pageOf(['A', 'B', 'C'], 0));
  eq(nicksOf(db), ['A', 'B', 'C'], 'stale page is dropped');
  const fresh = pageIds(calls)[2];
  db.onPage(fresh, pageOf(['A', 'B', 'C', 'Mloni'], 0));
  eq(nicksOf(db), ['A', 'B', 'C', 'Mloni'], 'the fresh page wins');
});

t('a change event while a page is in flight is not dropped', async () => {
  reset();
  const db = loadHistoryDb();
  const calls = makeBridge();
  db.init();                                   // gen 1 in flight
  const first = pageIds(calls)[0];
  db.onChanged();                              // debounced while in flight
  await sleep(320);                            // debounce timer fires
  eq(calls.page.length, 2,
     'the reload issued its page while gen 1 was still in flight');
  db.onPage(first, pageOf(['A'], 0));          // gen 1 lands, stale
  const second = pageIds(calls)[1];
  db.onPage(second, pageOf(['A', 'Mloni'], 0));
  eq(nicksOf(db), ['A', 'Mloni'], 'the view shows the post-change state');
});

t('a burst of change events coalesces into one reload', async () => {
  reset();
  const db = loadHistoryDb();
  const calls = makeBridge();
  db.init();                                   // gen 1
  const first = pageIds(calls)[0];
  db.onPage(first, pageOf(['A'], 0));
  db.onChanged();                              // e.g. userdb_changed
  db.onChanged();                              // … and users_updated
  db.onChanged();                              // … and labels_changed
  await sleep(320);
  eq(calls.page.length, 2, 'three events → exactly one extra page request');
  db.onPage(pageIds(calls)[1], pageOf(['A'], 0));
});

t('deletePerson confirms first and only then touches the bridge', async () => {
  reset();
  const db = loadHistoryDb();
  const calls = makeBridge();
  db.init();
  db.onPage(pageIds(calls)[0], pageOf(['Mloni'], 0));

  db.deletePerson('Mloni');
  eq(calls.del, [], 'no delete before the user confirms');
  eq(dialogAsks.length, 1, 'one confirm dialog');
  ok(dialogAsks[0].title.includes('Remove'), 'a real title');
  ok(dialogAsks[0].text.includes('Mloni'), 'names the person');
  ok(dialogAsks[0].text.includes('Ctrl+Z'), 'tells them it is undoable');
  eq(dialogAsks[0].okLabel, 'Remove', 'a distinct, honest button label');
  dialogAsks[0].onYes();
  eq(calls.del, [['Mloni', false]], 'confirmed → soft delete');
});

t('a cancelled confirm deletes nothing', async () => {
  reset();
  const db = loadHistoryDb();
  const calls = makeBridge();
  db.init();
  db.deletePerson('Mloni');
  eq(dialogAsks.length, 1);
  // the user pressed No — onYes is simply never called
  eq(calls.del, [], 'cancel → no bridge call');
});

t('the in-app dialog is used, never window.confirm', async () => {
  const src = fs.readFileSync(
    path.join(__dirname, '..', 'ui', 'js', 'history-db.js'), 'utf8');
  ok(!/window\.confirm|[^.\w]confirm\(/.test(src.replace(
    'Dialog.confirm', '')),
    'no native confirm() anywhere in the DB window');
  ok(src.includes('Dialog.confirm'), 'the in-app Dialog is used');
});

t('app.js feeds the DB view from users_updated and labels_changed', async () => {
  const src = fs.readFileSync(
    path.join(__dirname, '..', 'ui', 'js', 'app.js'), 'utf8');
  // slice each handler up to the NEXT wiring block, so a HistoryDb call
  // in some unrelated later handler cannot satisfy this pin
  const users = src.slice(
    src.indexOf('b.users_updated.connect'),
    src.indexOf('b.users_deleted.connect'));
  const labels = src.slice(
    src.indexOf('b.labels_changed'),
    src.indexOf('b.db_info_ready'));
  ok(users.includes('HistoryDb.onChanged()'),
     'users_updated (new person / any people change) refreshes the DB view');
  ok(labels.includes('HistoryDb.onChanged()'),
     'labels_changed refreshes the DB view');
});

(async () => {
  for (const { name, fn } of tests) {
    try {
      await fn();
      passed++;
    } catch (e) {
      failed++;
      console.error('FAIL ' + name + '\n   ' + (e && e.stack || e));
    }
  }
  console.log(passed + ' passed, ' + failed + ' failed');
  console.log(failed ? 'FAILED' : 'OK');
  process.exit(failed ? 1 : 0);
})();
