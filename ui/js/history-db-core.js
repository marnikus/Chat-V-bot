/* history-db-core.js — state + bootstrap for HistoryDb facade (H-B2b JS split)

Design: ≤150 LOC.
*/

'use strict';

const HistoryDbCore = {
  rows: [],
  total: 0,
  hasMore: true,
  loading: false,
  query: '',
  sortKey: 'last',
  sortDir: 'desc',
  NATURAL: { nick: 'asc', first: 'asc', my_nick: 'asc', msgs: 'desc', media: 'desc', last: 'desc' },
  pageSize: 50,
  preloadRows: 40,
  _seq: 0,
  _els: {},
  RETRY_MAX: 5,
  RETRY_MS: 1000,
  _retries: 0,
  _retryTimer: null,

  init() {
    const $ = (id) => document.getElementById(id);
    this._els = {
      panel: $('winUserDb'), list: $('userdbList'), body: $('userdbBody'),
      search: $('userdbSearch'), foot: $('userdbFoot'),
      preload: $('userdbPreload'), refresh: $('userdbRefreshBtn'),
    };
    this._flashNick = '';
    if (!this._els.body) return;
    this._wireSortHeaders();
    this._updateSortHeaders();
    this._els.list.addEventListener('scroll', () => this._onScroll());
    this._els.body.addEventListener('click', (event) => {
      const row = event.target && event.target.closest ? event.target.closest('.userdb-row') : null;
      if (!row) return;
      const nick = row.dataset.nick;
      if (!nick) return;
      const action = (event.target.dataset && event.target.dataset.action) || '';
      if (action) {
        if (event.stopPropagation) event.stopPropagation();
        if (action === 'delete') this.deletePerson(nick);
        else if (action === 'clear') this.clearHistory(nick);
        else if (action === 'label') this.labelPerson(nick);
        return;
      }
      if (typeof Labels !== 'undefined') Labels.setPerson(nick);
      if (typeof HistoryStore !== 'undefined') HistoryStore.openPerson(nick);
    });
    if (this._els.search) {
      this._els.search.addEventListener('input', () => {
        clearTimeout(this._timer);
        this._timer = setTimeout(() => { this.query = this._els.search.value.trim(); this.reload(); }, 220);
      });
    }
    if (this._els.preload) {
      this._els.preload.addEventListener('change', () => {
        const value = Math.max(5, Math.min(500, Number(this._els.preload.value) || 40));
        this.preloadRows = value;
        this._els.preload.value = String(value);
        if (typeof HistoryStore !== 'undefined') { HistoryStore.preloadRows = value; HistoryStore.saveSettings(); }
      });
    }
    if (this._els.refresh) this._els.refresh.addEventListener('click', () => this.reload());
    this.reload();
  },

  applySettings(settings) {
    const preview = (settings && settings.preview) || {};
    if (preview.preload_rows) {
      this.preloadRows = Number(preview.preload_rows);
      if (this._els.preload) this._els.preload.value = String(this.preloadRows);
    }
    if (preview.page_size) this.pageSize = Number(preview.page_size);
  },

  reload(options) {
    options = options || {};
    this.rows = []; this.hasMore = true; this.loading = false;
    clearTimeout(this._retryTimer); this._retryTimer = null;
    if (!options._retry) this._retries = 0;
    if (this._els.list && !options.keepScroll) this._els.list.scrollTop = 0;
    this._request(0);
    this._requestStats();
  },

  _request(offset) {
    if (this.loading || !this.hasMore) return;
    if (!App.bridge || !App.bridge.userdb_page) return;
    this.loading = true;
    const id = 'u' + (++this._seq);
    App.bridge.userdb_page(id, JSON.stringify({ q: this.query, limit: this.pageSize, offset: offset, sort: this.sortKey, dir: this.sortDir }));
  },

  _requestStats() {
    if (!App.bridge || !App.bridge.userdb_stats) return;
    App.bridge.userdb_stats('s' + (++this._seq));
  },
};

if (typeof window !== 'undefined') window.HistoryDbCore = HistoryDbCore;
