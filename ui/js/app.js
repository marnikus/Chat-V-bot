/* ═══════════════════════════════════════════════════════════════
   app.js — Main initialization, QWebChannel bridge, session restore
   ═══════════════════════════════════════════════════════════════ */

'use strict';

const App = {
  bridge: null,
  ready: false,
  tabs: [],
};

// ── QWebChannel init ──────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  if (typeof QWebChannel !== 'undefined') {
    new QWebChannel(qt.webChannelTransport, (channel) => {
      App.bridge = channel.objects.bridge;
      App.ready = true;
      console.log('QWebChannel connected');
      initApp();
    });
  } else {
    console.warn('QWebChannel not available — running in standalone mode');
    initApp();
  }
});

function initApp() {
  setupHeader();
  UserTable.init();
  document.getElementById('clearLogBtn').addEventListener('click', () => LogConsole.clear());
  if (App.bridge) {
    setupBridgeListeners();
    // fill the people list on start, not only after connecting to a tab
    App.bridge.refresh_users();
    // single payload with everything needed to restore the session (BUG #2)
    App.bridge.get_app_state((json) => restoreSession(json));
  }
}

// ── Session restore (BUG #2 / single preset storage) ──────────
function restoreSession(json) {
  let payload = {};
  try { payload = JSON.parse(json); } catch (e) { payload = {}; }

  // seed chips from the single store
  PresetsUI.setStackPresets(JSON.stringify(payload.stack_presets || []));
  PresetsUI.setTemplatePresets(JSON.stringify(payload.template_presets || []));
  PresetsUI.setCustomBlocks(payload.custom_blocks || []);
  StackDnD.setCustomBlocks(payload.custom_blocks || []);
  UrlToolbar.setPresets(JSON.stringify(payload.url_presets || []));

  const state = payload.state || {};

  // 1) restore the last stack (snapshot or the named preset)
  const lastStack = Array.isArray(state.last_stack) ? state.last_stack : null;
  const lastPreset = state.last_stack_preset || '';
  if (Array.isArray(lastStack) && lastStack.length) {
    StackDnD.setStack(lastStack, { silent: true });
    LogConsole.log(`♻ Restored last stack (${lastStack.length} block(s))`, 'info');
  } else if (lastPreset) {
    PresetsUI.loadStack(lastPreset);
  } else {
    StackDnD.refreshPresets();
  }

  // 2) restore the last bookmark + try auto-connect with its URL
  UrlToolbar.restoreSession(payload);

  // refresh remaining lists
  PresetsUI.refreshAll();
}

// ── Header: tabs + connect ────────────────────────────────────
function setupHeader() {
  const refreshBtn = document.getElementById('refreshTabsBtn');
  const connectBtn = document.getElementById('connectBtn');
  const tabSelect = document.getElementById('tabSelect');

  refreshBtn.addEventListener('click', () => {
    if (!App.bridge) return;
    App.bridge.get_tabs();
  });

  connectBtn.addEventListener('click', () => {
    if (!App.bridge) return;
    const wsUrl = tabSelect.value;
    if (!wsUrl) { LogConsole.log('⚠ Select a tab first', 'warn'); return; }
    App.bridge.connect_tab(wsUrl);
  });
}

// ── Bridge signal listeners ───────────────────────────────────
function setupBridgeListeners() {
  const b = App.bridge;

  b.tabs_received.connect((json) => {
    const tabs = JSON.parse(json);
    App.tabs = tabs;
    const sel = document.getElementById('tabSelect');
    const prev = sel.value;
    sel.innerHTML = '<option value="">— Select Chrome Tab —</option>';
    tabs.forEach(t => {
      const opt = document.createElement('option');
      opt.value = t.ws_url || t.url;
      opt.textContent = `${t.title} — ${t.url}`.substring(0, 80);
      sel.appendChild(opt);
    });
    // re-select the previous choice if it still exists
    if (prev && Array.prototype.some.call(sel.options, (o) => o.value === prev)) {
      sel.value = prev;
    }
  });

  b.connection_status.connect((status) => {
    const dot = document.getElementById('connectionStatus');
    dot.className = 'status-dot ' + status;
    dot.title = status.charAt(0).toUpperCase() + status.slice(1);
    if (status === 'connected') {
      LogConsole.log('🔗 Connected to Chrome tab', 'success');
    } else if (status === 'disconnected') {
      LogConsole.log('🔴 Disconnected', 'error');
    }
  });

  b.users_updated.connect((json) => {
    let users = [];
    try { users = JSON.parse(json); } catch (e) { users = []; }
    UserTable.render(users);
  });

  // people list: deletions (single / selection / clear all)
  b.users_deleted.connect((nicksJson, count) => {
    UserTable.onDeleted(nicksJson);
  });

  b.stats_updated.connect((json) => {
    const s = JSON.parse(json);
    document.getElementById('statTotal').textContent = s.total || 0;
    document.getElementById('statQueued').textContent = s.queued || 0;
    document.getElementById('statDone').textContent = s.done || 0;
  });

  b.log_message.connect((msg, level) => {
    LogConsole.log(msg, level);
  });

  // debugger: highlight the currently running block in the stack
  b.step_started.connect((idx, blockId, nick) => {
    StackDnD.setRunningBlock(idx - 1);
  });

  b.step_complete.connect(() => {
    // (log lines for each step are streamed via log_message)
  });

  b.stack_complete.connect(() => {
    StackDnD.setRunning(false);
  });

  // presets / templates / custom blocks live updates
  b.preset_list_updated.connect((json) => PresetsUI.setStackPresets(json));
  b.template_list_updated.connect((json) => PresetsUI.setTemplatePresets(json));
  b.url_presets_updated.connect((json) => UrlToolbar.setPresets(json));
  b.custom_blocks_updated.connect((json) => {
    try {
      const list = JSON.parse(json);
      StackDnD.setCustomBlocks(list);
      PresetsUI.setCustomBlocks(list);
    } catch (e) { /* ignore */ }
  });
  b.tab_match_result.connect((query, json) => UrlToolbar.onMatch(query, json));

  // Load initial criteria display
  b.get_criteria((json) => {
    CriteriaEditor.loadFromJson(json);
    CriteriaEditor.renderDisplay();
  });
}
