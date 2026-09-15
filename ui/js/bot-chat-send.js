/* bot-chat-send.js — sending + labels + bubble for BotChat facade (H-B2b JS split)

Design: ≤200 LOC.
*/

'use strict';

const BotChatSend = {
  sendApproved() {
    if (!this.approved) return;
    this.setStatus('Sending the approved message…'); this._deliver(this.approved);
  },

  sendDirect() {
    const text = this._els.direct ? this._els.direct.value.trim() : '';
    if (!text) { this.setStatus('⚠ Write a message first.'); return; }
    this.setStatus('Sending your message…'); this._deliver(text);
  },

  _deliver(text) {
    const id = 'bot' + (++this._seq);
    this._pending[id] = 'send';
    if (App.bridge && typeof App.bridge.bot_send_message === 'function') App.bridge.bot_send_message(id, this.nick, text);
  },

  onSent(payload) {
    const text = typeof payload === 'string' ? payload : String(payload || '');
    this._bubble({ dir: 'out', from: 'me', text: text, time: '' });
    if (text === this.approved) { this.approved = ''; this._updateSendButton(); } else if (this._els.direct) this._els.direct.value = '';
    this.setStatus('✅ Delivered.');
  },

  applyReaction(reaction, source) {
    if (!this.nick || !App.bridge || !App.bridge.bot_apply_reaction) return;
    App.bridge.bot_apply_reaction(this.nick, reaction, (json) => {
      let state = null; try { state = JSON.parse(json); } catch (e) { return; }
      if (!state || state.error) { this.setStatus('⚠ Label not applied: ' + ((state || {}).error || '')); return; }
      this.renderLabels(state);
      this.setStatus(source === 'manual' ? 'Label set manually — this is the final decision.' : 'Confirmed — label applied to the person.');
    });
  },

  renderLabels(state) {
    const host = this._els.labels; if (!host) return; host.textContent = '';
    (state.available || []).forEach((item) => {
      const pill = document.createElement('button'); pill.type = 'button';
      pill.className = 'bot-label' + (state.active === item.id ? ' active' : '');
      pill.dataset.reaction = item.id; pill.style.borderColor = item.color;
      if (state.active === item.id) pill.style.background = item.color;
      pill.textContent = item.name; pill.title = state.active === item.id ? 'Active label' : 'Click to make this the active label';
      host.appendChild(pill);
    });
  },

  _bubble(item) { return BotMessages.bubble(item, this._els.box, (id, row) => this._restore(id, row)); },

  _restore(mediaId, row) {
    if (row) row.dataset.restoring = '1';
    if (!App.bridge || typeof App.bridge.media_restore !== 'function') return;
    App.bridge.media_restore('bot-media-' + (++this._mediaSeq), String(mediaId));
    if (this.nick) setTimeout(() => this.openPerson(this.nick), RESTORE_RELOAD_MS);
  },
};

if (typeof window !== 'undefined') window.BotChatSend = BotChatSend;
