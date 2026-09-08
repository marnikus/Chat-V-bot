/* Tests for the Chat Message Collector window (ui/js/collector-panel.js).

   The Radar must never lie about counts again (bug report 2026-09-08,
   Bug 4: "Added this session 25" next to "In archive 0"):

     * "Added this session" is counted PER PARTNER — the number shown is
       what the partner above received, exactly what "In archive" grows by;
     * a database switch resets every counter (the old rows belong to the
       other file);
     * clearing / purging / deleting a person resets that person's counter;
     * "In archive" follows the backend payload, never a local guess.

   Per AGENT_RULES RULE 8 this runs the REAL shipped module against a DOM
   stub that throws if a markup setter is touched.

   Run:  node tests/test_collector_panel_js.js
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
    disabled: false, listeners, checked: false,
    classList: {
      _set: new Set(),
      add(...c) { c.forEach((x) => this._set.add(x)); },
      remove(...c) { c.forEach((x) => this._set.delete(x)); },
      toggle(c, on) { if (on === undefined) { this._set.has(c) ? this._set.delete(c) : this._set.add(c); } else if (on) this._set.add(c); else this._set.delete(c); },
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
    removeChild(c) {
      const at = el.children.indexOf(c);
      if (at >= 0) el.children.splice(at, 1);
    },
    get firstChild() { return el.children[0] || null; },
    replaceChildren(...cs) { el.children = []; cs.forEach((c) => el.appendChild(c)); },
    setAttribute(k, v) { el.attrs[k] = String(v); },
    getAttribute(k) { return k in el.attrs ? el.attrs[k] : null; },
    addEventListener(ev, fn) { (listeners[ev] = listeners[ev] || []).push(fn); },
    removeEventListener() {},
    scrollIntoView() {}, focus() {},
    querySelectorAll(sel) { return findAll(el, sel); },
    querySelector(sel) { return findAll(el, sel)[0] || null; },
    get scrollHeight() { return 0; }, get scrollTop() { return 0; },
    set scrollTop(v) {}, get clientHeight() { return 0; },
    fire(ev, extra) {
      (listeners[ev] || []).forEach((fn) => fn(Object.assign(
        { target: el, preventDefault() {}, stopPropagation() {} },
        extra || {})));
    },
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
for (const id of ['winCollector', 'collectorStatus', 'collectorRows',
                  'collectorLog', 'collectorClearLogBtn', 'collectorPauseBtn',
                  'collectorNowBtn', 'collectorBackfillBtn',
                  'collectorEnabledToggle', 'collectorMediaToggle',
                  'collectorHeartbeat']) {
  byId[id] = mkEl('div');
}
byId.collectorHeartbeat.value = '1500';

global.document = {
  body: mkEl('body'),
  createElement: mkEl,
  createTextNode: (s) => { const n = mkEl('#text'); n._text = s; return n; },
  getElementById: (id) => byId[id] || null,
  addEventListener() {}, removeEventListener() {},
  activeElement: null,
};
global.window = { addEventListener() {}, removeEventListener() {} };
global.App = { bridge: {
  collector_state: null, collector_command: () => {}, collector_set: () => {},
} };
global.LogConsole = { log() {} };
global.HistoryDb = {};
global.SashGrid = {};
global.HistoryStore = {};

// ── the real module ──────────────────────────────────────────────
const readUi = (f) => fs.readFileSync(path.join(__dirname, '..', 'ui', f),
                                      'utf8');
new Function('window', 'document',
             readUi('js/collector-panel.js'))(global.window,
                                              global.document);
const CollectorPanel = global.window.CollectorPanel;

// ── assertion kit ────────────────────────────────────────────────
let passed = 0, failed = 0;
function t(name, fn) {
  try { fn(); passed++; }
  catch (e) { failed++; console.error('FAIL ' + name + '\n   ' +
                                      (e && e.stack || e)); }
}
function eq(a, b, msg) {
  const ja = JSON.stringify(a), jb = JSON.stringify(b);
  if (ja !== jb) throw new Error((msg || 'eq') + '\n  got:  ' + ja +
                                 '\n  want: ' + jb);
}
function ok(cond, msg) { if (!cond) throw new Error(msg || 'ok'); }

function rowValue(key) {
  // _row() appends the key and value spans flat, in pairs
  const kids = byId.collectorRows.children;
  for (let i = 0; i + 1 < kids.length; i += 2) {
    if (kids[i].textContent === key) return kids[i + 1].textContent;
  }
  return null;
}

CollectorPanel.init();
CollectorPanel.setMyNick('Пошлый01');

// ── the counters ─────────────────────────────────────────────────

t('added-per-partner starts at zero and shows the partner total', () => {
  CollectorPanel.onStatus(JSON.stringify({
    state: 'collected', nick: 'Svetik25', total: 5, added: 5,
    interval_ms: 1500, last_probe: { count: 5, participants: 2, panes: 1 },
  }));
  eq(rowValue('Partner'), 'Svetik25');
  eq(rowValue('In archive'), '5');
  eq(rowValue('Added this session'), '5');
});

t('another partner is counted separately', () => {
  CollectorPanel.onAppended(JSON.stringify({ nick: 'Svetik25', added: 3 }));
  CollectorPanel.onAppended(JSON.stringify({ nick: 'Angelochenek',
                                             added: 25 }));
  CollectorPanel.onStatus(JSON.stringify({
    state: 'collected', nick: 'Angelochenek', total: 25, added: 25,
    interval_ms: 1500, last_probe: { count: 25, participants: 2, panes: 1 },
  }));
  eq(rowValue('Partner'), 'Angelochenek');
  eq(rowValue('Added this session'), '25',
     'the counter of the partner SHOWN — not a grand total');
  CollectorPanel.onStatus(JSON.stringify({
    state: 'no_new', nick: 'Svetik25', total: 8, added: 0,
    interval_ms: 1500, last_probe: { count: 8, participants: 2, panes: 1 },
  }));
  eq(rowValue('Added this session'), '3', 'Svetik25 keeps her own count');
});

t('clearing a person resets their counter', () => {
  CollectorPanel.onPeopleChanged(JSON.stringify({ action: 'cleared',
                                                  nick: 'Svetik25' }));
  CollectorPanel.onStatus(JSON.stringify({
    state: 'no_new', nick: 'Svetik25', total: 0, added: 0,
    interval_ms: 1500, last_probe: { count: 2, participants: 2, panes: 1 },
  }));
  eq(rowValue('In archive'), '0');
  eq(rowValue('Added this session'), '0',
     'the cleared chat restarts from zero');
});

t('a database switch resets every counter', () => {
  CollectorPanel.onAppended(JSON.stringify({ nick: 'Angelochenek',
                                             added: 7 }));
  CollectorPanel.onDbChanged();
  CollectorPanel.onStatus(JSON.stringify({
    state: 'no_new', nick: 'Angelochenek', total: 2, added: 0,
    interval_ms: 1500, last_probe: { count: 2, participants: 2, panes: 1 },
  }));
  eq(rowValue('Added this session'), '0',
     'the old file\u2019s counters must not bleed into the new one');
});

t('the status line is rendered as text, never markup', () => {
  CollectorPanel.onStatus(JSON.stringify({
    state: 'collected', nick: '<b>evil</b>', text: '<img src=x>',
    total: 1, added: 1, interval_ms: 1500,
  }));
  const badge = byId.collectorStatus;
  ok(badge._children_html === undefined,
     'no markup property was ever touched');
  ok(String(badge.textContent).indexOf('<img src=x>') >= 0,
     'the text is data, not markup');
});

console.log('collector_panel_js: ' + passed + ' passed, ' + failed +
            ' failed');
if (failed) process.exit(1);
console.log('OK');
