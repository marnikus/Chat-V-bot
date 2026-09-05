/* Tests for the block-schema migration in ui/js/stack-dnd.js.

Covers BUG #1 (the dead "use_panel_filters" checkbox must never render) and
the "Only scroll, no people adding" feature at the UI layer: old stacks
persisted before scroll_only existed must pick up the new setting (and shed
retired keys) on load, while saved values survive and unknown keys are kept.

Per AGENT_RULES RULE 6 this executes the REAL shipped module (ui/js/
stack-dnd.js) in a real runtime (Node), against a tiny DOM stub.

Run:  node tests/test_stack_dnd_migration.js
Exits 0 + prints "OK" when every test passes.
*/
'use strict';
const fs = require('fs');
const path = require('path');

// ── minimal DOM / global stubs (just enough for init() + _showConfig) ──
function makeEl() {
  const listeners = {};
  return {
    innerHTML: '',
    textContent: '',
    value: '',
    disabled: false,
    classList: {
      _set: new Set(),
      add(...c) { c.forEach((x) => this._set.add(x)); },
      remove(...c) { c.forEach((x) => this._set.delete(x)); },
      toggle(c, on) { on ? this._set.add(c) : this._set.delete(c); },
      contains(c) { return this._set.has(c); },
    },
    style: {},
    _listeners: listeners,
    addEventListener(ev, fn) { (listeners[ev] = listeners[ev] || []).push(fn); },
    querySelector() { return makeEl(); },
    querySelectorAll() { return []; },
    closest() { return null; },
    setAttribute() {},
    appendChild() {},
  };
}
const elements = {};
function el(id) { return elements[id] || (elements[id] = makeEl()); }

global.document = {
  addEventListener() {},
  createElement() { return makeEl(); },
  getElementById(id) { return el(id); },
  querySelector() { return makeEl(); },
  querySelectorAll() { return []; },
};
global.window = global;
global.App = { bridge: null };
global.LogConsole = { log() {} };
global.PresetsUI = { promptName() {} };
global.StackDrag = { attach() {}, dragging: false };

// Load the real shipped module. It declares `const StackDnD = {...}` at top
// level and binds the init listener, so evaluate it in this scope.
const src = fs.readFileSync(
  path.join(__dirname, '..', 'ui', 'js', 'stack-dnd.js'), 'utf8');
const StackDnD = new Function(src + '\nreturn StackDnD;')();
StackDnD.init();

// ── tiny assertion kit ──────────────────────────────────────────────
let passed = 0, failed = 0;
function t(name, fn) {
  try { fn(); passed++; }
  catch (e) { failed++; console.error('FAIL ' + name + '\n   ' + (e && e.stack || e)); }
}
function ok(cond, msg) { if (!cond) throw new Error(msg || 'ok'); }
function eq(a, b, msg) {
  const ja = JSON.stringify(a), jb = JSON.stringify(b);
  if (ja !== jb) throw new Error((msg || 'eq') + '\n  got:  ' + ja + '\n  want: ' + jb);
}

// The exact shape of the SCROLL_PARSE block in the user's config.json from
// the bug report: has use_panel_filters, lacks scroll_only/person_selector.
function legacyScrollParse(over) {
  return Object.assign({
    block_id: 'SCROLL_PARSE',
    pre_delay_ms: 300,
    max_scrolls: 1000,
    scroll_pause_ms: 800,
    scroll_delta_y: 1000,
    viewport_selector: 'cdk-virtual-scroll-viewport.users-list-viewport',
    load_timeout_ms: 2500,
    stall_threshold: 100,
    min_new_users: 2,
    filter_female: 'yes',
    filter_registered: 'any',
    filter_guest: 'any',
    filter_anonymous: 'any',
    use_panel_filters: true,
  }, over || {});
}

// ── _migrateBlock: retired keys & back-filled defaults ───────────────

t('migration strips use_panel_filters and the other retired keys', () => {
  const b = StackDnD._migrateBlock(
    legacyScrollParse({ skip_if_backlog: true, backlog_threshold: 3 }));
  ok(b, 'block returned');
  ok(!('use_panel_filters' in b), 'use_panel_filters must be deleted');
  ok(!('skip_if_backlog' in b), 'skip_if_backlog must be deleted');
  ok(!('backlog_threshold' in b), 'backlog_threshold must be deleted');
});

t('migration back-fills scroll_only (and other new settings) with defaults', () => {
  const b = StackDnD._migrateBlock(legacyScrollParse());
  eq(b.scroll_only, false, 'scroll_only missing on old stacks must default false');
  eq(b.purge_rejected, true, 'purge_rejected must be back-filled');
  eq(b.person_selector, 'user-item', 'person_selector must be back-filled');
  eq(b.nick_selector, '.primary-text', 'nick_selector must be back-filled');
  eq(b.enabled, true, 'enabled defaults true');
});

t('migration preserves the user’s saved values', () => {
  const b = StackDnD._migrateBlock(legacyScrollParse({
    max_scrolls: 1000, min_new_users: 2,
    filter_registered: 'any', filter_guest: 'any',
  }));
  eq(b.max_scrolls, 1000);
  eq(b.min_new_users, 2);
  eq(b.filter_female, 'yes');
  eq(b.filter_registered, 'any');
  eq(b.scroll_delta_y, 1000);
});

t('an explicit saved scroll_only:true survives migration', () => {
  const b = StackDnD._migrateBlock(legacyScrollParse({ scroll_only: true }));
  eq(b.scroll_only, true);
});

t('migration keeps unknown keys (CUSTOM_FIND fields)', () => {
  const b = StackDnD._migrateBlock({
    block_id: 'CUSTOM_FIND', custom_name: 'My Finder',
    selector: '.box', label_selector: '.lbl', match_text: 'Settings',
    click_enabled: false, click_selector: '.go',
    pre_delay_ms: 432, enabled: false,
    use_panel_filters: true,   // retired key must still be stripped
    some_future_field: 7,
  });
  eq(b.custom_name, 'My Finder');
  eq(b.match_text, 'Settings');
  eq(b.click_enabled, false);
  eq(b.pre_delay_ms, 432);
  eq(b.enabled, false);
  eq(b.some_future_field, 7, 'unknown keys are preserved');
  ok(!('use_panel_filters' in b), 'retired key stripped even on custom blocks');
});

t('migration ignores junk input', () => {
  eq(StackDnD._migrateBlock(null), null);
  eq(StackDnD._migrateBlock(42), null);
  eq(StackDnD._migrateBlock('x'), null);
  eq(StackDnD._migrateBlock([1, 2]), null);
});

// ── setStack: the path used by session restore / preset load / undo ──

t('setStack migrates a legacy stack (session restore)', () => {
  StackDnD.setStack([legacyScrollParse()], { silent: true });
  eq(StackDnD.stack.length, 1);
  const b = StackDnD.stack[0];
  ok(!('use_panel_filters' in b), 'dead key gone after restore');
  eq(b.scroll_only, false, 'new checkbox setting present after restore');
});

t('addBlockConfig migrates too (add-menu / custom presets)', () => {
  StackDnD.setStack([], { silent: true });
  StackDnD.addBlockConfig(legacyScrollParse());
  const b = StackDnD.stack[0];
  ok(b && !('use_panel_filters' in b), 'dead key gone after add');
  eq(b.scroll_only, false, 'new checkbox setting present after add');
});

t('toggling scroll_only persists on the block', () => {
  StackDnD.setStack([legacyScrollParse()], { silent: true });
  StackDnD.stack[0].scroll_only = true;   // what the checkbox change handler does
  const b = StackDnD._migrateBlock(StackDnD.stack[0]);
  eq(b.scroll_only, true, 'scroll_only:true round-trips through migration');
});

// ── _showConfig: the Tune panel must not render the dead control ─────

t('Tune panel renders the scroll_only checkbox and NOT use_panel_filters', () => {
  StackDnD.setStack([legacyScrollParse()], { silent: true });
  StackDnD._showConfig(0);
  const html = el('blockConfigForm').innerHTML;
  ok(html.indexOf('data-key="scroll_only"') !== -1,
     'panel must contain the scroll_only checkbox');
  ok(html.indexOf('Only scroll, no people adding') !== -1,
     'panel must contain the scroll-only label');
  ok(html.indexOf('use_panel_filters') === -1,
     'panel must NEVER render use_panel_filters');
  // the four tri-state filter selects are the single filter control
  for (const k of ['filter_female', 'filter_registered',
                   'filter_guest', 'filter_anonymous']) {
    ok(html.indexOf('data-key="' + k + '"') !== -1, 'filter control present: ' + k);
  }
});

t('Tune panel still hides a retired key even if a block smuggles one in', () => {
  StackDnD.setStack([], { silent: true });
  StackDnD.stack = [{ block_id: 'SCROLL_PARSE', use_panel_filters: true,
                      enabled: true, pre_delay_ms: 300 }];
  StackDnD._showConfig(0);
  const html = el('blockConfigForm').innerHTML;
  ok(html.indexOf('use_panel_filters') === -1,
     'render loop must skip retired keys defensively');
});

console.log('stack-dnd migration: ' + passed + ' passed, ' + failed + ' failed');
if (failed) process.exit(1);
console.log('OK');
