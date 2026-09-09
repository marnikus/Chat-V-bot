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
  _generation: 0,
  _sessionTotals: new Map(),

  STATE_CLASS: {
    collecting: 'state-collecting',
    bootstrapping: 'state-collecting',
    collected: 'state-collected',
    no_new: 'state-idle',
    capture_pending: 'state-capture-pending',
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
    entry.dataset.nick = nick;
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

  _acceptGeneration(payload) {
    if (typeof payload.generation !== 'number') return true;
    if (payload.generation < this._generation) return false;
    this._generation = payload.generation;
    return true;
  },

  onReset(json) {
    let payload;
    try { payload = typeof json === 'string' ? JSON.parse(json) : json; } catch (_) { return; }
    if (!payload || !this._acceptGeneration(payload)) return;
    const nick = payload.nick;
    if (nick == null) this._sessionTotals.clear();
    else this._sessionTotals.delete(nick);
    if (this._els.log) {
      Array.from(this._els.log.children).forEach((entry) => {
        if (nick == null || entry.dataset.nick === nick) entry.remove();
      });
    }
    if (!this._last || !this._last.nick || nick == null || this._last.nick === nick) {
      this._last = { nick: nick || '', my_nick: this.myNick, added: 0, session_added: 0,
        total: 0, state: 'no_new', text: 'History reset — next scan starts fresh',
        generation: this._generation };
      if (this._els.status) this._els.status.textContent = this._last.text;
    }
    this.renderRows(this._last || {});
  },

  onStatus(json) {
    let payload = null;
    try { payload = JSON.parse(json); } catch (e) { return; }
    if (!payload || !this._acceptGeneration(payload)) return;
    if (payload.nick && payload.session_added !== undefined)
      this._sessionTotals.set(payload.nick, Number(payload.session_added) || 0);
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
    if (!payload || !this._acceptGeneration(payload)) return;
    if (payload.nick) {
      const total = payload.session_added !== undefined ? Number(payload.session_added)
        : (this._sessionTotals.get(payload.nick) || 0) + (Number(payload.added) || 0);
      this._sessionTotals.set(payload.nick, total || 0);
    }
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
    const currentSelf = payload.my_nick || this.myNick || (payload.settings || {}).my_nick;
    this._row(host, 'My nick', currentSelf);
    if (payload.configured_my_nick && payload.configured_my_nick !== currentSelf)
      this._row(host, 'Configured nick', payload.configured_my_nick);
    const ownNames = Array.isArray(payload.known_self_nicks) ? payload.known_self_nicks : [];
    const previous = ownNames.filter((n) => n !== currentSelf);
    if (previous.length) this._row(host, 'My previous nicks', previous.join(', '));
    if (payload.identity_source) this._row(host, 'Identity source', payload.identity_source);
    this._row(host, 'In archive', payload.total);
    this._row(host, 'Added this session', this._sessionTotals.get(partner) || 0);
    this._row(host, 'Check every',
              payload.interval_ms ? payload.interval_ms + ' ms' : '');
    if (payload.throttled)
      this._row(host, 'Throttled', 'yes — an Action Stack run is in progress');
    if (payload.self_heals) this._row(host, 'Re-syncs', payload.self_heals);
    if (typeof payload.agent === 'number')
      this._row(host, 'Capture agent', payload.agent ? 'v' + payload.agent : 'not installed');
    if (payload.last_probe) {
      const p = payload.last_probe;
      this._row(host, 'Page count', p.count);
      if (p.page_self) this._row(host, 'Browser self', p.page_self);
      if ((p.in_authors || []).length || (p.out_authors || []).length)
        this._row(host, 'Message authors', 'in: ' + (p.in_authors || []).join(', ') +
          ' · out: ' + (p.out_authors || []).join(', '));
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
    if (payload.text_repaired || payload.capture_missing || payload.capture_errors) {
      this._row(host, 'Text capture',
        'repaired ' + (payload.text_repaired || 0) +
        ' · awaiting retry ' + (payload.capture_missing || 0) +
        ' · read errors ' + (payload.capture_errors || 0));
    }
    const reads = payload.capture_diagnostics || [];
    if (reads.length) {
      const read = reads[reads.length - 1];
      this._row(host, 'Last read',
        '[' + read.from + ':' + read.to + '] · ' + (read.ready || 0) +
        '/' + (read.returned || 0) + ' ready · ' + (read.reason || 'unknown') +
        (read.error ? ' · ' + read.error : ''));
      const sources = read.sources || {};
      if (Object.keys(sources).length)
        this._row(host, 'Text source', Object.keys(sources).map((s) => s + ': ' + sources[s]).join(', '));
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
