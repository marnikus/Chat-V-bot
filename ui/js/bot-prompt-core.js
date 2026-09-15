/* bot-prompt-core.js — state + bootstrap + wiring for BotPrompt facade (H-B2b JS split)

Design: ≤150 LOC.
*/

'use strict';

const BotPromptCore = {
  templates: [],
  variables: [],
  presets: [],
  preset: '',
  current: '',
  nick: '',
  _seq: 0,
  _els: {},

  init() {
    const $ = (id) => document.getElementById(id);
    this._els = {
      panel: $('winBotPrompt'), tabs: $('botPromptTabs'), text: $('botPromptText'), status: $('botPromptStatus'),
      preview: $('botPromptPreview'), previewBtn: $('botPromptPreviewBtn'), save: $('botPromptSaveBtn'), cancel: $('botPromptCancelBtn'), reset: $('botPromptResetBtn'),
      vars: $('botVarsList'), warn: $('botPromptWarn'), preset: $('botPresetSelect'), presetSave: $('botPresetSaveBtn'), presetUpdate: $('botPresetUpdateBtn'), presetDelete: $('botPresetDeleteBtn'),
    };
    if (!this._els.text) return;
    this._presetBox = DarkSelect.attach(this._els.preset, { placeholder: '— current template —', onPick: (value) => this.applyPreset(value) });
    this._wire(); this.load(); this.loadVariables();
  },

  _wire() {
    const on = (el, fn) => { if (el) el.addEventListener('click', fn); };
    on(this._els.save, () => this.save()); on(this._els.cancel, () => this.cancel()); on(this._els.reset, () => this.reset()); on(this._els.previewBtn, () => this.preview());
    on(this._els.presetSave, () => this.savePresetAs()); on(this._els.presetUpdate, () => this.updatePreset()); on(this._els.presetDelete, () => this.deletePreset());
    if (this._els.text) ['input', 'keyup', 'click'].forEach((ev) => this._els.text.addEventListener(ev, () => this.checkVariables()));
    if (this._els.vars) {
      this._els.vars.addEventListener('click', (event) => {
        const chip = event.target && event.target.closest ? event.target.closest('.bot-var') : null;
        if (chip && chip.dataset.token) this.insert(chip.dataset.token);
      });
    }
    if (this._els.tabs) {
      this._els.tabs.addEventListener('click', (event) => {
        const tab = event.target && event.target.closest ? event.target.closest('.bot-prompt-tab') : null;
        if (tab && tab.dataset.template) this.select(tab.dataset.template);
      });
    }
  },

  load() { if (!App.bridge || !App.bridge.bot_get_prompts) return; App.bridge.bot_get_prompts((json) => this.setTemplates(json)); },

  setTemplates(json) {
    let list = []; try { list = JSON.parse(json) || []; } catch (e) { return; }
    this.templates = list; this.renderTabs(); this.select(this.current || (list[0] || {}).id || '');
  },

  open(templateId, nick) {
    this.nick = nick || this.nick; this.select(templateId);
    if (this._els.panel && this._els.panel.scrollIntoView) this._els.panel.scrollIntoView({ block: 'nearest' });
  },

  select(templateId) {
    const found = this.templates.filter((t) => t.id === templateId)[0]; if (!found) return;
    this.current = templateId; this.preset = '';
    if (this._els.text) this._els.text.value = found.text || '';
    if (this._els.preview) this._els.preview.classList.add('hidden');
    this.renderTabs(); this.loadPresets(); this.setStatus(found.edited ? 'Customised template' : 'Shipped default');
  },

  renderTabs() {
    const host = this._els.tabs; if (!host) return; host.textContent = '';
    this.templates.forEach((item) => {
      const tab = document.createElement('button'); tab.type = 'button'; tab.className = 'bot-prompt-tab' + (item.id === this.current ? ' active' : ''); tab.dataset.template = item.id; tab.textContent = item.title + (item.edited ? ' •' : ''); host.appendChild(tab);
    });
  },

  setStatus(text) { if (this._els.status) this._els.status.textContent = text || ''; },

  onPromptsChanged(json) { this.setTemplates(json); },
};

if (typeof window !== 'undefined') window.BotPromptCore = BotPromptCore;
