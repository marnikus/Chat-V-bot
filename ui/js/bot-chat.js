/* ═══════════════════════════════════════════════════════════════
   bot-chat.js — the AI Bot Chat window

   Loads the CURRENT DAY's messages of one person, asks Grok for a
   suggested reply or a reaction analysis, and lets the user send a
   message of their own. Nothing leaves this window on its own:

     * a suggestion arrives PENDING — ✅ approves it (which only ENABLES
       the "Send to Person" button), ❌ rejects it and offers 🔄 retry;
     * an analysis arrives PENDING — ✅ applies exactly one reaction
       label, ❌ offers 🔄 re-analyze;
     * clicking an inactive label is a manual override and wins over
       whatever the AI said earlier.

   Nodes are built with createElement/textContent only: a message is
   user (or model) text and must never become markup.

   ideal-size: 396 lines reason=one window = one controller, and the
   verification flow above is what a reader must hold whole. Everything
   separable HAS been separated: the Prompt Editor (bot-prompt.js), the AI
   Connections window (bot-settings.js), how one message becomes a row
   (bot-messages.js), and the media rendering, which is not ours at all —
   it is the DB window's renderer, called.
   ═══════════════════════════════════════════════════════════════ */

'use strict';

/** how long to let the collector fetch a restored file before reloading */
const RESTORE_RELOAD_MS = 1200;

/** where the "today only" checkbox remembers itself */
const SCOPE_KEY = 'cvb.bot.scope';

const BotChat = {
  nick: '',
  approved: '',                 // the approved suggestion text, '' when none
  _seq: 0,
  _pending: {},                 // req id -> what was asked for
  _mediaSeq: 0,                 // one counter for media-restore requests
  _els: {},

  init() {
    const $ = (id) => document.getElementById(id);
    this._els = {
      panel: $('winBotChat'), person: $('botChatPerson'),
      box: $('botChatBox'), labels: $('botReactionLabels'),
      scope: $('botScopeToday'),
      status: $('botChatStatus'), send: $('botSendApprovedBtn'),
      hint: $('botApprovedHint'), direct: $('botDirectInput'),
      sendDirect: $('botSendDirectBtn'), reload: $('botReloadBtn'),
      suggest: $('botSuggestBtn'), analyze: $('botAnalyzeBtn'),
    };
    if (!this._els.box) return;
    this._restoreScope();
    this._wire();
    this._updateSendButton();      // the disabled state is code, not markup
    this.renderLabels({ active: '', available: [] });
    this.setStatus('Click a nick in User Memory to work on that person.');
  },

  _wire() {
    const on = (el, fn) => { if (el) el.addEventListener('click', fn); };
    on(this._els.suggest, () => this.ask('bot_suggest_reply', 'suggest'));
    on(this._els.analyze, () => this.ask('bot_analyze_reaction', 'analyze'));
    on(this._els.reload, () => this.openPerson(this.nick));
    if (this._els.scope) {
      this._els.scope.addEventListener('change', () => {
        this._rememberScope();
        if (this.nick) this.openPerson(this.nick);
      });
    }
    on(this._els.send, () => this.sendApproved());
    on(this._els.sendDirect, () => this.sendDirect());
    ['botSuggestEditBtn', 'botAnalyzeEditBtn'].forEach((id) => {
      const btn = document.getElementById(id);
      on(btn, () => {
        if (typeof BotPrompt !== 'undefined')
          BotPrompt.open(btn.dataset.template, this.nick);
      });
    });
    if (this._els.labels) {
      this._els.labels.addEventListener('click', (event) => {
        const pill = event.target && event.target.closest
          ? event.target.closest('.bot-label') : null;
        if (pill && pill.dataset.reaction)
          this.applyReaction(pill.dataset.reaction, 'manual');
      });
    }
  },

  // ── person + today's messages ────────────────────────────────

  openPerson(nick) {
    if (!nick) return;
    this.nick = nick;
    this.approved = '';
    this._updateSendButton();
    if (this._els.person) this._els.person.textContent = nick;
    this._clear();
    this.setStatus('Loading today’s messages for “' + nick + '” …');
    this._send('bot_load_today', 'today', nick);
    this.refreshLabels();
  },

  refreshLabels() {
    if (!App.bridge || !App.bridge.bot_reaction_state || !this.nick) return;
    App.bridge.bot_reaction_state(this.nick, (json) => {
      let state = null;
      try { state = JSON.parse(json); } catch (e) { return; }
      this.renderLabels(state || { active: '', available: [] });
    });
  },

  ask(slot, kind) {
    if (!this.nick) { this.setStatus('⚠ No person selected.'); return; }
    this.setStatus('Asking Grok…');
    this._send(slot, kind, this.nick);
  },

  _send(slot, kind, arg) {
    const id = 'bot' + (++this._seq);
    this._pending[id] = kind;
    if (App.bridge && typeof App.bridge[slot] === 'function')
      App.bridge[slot](id, arg, this.scope());
    return id;
  },

  /** The scope survives a restart, in `localStorage` — the same place
   *  sash-grid keeps its window state. A UI toggle is not world data, so
   *  it does not belong in the config file the bridges own. */
  _rememberScope() {
    try { localStorage.setItem(SCOPE_KEY, this.scope()); }
    catch (err) { /* private mode: the toggle still works this session */ }
  },

  _restoreScope() {
    let saved = '';
    try { saved = localStorage.getItem(SCOPE_KEY) || ''; }
    catch (err) { saved = ''; }
    if (saved && this._els.scope) this._els.scope.checked = saved !== 'all';
  },

  /** Which conversation the AI reads: today's messages, or all of them.
   *
   *  The checkbox travels with EVERY request, not just the message list —
   *  otherwise it would change what the user sees while the model kept
   *  reading a different conversation.
   */
  scope() {
    const box = this._els.scope;
    return (box && box.checked === false) ? 'all' : 'today';
  },

  // ── bridge answers ───────────────────────────────────────────

  onReply(reqId, json) {
    // The Prompt Editor and the AI Settings dialog answer on THIS bridge's
    // signals (the router exposes one signal of each name), so each first
    // claims the requests it made, keyed by req_id.
    if (typeof BotSettings !== 'undefined' &&
        BotSettings.onReply(reqId, json)) return;
    const kind = this._pending[reqId];
    delete this._pending[reqId];
    let payload = null;
    try { payload = JSON.parse(json); } catch (e) { return; }
    if (kind === 'today') return this.renderDay(payload);
    if (kind === 'suggest') return this.renderSuggestion(payload);
    if (kind === 'analyze') return this.renderAnalysis(payload);
    if (kind === 'send') return this.onSent(payload);
  },

  onError(reqId, message) {
    if (typeof BotSettings !== 'undefined' &&
        BotSettings.onError(reqId, '', message)) return;
    delete this._pending[reqId];
    this.setStatus('⚠ ' + message);
  },

  renderDay(page) {
    if (!page || page.nick !== this.nick) return;
    this._clear();
    (page.items || []).forEach((item) => this._bubble(item));
    this.setStatus(page.empty ? this._emptyNote(page)
                              : this._countNote(page));
  },

  _emptyNote(page) {
    return page.scope === 'all'
      ? 'No messages with this person in the archive yet.'
      : 'No messages with this person today yet.';
  },

  /** Say how many messages are in play, and admit when the cap trimmed them:
   *  a silently shortened history is a wrong answer the user cannot see. */
  _countNote(page) {
    const used = (page.items || []).length;
    const where = page.scope === 'all' ? 'the whole conversation'
                                       : page.day;
    return page.truncated
      ? (used + ' most recent of ' + page.total + ' message(s) from ' + where)
      : (used + ' message(s) from ' + where);
  },

  // ── the two pending cards ────────────────────────────────────

  renderSuggestion(payload) {
    if (!payload || !payload.text) return;
    const card = this._card('Suggested reply', payload.text);
    card.appendChild(this._verifyRow({
      approve: () => this.approve(payload.text, card),
      reject: () => this.reject(card, () => this.ask('bot_suggest_reply',
                                                     'suggest')),
    }));
    this.setStatus('Suggestion ready — approve it to enable sending.');
  },

  renderAnalysis(payload) {
    if (!payload || !payload.reaction) return;
    const card = this._card('Reaction: ' + payload.reaction,
                            payload.reason || payload.raw || '');
    card.classList.add('reaction-' + payload.reaction);
    card.appendChild(this._verifyRow({
      approve: () => {
        card.classList.add('confirmed');
        this.applyReaction(payload.reaction, 'ai');
      },
      reject: () => this.reject(card, () => this.ask('bot_analyze_reaction',
                                                     'analyze')),
    }));
    this.setStatus('Analysis ready — confirm it to apply the label.');
  },

  approve(text, card) {
    this.approved = text;
    card.classList.add('approved');
    this._updateSendButton();
    this.setStatus('Approved — click “Send to Person” to deliver it.');
  },

  reject(card, retry) {
    card.classList.add('rejected');
    if (this.approved) { this.approved = ''; this._updateSendButton(); }
    const row = card.querySelector('.bot-verify');
    if (row) row.remove();
    const again = document.createElement('button');
    again.className = 'btn-small bot-retry';
    again.type = 'button';
    again.title = 'Ask Grok again';
    again.textContent = '🔄 Retry';
    again.addEventListener('click', retry);
    card.appendChild(again);
    this.setStatus('Rejected — press 🔄 Retry for another answer.');
  },

  // ── sending ──────────────────────────────────────────────────

  sendApproved() {
    if (!this.approved) return;              // the button is the only gate
    this.setStatus('Sending the approved message…');
    this._deliver(this.approved);
  },

  sendDirect() {
    const text = this._els.direct ? this._els.direct.value.trim() : '';
    if (!text) { this.setStatus('⚠ Write a message first.'); return; }
    this.setStatus('Sending your message…');
    this._deliver(text);
  },

  /* Both send paths carry the nick: the backend refuses to deliver into a
     chat tab that belongs to somebody else. */
  _deliver(text) {
    const id = 'bot' + (++this._seq);
    this._pending[id] = 'send';
    if (App.bridge && typeof App.bridge.bot_send_message === 'function')
      App.bridge.bot_send_message(id, this.nick, text);
  },

  onSent(payload) {
    const text = typeof payload === 'string' ? payload : String(payload || '');
    this._bubble({ dir: 'out', from: 'me', text: text, time: '' });
    if (text === this.approved) { this.approved = ''; this._updateSendButton(); }
    else if (this._els.direct) this._els.direct.value = '';
    this.setStatus('✅ Delivered.');
  },

  // ── reaction labels ──────────────────────────────────────────

  applyReaction(reaction, source) {
    if (!this.nick || !App.bridge || !App.bridge.bot_apply_reaction) return;
    App.bridge.bot_apply_reaction(this.nick, reaction, (json) => {
      let state = null;
      try { state = JSON.parse(json); } catch (e) { return; }
      if (!state || state.error) {
        this.setStatus('⚠ Label not applied: ' + ((state || {}).error || ''));
        return;
      }
      this.renderLabels(state);
      this.setStatus(source === 'manual'
        ? 'Label set manually — this is the final decision.'
        : 'Confirmed — label applied to the person.');
    });
  },

  renderLabels(state) {
    const host = this._els.labels;
    if (!host) return;
    host.textContent = '';
    (state.available || []).forEach((item) => {
      const pill = document.createElement('button');
      pill.type = 'button';
      pill.className = 'bot-label' +
        (state.active === item.id ? ' active' : '');
      pill.dataset.reaction = item.id;
      pill.style.borderColor = item.color;
      if (state.active === item.id) pill.style.background = item.color;
      pill.textContent = item.name;
      pill.title = state.active === item.id
        ? 'Active label' : 'Click to make this the active label';
      host.appendChild(pill);
    });
  },

  // ── DOM helpers ──────────────────────────────────────────────

  _clear() { if (this._els.box) this._els.box.textContent = ''; },

  /** One message row — drawn by bot-messages.js, restored through here. */
  _bubble(item) {
    return BotMessages.bubble(item, this._els.box,
                              (id, row) => this._restore(id, row));
  },

  /**
   * Ask the collector to fetch a media file again, then reload the day.
   *
   * Same `media_restore` slot the DB window's store calls — the archive has
   * one restore path and this is it.
   */
  _restore(mediaId, row) {
    if (row) row.dataset.restoring = '1';
    if (!App.bridge || typeof App.bridge.media_restore !== 'function') return;
    App.bridge.media_restore('bot-media-' + (++this._mediaSeq),
                             String(mediaId));
    if (this.nick)
      setTimeout(() => this.openPerson(this.nick), RESTORE_RELOAD_MS);
  },

  _card(title, text) {
    const card = document.createElement('div');
    card.className = 'bot-card pending';
    const head = document.createElement('div');
    head.className = 'bot-card-title';
    head.textContent = title;
    const body = document.createElement('div');
    body.className = 'bot-card-text';
    body.textContent = text;
    card.appendChild(head);
    card.appendChild(body);
    if (this._els.box) this._els.box.appendChild(card);
    return card;
  },

  _verifyRow(handlers) {
    const row = document.createElement('div');
    row.className = 'bot-verify';
    [['✅', 'bot-approve', 'Approve', handlers.approve],
     ['❌', 'bot-reject', 'Reject', handlers.reject]].forEach((spec) => {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'btn-small ' + spec[1];
      btn.title = spec[2];
      btn.textContent = spec[0];
      btn.addEventListener('click', spec[3]);
      row.appendChild(btn);
    });
    return row;
  },

  _updateSendButton() {
    const btn = this._els.send;
    if (btn) btn.disabled = !this.approved;
    if (this._els.hint) {
      this._els.hint.textContent = this.approved
        ? 'Approved message ready to send'
        : 'Approve a suggestion (✅) to enable sending';
    }
  },

  setStatus(text) {
    if (this._els.status) this._els.status.textContent = text || '';
  },
};

if (typeof window !== 'undefined') window.BotChat = BotChat;
if (typeof module === 'object' && module.exports) module.exports = BotChat;
