/* ═══════════════════════════════════════════════════════════════
   history-db.js — the Full User Database window

   ideal-size: 431 lines reason=this is the ONE module behind the window's
   DOM (list, sort headers, paging, live refresh, per-row actions and the
   trash button); splitting it would put one window's behaviour in two files
   and break the `HistoryDb.<method>` surface the Node harness loads.

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
  // ── column sort ───────────────────────────────────────────────
  // The order is decided by the database, never here: the table is paged, so
  // sorting `rows` would only order the page that happens to be loaded.
  // Both values live for the session (like UserTable.sort) and are sent with
  // EVERY page request, which is what makes the choice stick.
  sortKey: 'last',
  sortDir: 'desc',
  /** The direction a first click on that header gives. */
  NATURAL: {
    nick: 'asc', first: 'asc', my_nick: 'asc',
    msgs: 'desc', media: 'desc', last: 'desc',
  },
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
      emptyTrash: $('userdbEmptyTrash'),
    };
    this._flashNick = '';
    if (!this._els.body) return;
    this._wireSortHeaders();
    this._updateSortHeaders();
    this._els.list.addEventListener('scroll', () => this._onScroll());
    this._els.body.addEventListener('click', (event) => {
      const row = event.target && event.target.closest
        ? event.target.closest('.userdb-row') : null;
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
      // A click anywhere else opens the conversation and points the Label
      // Manager at this person — one click, one obvious outcome (RULE 10).
      if (typeof Labels !== 'undefined') Labels.setPerson(nick);
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
    if (this._els.emptyTrash)
      this._els.emptyTrash.addEventListener('click', () => this.emptyTrash());
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

  // ── sortable columns ─────────────────────────────────────────

  /** Attach the header handlers once. The <th> is a real <button>, so
   *  Enter/Space arrive as keydown and must not scroll the page. */
  _wireSortHeaders() {
    document.querySelectorAll('#userdbTable th[data-sort]').forEach((th) => {
      th.addEventListener('click', () => this.sortBy(th.dataset.sort));
      th.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          this.sortBy(th.dataset.sort);
        }
      });
    });
  },

  /** Same header as before ⇒ flip. A new header ⇒ its own natural direction,
   *  never the one the previous column happened to be in. */
  sortBy(key) {
    if (!key || !Object.prototype.hasOwnProperty.call(this.NATURAL, key))
      return;
    if (this.sortKey === key) {
      this.sortDir = this.sortDir === 'asc' ? 'desc' : 'asc';
    } else {
      this.sortKey = key;
      this.sortDir = this.NATURAL[key];
    }
    this._updateSortHeaders();
    this.reload();
  },

  /** ▲▼ idle · ▲ ascending · ▼ descending, and `aria-sort` to match. The
   *  glyph comes from the SAME helper the User Memory table uses, so the two
   *  tables can never show different arrows for the same state. */
  _updateSortHeaders() {
    document.querySelectorAll('#userdbTable th[data-sort]').forEach((th) => {
      const active = th.dataset.sort === this.sortKey;
      const arrow = th.querySelector('.sort-arrow');
      if (arrow) arrow.textContent =
        window.UIHelpers.sortArrow(active, this.sortDir === 'desc' ? -1 : 1);
      th.setAttribute('aria-sort', active
        ? (this.sortDir === 'asc' ? 'ascending' : 'descending') : 'none');
      th.classList.toggle('sort-active', active);
    });
  },

  reload(options) {
    this.rows = [];
    this.hasMore = true;
    this.loading = false;
    // A live append must not throw the reader back to the top of the table;
    // a new order or a new query makes the old position meaningless.
    if (this._els.list && !(options && options.keepScroll))
      this._els.list.scrollTop = 0;
    this._request(0);
    this._requestStats();
  },

  _request(offset) {
    if (this.loading || !this.hasMore) return;
    if (!App.bridge || !App.bridge.userdb_page) return;
    this.loading = true;
    const id = 'u' + (++this._seq);
    App.bridge.userdb_page(id, JSON.stringify({
      q: this.query, limit: this.pageSize, offset: offset,
      // The order travels with EVERY page, including the ones fetched while
      // scrolling — that is what keeps the sort for the whole session.
      sort: this.sortKey, dir: this.sortDir,
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
    clearTimeout(this._liveTimer);       // a named change beats the batch
    this.reload();
  },

  /** A change heard through the bridge (someone was collected, a label was
   *  edited): refresh, but not once per message — the collector writes in
   *  chunks. The scroll position is kept so a live chat does not jump. */
  liveChanged(reason) {
    this._liveReason = reason || '';
    clearTimeout(this._liveTimer);
    this._liveTimer = setTimeout(() => {
      this._liveReason = '';
      if (this._els.body) this.reload({ keepScroll: true });
    }, 400);
  },

  /** The only irreversible action in this window — always asks first. */
  emptyTrash() {
    const bridge = (typeof App !== 'undefined' && App.bridge) || null;
    if (!bridge || !bridge.history_purge_deleted) return;
    this._confirm(
      'Empty the trash?',
      'Every hidden message and every removed person is erased for good. ' +
      'Ctrl+Z cannot bring them back.',
      'Empty trash', () => bridge.history_purge_deleted(''));
  },

  /** Ask before an action that hides data; without a dialog, do it at once
   *  (the tests run headless — the backend stays the authority either way). */
  _confirm(title, text, okLabel, run) {
    const dialog = (typeof window !== 'undefined' && window.Dialog) || null;
    if (dialog && dialog.confirm) dialog.confirm(title, text, okLabel, run);
    else run();
  },

  _onScroll() {
    const list = this._els.list;
    if (!list || this.loading || !this.hasMore) return;
    const remaining = list.scrollHeight - list.scrollTop - list.clientHeight;
    if (remaining < 120) this._request(this.rows.length);
  },

  /** Remove the person AND their whole history (one undoable step). */
  deletePerson(nick) {
    if (!App.bridge || !App.bridge.history_delete_person) return;
    this._confirm(
      'Remove this person?',
      '“' + nick + '” and their entire history are hidden in this database. ' +
      'Ctrl+Z restores both; “Empty trash” is what erases them for good.',
      'Remove', () => App.bridge.history_delete_person(nick, false));
  },

  /** Wipe the conversation but keep the person in the database. */
  clearHistory(nick) {
    if (!App.bridge || !App.bridge.history_clear_person) return;
    App.bridge.history_clear_person(nick);
  },

  /** Point the Label Manager at this person and bring the window forward. */
  labelPerson(nick) {
    if (typeof Labels === 'undefined') return;
    Labels.setPerson(nick, { focus: true });
  },

  /**
   * Quick-assign target highlight, called by Labels.setPerson(): move the
   * accent bar to this person's row in place. render() stamps the same
   * class from Labels.person, so the two stay in agreement.
   */
  markLabelTarget(nick) {
    const body = this._els.body;
    if (!body || !body.querySelectorAll) return;
    const clean = String(nick || '').trim();
    body.querySelectorAll('tr[data-nick]').forEach((row) => {
      const on = !!clean && row.dataset.nick === clean;
      row.classList.toggle('row-label-target', on);
      if (on && row.scrollIntoView) row.scrollIntoView({ block: 'nearest' });
    });
  },

  /** Show one person in the database: filter to that nick, flash the row. */
  highlightNick(nick) {
    this._flashNick = String(nick || '').trim();
    if (!this._flashNick) return;
    this.query = this._flashNick;
    if (this._els.search) this._els.search.value = this._flashNick;
    this._flashIfPresent();
    this.reload();
  },

  // ── rendering (createElement only) ───────────────────────────

  /** Flash the row the collector just asked us to highlight, when loaded. */
  _flashIfPresent() {
    if (!this._flashNick || !this._els.body) return;
    const nick = this._flashNick;
    const rows = Array.from(this._els.body.querySelectorAll('.userdb-row') || []);
    const row = rows.find((r) => (r.dataset && r.dataset.nick) === nick);
    if (!row) {
      // The row may be on a later page; the query is already set to the nick,
      // so the next page load will bring it to the top.
      if (typeof HistoryStore !== 'undefined' && this.query === nick) this.reload();
      return;
    }
    row.classList.remove('row-flash');
    void (row.offsetWidth || 0);                    // restart the animation
    row.classList.add('row-flash');
    if (typeof row.scrollIntoView === 'function')
      row.scrollIntoView({ block: 'nearest' });
    clearTimeout(this._flashTimer);
    this._flashTimer = setTimeout(() => {
      row.classList.remove('row-flash');
      if (this._flashNick === nick) this._flashNick = '';
    }, 1800);
  },

  /** Rows left after the Label Manager's include/exclude filter. */
  visibleRows() {
    if (typeof Labels === 'undefined' || !Labels.filterActive) return this.rows;
    return this.rows.filter((person) => Labels.allows(person.nick));
  },

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

  /** Per-row buttons: label · clear history · remove person + history. */
  _actions(person) {
    const cell = document.createElement('td');
    cell.className = 'userdb-actions';
    const nick = person.nick || '';
    const button = (action, text, title, cls) => {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'btn-row' + (cls ? ' ' + cls : '');
      btn.dataset.action = action;
      btn.textContent = text;
      btn.title = title;
      cell.appendChild(btn);
      return btn;
    };
    button('label', '🏷', 'Label “' + nick + '” in the Label Manager');
    button('clear', '🧹', 'Delete the whole conversation but KEEP “' + nick +
           '” in the database (Ctrl+Z restores it)');
    button('delete', '🗑', 'Remove “' + nick + '” together with their entire ' +
           'history (Ctrl+Z restores both)', 'btn-row-danger');
    return cell;
  },

  render() {
    const body = this._els.body;
    if (!body) return;
    const nodes = [];
    const visible = this.visibleRows();
    if (!visible.length) {
      const empty = document.createElement('tr');
      const cell = document.createElement('td');
      cell.setAttribute('colspan', '7');
      cell.className = 'history-notice';
      const filtered = this.rows.length && !visible.length;
      cell.appendChild(document.createTextNode(
        filtered
          ? 'Every loaded person is hidden by the label filter — clear it in ' +
            'the Label Manager to see them again.'
          : this.query ? 'No person matches “' + this.query + '”.'
                       : 'The archive is still empty — the collector fills it ' +
                         'while you chat.'));
      empty.appendChild(cell);
      nodes.push(empty);
    }
    visible.forEach((person) => {
      const row = document.createElement('tr');
      row.className = 'userdb-row' + (person.deleted ? ' deleted' : '') +
        ((typeof Labels !== 'undefined' &&
          Labels.person === (person.nick || ''))
          ? ' row-label-target' : '');
      row.dataset.nick = person.nick || '';
      const nickCell = this._cell(row, person.nick, 'userdb-nick');
      nickCell.title = 'Open this conversation';
      // The very same pill renderer the People table uses, so a label can
      // never look different in the two tables.
      if (typeof Labels !== 'undefined') {
        nickCell.appendChild(Labels.pills(person.nick, {
          labels: Array.isArray(person.labels)
            ? person.labels.map((l) => (typeof l === 'string'
              ? Labels.byId(l) : l)).filter(Boolean)
            : undefined,
        }));
      }
      this._cell(row, person.message_count != null ? person.message_count
                                                   : (person.messages || 0));
      this._cell(row, person.media_count != null ? person.media_count
                                                 : (person.media || 0));
      this._cell(row, this._day(person.first_seen || person.first_day));
      this._cell(row, this._day(person.last_seen || person.last_day));
      this._cell(row, Array.isArray(person.my_nicks)
        ? person.my_nicks.join(', ') : (person.my_nick || '—'));
      row.appendChild(this._actions(person));
      nodes.push(row);
    });
    body.replaceChildren.apply(body, nodes);
    this._flashIfPresent();
    if (this._els.foot && this.total)
      this._els.foot.title = this.rows.length + ' of ' + this.total + ' loaded';
  },
};

if (typeof window !== 'undefined') window.HistoryDb = HistoryDb;
