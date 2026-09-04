/* ═══════════════════════════════════════════════════════════════
   app.js — Main initialization, QWebChannel bridge, global state
   ═══════════════════════════════════════════════════════════════ */

'use strict';

const App = {
  bridge: null,
  ready: false,
  tabs: [],
  urlPresets: [],
  finderPresets: [],
  // A URL preset only auto-selects the matching tab after the user picks it.
  // It must never auto-connect on startup.
  urlPresetChosen: false,
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
  setupUrlPresets();
  if (App.bridge) setupBridgeListeners();
  if (App.bridge) restorePersistedState();
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
    let wsUrl = tabSelect.value;
    if (!wsUrl && App.urlPresetChosen) {
      // Only auto-pick a tab when the user has explicitly chosen a URL preset.
      const preset = getActiveUrlPreset();
      if (preset) {
        const tab = autoSelectTabForPreset(preset);
        if (tab) wsUrl = tab.ws_url || tab.url;
      }
    }
    if (!wsUrl) { LogConsole.log('⚠ Select a tab first (or choose a URL preset)', 'warn'); return; }
    App.bridge.connect_tab(wsUrl);
  });
}

// ── URL presets ───────────────────────────────────────────────
function setupUrlPresets() {
  const sel = document.getElementById('urlPresetSelect');
  const saveBtn = document.getElementById('saveUrlPresetBtn');
  const manageBtn = document.getElementById('manageUrlPresetBtn');

  if (App.bridge) {
    App.bridge.get_url_presets((json) => {
      try { App.urlPresets = JSON.parse(json) || []; } catch (e) { App.urlPresets = []; }
      // Do NOT default-select a preset or auto-connect on startup.
      renderUrlPresetSelect();
    });
  }

  sel.addEventListener('change', () => {
    App.urlPresetChosen = !!sel.value;
    // Remember the user's last chosen URL preset.
    if (App.bridge) App.bridge.set_active_url_preset(sel.value);
    autoSelectByUrlPreset();
  });

  saveBtn.addEventListener('click', () => {
    const name = prompt('URL preset name:');
    if (!name) return;
    const tabSelect = document.getElementById('tabSelect');
    const selectedTab = App.tabs.find(t => (t.ws_url || t.url) === tabSelect.value);
    const pattern = prompt('URL pattern (substring of the tab URL):',
                           selectedTab ? selectedTab.url : 'ru.virt-chat.com');
    if (pattern && App.bridge) App.bridge.save_url_preset(name, pattern);
  });

  manageBtn.addEventListener('click', () => UrlPresetManager.open());
}

function renderUrlPresetSelect() {
  const sel = document.getElementById('urlPresetSelect');
  if (!sel) return;
  const current = sel.value;
  sel.innerHTML = '<option value="">— URL Preset —</option>';
  (App.urlPresets || []).forEach(p => {
    const o = document.createElement('option');
    o.value = p.name;
    o.textContent = `${p.name} (${p.pattern})`;
    sel.appendChild(o);
  });
  if (current && App.urlPresets.some(p => p.name === current)) {
    sel.value = current;
  } else {
    sel.value = '';
    App.urlPresetChosen = false;
  }
}

function getActiveUrlPreset() {
  const sel = document.getElementById('urlPresetSelect');
  const name = sel ? sel.value : '';
  return (App.urlPresets || []).find(p => p.name === name) || null;
}

function autoSelectTabForPreset(preset) {
  if (!preset || !preset.pattern) return null;
  const pattern = String(preset.pattern).toLowerCase();
  const tab = App.tabs.find(t => String(t.url || '').toLowerCase().includes(pattern));
  if (tab) {
    const tabSelect = document.getElementById('tabSelect');
    tabSelect.value = tab.ws_url || tab.url;
    LogConsole.log(`🔗 URL preset "${preset.name}" matched tab: ${tab.title}`, 'success');
    return tab;
  }
  LogConsole.log(`⚠ URL preset "${preset.name}" found no matching Chrome tab`, 'warn');
  return null;
}

function autoSelectByUrlPreset() {
  const preset = getActiveUrlPreset();
  if (preset) return autoSelectTabForPreset(preset);
  return null;
}

// Restore the last loaded stack preset and the last chosen URL preset.
// This must run after urlPresets are loaded so the dropdown can reflect it.
function restorePersistedState() {
  if (!App.bridge) return;
  App.bridge.get_state((json) => {
    try {
      const st = JSON.parse(json) || {};
      const sel = document.getElementById('urlPresetSelect');
      if (st.active_url_preset &&
          (App.urlPresets || []).some(p => p.name === st.active_url_preset)) {
        sel.value = st.active_url_preset;
        App.urlPresetChosen = true;
        LogConsole.log(`🔎 Restored last URL preset: ${st.active_url_preset}`, 'info');
      }
      if (st.last_preset) {
        LogConsole.log(`📂 Restoring last used preset: ${st.last_preset}`, 'info');
        App.bridge.load_stack_preset(st.last_preset);
      }
    } catch (e) {}
  });
}

const UrlPresetManager = {
  open() {
    document.getElementById('urlPresetModal').classList.remove('hidden');
    this.render();
  },
  close() {
    document.getElementById('urlPresetModal').classList.add('hidden');
  },
  render() {
    const list = document.getElementById('urlPresetList');
    list.innerHTML = (App.urlPresets || []).map(p => `
      <div class="preset-row">
        <span class="preset-name">${p.name}</span>
        <span class="preset-meta">${p.pattern}</span>
        <button onclick="UrlPresetManager.use('${p.name.replace(/'/g, "\\'")}')">Use</button>
        <button class="btn-danger-text" onclick="UrlPresetManager.remove('${p.name.replace(/'/g, "\\'")}')">Delete</button>
      </div>
    `).join('') || '<div class="preset-empty">No URL presets yet</div>';

    document.getElementById('urlPresetSaveBtn').onclick = () => {
      const name = document.getElementById('urlPresetName').value.trim();
      const pattern = document.getElementById('urlPresetPattern').value.trim();
      if (!name || !pattern) { LogConsole.log('⚠ Enter a name and URL pattern', 'warn'); return; }
      if (App.bridge) { App.bridge.save_url_preset(name, pattern); this.close(); }
    };
    document.getElementById('urlPresetCloseBtn').onclick = () => this.close();
  },
  use(name) {
    const preset = (App.urlPresets || []).find(p => p.name === name);
    if (!preset) return;
    const sel = document.getElementById('urlPresetSelect');
    if (sel) sel.value = name;
    App.urlPresetChosen = true;
    autoSelectTabForPreset(preset);
    this.close();
  },
  remove(name) {
    if (App.bridge) App.bridge.delete_url_preset(name);
    this.render();
  },
};

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
    // Only auto-select a matching tab if the user has explicitly chosen a preset.
    if (App.urlPresetChosen) autoSelectByUrlPreset();
  });

  b.url_presets_updated.connect((json) => {
    try { App.urlPresets = JSON.parse(json) || []; } catch (e) { App.urlPresets = []; }
    renderUrlPresetSelect();
    // Never auto-connect at startup; only re-select if the user chose one.
    if (App.urlPresetChosen) autoSelectByUrlPreset();
    const modal = document.getElementById('urlPresetModal');
    if (modal && !modal.classList.contains('hidden')) UrlPresetManager.render();
  });

  b.finder_presets_updated.connect((json) => {
    try { App.finderPresets = JSON.parse(json) || []; } catch (e) { App.finderPresets = []; }
    if (typeof StackDnD !== 'undefined') StackDnD.populateFinderPresetSelect();
  });

  b.active_url_updated.connect((name) => {
    const sel = document.getElementById('urlPresetSelect');
    if (!sel) return;
    sel.value = name || '';
    App.urlPresetChosen = !!name;
  });

  b.stack_presets_updated.connect(() => {
    if (typeof StackDnD !== 'undefined') {
      const modal = document.getElementById('stackPresetModal');
      if (modal && !modal.classList.contains('hidden')) StackDnD.renderStackPresets();
    }
  });

  b.stack_loaded.connect((json) => {
    try {
      const data = JSON.parse(json);
      const blocks = Array.isArray(data) ? data : (data.blocks || []);
      if (typeof StackDnD !== 'undefined') {
        StackDnD.stack = blocks;
        StackDnD._renderStack();
        if (StackDnD.selectedIdx >= 0 && StackDnD.selectedIdx < blocks.length) {
          StackDnD._showConfig(StackDnD.selectedIdx);
        }
      }
      const sel = document.getElementById('urlPresetSelect');
      if (data && data.url_preset && sel &&
          (App.urlPresets || []).some(p => p.name === data.url_preset)) {
        sel.value = data.url_preset;
        App.urlPresetChosen = true;
        autoSelectByUrlPreset();
      }
    } catch (e) {}
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
    // highlight active step in stack (handled by stack-dnd.js)
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
