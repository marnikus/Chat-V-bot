/* Tests for the history renderer (ui/js/history-view.js).

   The renderer turns model rows into DOM. What matters here is safety and
   the promises made to the user: message text is inserted as TEXT (never
   markup — chat text is hostile input), the text stays selectable, images
   and GIFs copy on a plain left click, and every view names both the
   partner and my nick.

   Per AGENT_RULES RULE 8 this executes the REAL shipped module in Node
   against a DOM stub, and asserts against the REAL shipped CSS.

   Run:  node tests/test_history_render.js
*/
'use strict';
const fs = require('fs');
const path = require('path');

// ── DOM stub ─────────────────────────────────────────────────────

function mkEl(tag) {
  const listeners = {};
  const el = {
    tagName: String(tag).toUpperCase(),
    _text: '',
    children: [],
    parentNode: null,
    style: {},
    dataset: {},
    attrs: {},
    title: '',
    listeners,
    classList: {
      _set: new Set(),
      add(...c) { c.forEach((x) => this._set.add(x)); },
      remove(...c) { c.forEach((x) => this._set.delete(x)); },
      toggle(c, on) { on ? this._set.add(c) : this._set.delete(c); },
      contains(c) { return this._set.has(c); },
      get value() { return [...this._set].join(' '); },
    },
    get className() { return [...el.classList._set].join(' '); },
    set className(v) {
      el.classList._set = new Set(String(v).split(/\s+/).filter(Boolean));
    },
    get textContent() {
      return el._text + el.children.map((c) => c.textContent).join('');
    },
    set textContent(v) { el._text = String(v); el.children = []; },
    set innerHTML(v) { throw new Error('innerHTML is forbidden in the renderer'); },
    get innerHTML() { return ''; },
    appendChild(c) { el.children.push(c); c.parentNode = el; return c; },
    append(...cs) { cs.forEach((c) => el.appendChild(
      typeof c === 'string' ? mkText(c) : c)); },
    removeChild(c) {
      const i = el.children.indexOf(c);
      if (i >= 0) el.children.splice(i, 1);
      return c;
    },
    replaceChildren(...cs) { el.children = []; el.append(...cs); },
    setAttribute(k, v) { el.attrs[k] = String(v); if (k === 'src') el.src = v; },
    getAttribute(k) { return k in el.attrs ? el.attrs[k] : null; },
    addEventListener(ev, fn) { (listeners[ev] = listeners[ev] || []).push(fn); },
    removeEventListener() {},
    querySelector(sel) { return findAll(el, sel)[0] || null; },
    querySelectorAll(sel) { return findAll(el, sel); },
    click(evt) {
      (listeners.click || []).forEach((fn) => fn(Object.assign(
        { target: el, button: 0, preventDefault() {}, stopPropagation() {} },
        evt || {})));
    },
    scrollIntoView() {},
  };
  return el;
}
function mkText(s) { const n = mkEl('#text'); n._text = s; return n; }
function walk(el, out) {
  out = out || [];
  el.children.forEach((c) => { out.push(c); walk(c, out); });
  return out;
}
function findAll(el, sel) {
  const parts = String(sel).trim().split(/\s+/);
  const last = parts[parts.length - 1];
  return walk(el).filter((n) => {
    if (last.startsWith('.')) return n.classList.contains(last.slice(1));
    if (last.startsWith('[')) {
      const m = /\[([\w-]+)/.exec(last);
      return n.getAttribute(m[1]) !== null || (m[1] in n.dataset);
    }
    return n.tagName === last.toUpperCase();
  });
}

global.document = {
  createElement: mkEl,
  createTextNode: mkText,
  getElementById: () => mkEl('div'),
  querySelector: () => null,
  querySelectorAll: () => [],
  addEventListener() {},
};
global.window = global;

// ── load the real modules ────────────────────────────────────────

const readUi = (f) => fs.readFileSync(
  path.join(__dirname, '..', 'ui', f), 'utf8');

const modelSrc = readUi('js/history-model.js');
const modelMod = { exports: {} };
new Function('module', 'exports', modelSrc)(modelMod, modelMod.exports);
global.HistoryModel = modelMod.exports;

const viewSrc = readUi('js/history-view.js');
const V = new Function('window', 'document', 'HistoryModel',
                       viewSrc + '\nreturn HistoryView;')(
  global.window, global.document, global.HistoryModel);

const css = readUi('css/history.css');

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

const row = (over) => Object.assign({
  ord: 1, fp: 'fp1', dir: 'in', from: 'Nick', kind: 'text', text: 'привет',
  media: null, time: '17:31', day: '2026-09-06',
}, over || {});

const ctx = (over) => Object.assign(
  { nick: 'Nick', myNick: 'Me', showImages: true }, over || {});

function renderInto(rows, opts) {
  const host = mkEl('div');
  V.renderRows(host, rows.map((r) => HistoryModel.toRow(r, ctx(opts))),
               Object.assign({}, ctx(opts), opts || {}));
  return host;
}

// ── text safety ──────────────────────────────────────────────────

t('message text is inserted as text, never as markup', () => {
  const host = renderInto([row({ text: '<b>bold</b><img src=x onerror=1>' })]);
  const body = host.querySelector('.msg-text');
  eq(body.textContent, '<b>bold</b><img src=x onerror=1>');
  eq(walk(body).filter((n) => n.tagName === 'IMG').length, 0,
     'no element may be created from the text');
});

t('the renderer file never uses innerHTML', () => {
  ok(!/innerHTML/.test(viewSrc), 'history-view.js must not touch innerHTML');
});

t('neither does the rest of the archive UI', () => {
  for (const f of ['js/history-store.js', 'js/history-db.js',
                   'js/collector-panel.js']) {
    ok(!/innerHTML/.test(readUi(f)), f + ' must not touch innerHTML');
  }
});

t('a nick is rendered as text too', () => {
  const host = renderInto([row({ from: '<script>x</script>' })]);
  eq(host.querySelector('.msg-author').textContent, '<script>x</script>');
});

// ── the row itself ───────────────────────────────────────────────

t('an incoming and an outgoing row are visually distinguishable', () => {
  const host = renderInto([row({ dir: 'in', from: 'Nick' }),
                           row({ ord: 2, fp: 'fp2', dir: 'out', from: 'Me' })]);
  const items = host.querySelectorAll('.msg');
  eq(items.length, 2);
  ok(items[0].classList.contains('in'), 'incoming class');
  ok(items[1].classList.contains('out'), 'outgoing class');
});

t('every row shows author and time', () => {
  const host = renderInto([row()]);
  eq(host.querySelector('.msg-author').textContent, 'Nick');
  eq(host.querySelector('.msg-time').textContent, '17:31');
});

t('rows carry their ord and fingerprint for anchoring', () => {
  const host = renderInto([row({ ord: 42, fp: 'abc' })]);
  const el = host.querySelector('.msg');
  eq(String(el.dataset.ord), '42');
  eq(el.dataset.fp, 'abc');
});

t('day separators are drawn between groups', () => {
  const host = mkEl('div');
  V.renderGroups(host, HistoryModel.groupByDay(
    [row({ day: '2026-09-05' }), row({ ord: 2, fp: 'f2', day: '2026-09-06' })],
    { today: '2026-09-06' }), ctx());
  eq(host.querySelectorAll('.day-sep').length, 2);
});

t('a gap marker is rendered and explains itself', () => {
  const host = mkEl('div');
  V.renderRows(host, [{ type: 'gap', ord: 10, reason: 'alignment_lost' }], ctx());
  const gap = host.querySelector('.msg-gap');
  ok(gap, 'a gap row is drawn');
  ok(/gap|missing|пропуск/i.test(gap.textContent), gap.textContent);
});

// ── media ────────────────────────────────────────────────────────

t('an image row renders an img with the archived url', () => {
  const host = renderInto([row({ kind: 'image', text: '',
                                 media: { id: 3, url: 'https://x/y.jpg',
                                          kind: 'image' } })]);
  const img = host.querySelector('.msg-media');
  ok(img, 'a media element is drawn');
  eq(String(img.dataset.mediaId), '3');
});

t('with images turned off only a placeholder is drawn', () => {
  const host = renderInto([row({ kind: 'image', text: '',
                                 media: { id: 3, url: 'https://x/y.jpg',
                                          kind: 'image' } })],
                          { showImages: false });
  eq(host.querySelectorAll('img').length, 0, 'no image is loaded');
  ok(/image|gif/i.test(host.querySelector('.msg-media-off').textContent),
     'a placeholder tells the user what it is');
});

t('a left click on media asks the bridge to copy it', () => {
  const copied = [];
  const host = mkEl('div');
  V.renderRows(host, [HistoryModel.toRow(
    row({ kind: 'gif', text: '', media: { id: 9, url: 'https://x/y.gif',
                                          kind: 'gif' } }), ctx())],
    Object.assign(ctx(), { onCopyMedia: (id) => copied.push(id) }));
  host.querySelector('.msg-media').click({ button: 0 });
  eq(copied, [9], 'a plain left click copies');
});

t('a click elsewhere in the row copies nothing', () => {
  const copied = [];
  const host = mkEl('div');
  V.renderRows(host, [HistoryModel.toRow(row(), ctx())],
               Object.assign(ctx(), { onCopyMedia: (id) => copied.push(id) }));
  host.querySelector('.msg').click({ button: 0 });
  eq(copied, [], 'text rows have nothing to copy on click');
});

// ── the header names both people ─────────────────────────────────

t('the header shows the partner and my nick', () => {
  const host = mkEl('div');
  V.renderHeader(host, { nick: 'Ангелина', myNick: 'HiHoney',
                         stats: { messages: 120, first_day: '2026-08-01',
                                  last_day: '2026-09-06' } });
  const text = host.textContent;
  ok(text.includes('Ангелина'), 'partner nick: ' + text);
  ok(text.includes('HiHoney'), 'my nick: ' + text);
  ok(text.includes('120'), 'the message count is shown');
});

t('the header survives a person with no stats yet', () => {
  const host = mkEl('div');
  V.renderHeader(host, { nick: 'Nick', myNick: '', stats: null });
  ok(host.textContent.includes('Nick'), 'still names the partner');
});

// ── search results ───────────────────────────────────────────────

t('search hits are highlighted without markup injection', () => {
  const host = mkEl('div');
  V.renderRows(host, [HistoryModel.toRow(row({ text: 'привет <b>мир</b>' }),
                                         ctx())],
               Object.assign(ctx(), { query: 'мир' }));
  const body = host.querySelector('.msg-text');
  eq(body.textContent, 'привет <b>мир</b>', 'the text is unchanged');
  const hits = body.querySelectorAll('.hit');
  eq(hits.length, 1);
  eq(hits[0].textContent, 'мир');
});

t('global search results are grouped per nick', () => {
  const host = mkEl('div');
  V.renderSearchGroups(host, [
    { nick: 'Nick', items: [{ ord: 3, snippet: 'hello' }] },
    { nick: 'Other', items: [{ ord: 9, snippet: 'hi' }, { ord: 10, snippet: 'yo' }] },
  ], ctx());
  eq(host.querySelectorAll('.search-group').length, 2);
  eq(host.querySelectorAll('.search-hit').length, 3);
  ok(host.textContent.includes('Other'), 'each group names its person');
});

// ── the shipped stylesheet keeps the promises ────────────────────

t('history text is selectable and copyable', () => {
  ok(/user-select\s*:\s*text/.test(css), 'the stylesheet must allow selection');
  ok(!/\.msg[^{]*\{[^}]*user-select\s*:\s*none/.test(css),
     'and must not disable it on messages');
});

t('media shows a copy affordance', () => {
  ok(/\.msg-media[^{]*\{[^}]*cursor\s*:\s*(copy|pointer)/.test(css),
     'the cursor must hint that a click copies');
});

t('the collector status has a style per state', () => {
  for (const state of ['collecting', 'collected', 'idle', 'off', 'error']) {
    ok(new RegExp('\\.state-' + state + '\\b').test(css),
       'missing style for state ' + state);
  }
});

// ── reporting ────────────────────────────────────────────────────

console.log('history_render: ' + passed + ' passed, ' + failed + ' failed');
if (failed) process.exit(1);
console.log('OK');
