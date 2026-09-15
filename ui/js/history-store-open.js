/* history-store-open.js — open/reload/send for HistoryStore facade (H-B2b JS split)

Design: ≤150 LOC.
*/

'use strict';

const HistoryStoreOpen = {
  openPerson(nick, options) {
    if (!nick || !this.model) return;
    options = options || {};
    this.nick = nick;
    this.query = '';
    if (this._els.search) this._els.search.value = '';
    this.model.reset({ nick: nick, myNick: this.myNick, showImages: this.showImages, preloadRows: this.preloadRows });
    this.renderHeader();
    this.renderEmpty('Loading “' + nick + '” …');
    if (typeof BotChat !== 'undefined' && BotChat.openPerson && BotChat.nick !== nick) BotChat.openPerson(nick);
    const request = this.model.requestInitial();
    if (options.around != null) request.around = options.around;
    this._open = this._send('history_open', request);
    if (this._els.panel && this._els.panel.scrollIntoView) this._els.panel.scrollIntoView({ block: 'nearest' });
  },

  reloadCurrent() {
    if (!this.nick || !this.model) return;
    this.openPerson(this.nick, { keepScroll: true });
  },

  _send(slot, request) {
    const id = 'h' + (++this._seq);
    if (!App.bridge || typeof App.bridge[slot] !== 'function') return id;
    if (slot === 'history_open' || slot === 'history_page') App.bridge[slot](id, request.nick, JSON.stringify(request));
    else App.bridge[slot](id, JSON.stringify(request));
    return id;
  },
};

if (typeof window !== 'undefined') window.HistoryStoreOpen = HistoryStoreOpen;
