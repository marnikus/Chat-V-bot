/* Tests for the Block Config panel UI fix:
   1. The On/Off toggle bar's switch keeps a fixed 36x20 size (same as the
      Action Stack list toggles) and never flex-grows into a wide blue bar.
   2. Config rows are a clean two-column grid with alternating zebra tones.

   Per AGENT_RULES RULE 8 this executes the REAL shipped module
   (ui/js/stack-dnd.js) in a real runtime (Node), against a tiny DOM stub,
   and asserts against the real shipped ui/css/stack.css.

   Run:  node tests/test_config_panel_rows.js
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

// Load the real shipped module.
const src = fs.readFileSync(
  path.join(__dirname, '..', 'ui', 'js', 'stack-dnd.js'), 'utf8');
const StackDnD = new Function(src + '\nreturn StackDnD;')();
StackDnD.init();

const css = fs.readFileSync(
  path.join(__dirname, '..', 'ui', 'css', 'stack.css'), 'utf8');

// ── tiny assertion kit ──────────────────────────────────────────────
let passed = 0, failed = 0;
function t(name, fn) {
  try { fn(); passed++; }
  catch (e) { failed++; console.error('FAIL ' + name + '\n   ' + (e && e.stack || e)); }
}
function ok(cond, msg) { if (!cond) throw new Error(msg || 'ok'); }

// A fully-populated modern SCROLL_PARSE block (post-migration shape).
function fullScrollParse() {
  return {
    block_id: 'SCROLL_PARSE',
    max_scrolls: 50, scroll_pause_ms: 800, scroll_delta_y: 300,
    viewport_selector: 'cdk-virtual-scroll-viewport.users-list-viewport',
    load_timeout_ms: 2500, stall_threshold: 3, min_new_users: 1,
    person_selector: 'user-item', nick_selector: '.primary-text',
    highlight_enabled: true, highlight_ms: 900, confirm_pause_ms: 500,
    purge_rejected: true, scroll_only: false,
    filter_female: 'yes', filter_registered: 'no', filter_guest: 'yes',
    filter_anonymous: 'no', pre_delay_ms: 300, enabled: true,
  };
}

function renderPanel(block) {
  StackDnD.setStack([block], { silent: true });
  StackDnD._showConfig(0);
  return el('blockConfigForm').innerHTML;
}

// ── zebra stripes: field rows alternate, special rows stay clean ─────

t('field rows get alternating zebra-0 / zebra-1 classes', () => {
  const html = renderPanel(fullScrollParse());
  ok(html.indexOf('zebra-0') !== -1, 'a zebra-0 row must exist');
  ok(html.indexOf('zebra-1') !== -1, 'a zebra-1 row must exist');
  const rows = (html.match(/form-row(?: form-row-check)? zebra-[01]/g) || []);
  ok(rows.length >= 10, 'most field rows are striped, got ' + rows.length);
  rows.forEach((r, i) => {
    const want = ' zebra-' + (i % 2);
    ok(r.indexOf(want) !== -1,
       'zebra must alternate: row ' + i + ' = ' + r);
  });
});

t('zebra stripes cover select rows (filter dropdowns) too', () => {
  const html = renderPanel(fullScrollParse());
  ok(html.indexOf('data-key="filter_female"') > 0, 'filter_female select rendered');
  // Each field row div is followed by its control; check the div that opens
  // the filter_female row carries a zebra class.
  const rows = html.split('<div class="');
  const row = rows.find((r) => r.indexOf('data-key="filter_female"') !== -1);
  ok(row && row.indexOf('form-row zebra-') !== -1,
     'filter_female row must be striped, got: ' + (row || '').slice(0, 80));
});

t('header row and On/Off bar are NOT zebra-striped', () => {
  const html = renderPanel(fullScrollParse());
  ok(html.indexOf('class="form-row form-row--head"') !== -1, 'head row present');
  ok(html.indexOf('class="form-row form-row-check form-row-enabled"') !== -1,
     'On/Off bar present and unstriped');
});

t('zebra stripe counting is per panel render (no leftover state)', () => {
  renderPanel(fullScrollParse());
  const html2 = renderPanel(fullScrollParse());
  const rows = (html2.match(/form-row(?: form-row-check)? zebra-[01]/g) || []);
  ok(rows.length > 0 && rows[0].indexOf(' zebra-0') !== -1,
     'first field row of a fresh render is zebra-0');
});

// ── On/Off toggle bar: structure + fixed size ───────────────────────

// Extract the body of the first CSS rule whose selector is `selector`.
function ruleBody(selector) {
  const at = css.indexOf(selector);
  if (at === -1) return '';
  const open = css.indexOf('{', at);
  if (open === -1) return '';
  const close = css.indexOf('}', open);
  return close === -1 ? css.slice(open + 1) : css.slice(open + 1, close);
}

t('On/Off bar renders toggle-switch + data-key="enabled"', () => {
  const html = renderPanel(fullScrollParse());
  ok(html.indexOf('toggle-switch') !== -1, 'toggle-switch present');
  ok(html.indexOf('data-key="enabled"') !== -1, 'enabled checkbox present');
  ok(html.indexOf('On/Off toggle bar') !== -1, 'bar label present');
});

t('CSS: enabled-bar switch is fixed 36x20 and never flex-grows', () => {
  const block = ruleBody('.config-panel .form-row-enabled .toggle-switch');
  ok(block.indexOf('flex: 0 0 auto') !== -1,
     'switch label must not grow: flex:0 0 auto');
  ok(block.indexOf('width: 36px') !== -1, 'fixed width 36px');
  ok(block.indexOf('height: 20px') !== -1, 'fixed height 20px');
  // the switch must not be sized by the generic label rule
  const labelRule = ruleBody('.config-panel .form-row-enabled > label:first-child');
  ok(labelRule.indexOf('flex: 1') !== -1, 'text label keeps flex:1');
});

t('CSS: no leftover oversized 44px toggle override', () => {
  ok(css.indexOf('width: 44px') === -1, '44px track override must be gone');
  ok(css.indexOf('translateX(18px)') === -1, 'old knob travel override gone');
});

t('CSS: stack-list and config toggle share the same base metrics', () => {
  // The config override only pins size/flex; knob sizing stays the shared
  // base (14px knob, 16px travel) defined once for .toggle-switch.
  ok(css.indexOf('.toggle-switch {\n  position: relative;') !== -1 ||
     css.indexOf('width: 36px;') !== -1, 'base 36px toggle present');
  ok(css.indexOf('height: 14px;') !== -1, 'base 14px knob present');
  ok(css.indexOf('translateX(16px)') !== -1, 'base 16px travel present');
});

// ── two-column rows in the shipped CSS ──────────────────────────────

t('CSS: rows are a two-column grid with a label column', () => {
  ok(css.indexOf('grid-template-columns: minmax(0, 2fr) minmax(0, 3fr)') !== -1,
     'two-column grid template present');
  ok(css.indexOf('.config-panel label {') !== -1, 'label rule present');
  ok(css.indexOf('min-width: 0; font-size: var(--font-size-sm);') !== -1,
     'labels no longer force a 130px gutter');
});

t('CSS: zebra tone rules exist', () => {
  ok(css.indexOf('.form-row.zebra-0') !== -1, 'zebra-0 rule present');
  ok(css.indexOf('.form-row.zebra-1') !== -1, 'zebra-1 rule present');
});

t('CSS: form container scrolls and spaces rows evenly', () => {
  ok(css.indexOf('#blockConfigForm') !== -1, 'form container rule present');
  ok(css.indexOf('overflow-y: auto') !== -1, 'form is scrollable');
  ok(css.indexOf('gap: 6px') !== -1, 'even vertical row gap');
});

console.log('config-panel rows: ' + passed + ' passed, ' + failed + ' failed');
if (failed) process.exit(1);
console.log('OK');
