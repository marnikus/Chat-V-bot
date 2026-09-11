/* The Full User Database keeps itself up to date (bug report 2026-09-11).

   The ticket's promise: adding a person, removing one, changing labels or
   pressing Ctrl+Z must show up in the database view at once — no manual
   reload, ever.

   And the user's rule the day after: removing a person asks NOTHING — the
   delete is one undoable step, the rows stay hidden for the rest of the
   session, and the world's own lifecycle erases them (no trash button).

   Per AGENT_RULES RULE 8 this runs the REAL shipped module
   (ui/js/history-db.js) against the REAL ids from ui/index.html, with a
   fake bridge that records every slot call.

   Run:  node tests/test_userdb_refresh.js
*/
'use strict';
const fs = require('fs');
const path = require('path');

const readUi = (f) => fs.readFileSync(path.join(__dirname, '..', 'ui', f),
                                      'utf8');
const html = readUi('index.html');

// ── DOM stub: only what HistoryDb reads, with recorded effects ────
const effects = { clicks: [], scrollTop: 0 };

function mkEl(id) {
  const listeners = {};
  const el = {
    id,
    dataset: {},
    attrs: {},
    children: [],
    scrollTop: 0,
    scrollHeight: 4000,
    clientHeight: 500,
    classList: {
      _set: new Set(),
      add(...c) { c.forEach((x) => this._set.add(x)); },
      remove(...c) { c.forEach((x) => this._set.delete(x)); },
      toggle(c, on) { if (on === undefined) { this._set.has(c) ? this._set.delete(c) : this._set.add(c); } else if (on) this._set.add(c); else this._set.delete(c); },
      contains(c) { return this._set.has(c); },
    },
    get className() { return [...el.classList._set].join(' '); },
    set className(v) { el.classList._set = new Set(String(v).split(/\s+/).filter(Boolean)); },
    textContent: '',
    appendChild(c) { el.children.push(c); return c; },
    addEventListener(ev, fn) { (listeners[ev] = listeners[ev] || []).push(fn); },
    removeEventListener() {},
    querySelectorAll() { return []; },
    querySelector() { return null; },
    scrollIntoView() {},
    fire(ev, arg) { (listeners[ev] || []).forEach((fn) => fn(arg)); },
    click() { effects.clicks.push(id); el.fire('click'); },
  };
  return el;
}

const ids = ['winUserDb', 'userdbList', 'userdbBody', 'userdbSearch',
             'userdbFoot', 'userdbPreload', 'userdbRefreshBtn',
             'userdbEmptyTrash'];
const byId = {};
ids.forEach((id) => { byId[id] = mkEl(id); });
byId.userdbList.scrollTop = 700;

global.document = {
  getElementById: (id) => byId[id] || null,
  querySelectorAll: () => [],
  createElement: (tag) => mkEl('<' + tag + '>'),
  addEventListener() {},
  removeEventListener() {},
};

// A deterministic clock: `flushTimers()` is one live-change window.
let timers = [];
global.setTimeout = (fn) => { timers.push(fn); return timers.length; };
global.clearTimeout = (id) => { if (id) timers[id - 1] = null; };
const flushTimers = () => { const due = timers; timers = []; due.forEach((fn) => fn && fn()); };

// ── fake bridge: every call the module can make ───────────────────
const calls = [];
global.App = {
  bridge: {
    userdb_page(id, json) { calls.push(['page', id, JSON.parse(json)]); },
    userdb_stats(id) { calls.push(['stats', id]); },
    history_delete_person(nick, hard) { calls.push(['delete', nick, hard]); },
    history_clear_person(nick) { calls.push(['clear', nick]); },
    history_purge_deleted(nick) { calls.push(['purge', nick]); },
  },
};
const pages = () => calls.filter((c) => c[0] === 'page').length;
const reset = () => { calls.length = 0; };

// ── the dialog: records the question, answers only when told ──────
let asked = null;
let answer = true;
global.window = {
  Dialog: {
    confirm(title, text, okLabel, onYes) {
      asked = { title, text, okLabel };
      if (answer) onYes();
    },
  },
};

// ── load the REAL module ──────────────────────────────────────────
const load = (file, name) => new Function(readUi(file) + '\nreturn ' + name + ';')();
const HistoryDb = load('js/history-db.js', 'HistoryDb');

// ── tiny test runner ──────────────────────────────────────────────
let failures = 0;
function t(name, fn) {
  try { fn(); console.log('  ok  ' + name); }
  catch (err) { failures++; console.log('  FAIL ' + name + '\n       ' + err.message); }
}
function eq(actual, expected, what) {
  if (JSON.stringify(actual) !== JSON.stringify(expected))
    throw new Error((what || 'value') + ': expected ' + JSON.stringify(expected) +
                    ', got ' + JSON.stringify(actual));
}
function ok(value, what) { if (!value) throw new Error(what || 'expected truthy'); }

console.log('Full User Database — live refresh + delete safety');

// 0 — the markup the module needs really exists, and nothing more
t('the footer is a stats line — no trash button to press', () => {
  ok(/id="userdbFoot"/.test(html), 'stats line missing');
  ok(!/userdbEmptyTrash/.test(html),
     'the DB window must not ship a trash button: the trash empties itself');
});

// 1 — boot asks for a page and for stats
t('the window loads a page and the stats when it starts', () => {
  reset();
  HistoryDb.init();
  eq(calls.map((c) => c[0]), ['page', 'stats'], 'boot requests');
  eq(calls[0][2].offset, 0, 'first page offset');
  eq(calls[0][2].sort, 'last', 'default sort travels with the request');
});

// 2 — one live change refreshes; a burst refreshes once
t('a burst of live changes reloads exactly once, after the quiet window', () => {
  reset();
  HistoryDb.liveChanged('appended');
  HistoryDb.liveChanged('appended');
  HistoryDb.liveChanged('appended');
  eq(pages(), 0, 'no request before the batch closes');
  flushTimers();
  eq(pages(), 1, 'one request for the whole burst');
});

// 3 — a live change keeps the reader where they were
t('a live change never throws the reader back to the top', () => {
  byId.userdbList.scrollTop = 700;
  reset();
  HistoryDb.liveChanged('appended');
  flushTimers();
  eq(byId.userdbList.scrollTop, 700, 'scroll position after a live reload');
});

// 4 — a named change is immediate and beats the batch
t('a named change reloads at once and cancels the pending batch', () => {
  reset();
  HistoryDb.liveChanged('labels');
  HistoryDb.onChanged();                       // undo / delete / db switch
  eq(pages(), 1, 'immediate request');
  flushTimers();
  eq(pages(), 1, 'the batch must not fire a second time');
  eq(byId.userdbList.scrollTop, 0, 'a named change starts from the top');
});

// 5 — removing a person happens at once, without a dialog
t('removing a person deletes straight away — one undoable step', () => {
  reset();
  asked = null;
  byId.userdbBody.fire('click', {
    target: { dataset: { action: 'delete' }, closest: () => ({ dataset: { nick: 'Mloni' } }) },
    stopPropagation() {},
  });
  eq(asked, null, 'no dialog may stand in the way');
  eq(calls, [['delete', 'Mloni', false]],
     'the soft, undoable delete is the one that runs');
});

// 5b — and the trash is not the user's job
t('the delete asks no question even when a dialog is available', () => {
  reset();
  asked = null;
  answer = true;
  HistoryDb.deletePerson('Bea');
  eq(asked, null, 'no confirmation for a person delete');
  eq(calls, [['delete', 'Bea', false]], 'the delete still reached the backend');
});

// 6 — the module owns no purge path any more
t('the window never purges by itself — no button, no method', () => {
  eq(typeof HistoryDb.emptyTrash, 'undefined',
     'the trash is emptied by the world lifecycle, not by this window');
  reset();
  byId.userdbList.fire('scroll');
  eq(calls.filter((c) => c[0] === 'purge'), [], 'nothing purged on its own');
});

// 7 — a restart fills the window without the refresh button (bug 2026-09-11)
// The page boots while the backend is still opening the world, so the first
// page request comes back empty (or never answers). The backend announces the
// live world once it is ready and JS runs `onChanged()`; that reload must not
// be swallowed by the request still marked as loading.
t('the world-ready broadcast reloads even after an unanswered boot request',
  () => {
    reset();
    HistoryDb.loading = false;
    HistoryDb.init();                    // boot: asks while the world is closed
    eq(pages(), 1, 'the boot request went out');
    HistoryDb.loading = true;            // the backend never answered it
    HistoryDb.onChanged();               // … then the world became ready
    eq(pages(), 2, 'the ready broadcast asks again, by itself');
  });

// 8 — the same broadcast is what the People table reacts to: the module must
// stay callable without a refresh button, i.e. reload() is the only entry
t('reload() is enough — no button press is ever required', () => {
  reset();
  HistoryDb.reload();
  eq(calls.map((c) => c[0]), ['page', 'stats'], 'one reload, one load');
});

console.log(failures ? 'FAILED ' + failures : 'all good');
process.exit(failures ? 1 : 0);
