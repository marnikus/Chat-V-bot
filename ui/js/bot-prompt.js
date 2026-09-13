/* ═══════════════════════════════════════════════════════════════
   bot-prompt.js — the Grok Prompt Editor window

   A SEPARATE window (never embedded in the AI Bot Chat): the [edit]
   buttons next to the Bot Chat actions open it on the matching
   template. The user edits the text, previews exactly what would be
   sent to Grok for the current person, and saves or cancels. A saved
   edit is stored by the backend and therefore survives a restart.

   ideal-size: 406 lines reason=one window = one controller. The editor has
   four jobs that only make sense together — the template tabs, the variable
   checker, the saved presets and the connection dropdown — and each is a
   handful of small methods over the SAME textarea and status line. Cutting
   them apart would move the state, not the complexity. Over RULE 18's 300
   in company with history-db.js, for the same reason.
   ═══════════════════════════════════════════════════════════════ */

'use strict';

const BotPrompt = {
  templates: [],
  variables: [],
  presets: [],
  connections: [],
  preset: '',
  connection: '',
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
      vars: $('botVarsList'), warn: $('botPromptWarn'),
      preset: $('botPresetSelect'), presetSave: $('botPresetSaveBtn'),
      presetUpdate: $('botPresetUpdateBtn'),
      presetDelete: $('botPresetDeleteBtn'),
      conn: $('botConnSelect'), connWarn: $('botConnWarn'),
      settings: $('botPromptSettingsBtn'),
    };
    if (!this._els.text) return;
    this._wire();
    this.load();
    this.loadVariables();
    this.loadConnections();
  },

  _wire() {
    const on = (el, fn) => { if (el) el.addEventListener('click', fn); };
    on(this._els.save, () => this.save());
    on(this._els.cancel, () => this.cancel());
    on(this._els.reset, () => this.reset());
    on(this._els.previewBtn, () => this.preview());
    on(this._els.presetSave, () => this.savePresetAs());
    on(this._els.presetUpdate, () => this.updatePreset());
    on(this._els.presetDelete, () => this.deletePreset());
    on(this._els.settings, () => {
      if (typeof BotSettings !== 'undefined') BotSettings.open();
    });
    if (this._els.preset) {
      this._els.preset.addEventListener('change', () =>
        this.applyPreset(this._els.preset.value));
    }
    if (this._els.conn) {
      this._els.conn.addEventListener('change', () =>
        this.useConnection(this._els.conn.value));
    }
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

  /* ── presets: saved wordings of this template ─────────────────
     Applying a preset only FILLS the editor. The user still presses Save
     for it to become the live template, so browsing presets cannot change
     what the app sends. */

  loadPresets() {
    if (!App.bridge || !App.bridge.bot_get_presets || !this.current) return;
    App.bridge.bot_get_presets(this.current, (json) => {
      try { this.presets = JSON.parse(json || '[]') || []; }
      catch (err) { this.presets = []; }
      this._renderPresets();
    });
  },

  _renderPresets() {
    const box = this._els.preset;
    if (!box) return;
    box.textContent = '';
    const none = document.createElement('option');
    none.value = '';
    none.textContent = this.presets.length
      ? '— current template —' : '— no presets saved —';
    box.appendChild(none);
    this.presets.forEach((preset) => {
      const opt = document.createElement('option');
      opt.value = preset.id;
      opt.textContent = preset.title;
      box.appendChild(opt);
    });
    box.value = this.preset;
  },

  /** Fill the editor from the selected preset (does not save it). */
  applyPreset(ident) {
    this.preset = ident || '';
    const found = this.presets.filter((p) => p.id === this.preset)[0];
    if (found && this._els.text) {
      this._els.text.value = found.text || '';
      this.checkVariables();
      this.setStatus('Preset “' + found.title + '” loaded — press Save to use it');
    }
    this._renderPresets();
  },

  /** Save the editor text as a NEW preset, leaving the others alone. */
  savePresetAs() {
    const title = this._ask('Name for this preset:');
    if (!title) return;
    this._writePreset(title, '');
  },

  /** Overwrite the selected preset. */
  updatePreset() {
    const found = this.presets.filter((p) => p.id === this.preset)[0];
    if (!found) { this.setStatus('⚠ Select a preset to update first.'); return; }
    this._writePreset(found.title, found.id);
  },

  _writePreset(title, ident) {
    if (!App.bridge || !App.bridge.bot_save_preset || !this.current) return;
    const text = this._els.text ? String(this._els.text.value || '') : '';
    App.bridge.bot_save_preset(this.current, title, text, ident, (saved) => {
      if (!saved) { this.setStatus('⚠ Could not save the preset.'); return; }
      this.preset = saved;
      this.setStatus('✅ Preset “' + title + '” saved.');
      this.loadPresets();
    });
  },

  deletePreset() {
    if (!this.preset) { this.setStatus('⚠ Select a preset to delete.'); return; }
    if (!App.bridge || !App.bridge.bot_delete_preset) return;
    App.bridge.bot_delete_preset(this.preset, (gone) => {
      this.setStatus(gone ? 'Preset deleted.' : '⚠ Could not delete it.');
      this.preset = '';
      this.loadPresets();
    });
  },

  /** Prompt the user for text. Split out so tests can drive it. */
  _ask(question) {
    if (typeof window !== 'undefined' && typeof window.prompt === 'function')
      return String(window.prompt(question) || '').trim();
    return '';
  },

  /* ── which connection runs the prompt ─────────────────────────
     Read-only here: keys, models and endpoints live in the AI Connections
     window. This only chooses between what is already configured. */

  loadConnections() {
    if (!App.bridge || !App.bridge.bot_prompt_connections) return;
    App.bridge.bot_prompt_connections((json) => {
      let data = null;
      try { data = JSON.parse(json || 'null'); } catch (err) { data = null; }
      this.connections = (data && data.connections) || [];
      this.connection = (data && data.active) || '';
      this._renderConnections();
    });
  },

  _renderConnections() {
    const box = this._els.conn;
    if (!box) return;
    box.textContent = '';
    if (!this.connections.length) {
      const none = document.createElement('option');
      none.value = '';
      none.textContent = '— no connections — open ⚙ to add one —';
      box.appendChild(none);
    }
    this.connections.forEach((conn) => {
      const opt = document.createElement('option');
      opt.value = conn.id;
      opt.textContent = conn.title + (conn.ok ? '' : ' ⚠');
      box.appendChild(opt);
    });
    box.value = this.connection;
    this._warnConnection();
  },

  /** A selected-but-unusable connection must say why, not fail silently. */
  _warnConnection() {
    const box = this._els.connWarn;
    if (!box) return;
    const found = this.connections.filter((c) => c.id === this.connection)[0];
    if (!this.connections.length)
      box.textContent = 'No AI connection configured yet.';
    else if (found && found.problem)
      box.textContent = '⚠ ' + found.problem + ' — fix it in ⚙';
    else
      box.textContent = '';
  },

  useConnection(ident) {
    this.connection = ident || '';
    this._warnConnection();
    if (!App.bridge || !App.bridge.bot_use_connection_for_prompts) return;
    App.bridge.bot_use_connection_for_prompts(this.connection, () => {});
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
    this.preset = '';                 // presets belong to a template
    if (this._els.text) this._els.text.value = found.text || '';
    if (this._els.preview) this._els.preview.classList.add('hidden');
    this.renderTabs();
    this.loadPresets();
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
    // The SAME scope the chat window is using, or the preview would show a
    // prompt that is not the one the app would send.
    const scope = (typeof BotChat !== 'undefined' && BotChat.scope)
      ? BotChat.scope() : 'today';
    App.bridge.bot_preview_prompt(this._previewId, nick, this.current, scope);
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
