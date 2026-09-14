/* app-bridge.js — QWebChannel signal wiring + header (App part, Round H)

   Owns every bridge signal listener the app subscribes to (the whole
   setupBridgeListeners body, grouped by feature) plus the header
   controls (refresh tabs / connect). setupListeners() is the single
   entry point; the group methods wire one cluster of signals each.

   Two collaborating objects (H-A6, RULE 16 object cap):
     AppBridge         header + dispatcher + the live/streaming signals
                       (tabs, connection, people table, stats, stepping)
     AppBridgeStores   the data-store signals (presets, history, archive,
                       labels/db, bot, collector, settings/criteria fetch)
   Methods bind onto the App facade (UIHelpers.mergeParts in app.js), so
   `this` is App (`this.bridge`) and the dispatcher resolves every
   wire* group across both objects. Loaded before the facade — see
   ui/index.html.
   */
'use strict';

const AppBridge = {
  // ── Header: tabs + connect ──────────────────────────────────
  setupHeader() {
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
  },

  setupListeners() {
    const b = App.bridge;
    this.wireTabsReceived(b);
    this.wireConnectionStatus(b);
    this.wireUsersTable(b);
    this.wirePersonSignals(b);
    this.wireStatsLog(b);
    this.wireStepSignals(b);
    this.wirePresetSignals(b);
    this.wireHistorySignals(b);
    this.wireArchiveSignals(b);
    this.wireLabelDbSignals(b);
    this.wireBotSignals(b);
    this.wireCollectorSignals(b);
    this.wireHistorySettings(b);
  },

  wireTabsReceived(b) {
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
  },

  wireConnectionStatus(b) {
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
  },

  wireUsersTable(b) {
    b.users_updated.connect((json) => {
      let users = [];
      try { users = JSON.parse(json); } catch (e) { users = []; }
      UserTable.render(users);
    });

    // people list: deletions (single / selection / clear all)
    b.users_deleted.connect((nicksJson, count) => {
      UserTable.onDeleted(nicksJson);
    });
  },

  wirePersonSignals(b) {
    // live collection: a person just matched the filter during Scroll &
    // Parse. users_updated fires right after, so the row exists when we
    // flash it.
    b.person_found.connect((payload) => {
      UserTable.onPersonFound(payload);
    });

    // a person failed the filter and was destroyed — drop the row
    // immediately
    b.person_removed.connect((payload) => {
      UserTable.onPersonRemoved(payload);
    });
  },

  wireStatsLog(b) {
    b.stats_updated.connect((json) => {
      const s = JSON.parse(json);
      document.getElementById('statTotal').textContent = s.total || 0;
      document.getElementById('statQueued').textContent = s.queued || 0;
      document.getElementById('statDone').textContent = s.done || 0;
    });

    b.log_message.connect((msg, level) => {
      LogConsole.log(msg, level);
    });
  },

  wireStepSignals(b) {
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
  },
};

const AppBridgeStores = {
  wirePresetSignals(b) {
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
    if (b.window_preset_list_updated && b.window_preset_list_updated.connect)
      b.window_preset_list_updated.connect((json) => WindowPresets.setPresets(json));
    b.tab_match_result.connect((query, json) => UrlToolbar.onMatch(query, json));
  },

  wireHistorySignals(b) {
    // backend records people-list edits in the global timeline itself —
    // keep the local mirror + undo/redo buttons in sync whenever it
    // grows/moves.
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
  },

  // ── message archive ─────────────────────────────────────────
  wireArchiveSignals(b) {
    if (b.history_page_ready)
      b.history_page_ready.connect((req, json) => HistoryStore.onPage(req, json));
    if (b.history_stats_ready)
      b.history_stats_ready.connect((req, json) => HistoryStore.onStats(req, json));
    if (b.history_search_ready)
      b.history_search_ready.connect((req, json) => HistoryStore.onSearch(req, json));
    if (b.userdb_page_ready)
      b.userdb_page_ready.connect((req, json) => HistoryDb.onPage(req, json));
    if (b.userdb_changed) {
      b.userdb_changed.connect((json) => {
        HistoryDb.onChanged();
        if (typeof CollectorPanel !== 'undefined' &&
            CollectorPanel.onPeopleChanged)
          CollectorPanel.onPeopleChanged(json);
        if (typeof HistoryStore !== 'undefined' && HistoryStore.reloadCurrent)
          HistoryStore.reloadCurrent();
        if (typeof DbPanel !== 'undefined') DbPanel.refresh();
      });
    }
  },

  // ── labels + database management ────────────────────────────
  wireLabelDbSignals(b) {
    if (b.labels_changed)
      b.labels_changed.connect((json) => {
        Labels.applyState(json);
        HistoryDb.liveChanged('labels');   // the badges live in the DB table too
      });
    if (b.db_info_ready)
      b.db_info_ready.connect((req, json) => DbPanel.onInfo(req, json));
    if (b.db_changed) {
      b.db_changed.connect((json) => {
        DbPanel.onChanged(json);
        HistoryDb.onChanged();
        if (typeof CollectorPanel !== 'undefined' && CollectorPanel.onDbChanged)
          CollectorPanel.onDbChanged();
        if (typeof HistoryStore !== 'undefined' && HistoryStore.reloadCurrent)
          HistoryStore.reloadCurrent();
      });
    }
  },

  // ── AI Bot Chat + Prompt Editor ─────────────────────────────
  wireBotSignals(b) {
    if (b.bot_reply_ready) {
      b.bot_reply_ready.connect((req, json) => {
        BotChat.onReply(req, json);
        BotPrompt.onReply(req, json);
      });
    }
    if (b.bot_error)
      b.bot_error.connect((req, message) => {
        BotChat.onError(req, message);
        LogConsole.log('⚠ Grok: ' + message, 'warn');
      });
    if (b.bot_prompts_changed)
      b.bot_prompts_changed.connect((json) => BotPrompt.onPromptsChanged(json));
  },

  wireCollectorSignals(b) {
    if (b.collector_status)
      b.collector_status.connect((json) => CollectorPanel.onStatus(json));
    if (b.collector_log)
      b.collector_log.connect((json) => CollectorPanel.onLog(json));
    if (b.history_appended) {
      b.history_appended.connect((json) => {
        HistoryStore.onLiveAppend(json);
        CollectorPanel.onAppended(json);
        HistoryDb.liveChanged('appended');   // a new person must appear here
      });
    }
    if (b.media_ready)
      b.media_ready.connect((req, json) => HistoryStore.onMediaReady(req, json));
    if (b.my_nick_changed)
      b.my_nick_changed.connect((nick) => HistoryStore.setMyNick(nick));
  },

  wireHistorySettings(b) {
    if (b.history_error) {
      b.history_error.connect((scope, message) => {
        LogConsole.log('⚠ ' + scope + ': ' + message, 'warn');
        HistoryStore.onError(scope, message);
        // A failed userdb read un-sticks the loader and re-asks on its own,
        // so a lost boot answer heals without the user pressing ↻ (2026-09-13).
        if (typeof HistoryDb !== 'undefined' && HistoryDb.onError)
          HistoryDb.onError(scope);
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
  },
};
