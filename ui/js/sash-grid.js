/* sash-grid.js — SashGrid facade (Round H, H-A3)

State, constants, and the thin lifecycle surface. All behaviour
lives in the part files (loaded before this one — see index.html):
  sash-grid-tree.js     tree→DOM, window controls, hidden/empty sync
  sash-grid-windows.js  persistence, window ops, dock, menus
  sash-grid-presets.js  portable window presets
  sash-grid-drag.js     pointer drag, drop spec, sash resize

Parts are merged onto this host with UIHelpers.mergeParts: every
part method binds `this` to the SashGrid facade, so all `this.*`
access (state + sibling methods) resolves exactly as before the
split. Public API is unchanged (SashGrid.*, incl. internals and
simulateDrop / simulateResize test hooks).
*/

'use strict';

const SashGrid = {
  STORAGE_KEY: 'chatbot.sashLayout.v1',
  STORAGE_CLOSED: 'chatbot.sashWindows.closed.v1',
  STORAGE_MINIMIZED: 'chatbot.sashWindows.minimized.v1',
  PRESET_FORMAT: 'chat-v-bot.window-preset',
  PRESET_SCHEMA_VERSION: 1,
  APP_VERSION: '0.1.0',

  THRESHOLD: 4,
  MIN_PX: 96,
  SASH_W: 6,

  gridEl: null,
  dockEl: null,
  root: null,
  winEls: {},
  _drag: null,
  _resize: null,

  closedWindows: null,
  minimizedWindows: null,

  WIN_ICONS: {
    stats: 'bar_chart', filters: 'filter_list', stack: 'view_list',
    config: 'tune', composer: 'chat', people: 'people', log: 'terminal',
    history: 'forum', userdb: 'storage', collector: 'radar',
    labels: 'sell', dbconn: 'dns',
  },

  init() {
    this.gridEl = document.getElementById('sashGrid');
    if (!this.gridEl) { console.warn('sash-grid: #sashGrid missing'); return; }
    this._ensureDock();
    this._collectPanels();
    this.closedWindows = new Set();
    this.minimizedWindows = new Set();
    this.root = this._loadTree() || SashCore.defaultTree();
    this._loadWindowStates();
    this.render();
    this._loadFromBackend();
    this.gridEl.addEventListener('pointerdown', this._onDown = this._pointerDown.bind(this));
    this.gridEl.addEventListener('dblclick', this._onDbl = this._onDblClick.bind(this));
    this._setupLayoutMenu();
    this._setupWindowsMenu();
    this._setupVisibilityWatch();
  },
  flushPersistence() {
    if (!this.root) return false;
    const payload = SashCore.serialize(this.root);
    try { localStorage.setItem(this.STORAGE_KEY, payload); } catch (e) {}
    try { this._saveWindowStates(); } catch (e) {}
    try {
      if (typeof App !== 'undefined' && App.bridge && typeof App.bridge.save_grid_layout === 'function') {
        App.bridge.save_grid_layout(payload);
        return true;
      }
    } catch (e) {
      console.warn('sash-grid: close-time backend save failed', e);
    }
    if (typeof App !== 'undefined' && App.recordGlobal) App.recordGlobal('grid', payload, { localOnly: true });
    return false;
  },
  render() {
    const frag = this._buildNode(this.root, []);
    frag.style.flex = '1 1 0%';
    this.gridEl.replaceChildren(frag);
    this._ensureWindowControls();
    this._applyStates();
  },
  /** Push all derived UI state (grid wrapper classes, empty splits, dock,
   *  windows menu, empty-grid hint) from the closed/minimized sets. */
  _applyStates() {
    this._syncHidden();
    this._syncEmptySplits();
    this._renderDock();
    this._updateWindowsMenu();
    this._checkEmptyGrid();
  },

  // ── minimized dock (bottom strip) ──────────────────────────
  getTree() { return SashCore.clone(this.root); },
  getWindowStates() {
    return { closed: Array.from(this.closedWindows), minimized: Array.from(this.minimizedWindows) };
  },};

UIHelpers.mergeParts(SashGrid,
  SashGridTree, SashGridWindowStore, SashGridWindows, SashGridMenus,
  SashGridPresets, SashGridDrag, SashGridSpec, SashGridResize);

(window.BridgeReady || { ready: (fn) => document.addEventListener('DOMContentLoaded', () => fn(null)) })
  .ready(() => SashGrid.init());
