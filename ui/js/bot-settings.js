/* ═══════════════════════════════════════════════════════════════
   bot-settings.js — the AI Connections window

   Opened by the ⚙ button in the Grok Prompt Editor title bar. Lists the
   user's NAMED connections — several may share one provider — and holds
   each one's key, model and endpoint. This is the ONLY place connection
   details live; the Prompt Editor selects one and nothing more.

   The key is write-only here. The backend reports only a MASKED form
   ("xai-…mnop"), so a stored secret is never echoed back into the DOM
   — which also means a blank key field on Save means "keep the one
   you have", not "erase it".
   ═══════════════════════════════════════════════════════════════ */

'use strict';

const BotSettings = {
  connections: [],
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
      title: $('botConnTitle'), provider: $('botConnProvider'),
      add: $('botConnNewBtn'), remove: $('botConnDeleteBtn'),
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
    on(this._els.add, () => this.addNew());
    on(this._els.remove, () => this.remove());
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
    if (!App.bridge || !App.bridge.bot_connections) return;
    App.bridge.bot_connections((json) => this.setConnections(json));
  },

  setConnections(json) {
    let data = null;
    try { data = JSON.parse(json || 'null'); } catch (err) { data = null; }
    this.connections = (data && data.connections) || [];
    this.providers = (data && data.providers) || [];
    this.active = (data && data.active) || '';
    if (!this.selected ||
        !this.connections.some((c) => c.id === this.selected)) {
      this.selected = this.active ||
        (this.connections[0] ? this.connections[0].id : '');
    }
    this._renderProviderChoices();
    this._renderList();
    this._renderForm();
  },

  _renderProviderChoices() {
    const box = this._els.provider;
    if (!box) return;
    box.textContent = '';
    this.providers.forEach((spec) => {
      const opt = document.createElement('option');
      opt.value = spec.id;
      opt.textContent = spec.title;
      box.appendChild(opt);
    });
  },

  _renderList() {
    const host = this._els.list;
    if (!host) return;
    host.textContent = '';
    this.connections.forEach((entry) => {
      const row = document.createElement('button');
      row.type = 'button';
      row.className = 'bot-provider' +
        (entry.id === this.selected ? ' selected' : '') +
        (entry.id === this.active ? ' active' : '');
      row.dataset.provider = entry.id;
      const name = document.createElement('span');
      name.className = 'bot-provider-name';
      name.textContent = entry.title;
      row.appendChild(name);
      const tag = document.createElement('span');
      tag.className = 'bot-provider-tag';
      tag.textContent = entry.problem ? '⚠ ' + entry.problem
        : (entry.id === this.active ? 'in use · ' + entry.model : entry.model);
      row.appendChild(tag);
      host.appendChild(row);
    });
  },

  _current() {
    return this.connections.find((c) => c.id === this.selected) || null;
  },

  _renderForm() {
    const entry = this._current() || {};
    if (this._els.key) this._els.key.value = '';
    if (this._els.title) this._els.title.value = entry.title || '';
    if (this._els.provider && entry.provider)
      this._els.provider.value = entry.provider;
    if (this._els.model) this._els.model.value = entry.model || '';
    if (this._els.url) this._els.url.value = entry.url || '';
    if (this._els.keyState) {
      this._els.keyState.textContent = entry.has_key
        ? 'A key is saved (' + (entry.masked || 'set') +
          ') — leave blank to keep it'
        : 'No key saved yet';
    }
  },

  /** Start a blank form for an additional connection. */
  addNew() {
    this.selected = '';
    this._renderList();
    this._renderForm();
    if (this._els.title) this._els.title.value = '';
    this.setStatus('New connection — name it, pick a provider, add a key.');
  },

  remove() {
    if (!this.selected || !App.bridge || !App.bridge.bot_delete_connection) {
      this.setStatus('Select a connection to delete.');
      return;
    }
    App.bridge.bot_delete_connection(this.selected, (gone) => {
      this.setStatus(gone ? 'Connection deleted.' : 'Could not delete it.');
      if (gone) this.selected = '';
      this.load();
    });
  },

  select(provider) {
    this.selected = provider;
    this._renderList();
    this._renderForm();
    this.setStatus('');
  },

  /** Save this connection. Never touches another connection, and never
   *  touches a prompt preset or template. */
  save() {
    if (!App.bridge || !App.bridge.bot_save_connection) return;
    const val = (el) => (el ? String(el.value || '') : '');
    if (!val(this._els.title)) { this.setStatus('Give it a name first.'); return; }
    App.bridge.bot_save_connection(
      this.selected, JSON.stringify({
        title: val(this._els.title), provider: val(this._els.provider),
        api_key: val(this._els.key), model: val(this._els.model),
        url: val(this._els.url) }),
      (ident) => {
        this.setStatus(ident ? 'Saved.' : 'Could not save.');
        if (ident) { this.selected = ident; this.load(); }
      });
  },

  /** One real request through the real transport — see the bridge. */
  test() {
    if (!this.selected || !App.bridge || !App.bridge.bot_test_connection) {
      this.setStatus('Save the connection before testing it.');
      return;
    }
    this.setStatus('Testing …');
    App.bridge.bot_test_connection('bot-test-' + (++this._seq), this.selected);
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
