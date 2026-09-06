/* ═══════════════════════════════════════════════════════════════
   history-db.js — the Full User Database window

   Every person the archive has ever seen, merged by nick (one row per
   person, never a duplicate), loaded lazily as the user scrolls, with a
   search over nicks and a live message-count. Clicking a row opens that
   person in the Person History window.
   ═══════════════════════════════════════════════════════════════ */

const HistoryDb = {
  rows: [],
  total: 0,
  hasMore: true,
  loading: false,
  query: '',
  sort: 'recent',
  pageSize: 50,
  preloadRows: 40,
  _seq: 0,
  _els: {},

  init() {
    const $ = (id) => document.getElementById(id);
    this._els = {
      panel: $('winUserDb'),
      list: $('userdbList'),
      body: $('userdbBody'),
      search: $('userdbSearch'),
      foot: $('userdbFoot'),
      preload: $('userdbPreload'),
      refresh: $('userdbRefreshBtn'),
    };
    if (!this._els.body) return;
    this._els.list.addEventListener('scroll', () => this._onScroll());
    this._els.body.addEventListener('click', (event) => {
      const row = event.target && event.target.closest
        ? event.target.closest('.userdb-row') : null;
      if (!row) return;
      const nick = row.dataset.nick;
      if (!nick) return;
      if (event.target.dataset && event.target.dataset.action === 'delete') {
        this.deletePerson(nick);
        return;
      }
      if (typeof HistoryStore !== 'undefined') HistoryStore.openPerson(nick);
    });
    if (this._els.search) {
      this._els.search.addEventListener('input', () => {
        clearTimeout(this._timer);
        this._timer = setTimeout(() => {
          this.query = this._els.search.value.trim();
          this.reload();
        }, 220);
      });
    }
    if (this._els.preload) {
      this._els.preload.addEventListener('change', () => {
        const value = Math.max(5, Math.min(500,
          Number(this._els.preload.value) || 40));
        this.preloadRows = value;
        this._els.preload.value = String(value);
        if (typeof HistoryStore !== 'undefined') {
          HistoryStore.preloadRows = value;
          HistoryStore.saveSettings();
        }
      });
    }
    if (this._els.refresh)
      this._els.refresh.addEventListener('click', () => this.reload());
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

  reload() {
    this.rows = [];
    this.hasMore = true;
    this.loading = false;
    this._request(0);
    this._requestStats();
  },

  _request(offset) {
    if (this.loading || !this.hasMore) return;
    if (!App.bridge || !App.bridge.userdb_page) return;
    this.loading = true;
    const id = 'u' + (++this._seq);
    App.bridge.userdb_page(id, JSON.stringify({
      q: this.query, limit: this.pageSize, offset: offset, sort: this.sort,
    }));
  },

  _requestStats() {
    if (!App.bridge || !App.bridge.userdb_stats) return;
    App.bridge.userdb_stats('s' + (++this._seq));
  },

  onPage(reqId, json) {
    let data = null;
    try { data = JSON.parse(json); } catch (e) { data = null; }
    if (!data) { this.loading = false; return; }
    this.loading = false;
    if (data.persons !== undefined && data.items === undefined) {
      this.onStats(data);
      return;
    }
    const items = data.items || [];
    if (data.offset ? data.offset === 0 : !this.rows.length) this.rows = items;
    else {
      const seen = new Set(this.rows.map((r) => r.nick));
      items.forEach((item) => { if (!seen.has(item.nick)) this.rows.push(item); });
    }
    this.total = data.total != null ? data.total : this.rows.length;
    this.hasMore = !!data.has_more;
    this.render();
  },

  onStats(data) {
    if (!this._els.foot) return;
    const parts = [];
    if (data.persons != null) parts.push(data.persons + ' people');
    if (data.messages != null) parts.push(data.messages + ' messages');
    if (data.media != null) parts.push(data.media + ' media');
    const bytes = data.bytes != null ? data.bytes : data.media_bytes;
    if (bytes != null) parts.push((bytes / 1048576).toFixed(1) + ' MB cached');
    if (data.gaps) parts.push(data.gaps + ' gaps');
    this._els.foot.textContent = parts.join(' · ');
  },

  onChanged() {
    this.reload();
  },

  _onScroll() {
    const list = this._els.list;
    if (!list || this.loading || !this.hasMore) return;
    const remaining = list.scrollHeight - list.scrollTop - list.clientHeight;
    if (remaining < 120) this._request(this.rows.length);
  },

  deletePerson(nick) {
    if (!App.bridge || !App.bridge.history_delete_person) return;
    App.bridge.history_delete_person(nick, false);
  },

  // ── rendering (createElement only) ───────────────────────────

  /** 'YYYY-MM-DD HH:MM:SS' → 'YYYY-MM-DD' (the table only has room for a day). */
  _day(value) {
    return value ? String(value).slice(0, 10) : '—';
  },

  _cell(row, text, cls) {
    const cell = document.createElement('td');
    if (cls) cell.className = cls;
    cell.appendChild(document.createTextNode(text == null ? '' : String(text)));
    row.appendChild(cell);
    return cell;
  },

  render() {
    const body = this._els.body;
    if (!body) return;
    const nodes = [];
    if (!this.rows.length) {
      const empty = document.createElement('tr');
      const cell = document.createElement('td');
      cell.setAttribute('colspan', '6');
      cell.className = 'history-notice';
      cell.appendChild(document.createTextNode(
        this.query ? 'No person matches “' + this.query + '”.'
                   : 'The archive is still empty — the collector fills it ' +
                     'while you chat.'));
      empty.appendChild(cell);
      nodes.push(empty);
    }
    this.rows.forEach((person) => {
      const row = document.createElement('tr');
      row.className = 'userdb-row' + (person.deleted ? ' deleted' : '');
      row.dataset.nick = person.nick || '';
      this._cell(row, person.nick, 'userdb-nick');
      this._cell(row, person.message_count != null ? person.message_count
                                                   : (person.messages || 0));
      this._cell(row, person.media_count != null ? person.media_count
                                                 : (person.media || 0));
      this._cell(row, this._day(person.first_seen || person.first_day));
      this._cell(row, this._day(person.last_seen || person.last_day));
      this._cell(row, Array.isArray(person.my_nicks)
        ? person.my_nicks.join(', ') : (person.my_nick || '—'));
      nodes.push(row);
    });
    body.replaceChildren.apply(body, nodes);
    if (this._els.foot && this.total)
      this._els.foot.title = this.rows.length + ' of ' + this.total + ' loaded';
  },
};

if (typeof window !== 'undefined') window.HistoryDb = HistoryDb;
