/* bot-settings-actions.js — view/save/select/test/presets for BotSettings facade (H-B2b JS split)

Design: ≤200 LOC.
*/

'use strict';

const BotSettingsActions = {
  view(ident) {
    if (this.dirty && !this._confirmDiscard()) return;
    this.viewed = ident; this.dirty = false; this.chosenPreset = ''; this.appliedPreset = ''; this._render(); this.setStatus('');
  },

  _confirmDiscard() {
    if (typeof window === 'undefined' || !window.confirm) return true;
    return window.confirm('Discard the unsaved changes to this connection?');
  },

  addNew() {
    this.viewed = ''; this.dirty = false; this.chosenPreset = ''; this.appliedPreset = ''; this._render();
    if (this._els.title) this._els.title.value = ''; this.setStatus('New connection — name it, pick a provider, add a key.');
  },

  toggleKey() { const el = this._els.key; if (!el) return; el.type = el.type === 'password' ? 'text' : 'password'; },

  choosePreset(ident) { this.chosenPreset = ident; this._renderPresets(); },

  applyPreset() {
    const preset = this.chosen(); if (!preset) { this.setStatus('Choose a preset first.'); return; }
    if (this._els.model) this._els.model.value = preset.model; if (this._els.url) this._els.url.value = preset.url;
    this.dirty = true; this.appliedPreset = preset.id; this._renderPresets(); this.setStatus('Preset applied to the fields — review, then Select.');
  },

  _fields() { return BotConnView.read(this._els, this.providerId()); },

  save(then) {
    if (!App.bridge || !App.bridge.bot_save_connection) return;
    const fields = this._fields(); if (!fields.title) { this.setStatus('Give it a name first.'); return; }
    App.bridge.bot_save_connection(this.viewed, JSON.stringify(fields), (ident) => {
      this.setStatus(ident ? 'Saved.' : 'Could not save.'); if (!ident) return; this.viewed = ident; this.dirty = false; this.load(); if (then) then(ident);
    });
  },

  select() {
    this.save((ident) => {
      if (!App.bridge.bot_use_connection) { this.close(); return; }
      App.bridge.bot_use_connection(ident, (ok) => { if (!ok) { this.setStatus('Could not switch connection.'); return; } this.active = ident; this.close(); });
    });
  },

  remove() {
    if (!this.viewed || !App.bridge || !App.bridge.bot_delete_connection) { this.setStatus('Select a connection to delete.'); return; }
    App.bridge.bot_delete_connection(this.viewed, (gone) => { this.setStatus(gone ? 'Connection deleted.' : 'Could not delete it.'); if (gone) this.viewed = ''; this.load(); });
  },

  test() {
    if (!this.viewed || !App.bridge || !App.bridge.bot_test_connection) { this.setStatus('Save the connection before testing it.'); return; }
    this.testing = true; BotConnView.footer(this._els, this); this.setStatus('Testing …');
    App.bridge.bot_test_connection('bot-test-' + (++this._seq), this.viewed);
  },

  _testDone(text) { this.testing = false; BotConnView.footer(this._els, this); this.setStatus(text); return true; },

  onReply(reqId, json) {
    if (String(reqId || '').indexOf('bot-test-') !== 0) return false;
    let payload = null; try { payload = JSON.parse(json || 'null'); } catch (err) { payload = null; }
    if (!payload) return this._testDone('The test gave no answer.');
    return this._testDone(payload.ok ? 'Connection works — ' + (payload.detail || 'ok') : 'Failed: ' + (payload.detail || payload.code || 'unknown error'));
  },

  onError(reqId, code, detail) {
    if (String(reqId || '').indexOf('bot-test-') !== 0) return false;
    return this._testDone('Failed: ' + (detail || code || 'unknown error'));
  },

  setStatus(text) { if (this._els.status) this._els.status.textContent = text || ''; },
};

if (typeof window !== 'undefined') window.BotSettingsActions = BotSettingsActions;
