/* bot-chat-core.js — state + bootstrap + scope for BotChat facade (H-B2b JS split)

Design: ≤150 LOC.
*/

'use strict';

const RESTORE_RELOAD_MS = 1200;
const SCOPE_KEY = 'cvb.bot.scope';

const BotChatCore = {
  nick: '',
  approved: '',
  _seq: 0,
  _pending: {},
  _mediaSeq: 0,
  _els: {},

  init() {
    const $ = (id) => document.getElementById(id);
    this._els = {
      panel: $('winBotChat'), person: $('botChatPerson'),
      box: $('botChatBox'), labels: $('botReactionLabels'),
      scope: $('botScopeToday'), status: $('botChatStatus'), send: $('botSendApprovedBtn'),
      hint: $('botApprovedHint'), direct: $('botDirectInput'),
      sendDirect: $('botSendDirectBtn'), reload: $('botReloadBtn'),
      suggest: $('botSuggestBtn'), analyze: $('botAnalyzeBtn'),
    };
    if (!this._els.box) return;
    this._restoreScope();
    this._wire();
    this._updateSendButton();
    this.renderLabels({ active: '', available: [] });
    this.setStatus('Click a nick in User Memory to work on that person.');
  },

  _wire() {
    const on = (el, fn) => { if (el) el.addEventListener('click', fn); };
    on(this._els.suggest, () => this.ask('bot_suggest_reply', 'suggest'));
    on(this._els.analyze, () => this.ask('bot_analyze_reaction', 'analyze'));
    on(this._els.reload, () => this.openPerson(this.nick));
    if (this._els.scope) {
      this._els.scope.addEventListener('change', () => { this._rememberScope(); if (this.nick) this.openPerson(this.nick); });
    }
    on(this._els.send, () => this.sendApproved());
    on(this._els.sendDirect, () => this.sendDirect());
    ['botSuggestEditBtn', 'botAnalyzeEditBtn'].forEach((id) => {
      const btn = document.getElementById(id);
      on(btn, () => { if (typeof BotPrompt !== 'undefined') BotPrompt.open(btn.dataset.template, this.nick); });
    });
    if (this._els.labels) {
      this._els.labels.addEventListener('click', (event) => {
        const pill = event.target && event.target.closest ? event.target.closest('.bot-label') : null;
        if (pill && pill.dataset.reaction) this.applyReaction(pill.dataset.reaction, 'manual');
      });
    }
  },

  _rememberScope() {
    try { localStorage.setItem(SCOPE_KEY, this.scope()); } catch (err) {}
  },

  _restoreScope() {
    let saved = '';
    try { saved = localStorage.getItem(SCOPE_KEY) || ''; } catch (err) { saved = ''; }
    if (saved && this._els.scope) this._els.scope.checked = saved !== 'all';
  },

  scope() {
    const box = this._els.scope;
    return (box && box.checked === false) ? 'all' : 'today';
  },

  _clear() { if (this._els.box) this._els.box.textContent = ''; },

  _updateSendButton() {
    const btn = this._els.send;
    if (btn) btn.disabled = !this.approved;
    if (this._els.hint) this._els.hint.textContent = this.approved ? 'Approved message ready to send' : 'Approve a suggestion (✅) to enable sending';
  },

  setStatus(text) { if (this._els.status) this._els.status.textContent = text || ''; },
};

if (typeof window !== 'undefined') window.BotChatCore = BotChatCore;
