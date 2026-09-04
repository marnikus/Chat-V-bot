/* ═══════════════════════════════════════════════════════════════
   url-toolbar.js — URL Parse Preset (FEATURE #2) + bookmark restore

   Parses the URL / keyword in the field, matches it against the open
   Chrome tabs and auto-connects to the best match. Saved URL presets are
   rendered as small chips (click ⇒ parse & connect). The last selected
   bookmark is highlighted and persisted via set_last_url_preset().
   ═══════════════════════════════════════════════════════════════ */

'use strict';

const UrlToolbar = {
  presets: [],
  selectedUrl: '',
  _autoConnected: false,

  init() {
    const input = document.getElementById('urlInput');
    const connectBtn = document.getElementById('urlConnectBtn');
    const addBtn = document.getElementById('addUrlPresetBtn');

    const doConnect = () => this.connectNow(input.value.trim());
    connectBtn.addEventListener('click', doConnect);
    input.addEventListener('keydown', (e) => { if (e.key === 'Enter') doConnect(); });
    addBtn.addEventListener('click', () => this.addPreset(input.value.trim()));

    // manual connect via the header: keep the URL field/bookmark in sync
    document.getElementById('connectBtn').addEventListener('click', () => {
      const url = this._selectedTabUrl();
      if (url) {
        input.value = url;
        this.rememberUrl(url);
      }
    });
  },

  // url of the currently selected option in the tab dropdown
  _selectedTabUrl() {
    const sel = document.getElementById('tabSelect');
    if (!sel || !sel.selectedOptions.length || !sel.selectedOptions[0].value) return '';
    const label = sel.selectedOptions[0].textContent || '';
    const m = label.match(/—\s*(\S+)\s*$/);
    return m ? m[1] : '';
  },

  setPresets(json) {
    try { this.presets = JSON.parse(json); } catch (e) { this.presets = []; }
    this.renderChips();
  },

  shortUrl(url) {
    return String(url || '').replace(/^https?:\/\//i, '').replace(/\/+$/, '');
  },

  renderChips() {
    const el = document.getElementById('urlPresetChips');
    if (!el) return;
    el.innerHTML = '';
    this.presets.forEach((url) => {
      const chip = document.createElement('span');
      const isSel = url === this.selectedUrl;
      chip.className = 'chip' + (isSel ? ' chip-selected' : '');
      chip.title = (isSel ? '✓ last bookmark — ' : 'Parse & connect: ') + url;
      const t = document.createElement('span');
      t.className = 'chip-title';
      t.textContent = (isSel ? '🔖 ' : '🔗 ') + this.shortUrl(url);
      const x = document.createElement('span');
      x.className = 'chip-x';
      x.textContent = '×';
      x.title = 'Remove preset';
      chip.appendChild(t);
      chip.appendChild(x);
      chip.addEventListener('click', () => this.selectBookmark(url, { connect: true }));
      x.addEventListener('click', (ev) => {
        ev.stopPropagation();
        if (this.selectedUrl === url) this.selectedUrl = '';
        if (App.bridge) App.bridge.remove_url_preset(url);
      });
      el.appendChild(chip);
    });
    if (!this.presets.length) {
      el.innerHTML = '<span class="preset-row-empty">no URL presets — type a URL above and press +</span>';
    }
  },

  // ── bookmark selection & persistence (BUG #2) ────────────────
  selectBookmark(url, opts) {
    opts = opts || {};
    url = String(url || '').trim();
    if (!url) return;
    this.selectedUrl = url;
    const input = document.getElementById('urlInput');
    if (input) input.value = url;
    this.renderChips();
    if (opts.notify !== false && App.bridge) {
      App.bridge.set_last_url_preset(url);
    }
    if (opts.connect) this.connectNow(url);
  },

  rememberUrl(url) {
    // mark + persist the bookmark without triggering a new connect
    this.selectBookmark(url, { connect: false, notify: true });
  },

  addPreset(url) {
    if (!url) { LogConsole.log('⚠ Type a URL in the field first, then press +', 'warn'); return; }
    if (App.bridge) App.bridge.add_url_preset(url);
  },

  connectNow(query) {
    if (!query) { LogConsole.log('⚠ URL field is empty — enter a URL or keyword', 'warn'); return; }
    if (!App.bridge) { LogConsole.log('⚠ Not connected to backend', 'warn'); return; }
    LogConsole.log(`🔍 Parsing “${query}” and searching open tabs…`, 'info');
    const dot = document.getElementById('connectionStatus');
    if (dot) dot.className = 'status-dot connecting';
    App.bridge.find_tab_by_url(query);
  },

  onMatch(query, json) {
    let matches = [];
    try { matches = JSON.parse(json); } catch (e) { matches = []; }
    if (!matches.length) {
      const dot = document.getElementById('connectionStatus');
      if (dot && dot.classList.contains('connecting')) {
        dot.className = 'status-dot disconnected';
      }
      return;
    }
    const best = matches[0];
    const sel = document.getElementById('tabSelect');
    if (sel) {
      // pick the option whose ws_url matches the best tab
      const opt = Array.prototype.find.call(sel.options, (o) => o.value === best.ws_url);
      if (opt) { sel.value = opt.value; }
      else {
        const o = document.createElement('option');
        o.value = best.ws_url;
        o.textContent = `${best.title} — ${best.url}`.substring(0, 80);
        sel.prepend(o);
        sel.value = o.value;
      }
    }
    LogConsole.log(`🎯 Auto-selected tab: ${best.title} — ${best.url}`, 'success');
    if (best.url) this.selectBookmark(best.url, { connect: false, notify: true });
    if (App.bridge) {
      const dot = document.getElementById('connectionStatus');
      if (dot) dot.className = 'status-dot connecting';
      App.bridge.connect_tab(best.ws_url);
    }
  },

  // ── session restore (BUG #2) ─────────────────────────────────
  restoreSession(payload) {
    const url = String(payload.state?.last_url_preset || '').trim();
    if (url) {
      this.selectBookmark(url, { connect: false, notify: false });
      LogConsole.log(`🔖 Restored bookmark: ${url}`, 'info');
      // attempt the auto-connect once after startup
      if (!this._autoConnected && App.bridge) {
        this._autoConnected = true;
        setTimeout(() => this.connectNow(url), 600);
      }
    }
  },

  refresh() {
    if (!App.bridge) return;
    App.bridge.get_url_presets((json) => this.setPresets(json));
  },
};

document.addEventListener('DOMContentLoaded', () => UrlToolbar.init());
