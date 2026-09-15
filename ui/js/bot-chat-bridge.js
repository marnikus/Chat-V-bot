/* bot-chat-bridge.js — open + bridge + day rendering for BotChat facade (H-B2b JS split)

Design: ≤200 LOC.
*/

'use strict';

const BotChatBridge = {
  openPerson(nick) {
    if (!nick) return;
    this.nick = nick; this.approved = ''; this._updateSendButton();
    if (this._els.person) this._els.person.textContent = nick;
    this._clear();
    this.setStatus('Loading today’s messages for “' + nick + '” …');
    this._send('bot_load_today', 'today', nick);
    this.refreshLabels();
  },

  refreshLabels() {
    if (!App.bridge || !App.bridge.bot_reaction_state || !this.nick) return;
    App.bridge.bot_reaction_state(this.nick, (json) => {
      let state = null; try { state = JSON.parse(json); } catch (e) { return; }
      this.renderLabels(state || { active: '', available: [] });
    });
  },

  ask(slot, kind) {
    if (!this.nick) { this.setStatus('⚠ No person selected.'); return; }
    this.setStatus('Asking Grok…'); this._send(slot, kind, this.nick);
  },

  _send(slot, kind, arg) {
    const id = 'bot' + (++this._seq);
    this._pending[id] = kind;
    if (App.bridge && typeof App.bridge[slot] === 'function') App.bridge[slot](id, arg, this.scope());
    return id;
  },

  onReply(reqId, json) {
    if (typeof BotSettings !== 'undefined' && BotSettings.onReply(reqId, json)) return;
    const kind = this._pending[reqId]; delete this._pending[reqId];
    let payload = null; try { payload = JSON.parse(json); } catch (e) { return; }
    if (kind === 'today') return this.renderDay(payload);
    if (kind === 'suggest') return this.renderSuggestion(payload);
    if (kind === 'analyze') return this.renderAnalysis(payload);
    if (kind === 'send') return this.onSent(payload);
  },

  onError(reqId, message) {
    if (typeof BotSettings !== 'undefined' && BotSettings.onError(reqId, '', message)) return;
    delete this._pending[reqId]; this.setStatus('⚠ ' + message);
  },

  renderDay(page) {
    if (!page || page.nick !== this.nick) return;
    this._clear(); (page.items || []).forEach((item) => this._bubble(item));
    this.setStatus(page.empty ? this._emptyNote(page) : this._countNote(page));
  },

  _emptyNote(page) { return page.scope === 'all' ? 'No messages with this person in the archive yet.' : 'No messages with this person today yet.'; },

  _countNote(page) {
    const used = (page.items || []).length;
    const where = page.scope === 'all' ? 'the whole conversation' : page.day;
    return page.truncated ? (used + ' most recent of ' + page.total + ' message(s) from ' + where) : (used + ' message(s) from ' + where);
  },
};

if (typeof window !== 'undefined') window.BotChatBridge = BotChatBridge;
