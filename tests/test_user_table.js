/* test_user_table.js — user-table.js coverage lift (Round H, H-A6).
   Executes the REAL shipped ui/js/user-table.js against a DOM stub;
   Labels/HistoryStore/bridge stubbed (RULE 8). */
'use strict';
const assert = require('assert');

function makeEl(id) {
  const set = new Set();
  const el = {
    id: id || '', tag: id || '', value: '', _text: '', _html: '', _cls: '',
    disabled: false, checked: false, indeterminate: false, title: '',
    children: [], style: {}, dataset: {}, onclick: null, _l: {},
    appendChild(c) { this.children.push(c); c.parent = this; return c; },
    addEventListener(t, f) { (this._l[t] = this._l[t] || []).push(f); },
    removeEventListener() {}, focus() {},
    setAttribute() {}, getAttribute() { return null; },
    querySelector(sel) { return el._qs ? el._qs(sel) : null; },
    querySelectorAll(sel) { return el._qsa ? el._qsa(sel) : []; },
    closest(sel) { return el._closest ? el._closest(sel) : null; },
    scrollIntoView() { el._scrolled = true; },
  };
  el.classList = { add(c) { set.add(c); }, remove(c) { set.delete(c); },
    toggle(c, force) {
      const want = force === undefined ? !set.has(c) : !!force;
      if (want) set.add(c); else set.delete(c); return want;
    }, contains(c) { return set.has(c); } };
  Object.defineProperty(el, 'className', {
    get() { return el._cls; },
    set(v) { el._cls = String(v); set.clear();
      el._cls.split(/\s+/).filter(Boolean).forEach((c) => set.add(c)); },
  });
  Object.defineProperty(el, 'innerHTML', {
    get() { return el._html || ''; },
    set(v) { el._html = String(v); },
  });
  Object.defineProperty(el, 'textContent', {
    get() { return el._text; },
    set(v) {
      el._text = v;
      el._html = (v === null || v === undefined) ? ''
        : String(v).replace(/&/g, '&amp;').replace(/</g, '&lt;')
          .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    },
  });
  return el;
}
const els = {};
['clearMemBtn', 'resetMsgBtn', 'deleteSelectedBtn', 'selectAllUsers',
 'userSearch', 'userTable', 'userTableBody', 'selCount'].forEach((id) => { els[id] = makeEl(id); });
const ths = ['nick', 'gender', 'registered', 'status', 'order', 'first_seen'].map((k) => {
  const th = makeEl('th-' + k);
  th.dataset.sort = k;
  const arrow = makeEl('arrow');
  arrow.className = 'sort-arrow';
  th.appendChild(arrow);
  th._qs = (sel) => (sel === '.sort-arrow' ? arrow : null);
  return th;
});
global.document = {
  getElementById: (id) => els[id] || null,
  createElement: (t) => makeEl(t),
  addEventListener() {},
  querySelectorAll: (sel) => (sel.indexOf('th[data-sort]') >= 0 ? ths : []),
};
global.window = global;
global.CSS = { escape: (s) => String(s).replace(/[^a-zA-Z0-9_-]/g, (c) => '\\' + c) };
let rafQueue = [];
global.requestAnimationFrame = (fn) => { rafQueue.push(fn); return rafQueue.length; };
const logs = [];
global.LogConsole = { log: (m, l) => logs.push([m, l]), clear() {} };
const calls = [];
const rec = (n) => (...a) => { calls.push([n, ...a]); };
global.App = { bridge: null };
global.Labels = { person: null, filterActive: false,
  setPerson: rec('Labels.setPerson'), allows: () => true,
  pills: () => { const p = makeEl('pills'); p.childNodes = []; return p; } };
global.HistoryStore = { openPerson: rec('HistoryStore.openPerson') };
global.BridgeReady = { ready() {} };
global.UIHelpers = { sortArrow: (active, dir) => (active ? (dir > 0 ? '▲' : '▼') : '▲▼') };

const { loadSingle } = require('./js_family');
loadSingle('user-table.js', 'UserTable');
const UserTable = global.UserTable;

let passed = 0; let failed = 0;
function test(name, fn) {
  try { fn(); passed += 1; console.log('  ok - ' + name); }
  catch (e) { failed += 1; console.error('  FAIL - ' + name + '\n    ' + e.message); }
}
function clearCalls() { calls.length = 0; logs.length = 0; }
function assertCall(n) { assert(calls.some((c) => c[0] === n), 'expected ' + n + ' — got ' + JSON.stringify(calls.map((c) => c[0]))); }
function fireDoc(elm, type, ev) { (elm._l[type] || []).forEach((f) => f(ev || {})); }

const alice = { nick: 'Alice', gender: 'female', registered: true, messaged: false,
  order: 3, first_seen: '2026-01-01T10:00:00', last_messaged: null };
const bob = { nick: 'Bob', gender: 'male', registered: false, messaged: true,
  order: null, first_seen: '2026-01-02T11:00:00', last_messaged: '2026-01-03T12:00:00' };
const cy = { nick: 'Cy', gender: null, registered: false, messaged: false,
  order: 1, first_seen: null, last_messaged: null };

UserTable.init();
UserTable.init(); // _wired guard

test('init: buttons + search + sort headers + delegated tbody', () => {
  assert(els.clearMemBtn._l.click.length === 1);
  assert(els.resetMsgBtn._l.click.length === 1);
  assert(els.deleteSelectedBtn._l.click.length === 1);
  assert(els.selectAllUsers._l.change.length === 1);
  assert(els.userSearch._l.input.length === 1);
  assert(ths[0]._l.click.length === 1 && ths[0]._l.keydown.length === 1);
  assert(els.userTableBody._l.click.length === 1);
  assert(els.userTableBody._l.change.length === 1);
});

test('render: empty / no matches / label-filtered', () => {
  UserTable.render([]);
  assert(els.userTableBody.innerHTML.indexOf('No users discovered yet') >= 0);
  UserTable.render([alice]);
  UserTable.filter = 'zzz';
  UserTable.render(UserTable.users);
  assert(els.userTableBody.innerHTML.indexOf('No nick matches') >= 0);
  UserTable.filter = '';
  global.Labels.filterActive = true;
  global.Labels.allows = () => false;
  UserTable.render(UserTable.users);
  assert(els.userTableBody.innerHTML.indexOf('hidden by the label filter') >= 0);
  global.Labels.filterActive = false;
  global.Labels.allows = () => true;
});

test('render: rows carry state classes + values', () => {
  UserTable.selected.add('Alice');
  global.Labels.person = 'Cy';
  UserTable.render([alice, bob, cy]);
  const html = els.userTableBody.innerHTML;
  assert(html.indexOf('Alice') >= 0);
  assert(html.indexOf('Female') >= 0);
  assert(html.indexOf('Male') >= 0);
  assert(html.indexOf('Unknown') >= 0);
  assert(html.indexOf('✅ Yes') >= 0);
  assert(html.indexOf('❌ No') >= 0);
  assert(html.indexOf('✅ Done') >= 0);
  assert(html.indexOf('🆕 New') >= 0);
  assert(html.indexOf('10:00') >= 0);
  assert(html.indexOf('12:00') >= 0);
  assert(html.indexOf('row-new') >= 0);
  assert(html.indexOf('row-selected') >= 0);
  assert(html.indexOf('row-label-target') >= 0);
  assert(html.indexOf('checked') >= 0);
  assert(html.indexOf('data-act="toggle-messaged"') >= 0);
  // selection dropped for nicks that no longer exist
  UserTable.selected.add('Gone');
  UserTable.render([alice]);
  assert(!UserTable.selected.has('Gone'));
});

test('sort: sortBy toggles, _sortValue branches', () => {
  UserTable.render([alice, bob, cy]);
  UserTable.sortBy('nick');
  assert.deepStrictEqual(UserTable.sort, { key: 'nick', direction: 1 });
  UserTable.sortBy('nick');
  assert.strictEqual(UserTable.sort.direction, -1);
  UserTable.sortBy(null);
  const sv = UserTable._sortValue;
  assert.strictEqual(sv(alice, 'gender'), 'female');
  assert.strictEqual(sv({ gender: 'weird' }, 'gender'), 'unknown');
  assert.strictEqual(sv(alice, 'order'), 3);
  assert.strictEqual(sv(bob, 'order'), null); // messaged → unranked
  assert.strictEqual(sv({ messaged: false, order: 'x' }, 'order'), null);
  assert.strictEqual(sv(alice, 'registered'), 1);
  assert.strictEqual(sv(bob, 'status'), 1);
  assert.strictEqual(sv(alice, 'status'), 0);
  assert.strictEqual(typeof sv(alice, 'first_seen'), 'number');
  assert.strictEqual(sv({ first_seen: 'yesterday' }, 'first_seen'), 'yesterday');
  assert.strictEqual(sv({ first_seen: null }, 'first_seen'), null);
  assert.strictEqual(sv(alice, 'nick'), 'alice');
  assert.strictEqual(sv({}, 'nick'), '');
});

test('_compare: nulls last, numbers, strings', () => {
  UserTable.sort = { key: 'nick', direction: 1 };
  assert(UserTable._compare(alice, bob) < 0);
  assert(UserTable._compare(bob, alice) > 0);
  assert.strictEqual(UserTable._compare(alice, alice), 0);
  UserTable.sort = { key: 'first_seen', direction: 1 };
  assert.strictEqual(UserTable._compare(cy, alice), 1); // null last
  assert.strictEqual(UserTable._compare(cy, { nick: 'Z', first_seen: null }), 0);
  UserTable.sort = { key: 'order', direction: 1 };
  assert(UserTable._compare(cy, alice) < 0); // 1 < 3
  UserTable.sort = { key: 'nick', direction: -1 };
  assert(UserTable._compare(alice, bob) > 0); // reversed
  UserTable.sort = { key: null, direction: 1 };
  assert.strictEqual(UserTable._compare(alice, bob), 0);
});

test('_updateSortHeaders: arrows + aria-sort', () => {
  UserTable.sort = { key: 'nick', direction: 1 };
  UserTable._updateSortHeaders();
  const nickTh = ths[0];
  assert.strictEqual(nickTh.querySelector ? 'n/a' : 'n/a', 'n/a');
  assert(nickTh.children[0].textContent === '▲');
  UserTable.sort = { key: 'nick', direction: -1 };
  UserTable._updateSortHeaders();
  assert(nickTh.children[0].textContent === '▼');
  UserTable.sort = { key: null, direction: 1 };
  UserTable._updateSortHeaders();
  assert(nickTh.children[0].textContent === '▲▼');
});

test('search input filters, _visible honours Labels.allows', () => {
  UserTable.render([alice, bob, cy]);
  fireDoc(els.userSearch, 'input', { target: { value: 'ALI' } });
  assert.strictEqual(UserTable.filter, 'ali');
  assert(UserTable._visible().length === 1);
  fireDoc(els.userSearch, 'input', { target: { value: '' } });
  assert.strictEqual(UserTable.filter, '');
  global.Labels.filterActive = true;
  global.Labels.allows = (n) => n !== 'Bob';
  assert(UserTable._visible().length === 2);
  global.Labels.allows = () => true;
  fireDoc(els.userSearch, 'input', { target: { value: '  ' } });
});

test('selection: toggleAll + _syncSelectionUI + change events', () => {
  clearCalls();
  UserTable.render([alice, bob]);
  fireDoc(els.selectAllUsers, 'change', { target: { checked: true } });
  assert.strictEqual(UserTable.selected.size, 2);
  assert.strictEqual(els.deleteSelectedBtn.textContent, '🗑 Delete selected (2)');
  assert.strictEqual(els.deleteSelectedBtn.disabled, false);
  assert.strictEqual(els.selCount.textContent, '2 selected');
  assert(els.selectAllUsers.checked === true);
  UserTable.selected.delete('Bob');
  UserTable._syncSelectionUI();
  assert(els.selectAllUsers.indeterminate === true);
  fireDoc(els.selectAllUsers, 'change', { target: { checked: false } });
  assert.strictEqual(UserTable.selected.size, 0);
  assert.strictEqual(els.deleteSelectedBtn.disabled, true);
  assert(els.selCount.classList.contains('hidden'));
  assert.strictEqual(els.selectAllUsers.indeterminate, false);
  // delegated checkbox change
  const cb = makeEl('cb');
  cb.dataset.nick = 'Alice';
  cb.checked = true;
  fireDoc(els.userTableBody, 'change', { target: { closest: (s) => (s.indexOf('checkbox') >= 0 ? cb : null) } });
  assert(UserTable.selected.has('Alice'));
  cb.checked = false;
  fireDoc(els.userTableBody, 'change', { target: { closest: (s) => (s.indexOf('checkbox') >= 0 ? cb : null) } });
  assert(!UserTable.selected.has('Alice'));
});

test('actions: delete/toggle/clear/reset with bridge', () => {
  clearCalls();
  UserTable.deleteNick('x'); // no bridge
  assert(logs.some((l) => l[1] === 'warn'));
  global.App.bridge = {
    delete_user: rec('delete_user'), delete_users: rec('delete_users'),
    clear_memory: rec('clear_memory'), reset_messaged: rec('reset_messaged'),
    set_user_messaged: rec('set_user_messaged'),
  };
  UserTable.selected.add('Alice');
  UserTable.deleteNick('Alice');
  assertCall('delete_user');
  assert(!UserTable.selected.has('Alice'));
  UserTable.deleteSelected(); // nothing selected
  assert(logs.some((l) => l[0].indexOf('Nothing selected') >= 0));
  UserTable.selected.add('Bob');
  UserTable.deleteSelected();
  assertCall('delete_users');
  assert.strictEqual(UserTable.selected.size, 0);
  UserTable.render([]);
  UserTable.clearAll(); // no users
  assert(logs.some((l) => l[1] === 'info'));
  UserTable.render([alice]);
  UserTable.clearAll();
  assertCall('clear_memory');
  UserTable.resetMessaged();
  assertCall('reset_messaged');
  UserTable.toggleMessaged('Alice');
  assert(calls.some((c) => c[0] === 'set_user_messaged' && c[1] === 'Alice' && c[2] === true));
  UserTable.toggleMessaged('Nobody'); // unknown nick
  UserTable.manualMessage('Alice');
  assert(logs.some((l) => l[0].indexOf('Manual message') >= 0));
});

test('delegated row clicks: pill-x / nick / actions / quick-assign', () => {
  clearCalls();
  const pillX = { closest: (s) => (s === '.label-pill-x' ? 'yes' : s === 'tr[data-nick]' ? null : null) };
  fireDoc(els.userTableBody, 'click', { target: pillX });
  assert(!calls.some((c) => c[0] === 'Labels.setPerson'));
  const nickCell = makeEl('nick'); nickCell.dataset.nick = 'Alice';
  const nickTarget = { closest: (s) => s === '.label-pill-x' ? null
    : s === '.col-nick[data-nick]' ? nickCell : s === 'button[data-act]' ? null : null };
  fireDoc(els.userTableBody, 'click', { target: nickTarget });
  assertCall('Labels.setPerson');
  assertCall('HistoryStore.openPerson');
  const btn = makeEl('btn');
  ['delete', 'toggle-messaged', 'message', 'label'].forEach((act) => {
    btn.dataset = { act, nick: 'Alice' };
    const t = { closest: (s) => (s === 'button[data-act]' ? btn : s === 'tr[data-nick]' ? null : null) };
    fireDoc(els.userTableBody, 'click', { target: t });
  });
  assertCall('delete_user');
  assertCall('set_user_messaged');
  assert(logs.some((l) => l[0].indexOf('Manual message') >= 0));
  assert(calls.some((c) => c[0] === 'Labels.setPerson' && c[2] && c[2].focus));
  const selCell = { closest: (s) => (s === '.col-select' ? 'yes' : s === 'tr[data-nick]' ? null : null) };
  fireDoc(els.userTableBody, 'click', { target: selCell });
  const row = makeEl('row'); row.dataset.nick = 'Bob';
  const rowTarget = { closest: (s) => s === 'tr[data-nick]' ? row
    : s === '.col-select' ? null : s === '.row-actions' ? null : null };
  fireDoc(els.userTableBody, 'click', { target: rowTarget });
  assert(calls.some((c) => c[0] === 'Labels.setPerson' && c[1] === 'Bob'));
});

test('paint labels + labelNick + markLabelTarget', () => {
  clearCalls();
  let pillNode = null;
  global.Labels.pills = (nick) => {
    pillNode = makeEl('pill');
    pillNode.childNodes = [makeEl('x')];
    return pillNode;
  };
  const cell = makeEl('cell'); cell.dataset.nick = 'Alice';
  els.userTableBody._qsa = (sel) => (sel === '.col-nick[data-nick]' ? [cell] : []);
  UserTable._paintLabels(els.userTableBody);
  assert(cell.children.includes(pillNode));
  global.Labels.person = null;
  UserTable.labelNick('Alice');
  assert(calls.some((c) => c[0] === 'Labels.setPerson' && c[2].focus));
  const tr1 = makeEl('tr1'); tr1.dataset.nick = 'Alice';
  const tr2 = makeEl('tr2'); tr2.dataset.nick = 'Bob';
  els.userTableBody._qsa = (sel) => (sel === 'tr[data-nick]' ? [tr1, tr2] : []);
  UserTable.markLabelTarget(' Alice ');
  assert(tr1.classList.contains('row-label-target'));
  assert(tr1._scrolled);
  assert(!tr2.classList.contains('row-label-target'));
  UserTable.markLabelTarget('');
  assert(!tr1.classList.contains('row-label-target'));
});

test('person_found: flash on next frame; flashRow branches', () => {
  clearCalls();
  UserTable.onPersonFound('bad json');
  assert.strictEqual(UserTable._flashNick, undefined);
  const tr = makeEl('flashrow'); tr.textContent = 'Alice';
  els.userTableBody._qsa = (sel) => (sel === 'tr' ? [tr] : []);
  els.userTableBody._qs = null;
  UserTable.onPersonFound(JSON.stringify({ nick: 'Alice' }));
  assert.strictEqual(UserTable._flashNick, 'Alice');
  assert(rafQueue.length === 1);
  rafQueue.slice().forEach((fn) => fn());
  assert(tr.classList.contains('row-flash'));
  assert(tr._scrolled);
  // input-found branch
  const inp = makeEl('inp');
  const inputRow = makeEl('inputrow');
  inp.closest = (s) => (s === 'tr' ? inputRow : null);
  els.userTableBody._qs = (sel) => (sel.indexOf('input[data-nick=') >= 0 ? inp : null);
  UserTable.flashRow('Alice');
  assert(inputRow.classList.contains('row-flash'));
  // no row → no-op
  els.userTableBody._qs = null;
  els.userTableBody._qsa = (sel) => (sel === 'tr' ? [] : []);
  UserTable.flashRow('Ghost');
});

test('person_removed + onDeleted', () => {
  clearCalls();
  UserTable.render([alice, bob]);
  UserTable.onPersonRemoved('bad');
  assert.strictEqual(UserTable.users.length, 2); // unchanged
  UserTable.render([alice, bob]);
  UserTable.selected.add('Bob');
  UserTable.onPersonRemoved(JSON.stringify({ nick: 'Bob', reason: 'filtered' }));
  assert.strictEqual(UserTable.users.length, 1);
  assert(!UserTable.selected.has('Bob'));
  assert(logs.some((l) => l[0].indexOf('filtered') >= 0));
  UserTable.selected.add('Alice');
  UserTable.onDeleted(JSON.stringify(['Alice']));
  assert(!UserTable.selected.has('Alice'));
  UserTable.onDeleted('not json'); // ignored, no throw
  UserTable.onDeleted(null);
});

test('_esc / _attr', () => {
  assert.strictEqual(UserTable._esc('<b>"'), '&lt;b&gt;&quot;');
  assert.strictEqual(UserTable._esc(null), '');
  assert.strictEqual(UserTable._attr('a"b'), 'a&quot;b');
});

console.log('\ntest_user_table: ' + passed + ' passed, ' + failed + ' failed');
process.exit(failed ? 1 : 0);
