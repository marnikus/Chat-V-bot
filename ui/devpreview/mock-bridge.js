/* ═══════════════════════════════════════════════════════════════
   mock-bridge.js — DEV/PREVIEW ONLY.

   Emulates the Python QWebChannel bridge (backend/bridge.py) in a
   plain browser so the UI can be exercised without Qt/Chrome/CDP.
   It is loaded ONLY by ui/devpreview/index.html and is never
   referenced by the real ui/index.html shipped to the desktop app.
   ═══════════════════════════════════════════════════════════════ */

(function () {
  'use strict';

  const signal = () => {
    const subs = [];
    return { connect: (f) => subs.push(f), emit: (...a) => subs.forEach((f) => f(...a)) };
  };

  const NAMES = ['Mileena', 'Slut', 'goonette', 'Монстрссахаром', 'хвастаюсь попкой',
    '🤍🤍', 'Absd', 'Serg93', 'weZzzard', 'Андр86', 'Васильевич57',
    'Винкельчпок 😋', 'ВиртУниКач26', "O'Brien \"Quoted\"", 'Драсть',
    'ЖопастыйБи', 'Измена😏', 'Кактус18см', 'Франки', 'Хочумилфочку'];

  let users = NAMES.map((n, i) => ({
    nick: n,
    gender: i % 3 === 0 ? 'female' : i % 3 === 1 ? 'male' : 'unknown',
    registered: i % 2 === 0,
    anonymous: false, guest: i % 5 === 0,
    messaged: i % 4 === 0,
    first_seen: `2026-09-04T1${i % 10}:0${i % 6}:00`,
    last_messaged: i % 4 === 0 ? `2026-09-04T1${i % 9}:30:00` : null,
  }));

  const stacks = {};
  const templates = {};
  let urlPresets = ['https://ru.virt-chat.com/chat'];

  const bridge = {
    users_updated: signal(), stats_updated: signal(), log_message: signal(),
    users_deleted: signal(), tabs_received: signal(), connection_status: signal(),
    step_started: signal(), step_complete: signal(), stack_complete: signal(),
    preset_list_updated: signal(), template_list_updated: signal(),
    url_presets_updated: signal(), tab_match_result: signal(),
    stack_loaded: signal(), template_loaded: signal(),
  };

  const push = () => {
    bridge.users_updated.emit(JSON.stringify(users));
    const done = users.filter((u) => u.messaged).length;
    bridge.stats_updated.emit(JSON.stringify(
      { total: users.length, queued: users.length - done, done }));
  };
  const log = (m, l) => bridge.log_message.emit(m, l || 'info');

  // ── user memory slots ──────────────────────────────────────
  bridge.refresh_users = () => push();
  bridge.delete_user = (nick) => {
    const before = users.length;
    users = users.filter((u) => u.nick !== nick);
    const n = before - users.length;
    log(n ? `🗑 Deleted user “${nick}”` : `⚠ User “${nick}” not found`, 'warn');
    bridge.users_deleted.emit(JSON.stringify([nick]), n);
    push();
  };
  bridge.delete_users = (json) => {
    const list = JSON.parse(json || '[]');
    const set = new Set(list);
    const before = users.length;
    users = users.filter((u) => !set.has(u.nick));
    const n = before - users.length;
    log(`🗑 Deleted ${n} selected user(s): ${list.slice(0, 5).join(', ')}` +
        (list.length > 5 ? '…' : ''), 'warn');
    bridge.users_deleted.emit(json, n);
    push();
  };
  bridge.clear_memory = () => {
    const n = users.length; users = [];
    log(`🗑 Cleared ${n} users`, 'warn');
    bridge.users_deleted.emit('[]', n);
    push();
  };
  bridge.reset_messaged = () => {
    users = users.map((u) => Object.assign({}, u, { messaged: false, last_messaged: null }));
    log(`🔄 Reset ${users.length} users`, 'info');
    push();
  };
  bridge.set_user_messaged = (nick, m) => {
    users = users.map((u) => u.nick === nick
      ? Object.assign({}, u, { messaged: !!m,
          last_messaged: m ? new Date().toISOString().slice(0, 19) : null })
      : u);
    log(`${m ? '✅' : '↩'} “${nick}” marked as ${m ? 'messaged' : 'new'}`, 'info');
    push();
  };

  // ── everything else: harmless stubs ────────────────────────
  bridge.get_tabs = () => bridge.tabs_received.emit(JSON.stringify([
    { id: '1', title: 'Вирт чат', url: 'https://ru.virt-chat.com/chat', ws_url: 'ws://mock/1' },
    { id: '2', title: 'Google', url: 'https://google.com', ws_url: 'ws://mock/2' },
  ]));
  bridge.connect_tab = () => {
    bridge.connection_status.emit('connected');
    log('🔗 Connected (mock preview — no real Chrome tab)', 'success');
  };
  bridge.find_tab_by_url = (q) => {
    log(`🔍 URL preset: parsing “${q}” against open tabs…`);
    bridge.tab_match_result.emit(q, JSON.stringify(
      [{ title: 'Вирт чат', url: 'https://ru.virt-chat.com/chat',
         ws_url: 'ws://mock/1', score: 100, kind: 'url_exact' }]));
  };
  bridge.run_stack = (j) => {
    const blocks = JSON.parse(j);
    log(`▶ Mock run of ${blocks.length} block(s) in the current order`, 'success');
    blocks.forEach((b, i) => setTimeout(() => {
      bridge.step_started.emit(i + 1, b.block_id, 'MockUser');
      log(`▶ Step ${i + 1}/${blocks.length} — ${b.block_id}`, 'info');
      if (i === blocks.length - 1) setTimeout(() => bridge.stack_complete.emit(), 400);
    }, 400 * i));
  };
  bridge.stop_stack = () => bridge.stack_complete.emit();
  bridge.pause_stack = () => {};
  bridge.resume_stack = () => {};
  bridge.save_message = () => {};
  bridge.get_message = (cb) => cb('');
  bridge.save_criteria = () => {};
  bridge.get_criteria = (cb) => cb(JSON.stringify([
    { field: 'registered', op: 'must_have', value: 'true', enabled: true },
    { field: 'guest', op: 'must_not_have', value: 'true', enabled: true },
  ]));
  bridge.get_settings = (cb) => cb(JSON.stringify(
    { chrome: { host: '127.0.0.1', port: 9222 }, scroll: { max_scrolls: 50 } }));
  bridge.save_settings = () => log('💾 Settings saved (mock)');
  const listStacks = () => Object.entries(stacks).map(([name, b]) =>
    ({ name, blocks: b.length, updated_at: new Date().toISOString() }));
  bridge.save_stack_preset = (n, j) => {
    stacks[n] = JSON.parse(j);
    log(`💾 Preset “${n}” saved (${stacks[n].length} blocks)`, 'success');
    bridge.preset_list_updated.emit(JSON.stringify(listStacks()));
  };
  bridge.load_stack_preset = (n, cb) => {
    const b = stacks[n]; const p = b ? JSON.stringify(b) : 'null';
    log(`📂 Preset “${n}” loaded`, 'success');
    if (cb) cb(p); return p;
  };
  bridge.list_stack_presets = (cb) => { const j = JSON.stringify(listStacks()); if (cb) cb(j); return j; };
  bridge.delete_stack_preset = (n) => {
    delete stacks[n]; log(`🗑 Preset “${n}” deleted`, 'warn');
    bridge.preset_list_updated.emit(JSON.stringify(listStacks()));
  };
  const listTpl = () => Object.entries(templates).map(([name, body]) =>
    ({ name, len: body.length, updated_at: new Date().toISOString() }));
  bridge.save_template_preset = (n, b) => {
    templates[n] = b; log(`💾 Template “${n}” saved`, 'success');
    bridge.template_list_updated.emit(JSON.stringify(listTpl()));
  };
  bridge.load_template_preset = (n, cb) => { const b = templates[n] || ''; if (cb) cb(b); return b; };
  bridge.list_template_presets = (cb) => { const j = JSON.stringify(listTpl()); if (cb) cb(j); return j; };
  bridge.delete_template_preset = (n) => {
    delete templates[n];
    bridge.template_list_updated.emit(JSON.stringify(listTpl()));
  };
  bridge.get_url_presets = (cb) => { const j = JSON.stringify(urlPresets); if (cb) cb(j); return j; };
  bridge.add_url_preset = (u) => {
    if (u && urlPresets.indexOf(u) < 0) urlPresets.push(u);
    bridge.url_presets_updated.emit(JSON.stringify(urlPresets));
  };
  bridge.remove_url_preset = (u) => {
    urlPresets = urlPresets.filter((x) => x !== u);
    bridge.url_presets_updated.emit(JSON.stringify(urlPresets));
  };
  bridge.get_stack_json = (cb) => { if (cb) cb('[]'); return '[]'; };

  // Emulate the QWebChannel handshake app.js expects
  window.qt = { webChannelTransport: {} };
  window.QWebChannel = function (transport, cb) {
    setTimeout(() => cb({ objects: { bridge } }), 0);
  };
  window.__mockBridge = bridge;
  setTimeout(() => log('🧪 Preview mode — mock backend, no Chrome/CDP required', 'success'), 50);
})();
