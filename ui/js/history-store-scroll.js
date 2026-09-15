/* history-store-scroll.js — lazy loading + search debounce for HistoryStore facade (H-B2b JS split)

Design: ≤150 LOC.
*/

'use strict';

const HistoryStoreScroll = {
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
    this._send('history_search', { q: this.query, scope: this.scope, nick: this.nick, limit: 200 });
  },

  _context() {
    return {
      nick: this.nick, myNick: this.myNick, showImages: this.showImages,
      today: new Date().toISOString().slice(0, 10),
      onCopyMedia: (id) => this.copyMedia(id),
      onRestoreMedia: (id) => this.restoreMedia(id),
      onDeleteMessage: (id) => this.deleteMessage(id),
    };
  },
};

if (typeof window !== 'undefined') window.HistoryStoreScroll = HistoryStoreScroll;
