/* Regression pin for the User Memory (People) table's column sorting.

   The Full User Database is getting sortable headers
   (docs/archive/2026-09-10-history-push-and-sort/SORTABLE_DATABASE_COLUMNS_DESIGN_2026-09-10.md); this table already
   had them, from GRID_WINDOW_MEMORY_SORT_DESIGN_2026-09-05.md §5. These
   tests exist so the two tables cannot silently diverge: the same ▲▼ /
   ▲ / ▼ glyphs, the same toggle rule, the same aria-sort values, and the
   same "empty values stay at the end in either direction" behaviour.

   Unlike the database table this list is fully in memory, so the order IS
   computed here — the comparator itself is part of the contract.

   Per AGENT_RULES RULE 8 this executes the REAL ui/js/user-table.js against
   a DOM built from the REAL <thead> in ui/index.html.

   Run:  node tests/test_user_memory_sort.js
*/
'use strict';
const fs = require('fs');
const path = require('path');

const readUi = (f) => fs.readFileSync(path.join(__dirname, '..', 'ui', f),
                                      'utf8');
const html = readUi('index.html');
const css = readUi('css/table.css');

// ── DOM stub ─────────────────────────────────────────────────────

const escapeHtml = (s) => String(s)
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  .replace(/"/g, '&quot;');

function mkEl(tag) {
  const listeners = {};
  const el = {
    tagName: String(tag || 'div').toUpperCase(),
    _text: '',
    _html: undefined,
    children: [],
    parentNode: null,
    style: {},
    dataset: {},
    attrs: {},
    title: '',
    value: '',
    checked: false,
    indeterminate: false,
    disabled: false,
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
    set textContent(v) { el._text = String(v); el._html = undefined;
                         el.children = []; },
    // `UserTable._esc()` escapes through a detached <div>; `render()` writes
    // the whole tbody as markup. Both are real behaviour of the module.
    get innerHTML() {
      return el._html !== undefined ? el._html : escapeHtml(el._text);
    },
    set innerHTML(v) { el._html = String(v); el.children = []; },
    appendChild(c) { el.children.push(c); c.parentNode = el; return c; },
    append(...cs) { cs.forEach((c) => el.appendChild(c)); },
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
    scrollIntoView() {},
    focus() {},
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
        { target: el, key: '', checked: false, preventDefault() {},
          stopPropagation() {} }, extra || {})));
    },
    click(extra) { el.fire('click', extra); },
  };
  return el;
}
function mkText(s) { const n = mkEl('#text'); n._text = String(s); return n; }

function matches(node, sel) {
  if (!node || !node.classList) return false;
  const re = /([#.]?[\w-]+)|\[([\w-]+)(?:=["']?([^\]"']*)["']?)?\]/g;
  let m, tag = '', ids = [], classes = [], attrs = [];
  while ((m = re.exec(String(sel).trim()))) {
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
function findAll(root, sel) {
  const found = [];
  for (const group of String(sel).split(',')) {
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

// ── the real <thead>, parsed out of the shipped page ─────────────

const VOID = new Set(['input', 'br', 'img', 'hr', 'meta', 'link', 'source']);
function parseHtml(src) {
  const root = mkEl('#fragment');
  const stack = [root];
  const re = /<!--[\s\S]*?-->|<\/([a-zA-Z][\w-]*)\s*>|<([a-zA-Z][\w-]*)((?:\s+[^<>]*?)?)(\/?)>|([^<]+)/g;
  let m;
  while ((m = re.exec(src))) {
    if (m[0].startsWith('<!--')) continue;
    if (m[1]) {
      for (let i = stack.length - 1; i > 0; i--) {
        if (stack[i].tagName === m[1].toUpperCase()) { stack.length = i; break; }
      }
      continue;
    }
    if (m[2]) {
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
    if (m[5] && m[5].trim()) stack[stack.length - 1].appendChild(mkText(m[5]));
  }
  return root;
}

function peoplePanelMarkup() {
  const start = html.indexOf('<div class="panel table-panel" id="winPeople"');
  if (start < 0) throw new Error('ui/index.html has no #winPeople panel');
  if (html.indexOf('id="userTable"', start) < 0)
    throw new Error('ui/index.html has no #userTable');
  const end = html.indexOf('</table>', start) + '</table>'.length;
  return html.slice(start, end);
}

// ── page ─────────────────────────────────────────────────────────

const byId = {};
const page = mkEl('body');
page.appendChild(parseHtml(peoplePanelMarkup()));
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
global.CSS = { escape: (s) => s };
global.requestAnimationFrame = (fn) => fn();

// ── the real modules ─────────────────────────────────────────────

const load = (file, name) =>
  new Function(readUi(file) + '\nreturn ' + name + ';')();
load('js/core/ui-helpers.js', 'UIHelpers');      // sets window.UIHelpers
global.LogConsole = { log() {} };
global.App = { bridge: null };
const UserTable = load('js/user-table.js', 'UserTable');

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

const headers = () => document.querySelectorAll('#userTable th[data-sort]');
const thFor = (key) => headers().filter((th) => th.dataset.sort === key)[0];
const arrowOf = (key) => thFor(key).querySelector('.sort-arrow').textContent.trim();
const ariaOf = (key) => thFor(key).getAttribute('aria-sort');

/** The nick order the table actually painted. */
function painted() {
  const body = document.getElementById('userTableBody').innerHTML;
  const out = [];
  const re = /<tr[^>]*data-nick="([^"]*)"/g;
  let m;
  while ((m = re.exec(body))) out.push(m[1]);
  return out;
}

const person = (nick, over) => Object.assign({
  nick, gender: 'unknown', registered: false, messaged: false,
  first_seen: '', last_messaged: '', order: null,
}, over || {});

const SORTABLE = ['order', 'nick', 'gender', 'registered', 'status',
                  'first_seen', 'last_messaged'];

// ═════════════════════════════════════════════════════════════════
// markup
// ═════════════════════════════════════════════════════════════════

t('every data column of #userTable declares itself sortable', () => {
  eq(headers().map((th) => th.dataset.sort).sort(), SORTABLE.slice().sort());
});

t('each sortable header is a focusable button with a ▲▼ indicator', () => {
  for (const key of SORTABLE) {
    const button = thFor(key).querySelector('.sort-button');
    ok(button, key + ' has no .sort-button');
    eq(button.tagName, 'BUTTON');
    ok(thFor(key).querySelector('.sort-arrow'), key + ' has no arrow');
    eq(arrowOf(key), '▲▼', key + ' starts idle');
  }
});

t('the selection and Actions columns are not sortable', () => {
  const all = document.querySelectorAll('#userTable thead th');
  eq(all.length, SORTABLE.length + 2, 'checkbox + seven columns + Actions');
  const plain = all.filter((th) => !th.dataset.sort).map((th) => th.textContent);
  eq(plain.length, 2);
  ok(/Actions/i.test(plain[1]), 'the last plain header is Actions');
});

t('the two tables share one arrow renderer', () => {
  // Same helper, same glyphs — so the BD table can never drift away.
  eq(UIHelpers.sortArrow(false, 1), '▲▼');
  eq(UIHelpers.sortArrow(true, 1), '▲');
  eq(UIHelpers.sortArrow(true, -1), '▼');
  ok(/\.sort-active\s+\.sort-arrow/.test(css),
     'table.css accents the active arrow');
});

// ═════════════════════════════════════════════════════════════════
// behaviour
// ═════════════════════════════════════════════════════════════════

t('the table boots unsorted with every marker idle', () => {
  UserTable.init();
  eq(UserTable.sort.key, null);
  for (const key of SORTABLE) {
    eq(ariaOf(key), 'none', key);
    eq(arrowOf(key), '▲▼', key);
  }
});

t('the list is shown in collection order until a header is used', () => {
  UserTable.render([person('Zoe'), person('Amy'), person('Mia')]);
  eq(painted(), ['Zoe', 'Amy', 'Mia']);
});

t('a header click sorts ascending, a second one descending', () => {
  UserTable.render([person('Zoe'), person('Amy'), person('Mia')]);
  thFor('nick').fire('click');
  eq(painted(), ['Amy', 'Mia', 'Zoe']);
  eq(ariaOf('nick'), 'ascending');
  eq(arrowOf('nick'), '▲');
  thFor('nick').fire('click');
  eq(painted(), ['Zoe', 'Mia', 'Amy']);
  eq(ariaOf('nick'), 'descending');
  eq(arrowOf('nick'), '▼');
});

t('the nick comparison ignores case and counts naturally', () => {
  UserTable.render([person('bob'), person('Alice'), person('ann10'),
                    person('ann9')]);
  thFor('nick').fire('click');
  eq(painted(), ['Alice', 'ann9', 'ann10', 'bob'],
     'case-insensitive, and 9 before 10');
});

t('gender sorts female, male, unknown', () => {
  UserTable.render([person('u', { gender: 'unknown' }),
                    person('m', { gender: 'male' }),
                    person('f', { gender: 'female' })]);
  thFor('gender').fire('click');
  eq(painted(), ['f', 'm', 'u']);
});

t('Reg? and Status sort No before Yes', () => {
  UserTable.render([person('yes', { registered: true, messaged: true }),
                    person('no', { registered: false, messaged: false })]);
  thFor('registered').fire('click');
  eq(painted(), ['no', 'yes']);
  thFor('status').fire('click');
  eq(painted(), ['no', 'yes'], 'New before Done');
});

t('dates sort chronologically, not as text', () => {
  UserTable.render([
    person('late', { first_seen: '2026-09-02 08:00:00' }),
    person('early', { first_seen: '2026-01-30 23:00:00' }),
    person('mid', { first_seen: '2026-05-05 05:00:00' }),
  ]);
  thFor('first_seen').fire('click');
  eq(painted(), ['early', 'mid', 'late']);
  thFor('first_seen').fire('click');
  eq(painted(), ['late', 'mid', 'early']);
});

t('the processing order column sorts numerically', () => {
  UserTable.render([person('ten', { order: 10 }),
                    person('two', { order: 2 }),
                    person('one', { order: 1 })]);
  thFor('order').fire('click');
  eq(painted(), ['one', 'two', 'ten']);
});

t('empty values stay at the end in BOTH directions', () => {
  const rows = [person('blank', { first_seen: '' }),
                person('early', { first_seen: '2026-01-01 00:00:00' }),
                person('late', { first_seen: '2026-12-01 00:00:00' })];
  UserTable.render(rows);
  thFor('first_seen').fire('click');
  eq(painted(), ['early', 'late', 'blank']);
  thFor('first_seen').fire('click');
  eq(painted(), ['late', 'early', 'blank'],
     'reversing must not drag the blanks to the top');
});

t('an already-messaged person has no processing order and stays last', () => {
  UserTable.render([person('done', { messaged: true, order: 1 }),
                    person('third', { order: 3 }),
                    person('second', { order: 2 })]);
  thFor('order').fire('click');
  eq(painted(), ['second', 'third', 'done']);
});

t('switching column starts ascending and moves the marker', () => {
  thFor('nick').fire('click');
  thFor('nick').fire('click');          // descending …
  thFor('first_seen').fire('click');    // … does not leak into the next column
  eq(ariaOf('first_seen'), 'ascending');
  eq(ariaOf('nick'), 'none');
  eq(arrowOf('nick'), '▲▼');
  eq(headers().filter((th) => th.classList.contains('sort-active')).length, 1);
});

t('an unknown key is ignored', () => {
  thFor('nick').fire('click');
  UserTable.sortBy('');
  UserTable.sortBy(null);
  eq(UserTable.sort.key, 'nick');
});

t('Enter and Space sort, other keys do not', () => {
  UserTable.sort.key = null; UserTable.sort.direction = 1;
  UserTable.render([person('Zoe'), person('Amy')]);
  thFor('nick').fire('click');
  eq(painted(), ['Amy', 'Zoe'], 'the click sorted ascending');
  thFor('nick').fire('keydown', { key: 'Enter' });
  eq(painted(), ['Zoe', 'Amy'], 'Enter reversed it');
  thFor('nick').fire('keydown', { key: ' ' });
  eq(painted(), ['Amy', 'Zoe'], 'Space reversed it back');
  thFor('nick').fire('keydown', { key: 'x' });
  eq(painted(), ['Amy', 'Zoe'], 'an unrelated key changes nothing');
});

// ═════════════════════════════════════════════════════════════════
// the sort outlives every re-render
// ═════════════════════════════════════════════════════════════════

t('a backend refresh keeps the order while the app runs', () => {
  UserTable.sort.key = null; UserTable.sort.direction = 1;
  UserTable.render([person('Zoe'), person('Amy'), person('Mia')]);
  thFor('nick').fire('click');
  eq(painted(), ['Amy', 'Mia', 'Zoe']);
  // users_updated: the same people arrive again from Python
  UserTable.render([person('Mia'), person('Zoe'), person('Amy')]);
  eq(painted(), ['Amy', 'Mia', 'Zoe'], 'the arrival order must not win');
  // a person is added mid-scroll
  UserTable.render([person('Mia'), person('Zoe'), person('Amy'),
                    person('Bea')]);
  eq(painted(), ['Amy', 'Bea', 'Mia', 'Zoe']);
});

t('the nick filter and the sort compose', () => {
  UserTable.sort.key = null; UserTable.sort.direction = 1;
  UserTable.render([person('Zoe'), person('Amy'), person('Ada')]);
  thFor('nick').fire('click');
  const box = document.getElementById('userSearch');
  box.value = 'a';
  box.fire('input', { target: box });
  eq(painted(), ['Ada', 'Amy'], 'filtered, then sorted');
  box.value = '';
  box.fire('input', { target: box });
  eq(painted(), ['Ada', 'Amy', 'Zoe']);
});

t('the selection toolbar follows the visible rows, not the raw list', () => {
  UserTable.render([person('Zoe'), person('Amy')]);
  const all = document.getElementById('selectAllUsers');
  all.fire('change', { target: { checked: true } });
  eq([...UserTable.selected].sort(), ['Amy', 'Zoe']);
});

console.log('user_memory_sort: ' + passed + ' passed, ' + failed + ' failed');
if (failed) process.exit(1);
console.log('OK');
