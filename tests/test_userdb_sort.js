/* Sortable columns of the Full User Database (BD) — the UI half.

   What the user was promised:
     · every data column header carries a clickable ▲▼ and sorts the table;
     · clicking the same header toggles ascending/descending, clicking another
       header starts in that column's natural direction;
     · the order is asked from Python — the table is server-paged, so sorting
       the rows in memory would only order the page that happens to be loaded;
     · the choice survives every later refresh while the app runs.

   Per AGENT_RULES RULE 8 this executes the REAL shipped modules
   (ui/js/history-db.js, ui/js/core/ui-helpers.js) against a DOM built from
   the REAL <thead> in ui/index.html, and asserts against the REAL CSS.

   Run:  node tests/test_userdb_sort.js
*/
'use strict';
const fs = require('fs');
const path = require('path');

const readUi = (f) => fs.readFileSync(path.join(__dirname, '..', 'ui', f),
                                      'utf8');
const html = readUi('index.html');
const css = readUi('css/history.css');

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
    disabled: false,
    scrollTop: 0,
    scrollHeight: 4000,
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
    get innerHTML() { return ''; },
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
    setAttribute(k, v) {
      el.attrs[k] = String(v);
      if (k.startsWith('data-')) {
        el.dataset[k.slice(5).replace(/-(\w)/g, (_x, c) => c.toUpperCase())] =
          String(v);
      }
      if (k === 'class') el.className = v;
    },
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
        { target: el, button: 0, key: '', preventDefault() {},
          stopPropagation() {} }, extra || {})));
    },
    click(extra) { el.fire('click', extra); },
  };
  return el;
}
function mkText(s) { const n = mkEl('#text'); n._text = String(s); return n; }

/** Compound selector: tag, #id, .class, [attr], [attr="value"]. */
function matches(node, sel) {
  if (!node || !node.classList) return false;
  const s = String(sel).trim();
  const re = /([#.]?[\w-]+)|\[([\w-]+)(?:=["']?([^\]"']*)["']?)?\]/g;
  let m, tag = '', ids = [], classes = [], attrs = [];
  while ((m = re.exec(s))) {
    if (m[2] !== undefined) attrs.push([m[2], m[3]]);
    else if (m[1][0] === '#') ids.push(m[1].slice(1));
    else if (m[1][0] === '.') classes.push(m[1].slice(1));
    else tag = m[1].toLowerCase();
  }
  if (tag && node.tagName.toLowerCase() !== tag) return false;
  for (const id of ids) if (node.attrs.id !== id) return false;
  for (const c of classes) if (!node.classList.contains(c)) return false;
  for (const [name, value] of attrs) {
    const got = node.getAttribute(name);
    if (got === null) return false;
    if (value !== undefined && String(got) !== value) return false;
  }
  return true;
}
function walk(el, out) {
  out = out || [];
  el.children.forEach((c) => { out.push(c); walk(c, out); });
  return out;
}
/** Descendant-combinator support, which is what the modules actually use. */
function findAll(root, sel) {
  const groups = String(sel).split(',');
  const found = [];
  for (const group of groups) {
    const parts = group.trim().split(/\s+/).filter(Boolean);
    if (!parts.length) continue;
    let level = walk(root);
    for (let i = 0; i < parts.length; i++) {
      const hits = level.filter((n) => matches(n, parts[i]));
      if (i === parts.length - 1) {
        hits.forEach((h) => { if (found.indexOf(h) < 0) found.push(h); });
      } else {
        level = hits.reduce((acc, h) => acc.concat(walk(h)), []);
      }
    }
  }
  return found;
}

// ── a real <thead>, parsed out of the shipped page ───────────────

const VOID = new Set(['input', 'br', 'img', 'hr', 'meta', 'link', 'source']);

function parseHtml(src) {
  const root = mkEl('#fragment');
  const stack = [root];
  const re = /<!--[\s\S]*?-->|<\/([a-zA-Z][\w-]*)\s*>|<([a-zA-Z][\w-]*)((?:\s+[^<>]*?)?)(\/?)>|([^<]+)/g;
  let m;
  while ((m = re.exec(src))) {
    if (m[0].startsWith('<!--')) continue;
    if (m[1]) {                                   // closing tag
      for (let i = stack.length - 1; i > 0; i--) {
        if (stack[i].tagName === m[1].toUpperCase()) { stack.length = i; break; }
      }
      continue;
    }
    if (m[2]) {                                   // opening tag
      const el = mkEl(m[2]);
      const attr = /([\w-]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'>]+)))?/g;
      let a;
      while ((a = attr.exec(m[3] || ''))) {
        const value = a[2] !== undefined ? a[2]
          : a[3] !== undefined ? a[3] : a[4] !== undefined ? a[4] : '';
        el.setAttribute(a[1], value);
      }
      stack[stack.length - 1].appendChild(el);
      if (!m[4] && !VOID.has(m[2].toLowerCase())) stack.push(el);
      continue;
    }
    if (m[5] && m[5].trim()) {
      stack[stack.length - 1].appendChild(mkText(m[5]));
    }
  }
  return root;
}

/** The whole Full User Database panel exactly as shipped — toolbar, table
 *  and footer — so the module addresses the real elements. */
function userdbPanelMarkup() {
  const start = html.indexOf('<div class="panel userdb-panel" id="winUserDb"');
  if (start < 0) throw new Error('ui/index.html has no #winUserDb panel');
  if (html.indexOf('<table class="userdb-table" id="userdbTable"', start) < 0)
    throw new Error('ui/index.html has no #userdbTable');
  const foot = html.indexOf('id="userdbFoot"', start);
  if (foot < 0) throw new Error('ui/index.html has no #userdbFoot');
  const end = html.indexOf('</div>', foot) + '</div>'.length;
  return html.slice(start, end);
}

// ── page ─────────────────────────────────────────────────────────

const byId = {};
const page = mkEl('body');
page.appendChild(parseHtml(userdbPanelMarkup()));
['userdbList', 'userdbBody', 'userdbSearch', 'userdbFoot', 'userdbPreload',
 'userdbRefreshBtn', 'winUserDb'].forEach((id) => {
  if (!byId[id]) {
    byId[id] = findAll(page, '#' + id)[0] || null;
  }
});
global.document = {
  body: page,
  createElement: mkEl,
  createTextNode: mkText,
  getElementById(id) {
    if (!(id in byId)) {
      byId[id] = findAll(page, '#' + id)[0] ||
        (html.includes('id="' + id + '"') ? mkEl('div') : null);
    }
    return byId[id];
  },
  querySelector(sel) { return findAll(page, sel)[0] || null; },
  querySelectorAll(sel) { return findAll(page, sel); },
  addEventListener() {},
  removeEventListener() {},
};
global.window = global;
global.getSelection = () => '';
global.requestAnimationFrame = (fn) => fn();
global.CSS = { escape: (s) => s };

// ── bridge stub: records every request, like QWebChannel does ────

const calls = [];
global.App = {
  bridge: {
    userdb_page(reqId, queryJson) { calls.push({ reqId, queryJson }); },
    userdb_stats(reqId) { calls.push({ reqId, stats: true }); },
    history_delete_person() {},
    history_clear_person() {},
  },
};
global.LogConsole = { log() {} };

// ── load the REAL modules ────────────────────────────────────────

const load = (file, name) => new Function(readUi(file) + '\nreturn ' + name + ';')();
global.HistoryDb = load('js/history-db.js', 'HistoryDb');
load('js/core/ui-helpers.js', 'UIHelpers');   // sets window.UIHelpers

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

const pages = () => calls.filter((c) => !c.stats);
const lastQuery = () => JSON.parse(pages()[pages().length - 1].queryJson);
const headers = () => document.querySelectorAll('#userdbTable th[data-sort]');
const thFor = (key) => headers().filter((th) => th.dataset.sort === key)[0];
const arrowOf = (key) => {
  const span = thFor(key).querySelector('.sort-arrow');
  return span ? span.textContent.trim() : null;
};
const ariaOf = (key) => thFor(key).getAttribute('aria-sort');
const rowNicks = () => document.getElementById('userdbBody')
  .querySelectorAll('.userdb-row').map((r) => r.dataset.nick);

/** Deliver a page the way the signal does. */
function answer(items, extra) {
  const req = pages()[pages().length - 1].reqId;
  HistoryDb.onPage(req, JSON.stringify(Object.assign({
    items, total: items.length, has_more: false, offset: 0,
  }, extra || {})));
}
const person = (nick, over) => Object.assign({
  nick, message_count: 1, media_count: 0,
  first_seen: '2026-09-01 10:00:00', last_seen: '2026-09-06 18:00:00',
  my_nicks: ['Me'],
}, over || {});

// ═════════════════════════════════════════════════════════════════
// 1. the markup itself
// ═════════════════════════════════════════════════════════════════

const SORTABLE = ['nick', 'msgs', 'media', 'first', 'last', 'my_nick'];

t('every data column of #userdbTable declares itself sortable', () => {
  eq(headers().map((th) => th.dataset.sort).sort(), SORTABLE.slice().sort());
});

t('each sortable header is a real button carrying a ▲▼ indicator', () => {
  for (const key of SORTABLE) {
    const th = thFor(key);
    ok(th, 'no <th data-sort="' + key + '">');
    const button = th.querySelector('.sort-button');
    ok(button, key + ' has no .sort-button — it would not be focusable');
    eq(button.tagName, 'BUTTON', key + ' must be a <button>');
    eq(button.getAttribute('type'), 'button', key + ' must not submit');
    ok(th.querySelector('.sort-arrow'), key + ' has no .sort-arrow');
    eq(arrowOf(key), '▲▼', key + ' starts with the idle glyph');
    ok(button.textContent.includes(th.textContent.trim().split(/\s+/)[0]),
       key + ' button still shows the column label');
  }
});

t('the Actions column stays a plain label', () => {
  const all = document.querySelectorAll('#userdbTable thead th');
  eq(all.length, SORTABLE.length + 1, 'six sortable columns plus Actions');
  const plain = all.filter((th) => !th.dataset.sort);
  eq(plain.length, 1);
  ok(/Actions/i.test(plain[0].textContent), 'the one plain header is Actions');
  ok(!plain[0].querySelector('.sort-arrow'), 'Actions shows no arrow');
});

t('the stylesheet gives the sortable header an affordance', () => {
  ok(/\.userdb-table\s+th\[data-sort\]/.test(css),
     'history.css must style .userdb-table th[data-sort]');
  ok(/\.userdb-table\s+th\[data-sort\][\s\S]{0,400}cursor:\s*pointer/
       .test(css), 'the header must look clickable');
  ok(/sort-active/.test(css), 'the active column must be accented');
  ok(/\.sort-arrow\s*\{/.test(css), 'the arrow glyph keeps its own style');
});

// ═════════════════════════════════════════════════════════════════
// 2. boot
// ═════════════════════════════════════════════════════════════════

t('the table boots with the historical order and asks Python for it', () => {
  HistoryDb.init();
  eq(HistoryDb.sortKey, 'last', 'the default column is "Last"');
  eq(HistoryDb.sortDir, 'desc', 'newest activity first, as before');
  const request = lastQuery();
  eq(request.sort, 'last');
  eq(request.dir, 'desc');
  eq(request.offset, 0);
});

t('the default header shows the active arrow and nothing else does', () => {
  eq(ariaOf('last'), 'descending');
  eq(arrowOf('last'), '▼');
  ok(thFor('last').classList.contains('sort-active'));
  for (const key of SORTABLE.filter((k) => k !== 'last')) {
    eq(ariaOf(key), 'none', key);
    eq(arrowOf(key), '▲▼', key);
    ok(!thFor(key).classList.contains('sort-active'), key);
  }
});

// ═════════════════════════════════════════════════════════════════
// 3. clicking a header
// ═════════════════════════════════════════════════════════════════

t('clicking Nick asks the backend for the list in nick order', () => {
  const before = pages().length;
  thFor('nick').fire('click');
  eq(pages().length, before + 1, 'a click triggers exactly one request');
  eq(lastQuery().sort, 'nick');
  eq(lastQuery().dir, 'asc', 'a text column starts ascending');
  eq(lastQuery().offset, 0, 'paging restarts at the top');
  eq(ariaOf('nick'), 'ascending');
  eq(arrowOf('nick'), '▲');
  eq(ariaOf('last'), 'none', 'the previous column gives up its marker');
  eq(arrowOf('last'), '▲▼');
});

t('clicking the same header again reverses the direction', () => {
  thFor('nick').fire('click');
  eq(lastQuery().dir, 'desc');
  eq(ariaOf('nick'), 'descending');
  eq(arrowOf('nick'), '▼');
  thFor('nick').fire('click');
  eq(lastQuery().dir, 'asc', 'and back again');
});

t('each column starts in its own natural direction', () => {
  const natural = { nick: 'asc', first: 'asc', my_nick: 'asc',
                    msgs: 'desc', media: 'desc', last: 'desc' };
  for (const key of SORTABLE) {
    // Click another column first, so the click under test is genuinely the
    // FIRST one on this header and not a toggle of an already-active one.
    const other = key === 'nick' ? 'msgs' : 'nick';
    thFor(other).fire('click');
    eq(lastQuery().sort, other, 'the warm-up click landed');
    thFor(key).fire('click');
    eq(lastQuery().sort, key);
    eq(lastQuery().dir, natural[key],
       key + ' must start ' + natural[key] + ', not inherit the old direction');
  }
});

t('switching column does not inherit the previous direction', () => {
  thFor('nick').fire('click');      // nick asc
  thFor('nick').fire('click');      // nick desc
  thFor('msgs').fire('click');      // msgs natural
  eq(lastQuery().sort, 'msgs');
  eq(lastQuery().dir, 'desc');
  thFor('first').fire('click');
  eq(lastQuery().dir, 'asc', '"First" ignores the descending Msgs');
});

t('an unknown sort key is ignored rather than sent to SQL', () => {
  thFor('nick').fire('click');
  const request = lastQuery();
  HistoryDb.sortBy('message_count; DROP TABLE persons--');
  HistoryDb.sortBy('');
  HistoryDb.sortBy(null);
  eq(lastQuery(), request, 'no new request was issued');
  eq(HistoryDb.sortKey, 'nick', 'the state did not move');
});

t('Enter and Space on a focused header sort like a click', () => {
  thFor('media').fire('click');
  eq(lastQuery().sort, 'media');
  thFor('media').fire('keydown', { key: 'Enter' });
  eq(lastQuery().dir, 'asc', 'Enter toggled the direction');
  thFor('media').fire('keydown', { key: ' ' });
  eq(lastQuery().dir, 'desc', 'Space toggled it back');
  let prevented = false;
  thFor('media').fire('keydown',
    { key: 'Enter', preventDefault() { prevented = true; } });
  ok(prevented, 'the page must not scroll when Space/Enter sorts');
  const before = pages().length;
  thFor('media').fire('keydown', { key: 'a' });
  eq(pages().length, before, 'any other key does nothing');
});

// ═════════════════════════════════════════════════════════════════
// 4. the order belongs to the database, not to the loaded page
// ═════════════════════════════════════════════════════════════════

t('a new sort drops the loaded rows and scrolls back to the top', () => {
  answer([person('Zoe'), person('Amy')], { has_more: true, total: 200 });
  eq(rowNicks(), ['Zoe', 'Amy']);
  document.getElementById('userdbList').scrollTop = 900;
  thFor('nick').fire('click');
  eq(HistoryDb.rows.length, 0, 'the old page must not linger');
  eq(HistoryDb.hasMore, true, 'and more may be fetched');
  eq(document.getElementById('userdbList').scrollTop, 0,
     'a new order makes the old scroll position meaningless');
});

t('rows are painted in the order the server sent them', () => {
  // Regression guard: the table is paged, so a client-side comparator would
  // silently order only the page in memory (design §1.1).
  thFor('nick').fire('click');
  answer([person('Zoe'), person('Mia'), person('Amy')]);
  eq(rowNicks(), ['Zoe', 'Mia', 'Amy'],
     'the DOM must mirror the server order exactly');
  thFor('nick').fire('click');       // flip the direction …
  answer([person('Amy'), person('Mia'), person('Zoe')]);
  eq(rowNicks(), ['Amy', 'Mia', 'Zoe'], '… and follow the next answer');
});

// ═════════════════════════════════════════════════════════════════
// 5. the choice survives everything else that happens in the window
// ═════════════════════════════════════════════════════════════════

t('the sort survives a backend change notification', () => {
  thFor('msgs').fire('click');
  HistoryDb.onChanged();
  eq(lastQuery().sort, 'msgs');
  eq(lastQuery().dir, 'desc');
});

t('the sort survives typing in the nick search', () => {
  thFor('media').fire('click');
  const box = document.getElementById('userdbSearch');
  box.value = 'ang';
  HistoryDb.query = 'ang';
  HistoryDb.reload();
  eq(lastQuery().q, 'ang');
  eq(lastQuery().sort, 'media');
  eq(lastQuery().dir, 'desc');
});

t('the sort survives changing the preload and pressing refresh', () => {
  thFor('first').fire('click');
  const preload = document.getElementById('userdbPreload');
  preload.value = '120';
  preload.fire('change');
  eq(HistoryDb.preloadRows, 120);
  document.getElementById('userdbRefreshBtn').fire('click');
  eq(lastQuery().sort, 'first');
  eq(lastQuery().dir, 'asc');
});

t('every following page repeats the current order', () => {
  thFor('my_nick').fire('click');
  answer([person('Amy'), person('Bob')], { has_more: true, total: 200 });
  const list = document.getElementById('userdbList');
  list.scrollTop = list.scrollHeight;         // reach the preload margin
  list.fire('scroll');
  const request = lastQuery();
  eq(request.offset, 2, 'it asked for the next page');
  eq(request.sort, 'my_nick');
  eq(request.dir, 'asc');
});

t('the header markers survive a re-render', () => {
  thFor('last').fire('click');
  HistoryDb.render();
  eq(ariaOf('last'), 'descending');
  eq(arrowOf('last'), '▼');
  eq(headers().filter((th) => th.classList.contains('sort-active')).length, 1,
     'exactly one column is ever marked active');
});

t('the state is per-session, not persisted', () => {
  // The request asks for the sort to live while the app runs; a fresh page
  // starts from the default again (design §2 item 6, RULE 10).
  const reloaded = load('js/history-db.js', 'HistoryDb');
  eq(reloaded.sortKey, 'last');
  eq(reloaded.sortDir, 'desc');
});

// ── reporting ────────────────────────────────────────────────────

console.log('userdb_sort: ' + passed + ' passed, ' + failed + ' failed');
if (failed) process.exit(1);
console.log('OK');
