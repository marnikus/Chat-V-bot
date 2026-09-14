/* app-session.js — single-payload session restore (App part, Round H)

   Owns restoreSession() — the BUG #2 single get_app_state payload that
   restores theme, presets, the Block Config pin, the global history,
   the last stack, and the last bookmark.

   Part pattern: methods bind onto the App facade
   (UIHelpers.mergeParts in app.js), so `this` is App. The public global
   `restoreSession()` stays in app.js as a thin shim (stable surface).
   Loaded before the facade — see ui/index.html.
   */
'use strict';

const AppSession = {
  restoreSession(json) {
    let payload = {};
    try { payload = JSON.parse(json); } catch (e) { payload = {}; }

    this._applyTheme(payload);
    this._seedPresets(payload);
    if (payload.labels && typeof Labels !== 'undefined')
      Labels.applyState(payload.labels);

    const state = payload.state || {};
    this._restoreStackStep(state);

    // 2) restore the last bookmark + try auto-connect with its URL
    UrlToolbar.restoreSession(payload);

    // refresh remaining lists
    PresetsUI.refreshAll();
  },

  _applyTheme(payload) {
    // theme first — every later paint uses the right tokens
    // (dark is the default; "light" flips the core palette in
    //  ui/css/variables.css via <html data-theme="light">)
    if (payload.theme === 'light')
      document.documentElement.setAttribute('data-theme', 'light');
    else
      document.documentElement.removeAttribute('data-theme');
  },

  _seedPresets(payload) {
    // seed chips from the single store
    PresetsUI.setStackPresets(JSON.stringify(payload.stack_presets || []));
    PresetsUI.setTemplatePresets(JSON.stringify(payload.template_presets || []));
    PresetsUI.setCustomBlocks(payload.custom_blocks || []);
    StackDnD.setCustomBlocks(payload.custom_blocks || []);
    UrlToolbar.setPresets(JSON.stringify(payload.url_presets || []));
  },

  _restoreStackStep(state) {
    // 0) restore the Block Config pin FIRST, before any history/stack step
    // below that could throw and abort the tail of this restore. Applying it
    // early is safe: setStack()/loadStack() below respect the pin and will
    // keep a pinned (empty) panel open rather than closing it.
    if (typeof state.block_config_pinned === 'boolean' &&
        typeof StackDnD.applyConfigPin === 'function') {
      StackDnD.applyConfigPin(state.block_config_pinned);
    }
    // 0b) restore the one global history (persisted across sessions)
    App.loadGlobalHistory(state);
    // Keep StackDnD's legacy projection populated for old integrations; its
    // buttons and keyboard shortcuts delegate to App's global history below.
    if (state.stack_history || state.stack_history_index !== undefined) {
      StackDnD.loadHistoryFromState(state);
    }
    this._restoreLastStack(state);
  },

  _restoreLastStack(state) {
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
  },
};
