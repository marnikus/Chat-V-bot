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
      folder: $('historyFolderBtn'),
      clear: $('historyClearBtn'),
      removePerson: $('historyDeletePersonBtn'),
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
    if (this._els.folder) {
      this._els.folder.addEventListener('click', () => this.openFolder());
    }
    if (this._els.clear)
      this._els.clear.addEventListener('click', () => this.clearHistory());
    if (this._els.removePerson) {
      this._els.removePerson.addEventListener('click',
                                              () => this.deletePerson());
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

  /** Re-read the open conversation (after a delete, an undo, a DB switch). */
  reloadCurrent() {
    if (!this.nick || !this.model) return;
    this.openPerson(this.nick, { keepScroll: true });
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
    if (payload.total != null) {
      const total = Number(payload.total);
      this.stats = Object.assign({}, this.stats || {}, {
        messages: total, message_count: total,
      });
    }
    if (this.model && payload.total != null)
      this.model.total = Number(payload.total);
    if (added) this.render({ stickToBottom: true });
    else this._updateLatestButton();
    this.renderHeader();
    this.refreshStats();
  },

  /** Ask Python for the authoritative person stats after a live append. */
  refreshStats() {
    if (!this.nick || !App.bridge || !App.bridge.history_stats) return;
    App.bridge.history_stats('s' + (++this._seq), this.nick);
  },

  onStats(reqId, json) {
    let stats = null;
    try { stats = JSON.parse(json); } catch (e) { return; }
    if (!stats || stats.nick !== this.nick) return;
    this.stats = stats;
    if (this.model && stats.message_count != null)
      this.model.total = Number(stats.message_count);
    this.renderHeader();
  },

  /** Show this person's saved images and GIFs in the file manager. */
  openFolder() {
    if (!this.nick) {
      if (typeof LogConsole !== 'undefined')
        LogConsole.log('ℹ Open a conversation first', 'info');
      return;
    }
    if (App.bridge && App.bridge.open_media_folder)
      App.bridge.open_media_folder(this.nick);
  },

  /**
   * A media file finished caching (or we asked where it lives): swap the
   * <img> over to the saved file so the window never depends on the remote,
   * percent-encoded URL.
   */
  onMediaReady(reqId, json) {
    let info = null;
    try { info = JSON.parse(json); } catch (e) { return; }
    if (!info) return;
    const id = info.id != null ? info.id : reqId;
    if (info.path) {
      // Put the fresh local path into the model, then re-render.  That lets
      // a restored "click to restore" marker become a working <img> without
      // a manual refresh, while the scroll anchor is preserved by render().
      const hit = this._applyModelMedia(id, info);
      if (hit) { this.render(); return; }
      HistoryView.applyMediaPath(this._els.list, id, info.path);
    }
    if (!info.path && typeof LogConsole !== 'undefined')
      LogConsole.log('⚠ ' + (info.error || 'media is not available yet') +
                     (info.state ? ' (' + info.state + ')' : ''), 'warn');
  },

  _applyModelMedia(id, info) {
    if (!this.model) return false;
    const want = String(id == null ? '' : id);
    let changed = false;
    this.model.items.forEach((item) => {
      if (!item.media || String(item.media.id) !== want) return;
      if (info.path) item.media.path = info.path;
      if (info.state) item.media.state = info.state;
      if (info.url) item.media.url = info.url;
      if (info.kind) item.media.kind = info.kind;
      changed = true;
    });
    return changed;
  },

  /** Ask the backend to re-download one failed/missing image or GIF. */
  restoreMedia(mediaId) {
    if (App.bridge && App.bridge.media_restore)
      App.bridge.media_restore('r' + (++this._seq), String(mediaId));
    else if (App.bridge && App.bridge.media_path)
      App.bridge.media_path('r' + (++this._seq), String(mediaId));
    if (typeof LogConsole !== 'undefined')
      LogConsole.log('↻ Restoring media…', 'info');
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
             onCopyMedia: (id) => this.copyMedia(id),
             onRestoreMedia: (id) => this.restoreMedia(id),
             onDeleteMessage: (id) => this.deleteMessage(id) };
  },

  /** Remove ONE message from this conversation (undoable). */
  deleteMessage(id) {
    if (!this.nick || id == null) return;
    if (!App.bridge || !App.bridge.history_delete_message) {
      if (typeof LogConsole !== 'undefined')
        LogConsole.log('⚠ Not connected to backend — message kept', 'warn');
      return;
    }
    App.bridge.history_delete_message(this.nick, String(id));
  },

  /** Wipe the whole conversation but keep the person (undoable). */
  clearHistory() {
    if (!this.nick) return;
    if (!App.bridge || !App.bridge.history_clear_person) return;
    window.Dialog.confirm(
      'Clear this conversation?',
      'Every archived message with “' + this.nick + '” is removed. ' +
      'The person stays in the database and Ctrl+Z restores the messages.',
      'Clear', () => App.bridge.history_clear_person(this.nick));
  },

  /** Remove the person together with their whole history (undoable). */
  deletePerson() {
    if (!this.nick) return;
    if (!App.bridge || !App.bridge.history_delete_person) return;
    window.Dialog.confirm(
      'Remove this person?',
      '“' + this.nick + '” and their entire history are removed from the ' +
      'database. Ctrl+Z restores both.',
      'Remove', () => App.bridge.history_delete_person(this.nick, false));
  },

  renderHeader() {
    if (!this._els.header) return;
    HistoryView.renderHeader(this._els.header, {
      nick: this.nick, myNick: this.myNick, stats: this.stats || null,
      labels: (typeof Labels !== 'undefined' && this.nick)
        ? Labels.forNick(this.nick) : [],
      pill: (typeof Labels !== 'undefined')
        ? (label) => Labels.pill(label, this.nick, {
            onRemove: (id, nick) => Labels.unassign(nick, id) })
        : null,
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
