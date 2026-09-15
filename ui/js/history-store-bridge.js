/* history-store-bridge.js — bridge answers for HistoryStore facade (H-B2b JS split)

Design: ≤250 LOC.
*/

'use strict';

const HistoryStoreBridge = {
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
        query: this.query, onOpenHit: (nick, ord) => this.openPerson(nick, { around: ord }),
      });
    } else {
      const rows = (data.items || []).map((item) => HistoryModel.toRow(item, this._context()));
      HistoryView.renderRows(this._els.list, rows, Object.assign(this._context(), { query: this.query }));
    }
    if (!(data.items || data.groups || []).length) this.renderEmpty('Nothing found for “' + this.query + '”.');
  },

  onLiveAppend(json) {
    let payload = null;
    try { payload = JSON.parse(json); } catch (e) { return; }
    if (!payload || !this.model) return;
    if (payload.nick !== this.nick) return;
    const added = this.model.appendLive(payload.items || []);
    if (payload.total != null) {
      const total = Number(payload.total);
      this.stats = Object.assign({}, this.stats || {}, { messages: total, message_count: total });
    }
    if (this.model && payload.total != null) this.model.total = Number(payload.total);
    if (added) this.render({ stickToBottom: true });
    else this._updateLatestButton();
    this.renderHeader();
    this.refreshStats();
  },

  refreshStats() {
    if (!this.nick || !App.bridge || !App.bridge.history_stats) return;
    App.bridge.history_stats('s' + (++this._seq), this.nick);
  },

  onStats(reqId, json) {
    let stats = null;
    try { stats = JSON.parse(json); } catch (e) { return; }
    if (!stats || stats.nick !== this.nick) return;
    this.stats = stats;
    if (this.model && stats.message_count != null) this.model.total = Number(stats.message_count);
    this.renderHeader();
  },

  openFolder() {
    if (!this.nick) { if (typeof LogConsole !== 'undefined') LogConsole.log('ℹ Open a conversation first', 'info'); return; }
    if (App.bridge && App.bridge.open_media_folder) App.bridge.open_media_folder(this.nick);
  },

  onMediaReady(reqId, json) {
    let info = null;
    try { info = JSON.parse(json); } catch (e) { return; }
    if (!info) return;
    const id = info.id != null ? info.id : reqId;
    if (info.path) {
      const hit = this._applyModelMedia(id, info);
      if (hit) { this.render(); return; }
      HistoryView.applyMediaPath(this._els.list, id, info.path);
    }
    if (!info.path && typeof LogConsole !== 'undefined')
      LogConsole.log('⚠ ' + (info.error || 'media is not available yet') + (info.state ? ' (' + info.state + ')' : ''), 'warn');
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

  restoreMedia(mediaId) {
    if (App.bridge && App.bridge.media_restore) App.bridge.media_restore('r' + (++this._seq), String(mediaId));
    else if (App.bridge && App.bridge.media_path) App.bridge.media_path('r' + (++this._seq), String(mediaId));
    if (typeof LogConsole !== 'undefined') LogConsole.log('↻ Restoring media…', 'info');
  },

  onError(scope, message) {
    if (scope.indexOf('history') !== 0) return;
    HistoryView.renderNotice(this._els.list, message, 'error');
  },
};

if (typeof window !== 'undefined') window.HistoryStoreBridge = HistoryStoreBridge;
