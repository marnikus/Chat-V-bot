/* bot-chat-cards.js — suggestion + analysis cards + verify row for BotChat facade (H-B2b JS split)

Design: ≤200 LOC.
*/

'use strict';

const BotChatCards = {
  renderSuggestion(payload) {
    if (!payload || !payload.text) return;
    const card = this._card('Suggested reply', payload.text);
    card.appendChild(this._verifyRow({ approve: () => this.approve(payload.text, card), reject: () => this.reject(card, () => this.ask('bot_suggest_reply', 'suggest')) }));
    this.setStatus('Suggestion ready — approve it to enable sending.');
  },

  renderAnalysis(payload) {
    if (!payload || !payload.reaction) return;
    const card = this._card('Reaction: ' + payload.reaction, payload.reason || payload.raw || '');
    card.classList.add('reaction-' + payload.reaction);
    card.appendChild(this._verifyRow({ approve: () => { card.classList.add('confirmed'); this.applyReaction(payload.reaction, 'ai'); }, reject: () => this.reject(card, () => this.ask('bot_analyze_reaction', 'analyze')) }));
    this.setStatus('Analysis ready — confirm it to apply the label.');
  },

  approve(text, card) {
    this.approved = text; card.classList.add('approved'); this._updateSendButton(); this.setStatus('Approved — click “Send to Person” to deliver it.');
  },

  reject(card, retry) {
    card.classList.add('rejected'); if (this.approved) { this.approved = ''; this._updateSendButton(); }
    const row = card.querySelector('.bot-verify'); if (row) row.remove();
    const again = document.createElement('button'); again.className = 'btn-small bot-retry'; again.type = 'button'; again.title = 'Ask Grok again'; again.textContent = '🔄 Retry'; again.addEventListener('click', retry); card.appendChild(again);
    this.setStatus('Rejected — press 🔄 Retry for another answer.');
  },

  _card(title, text) {
    const card = document.createElement('div'); card.className = 'bot-card pending';
    const head = document.createElement('div'); head.className = 'bot-card-title'; head.textContent = title;
    const body = document.createElement('div'); body.className = 'bot-card-text'; body.textContent = text;
    card.appendChild(head); card.appendChild(body);
    if (this._els.box) this._els.box.appendChild(card); return card;
  },

  _verifyRow(handlers) {
    const row = document.createElement('div'); row.className = 'bot-verify';
    [['✅', 'bot-approve', 'Approve', handlers.approve], ['❌', 'bot-reject', 'Reject', handlers.reject]].forEach((spec) => {
      const btn = document.createElement('button'); btn.type = 'button'; btn.className = 'btn-small ' + spec[1]; btn.title = spec[2]; btn.textContent = spec[0]; btn.addEventListener('click', spec[3]); row.appendChild(btn);
    });
    return row;
  },
};

if (typeof window !== 'undefined') window.BotChatCards = BotChatCards;
