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
    let wsUrl = tabSelect.value;
    if (!wsUrl) {
      // URL preset auto-select: try the active preset, then any saved preset
      const active = getActiveUrlPreset();
      const preset = active || (App.urlPresets.length ? App.urlPresets[0] : null);
      if (preset) {
        const tab = autoSelectTabForPreset(preset);
        if (tab) wsUrl = tab.ws_url || tab.url;
      }
    }
    if (!wsUrl) { LogConsole.log('⚠ Select a tab first (or choose a URL preset)', 'warn'); return; }
    App.bridge.connect_tab(wsUrl);
  });

  settingsBtn.addEventListener('click', openSettings);
}

// ── URL presets ───────────────────────────────────────────────
function setupUrlPresets() {
  const sel = document.getElementById('urlPresetSelect');
  const saveBtn = document.getElementById('saveUrlPresetBtn');
  const manageBtn = document.getElementById('manageUrlPresetBtn');

  if (App.bridge) {
    App.bridge.get_url_presets((json) => {
      try { App.urlPresets = JSON.parse(json) || []; } catch (e) { App.urlPresets = []; }
      renderUrlPresetSelect();
      // Default to the first URL preset so the matching tab is auto-selected.
      if (!sel.value && App.urlPresets.length) sel.value = App.urlPresets[0].name;
      autoSelectByUrlPreset();
    });
  }

  sel.addEventListener('change', () => autoSelectByUrlPreset());

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
  if (current && App.urlPresets.some(p => p.name === current)) sel.value = current;
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
    autoSelectByUrlPreset();
  });

  b.url_presets_updated.connect((json) => {
    try { App.urlPresets = JSON.parse(json) || []; } catch (e) { App.urlPresets = []; }
    renderUrlPresetSelect();
    autoSelectByUrlPreset();
    const modal = document.getElementById('urlPresetModal');
    if (modal && !modal.classList.contains('hidden')) UrlPresetManager.render();
  });

  b.finder_presets_updated.connect((json) => {
    try { App.finderPresets = JSON.parse(json) || []; } catch (e) { App.finderPresets = []; }
    if (typeof StackDnD !== 'undefined') StackDnD.populateFinderPresetSelect();
  });

  b.stack_presets_updated.connect(() => {
    if (typeof StackDnD !== 'undefined') {
      const modal = document.getElementById('stackPresetModal');
      if (modal && !modal.classList.contains('hidden')) StackDnD.renderStackPresets();
    }
  });

  b.stack_loaded.connect((json) => {
    try {
      const blocks = JSON.parse(json);
      if (typeof StackDnD !== 'undefined') {
        StackDnD.stack = blocks;
        StackDnD._renderStack();
        if (StackDnD.selectedIdx >= 0 && StackDnD.selectedIdx < blocks.length) {
          StackDnD._showConfig(StackDnD.selectedIdx);
        }
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
    if (typeof values !== 'object' || values === null || Array.isArray(values)) continue;
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
