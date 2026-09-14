/* app.js — App facade: state, boot, init (Round H)

   Owns the App state (bridge / ready / tabs / globalHistory) and the
   boot sequence. Behaviour lives in the part files (loaded before this
   one — see index.html):
     app-history.js   the one global undo/redo timeline (AppHistory)
     app-bridge.js    QWebChannel signal wiring + header (AppBridge)
     app-session.js   single-payload session restore (AppSession)

   Parts are merged onto this host with UIHelpers.mergeParts: every part
   method binds `this` to the App facade, so all `this.*` access (state +
   sibling methods) resolves exactly as before the split. The public
   surface is unchanged: App.*, initApp, restoreSession and
   setupBridgeListeners all still exist (the last two as thin shims over
   the parts).
   */

'use strict';

const App = {
  bridge: null,
  ready: false,
  tabs: [],
  // One chronological history for stack edits and grid edits alike.
  globalHistory: [],
  globalHistoryIndex: -1,
};

UIHelpers.mergeParts(App, AppHistory, AppBridge, AppSession);

// ── boot ───────────────────────────────────────────────────────
// the QWebChannel handshake lives in js/core/bridge-ready.js now;
// it assigns App.bridge / App.ready and runs the queued boots
(window.BridgeReady || { ready: (fn) => document.addEventListener('DOMContentLoaded', () => fn(null)) })
  .ready(() => initApp());

function initApp() {
  AppBridge.setupHeader();
  initPanels();
  if (App.bridge) initWithBridge();
}

function initPanels() {
  if (typeof WindowPresets !== 'undefined') WindowPresets.init();
  UserTable.init();
  // Message archive windows (Person History / Full User Database /
  // Chat Message Collector). They are inert without a bridge.
  if (typeof HistoryStore !== 'undefined') HistoryStore.init();
  if (typeof HistoryDb !== 'undefined') HistoryDb.init();
  if (typeof CollectorPanel !== 'undefined') CollectorPanel.init();
  // Label Manager + DB Connection windows.
  if (typeof Labels !== 'undefined') Labels.init();
  if (typeof DbPanel !== 'undefined') DbPanel.init();
  // AI Bot Chat + Grok Prompt Editor windows.
  if (typeof BotChat !== 'undefined') BotChat.init();
  if (typeof BotSettings !== 'undefined') BotSettings.init();
  if (typeof BotPrompt !== 'undefined') BotPrompt.init();
  document.getElementById('clearLogBtn').addEventListener('click', () => LogConsole.clear());
}

function initWithBridge() {
  setupBridgeListeners();
  // sash-grid may have initialized before QWebChannel; load its
  // authoritative config.json copy now that the bridge is available.
  if (typeof SashGrid !== 'undefined' && SashGrid._loadFromBackend)
    SashGrid._loadFromBackend();
  // HistoryDb/DbPanel fired their first requests from init(), BEFORE the
  // signal listeners above existed — the only two windows that ask before
  // they listen (every other panel loads post-listener or via callback).
  // Re-ask now that every answer has a connected handler: the backend
  // waits for the world when it is still opening, and duplicate answers
  // merge idempotently — so the person list is filled on start, never
  // only after the first manual ↻ (2026-09-13).
  if (typeof HistoryDb !== 'undefined') HistoryDb.reload();
  if (typeof DbPanel !== 'undefined') DbPanel.refresh();
  if (typeof WindowPresets !== 'undefined') WindowPresets.refresh();
  // fill the people list on start, not only after connecting to a tab
  App.bridge.refresh_users();
  // single payload with everything needed to restore the session (BUG #2)
  App.bridge.get_app_state((json) => restoreSession(json));
}

// ── stable public shims (Round H) ──────────────────────────────
// The part implementations moved out of this file; these wrappers keep
// the global surface (initApp callers, tests, other modules) unchanged.
function restoreSession(json) {
  AppSession.restoreSession(json);
}

function setupBridgeListeners() {
  AppBridge.setupListeners();
}
