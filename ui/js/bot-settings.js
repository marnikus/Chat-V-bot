/* ═══════════════════════════════════════════════════════════════
   bot-settings.js — the AI Connections window

   An anchored popup under the ⚙ button in the Grok Prompt Editor title
   bar — same placement and same outside-click dismissal as the Grid view /
   Bookmarks menu, because that is the dropdown pattern this app already has.

   It lists the user's NAMED connections (several may share one provider)
   and holds each one's key, model and endpoint. This is the ONLY place
   connection details live AND the only place the active one is chosen:
   the Prompt Editor holds prompt controls and nothing else, so "which AI
   runs this?" has exactly one answer and one home.

   Every provider always has a row — the store seeds a keyless one — so
   adding a Google key is something the user can reach on a fresh install.
   An unusable connection is listed WITH its problem, never hidden.

   The key is write-only here. The backend reports only a MASKED form
   ("xai-…mnop"), so a stored secret is never echoed back into the DOM
   — which also means a blank key field on Save means "keep the one
   you have", not "erase it".

   ideal-size: 314 lines reason=one window = one controller, at the top of
   RULE 18's band. The separable part already left: the dropdown itself is
   `dark-select.js`, shared with the Prompt Editor's preset chooser.
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
      openFromEditor: $('botPromptSettingsBtn'),
      key: $('botProviderKey'), keyState: $('botProviderKeyState'),
      model: $('botProviderModel'), url: $('botProviderUrl'),
      status: $('botSettingsStatus'), open: $('botSettingsBtn'),
      save: $('botSettingsSaveBtn'), cancel: $('botSettingsCancelBtn'),
      close: $('botSettingsCloseBtn'), test: $('botTestConnBtn'),
      title: $('botConnTitle'), provider: $('botConnProvider'),
      add: $('botConnNewBtn'), remove: $('botConnDeleteBtn'),
      use: $('botConnUseBtn'),
    };
    if (!this._els.backdrop) return;
    this._providerBox = DarkSelect.attach(this._els.provider, {
      placeholder: 'Choose a provider',
      onPick: () => this._onProviderPicked(),
    });
    this._wire();
  },

  /** The provider decides the default model and endpoint, so show them
   *  the moment it changes rather than after a save the user cannot judge. */
  _onProviderPicked() {
    const spec = this.providers.filter(
      (p) => p.id === this.providerId())[0];
    if (!spec) return;
    if (this._els.model && !this._els.model.value)
      this._els.model.value = spec.model || '';
    if (this._els.url && !this._els.url.value)
      this._els.url.value = spec.url || '';
    this.setStatus('Provider: ' + spec.title);
  },

  providerId() {
    return this._providerBox ? this._providerBox.value : '';
  },

  _wire() {
    const on = (el, fn) => { if (el) el.addEventListener('click', fn); };
    const opener = (btn) => {
      if (!btn) return;
      btn.addEventListener('click', (event) => {
        event.stopPropagation();      // the outside-click handler would
        this.toggle(btn);             // otherwise close it immediately
      });
    };
    opener(this._els.open);
    opener(this._els.openFromEditor);
    on(this._els.use, () => this.useForPrompts());
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

  /** Open under the ⚙ that was clicked, like the Grid view / Bookmarks menu. */
  open(anchor) {
    if (!this._els.backdrop) return;
    this._els.backdrop.classList.remove('hidden');
    this._place(anchor || this._els.openFromEditor || this._els.open);
    this.setStatus('');
    this.load();
  },

  close() {
    if (this._els.backdrop) this._els.backdrop.classList.add('hidden');
    if (this._els.key) this._els.key.value = '';   // never leave a typed key
    if (typeof DarkSelect !== 'undefined') DarkSelect.closeAll(null);
  },

  toggle(anchor) {
    if (this.isOpen()) this.close(); else this.open(anchor);
  },

  isOpen() {
    return !!this._els.backdrop &&
      !this._els.backdrop.classList.contains('hidden');
  },

  /** Same arithmetic the layout menu uses: right-aligned, clamped on screen. */
  _place(anchor) {
    const panel = this._els.backdrop;
    if (!anchor || !panel || !anchor.getBoundingClientRect) return;
    const at = anchor.getBoundingClientRect();
    const width = panel.offsetWidth || 520;
    const left = Math.max(8, Math.min(at.right - width,
                                      window.innerWidth - width - 8));
    panel.style.left = left + 'px';
    panel.style.top = (at.bottom + 6) + 'px';
  },

  /** Run prompts through the selected connection from now on. */
  useForPrompts() {
    if (!this.selected) { this.setStatus('Select a connection first.'); return; }
    if (!App.bridge || !App.bridge.bot_use_connection) return;
    App.bridge.bot_use_connection(this.selected, (ok) => {
      this.setStatus(ok ? 'Prompts now run on this connection.'
                        : 'Could not switch connection.');
      this.load();
    });
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
    if (!this._providerBox) return;
    const current = this._current() || {};
    this._providerBox.setOptions(this.providers.map((spec) => ({
      value: spec.id, title: spec.title, sub: spec.model || '',
    })), current.provider || this.providerId());
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
    if (this._providerBox && entry.provider)
      this._providerBox.select(entry.provider);
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
        title: val(this._els.title), provider: this.providerId(),
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

/* Dismiss on a click outside, exactly like the Grid view / Bookmarks menu.
   Registered once at load: the popup's own clicks stopPropagation, and the
   two ⚙ triggers do too, so this only ever sees a genuine outside click. */
if (typeof document !== 'undefined' && document.addEventListener) {
  document.addEventListener('click', (event) => {
    if (!BotSettings.isOpen()) return;
    const inside = event.target && event.target.closest &&
      event.target.closest('#botSettingsBackdrop');
    if (!inside) BotSettings.close();
  });
}

if (typeof window !== 'undefined') window.BotSettings = BotSettings;
