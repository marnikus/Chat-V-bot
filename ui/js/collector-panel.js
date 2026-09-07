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
      log: $('collectorLog'),
      clearLog: $('collectorClearLogBtn'),
      pause: $('collectorPauseBtn'),
      now: $('collectorNowBtn'),
      backfill: $('collectorBackfillBtn'),
      enabled: $('collectorEnabledToggle'),
      media: $('collectorMediaToggle'),
      heartbeat: $('collectorHeartbeat'),
    };
    if (!this._els.status) return;
    if (this._els.rows) {
      this._els.rows.addEventListener('click', (event) => {
        const target = event && event.target;
        const link = target && target.closest
          ? target.closest('.collector-nick-link') : null;
        if (link && link.dataset && link.dataset.nick)
          this.openPartner(link.dataset.nick);
      });
    }
    if (this._els.clearLog) {
      this._els.clearLog.addEventListener('click', () => this.clearLog());
    }
    if (this._els.pause) {
      this._els.pause.addEventListener('click', () => {
        this.command(this.paused ? 'resume' : 'pause');
      });
    }
    if (this._els.now)
      this._els.now.addEventListener('click', () => this.command('tick'));
      if (this._els.backfill)
        this._els.backfill.addEventListener('click',
          () => this.command('backfill_older'));
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

  /** Open Person History for the partner and highlight that row in the DB. */
  openPartner(nick) {
    nick = String(nick || '').trim();
    if (!nick) return;
    if (typeof SashGrid !== 'undefined' && SashGrid.showWindow) {
      SashGrid.showWindow('history');
      SashGrid.showWindow('userdb');
    }
    if (typeof HistoryStore !== 'undefined' && HistoryStore.openPerson)
      HistoryStore.openPerson(nick);
    if (typeof HistoryDb !== 'undefined' && HistoryDb.highlightNick)
      HistoryDb.highlightNick(nick);
    if (typeof LogConsole !== 'undefined')
      LogConsole.log(`👤 Open history for “${nick}”`, 'info');
  },

  setMyNick(nick) {
    this.myNick = nick || '';
    this.renderRows(this._last || {});
  },

  /** One backend log line for this window only. */
  onLog(json) {
    let payload = null;
    try { payload = JSON.parse(json); } catch (e) { return; }
    if (!payload) return;
    const level = payload.level || 'info';
    const nick = String(payload.nick || '').trim();
    const message = String(payload.message || '');
    if (!message && !nick) return;
    const entry = document.createElement('div');
    entry.className = 'collector-log-entry ' + level;
    const ts = document.createElement('span');
    ts.className = 'collector-log-ts';
    ts.textContent = '[' + (payload.ts || '') + '] ';
    entry.appendChild(ts);
    if (nick) {
      const n = document.createElement('span');
      n.className = 'collector-log-nick';
      n.textContent = '«' + nick + '» ';
      entry.appendChild(n);
    }
    entry.appendChild(document.createTextNode(message));
    if (!this._els.log) return;
    this._els.log.appendChild(entry);
    this._els.log.scrollTop = this._els.log.scrollHeight;
    while (this._els.log.children.length > 400)
      this._els.log.removeChild(this._els.log.firstChild);
  },

  clearLog() {
    if (!this._els.log) return;
    this._els.log.replaceChildren();
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

  _rowLink(host, key, nick) {
    const k = document.createElement('span');
    k.className = 'collector-key';
    k.appendChild(document.createTextNode(key));
    const v = document.createElement('span');
    v.className = 'collector-val';
    const link = document.createElement('span');
    link.className = 'collector-nick-link';
    link.dataset.nick = nick || '';
    link.title = 'Open Person History and highlight “' + (nick || '') + '” in the database';
    link.appendChild(document.createTextNode(nick || ''));
    v.appendChild(link);
    host.appendChild(k);
    host.appendChild(v);
  },

  renderRows(payload) {
    const host = this._els.rows;
    if (!host) return;
    host.replaceChildren();
    const partner = String(payload.nick || payload.partner || '').trim();
    if (partner) this._rowLink(host, 'Partner', partner);
    else this._row(host, 'Partner', '');
    this._row(host, 'My nick', this.myNick || (payload.settings || {}).my_nick);
    this._row(host, 'In archive', payload.total);
    this._row(host, 'Added this session', this._appended || payload.added || 0);
    this._row(host, 'Check every',
              payload.interval_ms ? payload.interval_ms + ' ms' : '');
    if (payload.throttled)
      this._row(host, 'Throttled', 'yes — an Action Stack run is in progress');
    if (payload.self_heals) this._row(host, 'Re-syncs', payload.self_heals);
    if (payload.last_probe) {
      const p = payload.last_probe;
      this._row(host, 'Page count', p.count);
      this._row(host, 'People',
                String(p.participants) + ' · ' + String(p.panes) +
                ' pane(s) · ' + (p.pane_source || 'n/a'));
    }
    if (payload.sync_reason) {
      let sync = payload.sync_reason;
      if (payload.sync_count !== undefined)
        sync += ' · count ' + payload.sync_count;
      if (payload.sync_added !== undefined)
        sync += ' · added ' + payload.sync_added;
      this._row(host, 'Sync', sync);
    }
    if (payload.media_repaired || payload.media_requeued) {
      this._row(host, 'Media recovery',
        'repaired ' + (payload.media_repaired || 0) +
        ' · re-queued ' + (payload.media_requeued || 0));
    }
    if (payload.backfill_pending)
      this._row(host, 'Backfill', 'full scan pending retry');
    if (payload.warning) this._row(host, 'Warning', payload.warning);
    if (payload.error) this._row(host, 'Error', payload.error);
  },
};

if (typeof window !== 'undefined') window.CollectorPanel = CollectorPanel;
