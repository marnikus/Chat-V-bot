/* ═══════════════════════════════════════════════════════════════
   bot-prompt.js — the Grok Prompt Editor window

   A SEPARATE window (never embedded in the AI Bot Chat): the [edit]
   buttons next to the Bot Chat actions open it on the matching
   template. The user edits the text, previews exactly what would be
   sent to Grok for the current person, and saves or cancels. A saved
   edit is stored by the backend and therefore survives a restart.
   ═══════════════════════════════════════════════════════════════ */

'use strict';

const BotPrompt = {
  templates: [],
  variables: [],
  current: '',
  nick: '',
  _seq: 0,
  _els: {},

  init() {
    const $ = (id) => document.getElementById(id);
    this._els = {
      panel: $('winBotPrompt'), tabs: $('botPromptTabs'),
      text: $('botPromptText'), status: $('botPromptStatus'),
      preview: $('botPromptPreview'), previewBtn: $('botPromptPreviewBtn'),
      save: $('botPromptSaveBtn'), cancel: $('botPromptCancelBtn'),
      reset: $('botPromptResetBtn'),
      apiKey: $('botApiKeyInput'), model: $('botModelInput'),
      connSave: $('botConnSaveBtn'),
      vars: $('botVarsList'), warn: $('botPromptWarn'),
    };
    if (!this._els.text) return;
    this._wire();
    this.load();
    this.loadVariables();
    this.loadConnection();
  },

  _wire() {
    const on = (el, fn) => { if (el) el.addEventListener('click', fn); };
    on(this._els.save, () => this.save());
    on(this._els.cancel, () => this.cancel());
    on(this._els.reset, () => this.reset());
    on(this._els.previewBtn, () => this.preview());
    on(this._els.connSave, () => this.saveConnection());
    if (this._els.text) {
      ['input', 'keyup', 'click'].forEach((ev) =>
        this._els.text.addEventListener(ev, () => this.checkVariables()));
    }
    if (this._els.vars) {
      this._els.vars.addEventListener('click', (event) => {
        const chip = event.target && event.target.closest
          ? event.target.closest('.bot-var') : null;
        if (chip && chip.dataset.token) this.insert(chip.dataset.token);
      });
    }
    if (this._els.tabs) {
      this._els.tabs.addEventListener('click', (event) => {
        const tab = event.target && event.target.closest
          ? event.target.closest('.bot-prompt-tab') : null;
        if (tab && tab.dataset.template) this.select(tab.dataset.template);
      });
    }
  },

  load() {
    if (!App.bridge || !App.bridge.bot_get_prompts) return;
    App.bridge.bot_get_prompts((json) => this.setTemplates(json));
  },

  /* ── the variable library ─────────────────────────────────────
     The list comes from the backend, which is also what resolves the
     variables — so the editor cannot advertise a placeholder that does
     not work, which is the whole point of having a library. */

  loadVariables() {
    if (!App.bridge || !App.bridge.bot_get_variables) return;
    App.bridge.bot_get_variables((json) => this.setVariables(json));
  },

  setVariables(json) {
    let list = [];
    try { list = JSON.parse(json || '[]'); } catch (err) { list = []; }
    this.variables = Array.isArray(list) ? list : [];
    this._renderVariables();
  },

  _renderVariables() {
    const host = this._els.vars;
    if (!host) return;
    host.textContent = '';
    this.variables.forEach((spec) => {
      const chip = document.createElement('button');
      chip.type = 'button';
      chip.className = 'bot-var';
      chip.dataset.token = spec.token;
      const name = document.createElement('span');
      name.className = 'bot-var-token';
      name.textContent = spec.token;
      const desc = document.createElement('span');
      desc.className = 'bot-var-desc';
      desc.textContent = spec.description || '';
      chip.appendChild(name);
      chip.appendChild(desc);
      chip.title = 'Example → ' + (spec.example || '');
      host.appendChild(chip);
    });
  },

  /** Put a variable where the cursor is — not at the end of the text. */
  insert(token) {
    const box = this._els.text;
    if (!box) return;
    const value = String(box.value || '');
    const at = typeof box.selectionStart === 'number'
      ? box.selectionStart : value.length;
    const end = typeof box.selectionEnd === 'number' ? box.selectionEnd : at;
    box.value = value.slice(0, at) + token + value.slice(end);
    const caret = at + token.length;
    if (typeof box.setSelectionRange === 'function')
      box.setSelectionRange(caret, caret);
    if (typeof box.focus === 'function') box.focus();
    this.checkVariables();
  },

  /** Warn about placeholders the app cannot resolve. Never blocks saving. */
  checkVariables() {
    if (!App.bridge || !App.bridge.bot_check_prompt || !this._els.text) return;
    App.bridge.bot_check_prompt(String(this._els.text.value || ''),
                                (json) => this.showWarnings(json));
  },

  showWarnings(json) {
    let report = null;
    try { report = JSON.parse(json || 'null'); } catch (err) { report = null; }
    const box = this._els.warn;
    if (!box) return;
    const notes = report
      ? (report.unknown || []).map((n) => 'unknown variable {' + n + '}')
        .concat((report.malformed || []).map((m) => 'malformed: ' + m))
      : [];
    box.textContent = notes.join(' · ');
    box.classList.toggle('hidden', !notes.length);
  },

  /* ── the Grok connection ──────────────────────────────────────
     The key is write-only in the UI: the backend reports only whether one
     is set, so a saved secret is never echoed back into the DOM. */

  loadConnection() {
    if (!App.bridge || !App.bridge.bot_connection) return;
    App.bridge.bot_connection((json) => {
      let state = null;
      try { state = JSON.parse(json); } catch (e) { return; }
      if (!state) return;
      if (this._els.model) this._els.model.value = state.model || '';
      if (this._els.apiKey)
        this._els.apiKey.placeholder = state.has_key
          ? 'a key is saved — type a new one to replace it'
          : 'xai-… — stored in settings.json on this machine';
    });
  },

  saveConnection() {
    if (!App.bridge || !App.bridge.bot_save_connection) return;
    const key = this._els.apiKey ? this._els.apiKey.value.trim() : '';
    const model = this._els.model ? this._els.model.value.trim() : '';
    if (!key && !model) { this.setStatus('⚠ Nothing to save.'); return; }
    App.bridge.bot_save_connection(key, model, (ok) => {
      if (this._els.apiKey) this._els.apiKey.value = '';
      this.setStatus(ok ? '✅ Connection saved.' : '⚠ Could not save it.');
      this.loadConnection();
    });
  },

  setTemplates(json) {
    let list = [];
    try { list = JSON.parse(json) || []; } catch (e) { return; }
    this.templates = list;
    this.renderTabs();
    this.select(this.current || (list[0] || {}).id || '');
  },

  /** Called by the Bot Chat window's [edit] buttons. */
  open(templateId, nick) {
    this.nick = nick || this.nick;
    this.select(templateId);
    if (this._els.panel && this._els.panel.scrollIntoView)
      this._els.panel.scrollIntoView({ block: 'nearest' });
  },

  select(templateId) {
    const found = this.templates.filter((t) => t.id === templateId)[0];
    if (!found) return;
    this.current = templateId;
    if (this._els.text) this._els.text.value = found.text || '';
    if (this._els.preview) this._els.preview.classList.add('hidden');
    this.renderTabs();
    this.setStatus(found.edited ? 'Customised template' : 'Shipped default');
  },

  renderTabs() {
    const host = this._els.tabs;
    if (!host) return;
    host.textContent = '';
    this.templates.forEach((item) => {
      const tab = document.createElement('button');
      tab.type = 'button';
      tab.className = 'bot-prompt-tab' +
        (item.id === this.current ? ' active' : '');
      tab.dataset.template = item.id;
      tab.textContent = item.title + (item.edited ? ' •' : '');
      host.appendChild(tab);
    });
  },

  save() {
    if (!this.current || !App.bridge || !App.bridge.bot_save_prompt) return;
    const text = this._els.text ? this._els.text.value : '';
    App.bridge.bot_save_prompt(this.current, text, (ok) => {
      this.setStatus(ok ? 'Saved — it will be used from now on.'
                        : '⚠ Not saved: the template must keep only the ' +
                          '{nick}, {conversation} and {last_message} fields.');
    });
  },

  cancel() {
    this.select(this.current);
    this.setStatus('Changes discarded.');
  },

  reset() {
    if (!this.current || !App.bridge || !App.bridge.bot_reset_prompt) return;
    App.bridge.bot_reset_prompt(this.current, (ok) => {
      this.setStatus(ok ? 'Back to the shipped template.'
                        : 'Already the shipped template.');
    });
  },

  preview() {
    const nick = this.nick ||
      (typeof BotChat !== 'undefined' ? BotChat.nick : '');
    if (!App.bridge || !App.bridge.bot_preview_prompt) return;
    if (!nick) { this.setStatus('⚠ Pick a person in the AI Bot Chat first.');
                 return; }
    this._previewId = 'prompt' + (++this._seq);
    App.bridge.bot_preview_prompt(this._previewId, nick, this.current);
  },

  onReply(reqId, json) {
    if (reqId !== this._previewId) return;
    let payload = null;
    try { payload = JSON.parse(json); } catch (e) { return; }
    if (!payload || !this._els.preview) return;
    this._els.preview.textContent = payload.prompt || '';
    this._els.preview.classList.remove('hidden');
    this.setStatus('This is exactly what would be sent to Grok.');
  },

  onPromptsChanged(json) { this.setTemplates(json); },

  setStatus(text) {
    if (this._els.status) this._els.status.textContent = text || '';
  },
};

if (typeof window !== 'undefined') window.BotPrompt = BotPrompt;
if (typeof module === 'object' && module.exports) module.exports = BotPrompt;
