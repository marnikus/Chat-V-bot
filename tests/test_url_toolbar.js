/* test_url_toolbar.js — url-toolbar.js (Round H: first Node harness for this
   file, RULE 8: the real shipped file, DOM + bridge + sibling panels stubbed). */
'use strict';
const assert = require('assert');
const { loadSingle } = require('./js_family');

function makeEl(id) {
  const el = {
    id: id || '', tag: id || '', value: '', textContent: '', innerHTML: '',
    className: '', children: [], options: [], selectedOptions: [],
    appendChild(c) { this.children.push(c); if (c.tag === 'option') this.options.push(c); return c; },
    prepend(c) { this.children.unshift(c); if (c.tag === 'option') this.options.unshift(c); },
    addEventListener(t, f) { (this._l = this._l || {})[t] = (this._l[t] || []).concat(f); },
    dispatchEvent(ev) { ((this._l || {})[ev.type] || []).forEach((f) => f(ev)); },
    focus() {},
  };
  el.classList = {
    add(c) { const s = el.className.split(' ').filter(Boolean);
      if (!s.includes(c)) s.push(c); el.className = s.join(' '); },
    remove(c) { el.className = el.className.split(' ').filter((x) => x !== c).join(' '); },
    toggle(c) { el.classList.contains(c) ? el.classList.remove(c) : el.classList.add(c); },
    contains(c) { return el.className.split(' ').includes(c); },
  };
  return el;
}
const els = {};
['urlInput', 'urlConnectBtn', 'addUrlPresetBtn', 'connectBtn', 'tabSelect',
 'urlPresetChips', 'connectionStatus'].forEach((id) => { els[id] = makeEl(id); });
global.document = { getElementById: (id) => els[id] || null,
  createElement: (t) => makeEl(t), addEventListener() {} };
global.window = global;

const calls = [];
const rec = (name) => (...a) => { calls.push([name, ...a]); };
const chips = [];
global.UIHelpers = { chip(opts) { chips.push(opts); return makeEl('chip'); } };
const logs = [];
global.LogConsole = { log: (m, l) => logs.push([m, l]), clear() {} };
const b = { get calls() { return calls; } };
['set_last_url_preset', 'add_url_preset', 'remove_url_preset', 'find_tab_by_url',
 'connect_tab'].forEach((m) => { b[m] = rec(m); });
b.get_url_presets = (cb) => { calls.push(['get_url_presets']); b._presetsCb = cb; };
global.App = { bridge: b };

global.BridgeReady = { _cb: null, ready(fn) { this._cb = fn; } };
loadSingle('url-toolbar.js', 'UrlToolbar');
const UrlToolbar = global.UrlToolbar;
global.BridgeReady._cb(); // UrlToolbar.init()

let passed = 0; let failed = 0;
function test(name, fn) {
  try { fn(); passed += 1; console.log('  ok - ' + name); }
  catch (e) { failed += 1; console.error('  FAIL - ' + name + '\n    ' + e.message); }
}
function clearCalls() { calls.length = 0; logs.length = 0; chips.length = 0; }
function assertCall(name) {
  assert(calls.some((c) => c[0] === name), 'expected ' + name + ' — got ' + JSON.stringify(calls));
}

test('load + init: no crash, state defaults', () => {
  assert(Array.isArray(UrlToolbar.presets) && UrlToolbar.presets.length === 0);
  assert.strictEqual(UrlToolbar._autoConnected, false);
});

test('shortUrl strips scheme + trailing slashes', () => {
  assert.strictEqual(UrlToolbar.shortUrl('https://example.com/'), 'example.com');
  assert.strictEqual(UrlToolbar.shortUrl('http://a.io///'), 'a.io');
});

test('header connectBtn syncs field + bookmark from selected tab', () => {
  clearCalls();
  els.tabSelect.selectedOptions = [{ value: 'ws1', textContent: 'My tab — http://x.com' }];
  els.connectBtn._l.click[0]();
  assert.strictEqual(els.urlInput.value, 'http://x.com');
  assertCall('set_last_url_preset');
});

test('setPresets renders chips; empty renders the placeholder', () => {
  clearCalls();
  UrlToolbar.setPresets('["http://a.com","http://b.com"]');
  assert.strictEqual(chips.length, 2);
  assert.strictEqual(chips[0].title, '🔗 a.com');
  assert.strictEqual(els.urlPresetChips.innerHTML, '');
  chips.length = 0;
  UrlToolbar.setPresets('[]');
  assert(chips.length === 0 && els.urlPresetChips.innerHTML.indexOf('no URL presets') >= 0);
  UrlToolbar.setPresets('not json');
  assert.strictEqual(UrlToolbar.presets.length, 0);
});

test('selectBookmark: field, persist, connect', () => {
  clearCalls();
  UrlToolbar.selectBookmark('http://a.com', { connect: true, notify: true });
  assert.strictEqual(UrlToolbar.selectedUrl, 'http://a.com');
  assert.strictEqual(els.urlInput.value, 'http://a.com');
  assertCall('set_last_url_preset'); assertCall('find_tab_by_url');
  assert.strictEqual(els.connectionStatus.className, 'status-dot connecting');
});

test('selectBookmark notify:false skips persistence; rememberUrl skips connect', () => {
  clearCalls();
  UrlToolbar.selectBookmark('http://n.com', { connect: false, notify: false });
  assert(!calls.some((c) => c[0] === 'set_last_url_preset'));
  UrlToolbar.rememberUrl('http://r.com');
  assert.strictEqual(UrlToolbar.selectedUrl, 'http://r.com');
  assertCall('set_last_url_preset');
  assert(!calls.some((c) => c[0] === 'find_tab_by_url'));
});

test('addPreset: empty warns, otherwise asks the backend', () => {
  clearCalls();
  UrlToolbar.addPreset('');
  assert(logs.some((l) => l[1] === 'warn'));
  UrlToolbar.addPreset('http://new.com');
  assertCall('add_url_preset');
});

test('connectNow guards: empty query / no bridge warn', () => {
  clearCalls();
  UrlToolbar.connectNow('');
  assert(logs.some((l) => l[0].indexOf('empty') >= 0));
  const saved = global.App.bridge;
  global.App.bridge = null;
  UrlToolbar.connectNow('http://x.com');
  assert(logs.some((l) => l[0].indexOf('Not connected') >= 0));
  global.App.bridge = b;
});

test('onMatch: no match → dot back to disconnected', () => {
  clearCalls();
  els.connectionStatus.className = 'status-dot connecting';
  UrlToolbar.onMatch('q', '[]');
  assert.strictEqual(els.connectionStatus.className, 'status-dot disconnected');
  assert(!calls.some((c) => c[0] === 'connect_tab'));
});

test('onMatch: match → option added, bookmarked, tab connected', () => {
  clearCalls();
  els.tabSelect.options = [];
  els.connectionStatus.className = 'status-dot connecting';
  UrlToolbar.onMatch('q', '[{"ws_url":"ws9","title":"T","url":"http://best.com"}]');
  assert.strictEqual(els.tabSelect.options.length, 1);
  assert.strictEqual(els.tabSelect.options[0].value, 'ws9');
  assert.strictEqual(els.tabSelect.value, 'ws9');
  assert.strictEqual(UrlToolbar.selectedUrl, 'http://best.com');
  assertCall('set_last_url_preset'); assertCall('connect_tab');
  assert(logs.some((l) => l[0].indexOf('Auto-selected tab') >= 0));
});

test('onMatch: existing option re-selected (no prepend)', () => {
  clearCalls();
  els.tabSelect.options = [{ value: 'ws9' }];
  UrlToolbar.onMatch('q', '[{"ws_url":"ws9","title":"T","url":"http://best.com"}]');
  assert.strictEqual(els.tabSelect.options.length, 1);
  assert.strictEqual(els.tabSelect.value, 'ws9');
});

test('chip actions: load connects, delete removes preset', () => {
  clearCalls();
  UrlToolbar.setPresets('["http://a.com"]');
  UrlToolbar.selectedUrl = 'http://a.com';
  chips[0].onLoad();
  assertCall('find_tab_by_url');
  chips[0].onDelete();
  assertCall('remove_url_preset');
  assert.strictEqual(UrlToolbar.selectedUrl, '');
});

test('refresh() pulls the preset list through the backend', () => {
  clearCalls();
  UrlToolbar.refresh();
  assertCall('get_url_presets');
  b._presetsCb('["http://r.com"]');
  assert.strictEqual(UrlToolbar.presets[0], 'http://r.com');
});

test('restoreSession: no preset → inert', () => {
  clearCalls();
  UrlToolbar.restoreSession({ state: {} });
  assert.strictEqual(UrlToolbar.selectedUrl, '');
  assert.strictEqual(UrlToolbar._autoConnected, false);
});

test('restoreSession: preset → bookmark + auto-connect flag', () => {
  clearCalls();
  UrlToolbar.restoreSession({ state: { last_url_preset: 'http://last.com' } });
  assert.strictEqual(UrlToolbar.selectedUrl, 'http://last.com');
  assert.strictEqual(UrlToolbar._autoConnected, true);
  assert(logs.some((l) => l[0].indexOf('Restored bookmark') >= 0));
});

// the auto-connect fires ~600 ms after startup — verify it lands
setTimeout(() => {
  test('restoreSession: delayed auto-connect hit the backend', () => {
    assert(calls.some((c) => c[0] === 'find_tab_by_url' && c[1] === 'http://last.com'));
  });
  console.log('\ntest_url_toolbar: ' + passed + ' passed, ' + failed + ' failed');
  process.exit(failed ? 1 : 0);
}, 800);
