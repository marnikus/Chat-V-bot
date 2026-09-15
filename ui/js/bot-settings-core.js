/* bot-settings-core.js — state + bootstrap + wiring for BotSettings facade (H-B2b JS split)

Design: ≤200 LOC.
*/

'use strict';

const BotSettingsCore = {
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
    this._els = BotConnView.collect();
    if (!this._els.backdrop) return;
    this._providerBox = DarkSelect.attach(this._els.provider, { placeholder: 'Choose a provider', onPick: () => this._onProviderPicked() });
    this._wire();
  },

  current() { return this.connections.find((c) => c.id === this.viewed) || null; },

  providerId() { return this._providerBox ? this._providerBox.value : ''; },

  presetsFor(providerId) { return BotConnView.presetsFor(this.providers, providerId); },

  chosen() { return this.presetsFor(this.providerId()).filter((p) => p.id === this.chosenPreset)[0] || null; },

  _actions() {
    return { select: () => this.select(), save: () => this.save(), close: () => this.close(), cancel: () => this.close(), test: () => this.test(), add: () => this.addNew(), remove: () => this.remove(), apply: () => this.applyPreset(), reveal: () => this.toggleKey() };
  },

  _wire() {
    const actions = this._actions();
    Object.keys(actions).forEach((name) => { const el = this._els[name]; if (el) el.addEventListener('click', actions[name]); });
    [this._els.open, this._els.openFromEditor].forEach((btn) => {
      if (!btn) return;
      btn.addEventListener('click', (event) => { event.stopPropagation(); this.toggle(btn); });
    });
    this._wireLists(); this._wireDirty();
  },

  _wireLists() {
    const pick = (host, sel, attr, fn) => {
      if (!host) return;
      host.addEventListener('click', (event) => { const hit = event.target && event.target.closest ? event.target.closest(sel) : null; if (hit && hit.dataset[attr]) fn(hit.dataset[attr]); });
    };
    pick(this._els.list, '.bot-provider', 'provider', (id) => this.view(id));
    pick(this._els.presetOptions, '.bot-preset-opt', 'preset', (id) => this.choosePreset(id));
  },

  _wireDirty() {
    [this._els.title, this._els.key, this._els.model, this._els.url].forEach((el) => { if (el) el.addEventListener('input', () => { this.dirty = true; }); });
  },

  _onProviderPicked() {
    const spec = this.providers.filter((p) => p.id === this.providerId())[0];
    if (!spec) return;
    this.dirty = true; this.chosenPreset = ''; this.appliedPreset = '';
    this._renderPresets(); this.setStatus('Provider: ' + spec.title);
  },

  open(anchor) {
    if (!this._els.backdrop) return;
    this._els.backdrop.classList.remove('hidden'); this._place(anchor || this._els.openFromEditor || this._els.open); this.setStatus(''); this.load();
  },

  close() {
    if (this._els.backdrop) this._els.backdrop.classList.add('hidden');
    if (this._els.key) this._els.key.value = ''; this.dirty = false;
    if (typeof DarkSelect !== 'undefined') DarkSelect.closeAll(null);
  },

  toggle(anchor) { if (this.isOpen()) this.close(); else this.open(anchor); },

  isOpen() { return !!this._els.backdrop && !this._els.backdrop.classList.contains('hidden'); },

  _place(anchor) { BotConnView.place(this._els.backdrop, anchor); },

  load() { if (!App.bridge || !App.bridge.bot_connections) return; App.bridge.bot_connections((json) => this.setConnections(json)); },

  setConnections(json) {
    let data = null; try { data = JSON.parse(json || 'null'); } catch (err) { data = null; }
    this.connections = (data && data.connections) || []; this.providers = (data && data.providers) || []; this.active = (data && data.active) || '';
    if (!this.viewed || !this.connections.some((c) => c.id === this.viewed)) this.viewed = this.active || (this.connections[0] ? this.connections[0].id : '');
    this._renderProviderChoices(); this._render();
  },

  _renderProviderChoices() {
    if (!this._providerBox) return;
    const current = this.current() || {};
    this._providerBox.setOptions(this.providers.map((spec) => ({ value: spec.id, title: spec.title, sub: spec.model || '' })), current.provider || this.providerId());
  },

  _render() {
    BotConnView.rows(this._els.list, this); if (this._els.count) this._els.count.textContent = this.connections.length + ' saved';
    this._renderForm(); this._renderPresets(); BotConnView.footer(this._els, this);
  },

  _renderPresets() { BotConnView.presets(this._els, this.presetsFor(this.providerId()), this.chosen(), this.appliedPreset); },

  _renderForm() {
    const entry = this.current() || {}; BotConnView.fill(this._els, entry);
    if (this._providerBox && entry.provider) this._providerBox.select(entry.provider);
  },
};

if (typeof window !== 'undefined') window.BotSettingsCore = BotSettingsCore;
