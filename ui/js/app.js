/* ═══════════════════════════════════════════════════════════════
   app.js — Main initialization, QWebChannel bridge, session restore
   ═══════════════════════════════════════════════════════════════ */

'use strict';

const App = {
  bridge: null,
  ready: false,
  tabs: [],
  // One chronological history for stack edits and grid edits alike.
  globalHistory: [],
  globalHistoryIndex: -1,

  _copy(value) {
    try { return JSON.parse(JSON.stringify(value)); }
    catch (e) { return value; }
  },

  loadGlobalHistory(state) {
    state = state || {};
    let history = Array.isArray(state.undo_history) ? state.undo_history : [];
    if (!history.length && Array.isArray(state.stack_history)) {
      history = state.stack_history.map((value) => ({ kind: 'stack', value }));
      if (state.grid_layout) history.push({ kind: 'grid', value: state.grid_layout });
    }
    this.globalHistory = history.filter((entry) =>
      entry && (entry.kind === 'stack' || entry.kind === 'grid' ||
                entry.kind === 'people'))
      .map((entry) => ({ kind: entry.kind, value: this._copy(entry.value) }));
    const idx = Number.isInteger(state.undo_history_index)
      ? state.undo_history_index
      : this.globalHistory.length - 1;
    this.globalHistoryIndex = Math.max(-1,
      Math.min(idx, this.globalHistory.length - 1));
    this._updateUndoButtons();
  },

  _same(a, b) {
    try { return JSON.stringify(a) === JSON.stringify(b); }
    catch (e) { return a === b; }
  },

  recordGlobal(kind, value, options) {
    options = options || {};
    const entry = { kind, value: this._copy(value) };
    const current = this.globalHistory[this.globalHistoryIndex];
    if (current && this._same(current, entry)) return;
    if (this.globalHistoryIndex < this.globalHistory.length - 1) {
      this.globalHistory = this.globalHistory.slice(0, this.globalHistoryIndex + 1);
    }
    this.globalHistory.push(entry);
    this.globalHistoryIndex = this.globalHistory.length - 1;
    if (this.globalHistory.length > 100) {
      this.globalHistory.splice(0, this.globalHistory.length - 100);
      this.globalHistoryIndex = this.globalHistory.length - 1;
    }
    this._updateUndoButtons();
    if (!options.localOnly && this.bridge && this.bridge.push_global_history) {
      try { this.bridge.push_global_history(kind, JSON.stringify(value)); }
      catch (e) { /* local history still keeps the UI responsive */ }
    }
  },

  _peopleRowsOf(value) {
    // People entries carry {"before": rows, "after": rows}; undo/redo return
    // the matching half. A bare array is accepted too (defensive).
    if (Array.isArray(value)) return value;
    if (value && Array.isArray(value.after)) return value.after;
    return null;
  },

  _applyGlobalResult(raw) {
    if (!raw || raw === 'null') return false;
    let result;
    try { result = JSON.parse(raw); } catch (e) { return false; }
    if (!result || !result.kind) return false;
    if (Number.isInteger(result.index)) this.globalHistoryIndex = result.index;
    else if (result.kind) {
      // Old bridges did not return an index.
      this.globalHistoryIndex = Math.max(-1, this.globalHistoryIndex - 1);
    }
    if (result.kind === 'stack' && typeof StackDnD !== 'undefined') {
      StackDnD._isRestoringHistory = true;
      StackDnD.setStack(result.value, { silent: true });
      StackDnD._isRestoringHistory = false;
    } else if (result.kind === 'grid' && typeof SashGrid !== 'undefined') {
      SashGrid._applySerialized(result.value, false);
    } else if (result.kind === 'people' && typeof UserTable !== 'undefined') {
      const rows = this._peopleRowsOf(result.value);
      if (rows) {
        UserTable.render(rows);
        // The backend applies the snapshot asynchronously and re-emits
        // users_updated + stats_updated; a refresh keeps every panel in sync.
        if (this.bridge && this.bridge.refresh_users) this.bridge.refresh_users();
      }
    }
    this._updateUndoButtons();
    return true;
  },

  /** Re-sync the local history mirror from the backend's authoritative
      timeline (the backend records people-list edits itself). */
  _syncGlobalHistory() {
    if (!this.bridge || !this.bridge.get_undo_history) return;
    this.bridge.get_undo_history((json) => {
      try {
        const state = JSON.parse(json);
        if (state && Array.isArray(state.history)) {
          this.globalHistory = state.history
            .filter((e) => e && (e.kind === 'stack' || e.kind === 'grid' ||
                                 e.kind === 'people'))
            .map((e) => ({ kind: e.kind, value: this._copy(e.value) }));
          this.globalHistoryIndex = Number.isInteger(state.index)
            ? state.index : this.globalHistory.length - 1;
          this._updateUndoButtons();
        }
      } catch (e) { /* ignore */ }
    });
  },

  undoGlobal() {
    if (!this.bridge || !this.bridge.undo) return false;
    this.bridge.undo((raw) => {
      if (!this._applyGlobalResult(raw)) LogConsole.log('⚠ Nothing to undo', 'warn');
    });
    return true;
  },

  redoGlobal() {
    if (!this.bridge || !this.bridge.redo) return false;
    this.bridge.redo((raw) => {
      if (!raw || raw === 'null') LogConsole.log('⚠ Nothing to redo', 'warn');
      else this._applyGlobalResult(raw);
    });
    return true;
  },

  _updateUndoButtons() {
    const undo = document.getElementById('undoBtn');
    const redo = document.getElementById('redoBtn');
    const canUndo = this.globalHistoryIndex > 0;
    // Redo is available whenever an entry exists past the pointer. Index -1
    // (e.g. after undoing a sole people-list edit) still has entry 0 to
    // re-apply, so it must count.
    const canRedo = this.globalHistory.length > 0 &&
                    this.globalHistoryIndex < this.globalHistory.length - 1;
    if (undo) {
      undo.disabled = !canUndo;
      undo.title = canUndo ? 'Undo (Ctrl+Z) — global history' : 'Nothing to undo';
    }
    if (redo) {
      redo.disabled = !canRedo;
      redo.title = canRedo ? 'Redo (Ctrl+Y) — global history' : 'Nothing to redo';
    }
  },
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
  // Message archive windows (Person History / Full User Database /
  // Chat Message Collector). They are inert without a bridge.
  if (typeof HistoryStore !== 'undefined') HistoryStore.init();
  if (typeof HistoryDb !== 'undefined') HistoryDb.init();
  if (typeof CollectorPanel !== 'undefined') CollectorPanel.init();
  document.getElementById('clearLogBtn').addEventListener('click', () => LogConsole.clear());
  if (App.bridge) {
    setupBridgeListeners();
    // sash-grid may have initialized before QWebChannel; load its
    // authoritative config.json copy now that the bridge is available.
    if (typeof SashGrid !== 'undefined' && SashGrid._loadFromBackend)
      SashGrid._loadFromBackend();
    // fill the people list on start, not only after connecting to a tab
    App.bridge.refresh_users();
    // single payload with everything needed to restore the session (BUG #2)
    App.bridge.get_app_state((json) => restoreSession(json));
  }
}

// ── Session restore (BUG #2 / single preset storage + history) ──
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

  // 0) restore the one global history first (persisted across sessions)
  App.loadGlobalHistory(state);
  // Keep StackDnD's legacy projection populated for old integrations; its
  // buttons and keyboard shortcuts delegate to App's global history below.
  if (state.stack_history || state.stack_history_index !== undefined) {
    StackDnD.loadHistoryFromState(state);
  }

  // 1) restore the last stack (snapshot or the named preset)
  const lastStack = Array.isArray(state.last_stack) ? state.last_stack : null;
  const lastPreset = state.last_stack_preset || '';
  if (Array.isArray(lastStack) && lastStack.length) {
    StackDnD.setStack(lastStack, { silent: true });
    // ensure history contains this stack if history was empty
    if (!StackDnD.history.length) {
      StackDnD.pushHistory(lastStack, {force:true});
    }
    LogConsole.log(`♻ Restored last stack (${lastStack.length} block(s))`, 'info');
    if (StackDnD.history.length > 1) {
      LogConsole.log(`↩ History: ${StackDnD.history.length} steps, index ${StackDnD.historyIndex} — Undo/Redo available`, 'info');
    }
  } else if (lastPreset) {
    PresetsUI.loadStack(lastPreset);
  } else {
    StackDnD.refreshPresets();
  }

  // Block Config pin is persisted in the same session state (config.json) so
  // a pinned panel reopens (empty state) after an app restart. Applied AFTER
  // the stack restore so a pinned-but-deselected panel is reopened even when
  // setStack() cleared the selection.
  if (typeof state.block_config_pinned === 'boolean' &&
      typeof StackDnD.applyConfigPin === 'function') {
    StackDnD.applyConfigPin(state.block_config_pinned);
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

  // live collection: a person just matched the filter during Scroll & Parse.
  // users_updated fires right after, so the row exists when we flash it.
  b.person_found.connect((payload) => {
    UserTable.onPersonFound(payload);
  });

  // a person failed the filter and was destroyed — drop the row immediately
  b.person_removed.connect((payload) => {
    UserTable.onPersonRemoved(payload);
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
  // backend records people-list edits in the global timeline itself — keep
  // the local mirror + undo/redo buttons in sync whenever it grows/moves.
  if (b.history_changed && b.history_changed.connect) {
    b.history_changed.connect(() => App._syncGlobalHistory());
  }
  b.stack_loaded.connect((name, json) => {
    try {
      const blocks = JSON.parse(json);
      if (Array.isArray(blocks)) {
        // backend undo/redo emits this; treat as history navigation
        StackDnD._isRestoringHistory = true;
        StackDnD.setStack(blocks, {silent:true});
        StackDnD._isRestoringHistory = false;
        StackDnD.updateHistoryButtons();
      }
    } catch (e) { /* ignore */ }
  });

  // ── message archive ───────────────────────────────────────
  if (b.history_page_ready)
    b.history_page_ready.connect((req, json) => HistoryStore.onPage(req, json));
  if (b.history_search_ready)
    b.history_search_ready.connect((req, json) => HistoryStore.onSearch(req, json));
  if (b.userdb_page_ready)
    b.userdb_page_ready.connect((req, json) => HistoryDb.onPage(req, json));
  if (b.userdb_changed)
    b.userdb_changed.connect(() => HistoryDb.onChanged());
  if (b.collector_status)
    b.collector_status.connect((json) => CollectorPanel.onStatus(json));
  if (b.history_appended) {
    b.history_appended.connect((json) => {
      HistoryStore.onLiveAppend(json);
      CollectorPanel.onAppended(json);
    });
  }
  if (b.my_nick_changed)
    b.my_nick_changed.connect((nick) => HistoryStore.setMyNick(nick));
  if (b.history_error) {
    b.history_error.connect((scope, message) => {
      LogConsole.log('⚠ ' + scope + ': ' + message, 'warn');
      HistoryStore.onError(scope, message);
    });
  }
  if (b.get_history_settings) {
    b.get_history_settings((json) => {
      let settings = {};
      try { settings = JSON.parse(json); } catch (e) { settings = {}; }
      HistoryStore.applySettings(settings);
      HistoryDb.applySettings(settings);
    });
  }

  // Load initial criteria display
  b.get_criteria((json) => {
    CriteriaEditor.loadFromJson(json);
    CriteriaEditor.renderDisplay();
  });
}
