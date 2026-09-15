/* history-store-render.js — rendering + actions for HistoryStore facade (H-B2b JS split)

Design: ≤250 LOC.
*/

'use strict';

const HistoryStoreRender = {
  deleteMessage(id) {
    if (!this.nick || id == null) return;
    if (!App.bridge || !App.bridge.history_delete_message) {
      if (typeof LogConsole !== 'undefined') LogConsole.log('⚠ Not connected to backend — message kept', 'warn');
      return;
    }
    App.bridge.history_delete_message(this.nick, String(id));
  },

  clearHistory() {
    if (!this.nick) return;
    if (!App.bridge || !App.bridge.history_clear_person) return;
    window.Dialog.confirm('Clear this conversation?',
      'Every archived message with “' + this.nick + '” is removed. The person stays in the database and Ctrl+Z restores the messages.',
      'Clear', () => App.bridge.history_clear_person(this.nick));
  },

  deletePerson() {
    if (!this.nick) return;
    if (!App.bridge || !App.bridge.history_delete_person) return;
    window.Dialog.confirm('Remove this person?',
      '“' + this.nick + '” and their entire history are removed from the database. Ctrl+Z restores both.',
      'Remove', () => App.bridge.history_delete_person(this.nick, false));
  },

  renderHeader() {
    if (!this._els.header) return;
    HistoryView.renderHeader(this._els.header, {
      nick: this.nick, myNick: this.myNick, stats: this.stats || null,
      labels: (typeof Labels !== 'undefined' && this.nick) ? Labels.forNick(this.nick) : [],
      pill: (typeof Labels !== 'undefined') ? (label) => Labels.pill(label, this.nick, { onRemove: (id, nick) => Labels.unassign(nick, id) }) : null,
    });
  },

  renderEmpty(text) { HistoryView.renderNotice(this._els.list, text); },

  render(options) {
    options = options || {};
    if (!this.model || !this._els.list) return;
    if (this.model.isEmpty) {
      this.renderEmpty(this.model.missing ? 'Nothing archived for “' + this.nick + '” yet.' : 'No messages to show.');
      return;
    }
    const list = this._els.list;
    const atBottom = list.scrollHeight - list.scrollTop - list.clientHeight < 60;
    const anchor = list.querySelector('.msg');
    const anchorTop = anchor ? anchor.getBoundingClientRect().top : 0;
    HistoryView.renderRows(list, this.model.rowsWithMarkers(this._context()), this._context());
    if (options.stickToBottom || atBottom) {
      list.scrollTop = list.scrollHeight;
    } else if (anchor) {
      const same = list.querySelector('[data-ord=\"' + anchor.dataset.ord + '\"]');
      if (same) list.scrollTop += same.getBoundingClientRect().top - anchorTop;
    }
    this._updateLatestButton();
  },

  _updateLatestButton() {
    const button = this._els.latest;
    if (!button || !this.model) return;
    const show = this.model.pendingLive > 0 || this.model.hasNewer;
    button.classList.toggle('hidden', !show);
    button.textContent = this.model.pendingLive ? 'Jump to latest (' + this.model.pendingLive + ' new)' : 'Jump to latest';
  },

  copyMedia(mediaId) {
    if (App.bridge && App.bridge.copy_media) App.bridge.copy_media(String(mediaId));
    if (typeof LogConsole !== 'undefined') LogConsole.log('📋 Copying media…', 'info');
  },

  copySelection() {
    const selection = window.getSelection ? String(window.getSelection()) : '';
    if (selection && App.bridge && App.bridge.copy_text) App.bridge.copy_text(selection);
    return selection;
  },
};

if (typeof window !== 'undefined') window.HistoryStoreRender = HistoryStoreRender;
