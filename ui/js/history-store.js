/* ═══════════════════════════════════════════════════════════════
   history-store.js — the Person History window

   Talks to Python (bridge slots answer on signals carrying the request
   id), keeps one HistoryModel per open person, loads older rows lazily
   while the user scrolls up, and merges rows the passive collector
   appends live.

   Nodes are built by history-view.js with createElement only.
   ═══════════════════════════════════════════════════════════════ */

const HistoryStore = {
  model: null,
  nick: '',
  myNick: '',
  showImages: true,
  preloadRows: 40,
  pageSize: 50,
  query: '',
  scope: 'person',
  _seq: 0,
  _open: null,          // req id of the page request we are waiting for
  _els: {},

  // ── bootstrap ────────────────────────────────────────────────

  init() {
    const $ = (id) => document.getElementById(id);
    this._els = {
      panel: $('winHistory'),
      header: $('historyHeader'),
      list: $('historyList'),
      search: $('historySearchInput'),
      global: $('historySearchGlobalBtn'),
      images: $('historyImagesToggle'),
      latest: $('historyLatestBtn'),
      myNick: $('myNickInput'),
    };
    if (!this._els.list) return;
    this.model = HistoryModel.create({
      pageSize: this.pageSize, preloadRows: this.preloadRows, maxRows: 400,
    });
    this._els.list.addEventListener('scroll', () => this._onScroll());
    if (this._els.search) {
      this._els.search.addEventListener('input', () => {
        this.query = this._els.search.value.trim();
        this._debounceSearch();
      });
    }
    if (this._els.global) {
      this._els.global.addEventListener('click', () => {
        this.scope = this.scope === 'person' ? 'global' : 'person';
        this._els.global.classList.toggle('active', this.scope === 'global');
        this._debounceSearch();
      });
    }
    if (this._els.images) {
      this._els.images.addEventListener('change', () => {
        this.showImages = !!this._els.images.checked;
        this.saveSettings();
        this.render();
      });
    }
    if (this._els.latest) {
      this._els.latest.addEventListener('click', () => this.jumpToLatest());
    }
    this.initMyNick();
    this.renderEmpty('Click a nick in User Memory to read the whole ' +
                     'conversation with that person.');
  },

  /** The pinned header field: one persisted nick for the whole app. */
  initMyNick() {
    const input = this._els.myNick;
    if (!input) return;
    const commit = () => {
      const value = input.value.trim();
      if (value === this.myNick) return;
      this.myNick = value;
      if (App.bridge && App.bridge.set_my_nick) App.bridge.set_my_nick(value);
      input.classList.add('saved');
      setTimeout(() => input.classList.remove('saved'), 900);
    };
    input.addEventListener('change', commit);
    input.addEventListener('blur', commit);
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') { commit(); input.blur(); }
    });
    if (App.bridge && App.bridge.get_my_nick) {
      App.bridge.get_my_nick((value) => this.setMyNick(value || ''));
    }
  },

  setMyNick(value) {
    this.myNick = value || '';
    if (this._els.myNick && this._els.myNick.value !== this.myNick)
      this._els.myNick.value = this.myNick;
    if (this.model) this.model.myNick = this.myNick;
    if (this.nick) this.renderHeader();
    if (typeof CollectorPanel !== 'undefined') CollectorPanel.setMyNick(this.myNick);
  },

  applySettings(settings) {
    const preview = (settings && settings.preview) || {};
    if (preview.preload_rows) this.preloadRows = Number(preview.preload_rows);
    if (preview.page_size) this.pageSize = Number(preview.page_size);
    if (preview.show_images !== undefined) this.showImages = !!preview.show_images;
    if (this._els.images) this._els.images.checked = this.showImages;
    if (this.model) {
      this.model.preloadRows = this.preloadRows;
      this.model.pageSize = this.pageSize;
      this.model.showImages = this.showImages;
    }
  },

  saveSettings() {
    if (!App.bridge || !App.bridge.save_history_settings) return;
    App.bridge.save_history_settings(JSON.stringify({
      preview: { preload_rows: this.preloadRows, page_size: this.pageSize,
                 show_images: this.showImages },
    }));
  },

  // ── opening a person ─────────────────────────────────────────

  openPerson(nick, options) {
    if (!nick || !this.model) return;
    options = options || {};
    this.nick = nick;
    this.query = '';
    if (this._els.search) this._els.search.value = '';
    this.model.reset({ nick: nick, myNick: this.myNick,
                       showImages: this.showImages,
                       preloadRows: this.preloadRows });
    this.renderHeader();
    this.renderEmpty('Loading “' + nick + '” …');
    const request = this.model.requestInitial();
    if (options.around != null) request.around = options.around;
    this._open = this._send('history_open', request);
    if (this._els.panel && this._els.panel.scrollIntoView)
      this._els.panel.scrollIntoView({ block: 'nearest' });
  },

  _send(slot, request) {
    const id = 'h' + (++this._seq);
    if (!App.bridge || typeof App.bridge[slot] !== 'function') return id;
    if (slot === 'history_open' || slot === 'history_page')
      App.bridge[slot](id, request.nick, JSON.stringify(request));
    else App.bridge[slot](id, JSON.stringify(request));
    return id;
  },

  // ── bridge answers ───────────────────────────────────────────

  onPage(reqId, json) {
    let page = null;
    try { page = JSON.parse(json); } catch (e) { return; }
    if (!page || page.nick !== this.nick) return;
    const position = reqId === this._open ? 'initial' : undefined;
    this.model.applyPage(page, position ? { position } : undefined);
    this.stats = page.stats || this.stats;
    if (page.preview) this.applySettings({ preview: page.preview });
    if (page.my_nick && !this.myNick) this.setMyNick(page.my_nick);
    this.renderHeader();
    this.render();
  },

  onSearch(reqId, json) {
    let data = null;
    try { data = JSON.parse(json); } catch (e) { return; }
    if (!data) return;
    if (data.scope === 'global') {
      HistoryView.renderSearchGroups(this._els.list, data.groups || [], {
        query: this.query,
        onOpenHit: (nick, ord) => this.openPerson(nick, { around: ord }),
      });
    } else {
      const rows = (data.items || []).map(
        (item) => HistoryModel.toRow(item, this._context()));
      HistoryView.renderRows(this._els.list, rows,
                             Object.assign(this._context(), { query: this.query }));
    }
    if (!(data.items || data.groups || []).length)
      this.renderEmpty('Nothing found for “' + this.query + '”.');
  },

  onLiveAppend(json) {
    let payload = null;
    try { payload = JSON.parse(json); } catch (e) { return; }
    if (!payload || !this.model) return;
    if (payload.nick !== this.nick) return;
    const added = this.model.appendLive(payload.items || []);
    if (added) this.render({ stickToBottom: true });
    this._updateLatestButton();
  },

  onError(scope, message) {
    if (scope.indexOf('history') !== 0) return;
    HistoryView.renderNotice(this._els.list, message, 'error');
  },

  // ── lazy loading ─────────────────────────────────────────────

  _onScroll() {
    const list = this._els.list;
    if (!list || !this.model || this.query) return;
    const first = list.querySelector('.msg');
    if (first && list.scrollTop < 80) {
      const ord = Number(first.dataset.ord);
      if (this.model.needsOlder(ord)) {
        const request = this.model.requestOlder();
        if (request) this._send('history_page', request);
      }
    }
    const atBottom = list.scrollHeight - list.scrollTop - list.clientHeight < 40;
    if (atBottom && this.model.hasNewer) {
      const request = this.model.requestNewer();
      if (request) this._send('history_page', request);
    }
  },

  jumpToLatest() {
    if (!this.model || !this.nick) return;
    const request = this.model.requestLatest();
    this._open = this._send('history_open', request);
  },

  _debounceSearch() {
    clearTimeout(this._searchTimer);
    this._searchTimer = setTimeout(() => this.runSearch(), 220);
  },

  runSearch() {
    if (!this.query) { this.render(); return; }
    this._send('history_search', {
      q: this.query, scope: this.scope, nick: this.nick, limit: 200,
    });
  },

  // ── rendering ────────────────────────────────────────────────

  _context() {
    return { nick: this.nick, myNick: this.myNick,
             showImages: this.showImages,
             today: new Date().toISOString().slice(0, 10),
             onCopyMedia: (id) => this.copyMedia(id) };
  },

  renderHeader() {
    if (!this._els.header) return;
    HistoryView.renderHeader(this._els.header, {
      nick: this.nick, myNick: this.myNick, stats: this.stats || null,
    });
  },

  renderEmpty(text) {
    HistoryView.renderNotice(this._els.list, text);
  },

  render(options) {
    options = options || {};
    if (!this.model || !this._els.list) return;
    if (this.model.isEmpty) {
      this.renderEmpty(this.model.missing
        ? 'Nothing archived for “' + this.nick + '” yet.'
        : 'No messages to show.');
      return;
    }
    const list = this._els.list;
    const atBottom =
      list.scrollHeight - list.scrollTop - list.clientHeight < 60;
    const anchor = list.querySelector('.msg');
    const anchorTop = anchor ? anchor.getBoundingClientRect().top : 0;
    HistoryView.renderRows(list, this.model.rowsWithMarkers(this._context()),
                           this._context());
    if (options.stickToBottom || atBottom) {
      list.scrollTop = list.scrollHeight;
    } else if (anchor) {
      const same = list.querySelector('[data-ord="' + anchor.dataset.ord + '"]');
      if (same) list.scrollTop += same.getBoundingClientRect().top - anchorTop;
    }
    this._updateLatestButton();
  },

  _updateLatestButton() {
    const button = this._els.latest;
    if (!button || !this.model) return;
    const show = this.model.pendingLive > 0 || this.model.hasNewer;
    button.classList.toggle('hidden', !show);
    button.textContent = this.model.pendingLive
      ? 'Jump to latest (' + this.model.pendingLive + ' new)'
      : 'Jump to latest';
  },

  copyMedia(mediaId) {
    if (App.bridge && App.bridge.copy_media) App.bridge.copy_media(String(mediaId));
    if (typeof LogConsole !== 'undefined') LogConsole.log('📋 Copying media…', 'info');
  },

  copySelection() {
    const selection = window.getSelection ? String(window.getSelection()) : '';
    if (selection && App.bridge && App.bridge.copy_text)
      App.bridge.copy_text(selection);
    return selection;
  },
};

if (typeof window !== 'undefined') window.HistoryStore = HistoryStore;
