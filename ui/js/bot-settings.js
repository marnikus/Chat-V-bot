/* ═══════════════════════════════════════════════════════════════
   bot-settings.js — the AI provider settings dialog

   Opened by the ⚙ button in the AI Bot Chat title bar. Lists every
   provider the backend supports, holds each one's API key, model and
   endpoint, tests the connection, and marks which provider is active.

   The key is write-only here. The backend reports only a MASKED form
   ("xai-…mnop"), so a stored secret is never echoed back into the DOM
   — which also means a blank key field on Save means "keep the one
   you have", not "erase it".
   ═══════════════════════════════════════════════════════════════ */

'use strict';

const BotSettings = {
  providers: [],
  active: '',
  selected: '',
  _seq: 0,
  _els: {},

  init() {
    const $ = (id) => document.getElementById(id);
    this._els = {
      backdrop: $('botSettingsBackdrop'), list: $('botProviderList'),
      key: $('botProviderKey'), keyState: $('botProviderKeyState'),
      model: $('botProviderModel'), url: $('botProviderUrl'),
      status: $('botSettingsStatus'), open: $('botSettingsBtn'),
      save: $('botSettingsSaveBtn'), cancel: $('botSettingsCancelBtn'),
      close: $('botSettingsCloseBtn'), test: $('botTestConnBtn'),
      use: $('botUseProviderBtn'),
    };
    if (!this._els.backdrop) return;
    this._wire();
  },

  _wire() {
    const on = (el, fn) => { if (el) el.addEventListener('click', fn); };
    on(this._els.open, () => this.open());
    on(this._els.close, () => this.close());
    on(this._els.cancel, () => this.close());
    on(this._els.save, () => this.save());
    on(this._els.test, () => this.test());
    on(this._els.use, () => this.use());
    if (this._els.list) {
      this._els.list.addEventListener('click', (event) => {
        const row = event.target && event.target.closest
          ? event.target.closest('.bot-provider') : null;
        if (row && row.dataset.provider) this.select(row.dataset.provider);
      });
    }
  },

  open() {
    if (this._els.backdrop) this._els.backdrop.classList.remove('hidden');
    this.setStatus('');
    this.load();
  },

  close() {
    if (this._els.backdrop) this._els.backdrop.classList.add('hidden');
    if (this._els.key) this._els.key.value = '';   // never leave a typed key
  },

  load() {
    if (!App.bridge || !App.bridge.bot_providers) return;
    App.bridge.bot_providers((json) => this.setProviders(json));
  },

  setProviders(json) {
    let data = null;
    try { data = JSON.parse(json || 'null'); } catch (err) { data = null; }
    this.providers = (data && data.providers) || [];
    this.active = (data && data.active) || '';
    if (!this.selected ||
        !this.providers.some((p) => p.id === this.selected)) {
      this.selected = this.active ||
        (this.providers[0] ? this.providers[0].id : '');
    }
    this._renderList();
    this._renderForm();
  },

  _renderList() {
    const host = this._els.list;
    if (!host) return;
    host.textContent = '';
    this.providers.forEach((entry) => {
      const row = document.createElement('button');
      row.type = 'button';
      row.className = 'bot-provider' +
        (entry.id === this.selected ? ' selected' : '') +
        (entry.active ? ' active' : '');
      row.dataset.provider = entry.id;
      const name = document.createElement('span');
      name.className = 'bot-provider-name';
      name.textContent = entry.title;
      row.appendChild(name);
      const tag = document.createElement('span');
      tag.className = 'bot-provider-tag';
      tag.textContent = entry.active ? 'in use'
        : (entry.has_key ? 'configured' : 'no key');
      row.appendChild(tag);
      host.appendChild(row);
    });
  },

  _current() {
    return this.providers.find((p) => p.id === this.selected) || null;
  },

  _renderForm() {
    const entry = this._current();
    if (!entry) return;
    if (this._els.key) this._els.key.value = '';
    if (this._els.model) this._els.model.value = entry.model || '';
    if (this._els.url) this._els.url.value = entry.url || '';
    if (this._els.keyState) {
      this._els.keyState.textContent = entry.has_key
        ? 'A key is saved (' + (entry.masked || 'set') +
          ') — leave blank to keep it'
        : 'No key saved yet for ' + entry.title;
    }
  },

  select(provider) {
    this.selected = provider;
    this._renderList();
    this._renderForm();
    this.setStatus('');
  },

  /** Save this provider's settings. Never touches another provider's key,
   *  and never touches the prompt templates. */
  save() {
    if (!this.selected || !App.bridge || !App.bridge.bot_save_provider) return;
    const val = (el) => (el ? String(el.value || '') : '');
    App.bridge.bot_save_provider(this.selected, val(this._els.key),
                                 val(this._els.model), val(this._els.url),
                                 (ok) => {
                                   this.setStatus(ok ? 'Saved.'
                                                     : 'Could not save.');
                                   if (ok) this.load();
                                 });
  },

  /** Make the selected provider the one the AI Bot Chat sends to. */
  use() {
    if (!this.selected || !App.bridge || !App.bridge.bot_use_provider) return;
    App.bridge.bot_use_provider(this.selected, (ok) => {
      this.setStatus(ok ? 'Now using this provider.' : 'Could not switch.');
      if (ok) this.load();
    });
  },

  /** One real request through the real transport — see the bridge. */
  test() {
    if (!this.selected || !App.bridge || !App.bridge.bot_test_provider) return;
    this.setStatus('Testing …');
    App.bridge.bot_test_provider('bot-test-' + (++this._seq), this.selected);
  },

  /** The test's answer arrives on the Bot Chat bridge, keyed by req_id. */
  onReply(reqId, json) {
    if (String(reqId || '').indexOf('bot-test-') !== 0) return false;
    let payload = null;
    try { payload = JSON.parse(json || 'null'); } catch (err) { payload = null; }
    if (!payload) return this.setStatus('The test gave no answer.') || true;
    this.setStatus(payload.ok
      ? 'Connection works — ' + (payload.detail || 'ok')
      : 'Failed: ' + (payload.detail || payload.code || 'unknown error'));
    return true;
  },

  onError(reqId, code, detail) {
    if (String(reqId || '').indexOf('bot-test-') !== 0) return false;
    this.setStatus('Failed: ' + (detail || code || 'unknown error'));
    return true;
  },

  setStatus(text) {
    if (this._els.status) this._els.status.textContent = text || '';
  },
};

if (typeof window !== 'undefined') window.BotSettings = BotSettings;
