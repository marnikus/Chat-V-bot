/* Behaviour test for ui/js/dark-select.js — the dark dropdown that replaced
   the native <select> elements in the AI windows.

   Why this suite exists: the bug it fixes was invisible to every test we had,
   because a native <select> LOOKS correct in a DOM stub — the part that came
   out white on a black application is the option list, which the operating
   system draws and no test or stylesheet can reach. The only durable fix is
   "do not use a native select", so these tests assert the structure (a
   `.layout-menu` panel of buttons, the same one the Bookmarks popup uses) and
   not the colours.

   Run:  node tests/test_dark_select_js.js
*/
'use strict';
const fs = require('fs');
const path = require('path');

// ── DOM stub ─────────────────────────────────────────────────────

function mkEl(tag) {
  const listeners = {};
  const el = {
    tagName: String(tag || 'div').toUpperCase(),
    _text: '', children: [], parentNode: null, dataset: {}, attrs: {},
    id: '', value: '', type: '', listeners,
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
    appendChild(c) { el.children.push(c); c.parentNode = el; return c; },
    setAttribute(k, v) { el.attrs[k] = String(v); },
    getAttribute(k) { return el.attrs[k]; },
    addEventListener(ev, fn) { (listeners[ev] = listeners[ev] || []).push(fn); },
    focus() { el.focused = true; },
    querySelector(sel) { return findAll(el, sel)[0] || null; },
    querySelectorAll(sel) { return findAll(el, sel); },
    fire(ev, extra) {
      (listeners[ev] || []).forEach((fn) => fn(Object.assign(
        { target: el, preventDefault() {}, stopPropagation() {} },
        extra || {})));
    },
  };
  return el;
}
function matches(node, sel) {
  const s = String(sel).trim();
  if (s.startsWith('.')) return node.classList.contains(s.slice(1));
  return node.tagName === s.toUpperCase();
}
function walk(el, out) {
  out = out || [];
  el.children.forEach((c) => { out.push(c); walk(c, out); });
  return out;
}
function findAll(el, sel) { return walk(el).filter((n) => matches(n, sel)); }

const docListeners = {};
global.document = {
  createElement: mkEl,
  addEventListener(ev, fn) {
    (docListeners[ev] = docListeners[ev] || []).push(fn);
  },
  fire(ev) { (docListeners[ev] || []).forEach((fn) => fn({})); },
};
global.window = global;

const DarkSelect = new Function(
  fs.readFileSync(path.join(__dirname, '..', 'ui', 'js', 'dark-select.js'),
                  'utf8') + '\nreturn DarkSelect;')();

// ── assertion kit ────────────────────────────────────────────────

let passed = 0, failed = 0;
function t(name, fn) {
  try { fn(); passed++; }
  catch (e) { failed++; console.error('FAIL ' + name + '\n   ' + (e && e.stack || e)); }
}
function ok(cond, msg) { if (!cond) throw new Error(msg || 'expected truthy'); }
function eq(a, b, msg) {
  const sa = JSON.stringify(a), sb = JSON.stringify(b);
  if (sa !== sb) throw new Error((msg || 'mismatch') + '\n   got ' + sa +
                                 '\n   want ' + sb);
}

const OPTIONS = [
  { value: 'grok', title: 'Grok (xAI)', sub: 'grok-4.3' },
  { value: 'google', title: 'Google Gemini', sub: 'gemini-2.0-flash' },
  { value: 'broken', title: 'Old key', sub: 'no API key', warn: true },
];

function build(onPick) {
  const host = mkEl('div');
  const box = DarkSelect.attach(host, { placeholder: 'Pick one',
                                        onPick: onPick || function () {} });
  box.setOptions(OPTIONS, 'grok');
  return { host, box };
}
const rows = (host) => findAll(host, '.dark-select-option');

// ── it is not a native select ────────────────────────────────────

t('it builds buttons, never <option> elements', () => {
  const { host } = build();
  eq(findAll(host, 'option').length, 0,
     'an OS-drawn option list is exactly the white menu we are replacing');
  eq(rows(host).length, 3);
  ok(rows(host).every((r) => r.tagName === 'BUTTON'));
});

t('the open list reuses the Bookmarks panel, it does not copy it', () => {
  const { host } = build();
  const menu = host.querySelector('.dark-select-menu');
  ok(menu.classList.contains('layout-menu'),
     'sharing the class is what keeps the two menus identical');
  ok(rows(host)[0].querySelector('.lm-sub'), 'Bookmarks subtitle class');
});

t('it starts closed and announces that to assistive tech', () => {
  const { host, box } = build();
  ok(!box.isOpen());
  ok(host.querySelector('.dark-select-menu').classList.contains('hidden'));
  eq(host.querySelector('.dark-select-trigger').getAttribute('aria-expanded'),
     'false');
});

// ── choosing ─────────────────────────────────────────────────────

t('the trigger shows the selected title, not the raw value', () => {
  const { host } = build();
  eq(host.querySelector('.dark-select-label').textContent, 'Grok (xAI)');
});

t('an empty list shows the placeholder instead of looking broken', () => {
  const host = mkEl('div');
  const box = DarkSelect.attach(host, { placeholder: '— none yet —' });
  box.setOptions([], '');
  eq(host.querySelector('.dark-select-label').textContent, '— none yet —');
  ok(host.querySelector('.dark-select-empty'));
});

t('clicking a row picks it, closes the menu and notifies once', () => {
  const picks = [];
  const { host, box } = build((v) => picks.push(v));
  box.open();
  rows(host).find((r) => r.dataset.value === 'google').fire('click');
  eq(picks, ['google']);
  eq(box.value, 'google');
  ok(!box.isOpen());
});

t('the chosen row is marked, and only that one', () => {
  const { host, box } = build();
  box.pick('google');
  const marked = rows(host).filter((r) => r.classList.contains('selected'));
  eq(marked.length, 1);
  eq(marked[0].dataset.value, 'google');
});

t('setOptions restores state WITHOUT firing onPick', () => {
  const picks = [];
  const { box } = build((v) => picks.push(v));
  box.setOptions(OPTIONS, 'google');
  eq(box.value, 'google');
  eq(picks, [], 'redrawing a list is not a user decision');
});

t('select() sets the value silently — for restoring saved state', () => {
  const picks = [];
  const { box } = build((v) => picks.push(v));
  box.select('broken');
  eq(box.value, 'broken');
  eq(picks, []);
});

t('an unusable option is flagged, never dropped from the list', () => {
  const { host, box } = build();
  box.select('broken');
  ok(rows(host).some((r) => r.dataset.value === 'broken'),
     'hiding a broken connection is how it becomes unfixable');
  ok(host.classList.contains('warn'));
});

// ── dismissal ────────────────────────────────────────────────────

t('the trigger toggles rather than only opening', () => {
  const { host, box } = build();
  host.querySelector('.dark-select-trigger').fire('click');
  ok(box.isOpen());
  host.querySelector('.dark-select-trigger').fire('click');
  ok(!box.isOpen());
});

t('a click anywhere else closes it', () => {
  const { box } = build();
  box.open();
  document.fire('click');
  ok(!box.isOpen());
});

t('opening one menu closes another — two open lists is a UI bug', () => {
  const first = build();
  const second = build();
  first.box.open();
  second.box.open();
  ok(!first.box.isOpen());
  ok(second.box.isOpen());
});

// ── keyboard ─────────────────────────────────────────────────────

t('Enter opens, then picks the highlighted value', () => {
  const picks = [];
  const { host, box } = build((v) => picks.push(v));
  const trigger = host.querySelector('.dark-select-trigger');
  trigger.fire('keydown', { key: 'Enter' });
  ok(box.isOpen());
  trigger.fire('keydown', { key: 'Enter' });
  eq(picks, ['grok']);
});

t('arrows walk the list and stop at the ends', () => {
  const { host, box } = build();
  const trigger = host.querySelector('.dark-select-trigger');
  trigger.fire('keydown', { key: 'ArrowDown' });
  eq(box.value, 'google');
  trigger.fire('keydown', { key: 'ArrowDown' });
  trigger.fire('keydown', { key: 'ArrowDown' });
  eq(box.value, 'broken', 'must not run off the end');
  trigger.fire('keydown', { key: 'ArrowUp' });
  eq(box.value, 'google');
});

t('Escape closes and hands focus back to the trigger', () => {
  const { host, box } = build();
  box.open();
  host.querySelector('.dark-select-trigger').fire('keydown', { key: 'Escape' });
  ok(!box.isOpen());
  ok(host.querySelector('.dark-select-trigger').focused,
     'a closed menu that keeps focus traps the keyboard user');
});

t('attaching to nothing is survivable, not a crash', () => {
  eq(DarkSelect.attach(null, {}), null);
});

console.log('\n' + passed + ' passed, ' + failed + ' failed');
process.exit(failed ? 1 : 0);
