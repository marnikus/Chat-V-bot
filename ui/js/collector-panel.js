/* ═══════════════════════════════════════════════════════════════
   collector-panel.js — the Chat Message Collector window

   Shows what the passive collector is doing right now (Collecting /
   Collected / No new messages / Not in private tab now), which partner
   and which "my nick" it is writing under, and lets the user pause it,
   force a pass, or change the heartbeat — without ever blocking the UI:
   everything here is a signal handler.
   ═══════════════════════════════════════════════════════════════ */

const CollectorPanel = {
  state: 'off',
  paused: false,
  myNick: '',
  _els: {},

  STATE_CLASS: {
    collecting: 'state-collecting',
    bootstrapping: 'state-collecting',
    collected: 'state-collected',
    no_new: 'state-idle',
    not_private: 'state-idle',
    group_tab: 'state-idle',
    paused: 'state-idle',
    disconnected: 'state-off',
    off: 'state-off',
    error: 'state-error',
  },

  init() {
    const $ = (id) => document.getElementById(id);
    this._els = {
      panel: $('winCollector'),
      status: $('collectorStatus'),
      rows: $('collectorRows'),
      pause: $('collectorPauseBtn'),
      now: $('collectorNowBtn'),
      enabled: $('collectorEnabledToggle'),
      media: $('collectorMediaToggle'),
      heartbeat: $('collectorHeartbeat'),
    };
    if (!this._els.status) return;
    if (this._els.pause) {
      this._els.pause.addEventListener('click', () => {
        this.command(this.paused ? 'resume' : 'pause');
      });
    }
    if (this._els.now)
      this._els.now.addEventListener('click', () => this.command('tick'));
    if (this._els.enabled) {
      this._els.enabled.addEventListener('change', () => {
        this.configure({ enabled: !!this._els.enabled.checked });
      });
    }
    if (this._els.media) {
      this._els.media.addEventListener('change', () => {
        this.configure({ download_media: !!this._els.media.checked });
      });
    }
    if (this._els.heartbeat) {
      this._els.heartbeat.addEventListener('change', () => {
        const value = Math.max(300, Math.min(60000,
          Number(this._els.heartbeat.value) || 1500));
        this._els.heartbeat.value = String(value);
        this.configure({ heartbeat_ms: value });
      });
    }
    if (App.bridge && App.bridge.collector_state)
      App.bridge.collector_state((json) => this.onStatus(json));
  },

  command(name) {
    if (App.bridge && App.bridge.collector_command)
      App.bridge.collector_command(name);
  },

  configure(patch) {
    if (App.bridge && App.bridge.collector_set)
      App.bridge.collector_set(JSON.stringify(patch));
  },

  setMyNick(nick) {
    this.myNick = nick || '';
    this.renderRows(this._last || {});
  },

  onStatus(json) {
    let payload = null;
    try { payload = JSON.parse(json); } catch (e) { return; }
    if (!payload) return;
    this._last = payload;
    this.state = payload.state || 'off';
    this.paused = !!payload.paused;
    const badge = this._els.status;
    if (badge) {
      badge.className = 'collector-state ' +
        (this.STATE_CLASS[this.state] || 'state-idle');
      badge.textContent = payload.text || this.state;
      badge.title = payload.detail || '';
    }
    if (this._els.pause)
      this._els.pause.textContent = this.paused ? '▶ Resume' : '⏸ Pause';
    const settings = payload.settings || {};
    if (this._els.enabled && settings.enabled !== undefined)
      this._els.enabled.checked = !!settings.enabled;
    if (this._els.media && settings.download_media !== undefined)
      this._els.media.checked = !!settings.download_media;
    if (this._els.heartbeat && settings.heartbeat_ms &&
        document.activeElement !== this._els.heartbeat)
      this._els.heartbeat.value = String(settings.heartbeat_ms);
    if (settings.my_nick && !this.myNick) this.myNick = settings.my_nick;
    this.renderRows(payload);
  },

  onAppended(json) {
    let payload = null;
    try { payload = JSON.parse(json); } catch (e) { return; }
    if (!payload) return;
    this._appended = (this._appended || 0) + (payload.added || 0);
    if (typeof HistoryDb !== 'undefined' && HistoryDb.rows &&
        HistoryDb.rows.length) HistoryDb._requestStats();
    this.renderRows(this._last || {});
  },

  _row(host, key, value) {
    const k = document.createElement('span');
    k.className = 'collector-key';
    k.appendChild(document.createTextNode(key));
    const v = document.createElement('span');
    v.className = 'collector-val';
    v.appendChild(document.createTextNode(
      value == null || value === '' ? '—' : String(value)));
    host.appendChild(k);
    host.appendChild(v);
  },

  renderRows(payload) {
    const host = this._els.rows;
    if (!host) return;
    host.replaceChildren();
    this._row(host, 'Partner', payload.nick || payload.partner);
    this._row(host, 'My nick', this.myNick || (payload.settings || {}).my_nick);
    this._row(host, 'In archive', payload.total);
    this._row(host, 'Added this session', this._appended || payload.added || 0);
    this._row(host, 'Check every',
              payload.interval_ms ? payload.interval_ms + ' ms' : '');
    if (payload.throttled)
      this._row(host, 'Throttled', 'yes — an Action Stack run is in progress');
    if (payload.self_heals) this._row(host, 'Re-syncs', payload.self_heals);
    if (payload.warning) this._row(host, 'Warning', payload.warning);
    if (payload.error) this._row(host, 'Error', payload.error);
  },
};

if (typeof window !== 'undefined') window.CollectorPanel = CollectorPanel;
