/* The Full User Database keeps itself up to date (bug report 2026-09-11).

   The ticket's promise: adding a person, removing one, changing labels or
   pressing Ctrl+Z must show up in the database view at once — no manual
   reload, ever. And the one irreversible action in the window (“Empty
   trash”) must ask before it erases anything.

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

// 0 — the markup the module needs really exists
t('index.html ships the Empty trash button inside the footer', () => {
  ok(/id="userdbEmptyTrash"/.test(html), 'button missing from ui/index.html');
  ok(/id="userdbFoot"/.test(html), 'stats span missing');
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

// 5 — removing a person asks first
t('removing a person asks before anything is deleted', () => {
  reset();
  asked = null;
  answer = false;                              // the user said “no”
  byId.userdbBody.fire('click', {
    target: { dataset: { action: 'delete' }, closest: () => ({ dataset: { nick: 'Mloni' } }) },
    stopPropagation() {},
  });
  ok(asked, 'no question was asked');
  eq(asked.title, 'Remove this person?', 'dialog title');
  eq(calls, [], 'nothing may happen before the answer');
  answer = true;
  HistoryDb.deletePerson('Mloni');
  eq(calls, [['delete', 'Mloni', false]], 'the undoable, soft delete is the one');
});

// 6 — Empty trash asks, then empties the whole trash
t('Empty trash asks, then purges every hidden row and person', () => {
  reset();
  asked = null;
  answer = false;
  HistoryDb.emptyTrash();
  ok(asked, 'no question was asked');
  eq(calls, [], 'a refused question must not purge');
  answer = true;
  HistoryDb.emptyTrash();
  eq(calls, [['purge', '']], 'an empty nick sweeps the whole trash');
});

// 7 — without a dialog (headless) the actions still reach the backend
t('without a dialog the actions still run', () => {
  reset();
  const saved = window.Dialog;
  window.Dialog = undefined;
  HistoryDb.deletePerson('Bea');
  HistoryDb.emptyTrash();
  window.Dialog = saved;
  eq(calls.map((c) => c[0]), ['delete', 'purge'], 'fallback calls');
});

console.log(failures ? 'FAILED ' + failures : 'all good');
process.exit(failures ? 1 : 0);
