/* ═══════════════════════════════════════════════════════════════
   app.js — Main initialization, QWebChannel bridge, global state
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
  if (App.bridge) setupBridgeListeners();
}

// ── Header: tabs + connect ────────────────────────────────────
function setupHeader() {
  const refreshBtn = document.getElementById('refreshTabsBtn');
  const connectBtn = document.getElementById('connectBtn');
  const settingsBtn = document.getElementById('settingsBtn');
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

  settingsBtn.addEventListener('click', openSettings);
}

// ── Bridge signal listeners ───────────────────────────────────
function setupBridgeListeners() {
  const b = App.bridge;

  b.tabs_received.connect((json) => {
    const tabs = JSON.parse(json);
    App.tabs = tabs;
    const sel = document.getElementById('tabSelect');
    sel.innerHTML = '<option value="">— Select Chrome Tab —</option>';
    tabs.forEach(t => {
      const opt = document.createElement('option');
      opt.value = t.ws_url || t.url;
      opt.textContent = `${t.title} — ${t.url}`.substring(0, 80);
      sel.appendChild(opt);
    });
  });

  b.connection_status.connect((status) => {
    const dot = document.getElementById('connectionStatus');
    dot.className = 'status-dot ' + status;
    dot.title = status.charAt(0).toUpperCase() + status.slice(1);
    if (status === 'connected') LogConsole.log('🔗 Connected to Chrome', 'success');
    else if (status === 'disconnected') LogConsole.log('🔴 Disconnected', 'error');
  });

  b.users_updated.connect((json) => {
    const users = JSON.parse(json);
    UserTable.render(users);
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

  b.step_complete.connect((block, nick) => {
    // highlight active step in stack
  });

  b.stack_complete.connect(() => {
    document.getElementById('runBtn').disabled = false;
    document.getElementById('pauseBtn').disabled = true;
    document.getElementById('stopBtn').disabled = true;
    StackDnD.setRunning(false);
  });

  // Load initial criteria display
  b.get_criteria((json) => {
    CriteriaEditor.loadFromJson(json);
    CriteriaEditor.renderDisplay();
  });
}

// ── Settings modal ────────────────────────────────────────────
function openSettings() {
  const modal = document.getElementById('settingsModal');
  modal.classList.remove('hidden');
  if (App.bridge) {
    App.bridge.get_settings((json) => renderSettingsForm(JSON.parse(json)));
  }
  document.getElementById('settingsSaveBtn').onclick = () => {
    const data = collectSettingsForm();
    if (App.bridge) App.bridge.save_settings(JSON.stringify(data));
    modal.classList.add('hidden');
  };
  document.getElementById('settingsCancelBtn').onclick = () => {
    modal.classList.add('hidden');
  };
}

function renderSettingsForm(settings) {
  const form = document.getElementById('settingsForm');
  form.innerHTML = '';
  for (const [section, values] of Object.entries(settings)) {
    if (typeof values !== 'object') continue;
    const h = document.createElement('h4');
    h.textContent = section.toUpperCase();
    h.style.cssText = 'margin:12px 0 6px;color:var(--text-secondary);font-size:11px;letter-spacing:1px';
    form.appendChild(h);
    for (const [key, val] of Object.entries(values)) {
      const row = document.createElement('div');
      row.className = 'form-row';
      row.innerHTML = `<label>${key}</label><input data-section="${section}" data-key="${key}" value="${val}" type="${typeof val === 'number' ? 'number' : typeof val === 'boolean' ? 'checkbox' : 'text'}" ${typeof val === 'boolean' && val ? 'checked' : ''}>`;
      form.appendChild(row);
    }
  }
}

function collectSettingsForm() {
  const data = {};
  document.querySelectorAll('#settingsForm input[data-section]').forEach(inp => {
    const s = inp.dataset.section, k = inp.dataset.key;
    if (!data[s]) data[s] = {};
    if (inp.type === 'checkbox') data[s][k] = inp.checked;
    else if (inp.type === 'number') data[s][k] = Number(inp.value);
    else data[s][k] = inp.value;
  });
  return data;
}
