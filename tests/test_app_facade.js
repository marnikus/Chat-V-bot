/* test_app_facade.js — App facade + its parts (Round H, RULE 8: the real
   shipped files, loaded through tests/js_family like ui/index.html).
   Stubs: DOM elements, the QWebChannel bridge, and the sibling panels —
   everything else is the real app.js / app-history.js / app-bridge.js /
   app-session.js. */
'use strict';
const assert = require('assert');
const { FAMILIES, loadFamily } = require('./js_family');

// ── DOM stub ─────────────────────────────────────────────────────
function makeEl(id) {
  const el = {
    id: id || '', tag: id || '', value: '', textContent: '', innerHTML: '',
    className: '', title: '', disabled: false, children: [], options: [],
    scrollTop: 0, scrollHeight: 100, style: {},
    classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
    appendChild(c) { this.children.push(c); if (c.tag === 'option') this.options.push(c); },
    removeChild() {}, prepend(c) { this.children.unshift(c); },
    addEventListener(t, f) { (this._l = this._l || {})[t] = (this._l[t] || []).concat(f); },
    dispatchEvent(ev) { ((this._l || {})[ev.type] || []).forEach((f) => f(ev)); },
    focus() {}, blur() {}, querySelectorAll() { return []; },
    getBoundingClientRect() { return { top: 100, left: 50 }; },
  };
  return el;
}
const els = {};
['refreshTabsBtn', 'connectBtn', 'tabSelect', 'clearLogBtn', 'undoBtn', 'redoBtn',
 'connectionStatus', 'statTotal', 'statQueued', 'statDone'].forEach((id) => { els[id] = makeEl(id); });
global.document = {
  documentElement: { attrs: {}, setAttribute(k, v) { this.attrs[k] = v; },
                     removeAttribute(k) { delete this.attrs[k]; } },
  getElementById(id) { return els[id] || null; },
  createElement(tag) { return makeEl(tag); },
  addEventListener() {},
};
global.window = global;
global.Event = class { constructor(type) { this.type = type; } };

// ── call recorder + panel stubs ─────────────────────────────────
const calls = [];
const rec = (name) => (...a) => { calls.push([name, ...a]); };
global.UserTable = { init: rec('UserTable.init'), render: rec('UserTable.render'),
  onDeleted: rec('UserTable.onDeleted'), onPersonFound: rec('UserTable.onPersonFound'),
  onPersonRemoved: rec('UserTable.onPersonRemoved') };
const logs = [];
global.LogConsole = { log: (m, l) => logs.push([m, l]), clear: rec('LogConsole.clear') };
global.StackDnD = { history: [], historyIndex: 0, _isRestoringHistory: false,
  applyConfigPin: rec('StackDnD.applyConfigPin'),
  loadHistoryFromState: rec('StackDnD.loadHistoryFromState'),
  setStack: rec('StackDnD.setStack'), refreshPresets: rec('StackDnD.refreshPresets'),
  pushHistory: rec('StackDnD.pushHistory'), updateHistoryButtons: rec('StackDnD.updateHistoryButtons'),
  setRunningBlock: rec('StackDnD.setRunningBlock'), setRunning: rec('StackDnD.setRunning'),
  setCustomBlocks: rec('StackDnD.setCustomBlocks') };
global.PresetsUI = { setStackPresets: rec('PresetsUI.setStackPresets'),
  setTemplatePresets: rec('PresetsUI.setTemplatePresets'),
  setCustomBlocks: rec('PresetsUI.setCustomBlocks'), refreshAll: rec('PresetsUI.refreshAll'),
  loadStack: rec('PresetsUI.loadStack') };
global.UrlToolbar = { restoreSession: rec('UrlToolbar.restoreSession'),
  setPresets: rec('UrlToolbar.setPresets'), onMatch: rec('UrlToolbar.onMatch') };
global.WindowPresets = { init: rec('WindowPresets.init'), refresh: rec('WindowPresets.refresh'),
  setPresets: rec('WindowPresets.setPresets') };
global.HistoryStore = { init: rec('HistoryStore.init'), onPage: rec('HistoryStore.onPage'),
  onStats: rec('HistoryStore.onStats'), onSearch: rec('HistoryStore.onSearch'),
  applySettings: rec('HistoryStore.applySettings'), onError: rec('HistoryStore.onError'),
  onLiveAppend: rec('HistoryStore.onLiveAppend'), onMediaReady: rec('HistoryStore.onMediaReady'),
  setMyNick: rec('HistoryStore.setMyNick'), reloadCurrent: rec('HistoryStore.reloadCurrent') };
global.HistoryDb = { init: rec('HistoryDb.init'), reload: rec('HistoryDb.reload'),
  onPage: rec('HistoryDb.onPage'), onChanged: rec('HistoryDb.onChanged'),
  applySettings: rec('HistoryDb.applySettings'), liveChanged: rec('HistoryDb.liveChanged'),
  onError: rec('HistoryDb.onError') };
global.DbPanel = { init: rec('DbPanel.init'), refresh: rec('DbPanel.refresh'),
  onInfo: rec('DbPanel.onInfo'), onChanged: rec('DbPanel.onChanged') };
global.CollectorPanel = { init: rec('CollectorPanel.init'), onStatus: rec('CollectorPanel.onStatus'),
  onLog: rec('CollectorPanel.onLog'), onAppended: rec('CollectorPanel.onAppended'),
  onPeopleChanged: rec('CollectorPanel.onPeopleChanged'), onDbChanged: rec('CollectorPanel.onDbChanged') };
global.Labels = { init: rec('Labels.init'), applyState: rec('Labels.applyState') };
global.BotChat = { init: rec('BotChat.init'), onReply: rec('BotChat.onReply'),
  onError: rec('BotChat.onError') };
global.BotSettings = { init: rec('BotSettings.init') };
global.BotPrompt = { init: rec('BotPrompt.init'), onReply: rec('BotPrompt.onReply'),
  onPromptsChanged: rec('BotPrompt.onPromptsChanged') };
global.CriteriaEditor = { loadFromJson: rec('CriteriaEditor.loadFromJson'),
  renderDisplay: rec('CriteriaEditor.renderDisplay') };

// ── QWebChannel bridge stub: every signal records its handlers ──
const SIGNALS = ['tabs_received', 'connection_status', 'users_updated', 'users_deleted',
  'person_found', 'person_removed', 'stats_updated', 'log_message', 'step_started',
  'step_complete', 'stack_complete', 'preset_list_updated', 'template_list_updated',
  'url_presets_updated', 'custom_blocks_updated', 'window_preset_list_updated',
  'tab_match_result', 'history_changed', 'stack_loaded', 'history_page_ready',
  'history_stats_ready', 'history_search_ready', 'userdb_page_ready', 'userdb_changed',
  'labels_changed', 'db_info_ready', 'db_changed', 'bot_reply_ready', 'bot_error',
  'bot_prompts_changed', 'collector_status', 'collector_log', 'history_appended',
  'media_ready', 'my_nick_changed', 'history_error'];
function makeBridge() {
  const b = {};
  SIGNALS.forEach((s) => { b[s] = { fns: [], connect(f) { this.fns.push(f); },
    fire(...a) { this.fns.forEach((f) => f(...a)); } }; });
  ['get_tabs', 'connect_tab', 'refresh_users', 'push_global_history', 'save_criteria',
   'get_url_presets', 'set_last_url_preset', 'add_url_preset', 'remove_url_preset',
   'find_tab_by_url'].forEach((m) => { b[m] = (...a) => b.calls.push([m, ...a]); });
  const later = (key, name) => (cb) => { b[key] = cb; b.calls.push([name]); };
  b.get_app_state = later('_appStateCb', 'get_app_state');
  b.get_history_settings = later('_gsCb', 'get_history_settings');
  b.get_criteria = later('_gcCb', 'get_criteria');
  b.get_undo_history = later('_ghCb', 'get_undo_history');
  b.undo = later('_undoCb', 'undo');
  b.redo = later('_redoCb', 'redo');
  b.calls = calls; // shared with the panel recorder (assertCall / clearCalls)
  return b;
}

// ── boot the real family (capturing BridgeReady) ────────────────
global.BridgeReady = { _cb: null, ready(fn) { this._cb = fn; } };
loadFamily(FAMILIES.app);

let passed = 0; let failed = 0;
function test(name, fn) {
  try { fn(); passed += 1; console.log('  ok - ' + name); }
  catch (e) { failed += 1; console.error('  FAIL - ' + name + '\n    ' + e.message); }
}
function clearCalls() { calls.length = 0; logs.length = 0; }
function assertCall(name) {
  assert(calls.some((c) => c[0] === name), 'expected call to ' + name + ' — got: ' + JSON.stringify(calls));
}

test('family load: facade + parts on globalThis', () => {
  assert(typeof global.App === 'object' && typeof global.AppHistory === 'object');
  assert(typeof global.AppBridge === 'object' && typeof global.AppSession === 'object');
  assert.strictEqual(global.App.bridge, null);
  assert.strictEqual(global.App.ready, false);
  ['recordGlobal', 'undoGlobal', 'redoGlobal', 'loadGlobalHistory',
   '_applyGlobalResult', '_syncGlobalHistory'].forEach((m) =>
    assert.strictEqual(typeof global.App[m], 'function', 'App.' + m));
});

test('boot without bridge: header + panels init, not ready', () => {
  clearCalls();
  global.BridgeReady._cb();
  assertCall('UserTable.init'); assertCall('WindowPresets.init');
  assert.strictEqual(global.App.ready, false);
});

const b = makeBridge();
global.App.bridge = b;
global.App.ready = true;
global.initApp(); // top-level fn of app.js (global function declaration)

test('initWithBridge: all 36 signals wired + refresh + app_state', () => {
  SIGNALS.forEach((s) => assert.strictEqual(b[s].fns.length, 1, s + ' wired once'));
  assertCall('refresh_users'); assertCall('get_app_state');
  assertCall('WindowPresets.refresh');
});

test('get_history_settings + get_criteria fire during wiring', () => {
  b._gsCb('{"archive_days":30}'); b._gcCb('[{"label":"l","enabled":true}]');
  assertCall('HistoryStore.applySettings'); assertCall('CriteriaEditor.renderDisplay');
});

test('header: connect empty → warn; with tab → connect_tab; refresh', () => {
  clearCalls();
  els.tabSelect.value = '';
  els.connectBtn._l.click[0]();
  assert(logs.some((l) => l[0].indexOf('Select a tab') >= 0));
  els.tabSelect.value = 'ws1';
  els.connectBtn._l.click[0]();
  els.refreshTabsBtn._l.click[0]();
  assertCall('get_tabs');
  assert(calls.some((c) => c[0] === 'connect_tab' && c[1] === 'ws1'));
});

test('restoreSession: theme, presets, pin, history, last stack', () => {
  clearCalls();
  const payload = { theme: 'light', stack_presets: ['p1'], template_presets: ['t1'],
    custom_blocks: [{ id: 'x' }], url_presets: ['http://u'],
    state: { undo_history: [{ kind: 'people', value: { after: [] } }],
      undo_history_index: 0, block_config_pinned: true,
      last_stack: [{ t: 'click', id: '1' }] } };
  b._appStateCb(JSON.stringify(payload));
  assert.strictEqual(global.document.documentElement.attrs['data-theme'], 'light');
  assertCall('PresetsUI.setStackPresets'); assertCall('UrlToolbar.setPresets');
  assertCall('UrlToolbar.restoreSession'); assertCall('StackDnD.applyConfigPin');
  assert.strictEqual(global.App.globalHistory.length, 1);
  assertCall('StackDnD.setStack'); assertCall('StackDnD.pushHistory');
  assert(logs.some((l) => l[0].indexOf('Restored last stack') >= 0));
});

test('restoreSession: dark theme drops attribute, no stack → refresh', () => {
  clearCalls();
  b._appStateCb(JSON.stringify({ theme: 'dark', state: {} }));
  assert(!('data-theme' in global.document.documentElement.attrs));
  assertCall('StackDnD.refreshPresets');
});

test('recordGlobal: dedupe identical + cap at 100', () => {
  global.App.loadGlobalHistory({ undo_history: [] });
  global.App.recordGlobal('stack', { x: 1 });
  global.App.recordGlobal('stack', { x: 1 });
  assert.strictEqual(global.App.globalHistory.length, 1);
  for (let i = 0; i < 120; i += 1) global.App.recordGlobal('stack', { i });
  assert.strictEqual(global.App.globalHistory.length, 100);
  assert.strictEqual(global.App.globalHistoryIndex, 99);
  assert(calls.filter((c) => c[0] === 'push_global_history').length > 0);
});

test('loadGlobalHistory: legacy stack_history + grid + clamps', () => {
  global.App.loadGlobalHistory({ stack_history: [{ a: 1 }, { a: 2 }], grid_layout: { c: 1 } });
  assert.deepStrictEqual(global.App.globalHistory.map((e) => e.kind), ['stack', 'stack', 'grid']);
  assert.strictEqual(global.App.globalHistoryIndex, 2);
  global.App.loadGlobalHistory({ undo_history: [{ kind: 'grid', value: 1 }], undo_history_index: 9 });
  assert.strictEqual(global.App.globalHistoryIndex, 0);
});

test('undoGlobal: backend callback applies people result', () => {
  clearCalls();
  global.App.loadGlobalHistory({ undo_history: [{ kind: 'people',
    value: { before: [{ nick: 'a' }], after: [] } }] });
  assert.strictEqual(global.App.undoGlobal(), true);
  b._undoCb(JSON.stringify({ kind: 'people', index: 0,
    value: { before: [{ nick: 'a' }], after: [] } }));
  assertCall('UserTable.render'); assertCall('refresh_users');
  assert.strictEqual(global.App.globalHistoryIndex, 0);
});

test('_applyGlobalResult guards: null / bad json / no kind', () => {
  assert.strictEqual(global.App._applyGlobalResult('null'), false);
  assert.strictEqual(global.App._applyGlobalResult('nope'), false);
  assert.strictEqual(global.App._applyGlobalResult('{"n":1}'), false);
});

test('history_changed signal → _syncGlobalHistory re-mirrors', () => {
  clearCalls();
  b.history_changed.fire();
  assertCall('get_undo_history');
  b._ghCb(JSON.stringify({ history: [{ kind: 'grid', value: { c: 1 } }], index: 0 }));
  assert.deepStrictEqual(global.App.globalHistory.map((e) => e.kind), ['grid']);
  assert.strictEqual(global.App.globalHistoryIndex, 0);
});

// ── signal fan-out (one real handler per signal) ────────────────
function fan(sig, args, expect) {
  test('signal ' + sig + ' → ' + expect, () => {
    clearCalls();
    b[sig].fire(...args);
    assertCall(expect);
  });
}
fan('users_updated', ['[{"nick":"a"}]'], 'UserTable.render');
fan('users_deleted', ['[]', 1], 'UserTable.onDeleted');
fan('person_found', [{ nick: 'a' }], 'UserTable.onPersonFound');
fan('person_removed', [{ nick: 'a' }], 'UserTable.onPersonRemoved');
fan('step_started', [3, 'b1', 'a'], 'StackDnD.setRunningBlock');
fan('stack_complete', [], 'StackDnD.setRunning');
fan('preset_list_updated', ['["p1"]'], 'PresetsUI.setStackPresets');
fan('template_list_updated', ['[]'], 'PresetsUI.setTemplatePresets');
fan('url_presets_updated', ['["u"]'], 'UrlToolbar.setPresets');
fan('custom_blocks_updated', ['[{"id":"x"}]'], 'StackDnD.setCustomBlocks');
fan('window_preset_list_updated', ['[{}]'], 'WindowPresets.setPresets');
fan('tab_match_result', ['q', '[]'], 'UrlToolbar.onMatch');
fan('stack_loaded', ['n', '[{"t":"click"}]'], 'StackDnD.updateHistoryButtons');
fan('history_page_ready', ['r', '{}'], 'HistoryStore.onPage');
fan('history_stats_ready', ['r', '{}'], 'HistoryStore.onStats');
fan('history_search_ready', ['r', '{}'], 'HistoryStore.onSearch');
fan('userdb_page_ready', ['r', '{}'], 'HistoryDb.onPage');
fan('userdb_changed', ['{}'], 'DbPanel.refresh');
fan('labels_changed', ['{"labels":{}}'], 'Labels.applyState');
fan('db_info_ready', ['r1', '{}'], 'DbPanel.onInfo');
fan('db_changed', ['{}'], 'HistoryDb.onChanged');
fan('bot_reply_ready', ['r1', '{}'], 'BotChat.onReply');
fan('bot_error', ['r1', 'boom'], 'BotChat.onError');
fan('bot_prompts_changed', ['[]'], 'BotPrompt.onPromptsChanged');
fan('collector_status', ['{}'], 'CollectorPanel.onStatus');
fan('collector_log', ['{}'], 'CollectorPanel.onLog');
fan('history_appended', ['{}'], 'HistoryStore.onLiveAppend');
fan('media_ready', ['m1', '{}'], 'HistoryStore.onMediaReady');
fan('my_nick_changed', ['me'], 'HistoryStore.setMyNick');
fan('history_error', ['userdb', 'oops'], 'HistoryStore.onError');

test('stats_updated paints the counters', () => {
  b.stats_updated.fire('{"total":5,"queued":1,"done":4}');
  assert.strictEqual(els.statTotal.textContent, 5);
  assert.strictEqual(els.statQueued.textContent, 1);
  assert.strictEqual(els.statDone.textContent, 4);
});

test('connection_status paints the dot + logs', () => {
  b.connection_status.fire('connected');
  assert.strictEqual(els.connectionStatus.className, 'status-dot connected');
  assert(logs.some((l) => l[0].indexOf('Connected') >= 0));
});

test('tabs_received rebuilds options', () => {
  b.tabs_received.fire('[{"ws_url":"ws1","title":"T1","url":"http://a"}]');
  assert.strictEqual(els.tabSelect.options.length, 1);
  assert.strictEqual(els.tabSelect.options[0].value, 'ws1');
  assert.strictEqual(global.App.tabs.length, 1);
});

test('log_message routes to LogConsole', () => {
  clearCalls();
  b.log_message.fire('hello', 'warn');
  assert.deepStrictEqual(logs[0], ['hello', 'warn']);
});

console.log('\ntest_app_facade: ' + passed + ' passed, ' + failed + ' failed');
process.exit(failed ? 1 : 0);
