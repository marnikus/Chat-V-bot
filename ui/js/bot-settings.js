/* ═══════════════════════════════════════════════════════════════
   bot-settings.js — the "Choose AI connection" popup

   An anchored popup under the ⚙ in the Grok Prompt Editor title bar —
   same placement and outside-click dismissal as the Grid view / Bookmarks
   menu. It lists the user's NAMED connections (several may share one
   provider) and holds each one's key, model and endpoint. This is the ONLY
   place connection details live AND the only place the active one is
   chosen, so "which AI runs this?" has one answer and one home.

   BROWSING IS NOT CHOOSING. Two pieces of state, deliberately apart:

     viewed  — the connection the form is showing. Clicking a row moves
               this and nothing else. No save, no activation, no close.
     active  — the connection prompts actually run on. Only `select()`
               moves it, and `select()` is the only action that closes.

   Conflating those two was the reported bug: a click meant to inspect a
   connection was read by the app as a commitment to it.

   Applying a preset is likewise not choosing. `applyPreset()` copies the
   provider's recommended model and endpoint into the visible fields and
   stops there — the popup stays open and every value stays editable, so
   the user can see and correct what was written before committing.

   The key is write-only. The backend reports only a MASKED form, so a
   stored secret is never echoed into the DOM — which also means a blank
   key field means "keep the one you have", not "erase it".

   ideal-size: 314 lines reason=one window = one controller, at the top of
   RULE 18's band and level with bot-chat.js. The drawing half is
   bot-connection-view.js and the dropdown is dark-select.js.
   ═══════════════════════════════════════════════════════════════ */

'use strict';

const BotSettings = {
  connections: [],
  providers: [],
  active: '',
  viewed: '',
  testing: false,
  dirty: false,
  chosenPreset: '',
  appliedPreset: '',
  _seq: 0,
  _els: {},

  init() {
    const $ = (id) => document.getElementById(id);
    this._els = {
      backdrop: $('botSettingsBackdrop'), list: $('botProviderList'),
      openFromEditor: $('botPromptSettingsBtn'), count: $('botConnCount'),
      key: $('botProviderKey'), keyState: $('botProviderKeyState'),
      model: $('botProviderModel'), url: $('botProviderUrl'),
      status: $('botSettingsStatus'), open: $('botSettingsBtn'),
      cancel: $('botSettingsCancelBtn'), close: $('botSettingsCloseBtn'),
      test: $('botTestConnBtn'), title: $('botConnTitle'),
      provider: $('botConnProvider'), add: $('botConnNewBtn'),
      remove: $('botConnDeleteBtn'), select: $('botConnSelectBtn'),
      reveal: $('botKeyRevealBtn'), detailTitle: $('botDetailTitle'),
      dot: $('botConnDot'), readyText: $('botConnReadyText'),
      presetOptions: $('botPresetOptions'), presetDesc: $('botPresetDesc'),
      apply: $('botApplyPresetBtn'),
    };
    if (!this._els.backdrop) return;
    this._providerBox = DarkSelect.attach(this._els.provider, {
      placeholder: 'Choose a provider',
      onPick: () => this._onProviderPicked(),
    });
    this._wire();
  },

  /* ── state helpers ─────────────────────────────────────────── */

  current() {
    return this.connections.find((c) => c.id === this.viewed) || null;
  },

  providerId() {
    return this._providerBox ? this._providerBox.value : '';
  },

  presetsFor(providerId) {
    return BotConnView.presetsFor(this.providers, providerId);
  },

  chosen() {
    return this.presetsFor(this.providerId())
      .filter((p) => p.id === this.chosenPreset)[0] || null;
  },

  /* ── wiring ────────────────────────────────────────────────── */

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
    on(this._els.select, () => this.select());
    on(this._els.close, () => this.close());
    on(this._els.cancel, () => this.close());
    on(this._els.test, () => this.test());
    on(this._els.add, () => this.addNew());
    on(this._els.remove, () => this.remove());
    on(this._els.apply, () => this.applyPreset());
    on(this._els.reveal, () => this.toggleKey());
    this._wireLists();
    this._wireDirty();
  },

  _wireLists() {
    const pick = (host, sel, attr, fn) => {
      if (!host) return;
      host.addEventListener('click', (event) => {
        const hit = event.target && event.target.closest
          ? event.target.closest(sel) : null;
        if (hit && hit.dataset[attr]) fn(hit.dataset[attr]);
      });
    };
    pick(this._els.list, '.bot-provider', 'provider',
         (id) => this.view(id));
    pick(this._els.presetOptions, '.bot-preset-opt', 'preset',
         (id) => this.choosePreset(id));
  },

  /** Typing marks the form dirty so Cancel can warn — and only then. */
  _wireDirty() {
    [this._els.title, this._els.key, this._els.model, this._els.url]
      .forEach((el) => {
        if (el) el.addEventListener('input', () => { this.dirty = true; });
      });
  },

  /** The provider decides the default model and endpoint, so show the
   *  preset for the new provider the moment it changes. */
  _onProviderPicked() {
    const spec = this.providers.filter(
      (p) => p.id === this.providerId())[0];
    if (!spec) return;
    this.dirty = true;
    this.chosenPreset = '';
    this.appliedPreset = '';
    this._renderPresets();
    this.setStatus('Provider: ' + spec.title);
  },

  /* ── opening and closing ───────────────────────────────────── */

  open(anchor) {
    if (!this._els.backdrop) return;
    this._els.backdrop.classList.remove('hidden');
    this._place(anchor || this._els.openFromEditor || this._els.open);
    this.setStatus('');
    this.load();
  },

  /** Closing NEVER changes which connection is active. */
  close() {
    if (this._els.backdrop) this._els.backdrop.classList.add('hidden');
    if (this._els.key) this._els.key.value = '';   // never leave a typed key
    this.dirty = false;
    if (typeof DarkSelect !== 'undefined') DarkSelect.closeAll(null);
  },

  toggle(anchor) {
    if (this.isOpen()) this.close(); else this.open(anchor);
  },

  isOpen() {
    return !!this._els.backdrop &&
      !this._els.backdrop.classList.contains('hidden');
  },

  _place(anchor) {
    BotConnView.place(this._els.backdrop, anchor);
  },

  /* ── loading ───────────────────────────────────────────────── */

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
    if (!this.viewed ||
        !this.connections.some((c) => c.id === this.viewed)) {
      this.viewed = this.active ||
        (this.connections[0] ? this.connections[0].id : '');
    }
    this._renderProviderChoices();
    this._render();
  },

  _renderProviderChoices() {
    if (!this._providerBox) return;
    const current = this.current() || {};
    this._providerBox.setOptions(this.providers.map((spec) => ({
      value: spec.id, title: spec.title, sub: spec.model || '',
    })), current.provider || this.providerId());
  },

  _render() {
    BotConnView.rows(this._els.list, this);
    if (this._els.count)
      this._els.count.textContent = this.connections.length + ' saved';
    this._renderForm();
    this._renderPresets();
    BotConnView.footer(this._els, this);
  },

  _renderPresets() {
    BotConnView.presets(this._els, this.presetsFor(this.providerId()),
                        this.chosen(), this.appliedPreset);
  },

  _renderForm() {
    const entry = this.current() || {};
    BotConnView.fill(this._els, entry);
    if (this._providerBox && entry.provider)
      this._providerBox.select(entry.provider);
  },

  /* ── browsing (never commits) ──────────────────────────────── */

  /** Load a connection into the form. Does NOT activate it, does NOT
   *  save, does NOT close — the whole point of the redesign. */
  view(ident) {
    if (this.dirty && !this._confirmDiscard()) return;
    this.viewed = ident;
    this.dirty = false;
    this.chosenPreset = '';
    this.appliedPreset = '';
    this._render();
    this.setStatus('');
  },

  _confirmDiscard() {
    if (typeof window === 'undefined' || !window.confirm) return true;
    return window.confirm('Discard the unsaved changes to this connection?');
  },

  /** Start a blank form for an additional connection. */
  addNew() {
    this.viewed = '';
    this.dirty = false;
    this.chosenPreset = '';
    this.appliedPreset = '';
    this._render();
    if (this._els.title) this._els.title.value = '';
    this.setStatus('New connection — name it, pick a provider, add a key.');
  },

  toggleKey() {
    const el = this._els.key;
    if (!el) return;
    el.type = el.type === 'password' ? 'text' : 'password';
  },

  /* ── presets ───────────────────────────────────────────────── */

  /** Highlight and describe a preset. Writes nothing. */
  choosePreset(ident) {
    this.chosenPreset = ident;
    this._renderPresets();
  },

  /** Copy the preset's values into the visible fields. The popup stays
   *  open and the fields stay editable: applying is not selecting. */
  applyPreset() {
    const preset = this.chosen();
    if (!preset) { this.setStatus('Choose a preset first.'); return; }
    if (this._els.model) this._els.model.value = preset.model;
    if (this._els.url) this._els.url.value = preset.url;
    this.dirty = true;
    this.appliedPreset = preset.id;
    this._renderPresets();
    this.setStatus('Preset applied to the fields — review, then Select.');
  },

  /* ── committing ────────────────────────────────────────────── */

  _fields() {
    return BotConnView.read(this._els, this.providerId());
  },

  /** Save this connection. Never touches another connection, and never
   *  touches a prompt preset or template. */
  save(then) {
    if (!App.bridge || !App.bridge.bot_save_connection) return;
    const fields = this._fields();
    if (!fields.title) { this.setStatus('Give it a name first.'); return; }
    App.bridge.bot_save_connection(
      this.viewed, JSON.stringify(fields), (ident) => {
        this.setStatus(ident ? 'Saved.' : 'Could not save.');
        if (!ident) return;
        this.viewed = ident;
        this.dirty = false;
        this.load();
        if (then) then(ident);
      });
  },

  /** The ONLY action that confirms and closes: save what is on screen,
   *  make it the connection prompts run on, then close. Saving first
   *  matters — activating an unsaved edit would run prompts on values
   *  the user cannot see. */
  select() {
    this.save((ident) => {
      if (!App.bridge.bot_use_connection) { this.close(); return; }
      App.bridge.bot_use_connection(ident, (ok) => {
        if (!ok) { this.setStatus('Could not switch connection.'); return; }
        this.active = ident;
        this.close();
      });
    });
  },

  remove() {
    if (!this.viewed || !App.bridge || !App.bridge.bot_delete_connection) {
      this.setStatus('Select a connection to delete.');
      return;
    }
    App.bridge.bot_delete_connection(this.viewed, (gone) => {
      this.setStatus(gone ? 'Connection deleted.' : 'Could not delete it.');
      if (gone) this.viewed = '';
      this.load();
    });
  },

  /* ── testing (never closes, never activates) ───────────────── */

  test() {
    if (!this.viewed || !App.bridge || !App.bridge.bot_test_connection) {
      this.setStatus('Save the connection before testing it.');
      return;
    }
    this.testing = true;
    BotConnView.footer(this._els, this);
    this.setStatus('Testing …');
    App.bridge.bot_test_connection('bot-test-' + (++this._seq), this.viewed);
  },

  _testDone(text) {
    this.testing = false;
    BotConnView.footer(this._els, this);
    this.setStatus(text);
    return true;
  },

  /** The test's answer arrives on the Bot Chat bridge, keyed by req_id. */
  onReply(reqId, json) {
    if (String(reqId || '').indexOf('bot-test-') !== 0) return false;
    let payload = null;
    try { payload = JSON.parse(json || 'null'); } catch (err) { payload = null; }
    if (!payload) return this._testDone('The test gave no answer.');
    return this._testDone(payload.ok
      ? 'Connection works — ' + (payload.detail || 'ok')
      : 'Failed: ' + (payload.detail || payload.code || 'unknown error'));
  },

  onError(reqId, code, detail) {
    if (String(reqId || '').indexOf('bot-test-') !== 0) return false;
    return this._testDone('Failed: ' + (detail || code || 'unknown error'));
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
