/* bot-prompt-presets.js — presets for BotPrompt facade (H-B2b JS split)

Design: ≤150 LOC.
*/

'use strict';

const BotPromptPresets = {
  loadPresets() {
    if (!App.bridge || !App.bridge.bot_get_presets || !this.current) return;
    App.bridge.bot_get_presets(this.current, (json) => {
      try { this.presets = JSON.parse(json || '[]') || []; } catch (err) { this.presets = []; }
      this._renderPresets();
    });
  },

  _renderPresets() {
    if (!this._presetBox) return;
    const rows = [{ value: '', title: '— current template —', sub: 'the live template, as saved' }];
    this.presets.forEach((preset) => rows.push({ value: preset.id, title: preset.title, sub: this._excerpt(preset.text) }));
    this._presetBox.setOptions(rows, this.preset);
  },

  _excerpt(text) { const flat = String(text || '').replace(/\s+/g, ' ').trim(); return flat.length > 60 ? flat.slice(0, 57) + '…' : flat; },

  applyPreset(ident) {
    this.preset = ident || ''; const found = this.presets.filter((p) => p.id === this.preset)[0];
    if (found && this._els.text) { this._els.text.value = found.text || ''; this.checkVariables(); this.setStatus('Preset “' + found.title + '” loaded — press Save to use it'); }
    this._renderPresets();
  },

  savePresetAs() { const title = this._ask('Name for this preset:'); if (!title) return; this._writePreset(title, ''); },

  updatePreset() { const found = this.presets.filter((p) => p.id === this.preset)[0]; if (!found) { this.setStatus('⚠ Select a preset to update first.'); return; } this._writePreset(found.title, found.id); },

  _writePreset(title, ident) {
    if (!App.bridge || !App.bridge.bot_save_preset || !this.current) return;
    const text = this._els.text ? String(this._els.text.value || '') : '';
    App.bridge.bot_save_preset(this.current, title, text, ident, (saved) => {
      if (!saved) { this.setStatus('⚠ Could not save the preset.'); return; }
      this.preset = saved; this.setStatus('✅ Preset “' + title + '” saved.'); this.loadPresets();
    });
  },

  deletePreset() {
    if (!this.preset) { this.setStatus('⚠ Select a preset to delete.'); return; }
    if (!App.bridge || !App.bridge.bot_delete_preset) return;
    App.bridge.bot_delete_preset(this.preset, (gone) => { this.setStatus(gone ? 'Preset deleted.' : '⚠ Could not delete it.'); this.preset = ''; this.loadPresets(); });
  },

  _ask(question) { if (typeof window !== 'undefined' && typeof window.prompt === 'function') return String(window.prompt(question) || '').trim(); return ''; },
};

if (typeof window !== 'undefined') window.BotPromptPresets = BotPromptPresets;
