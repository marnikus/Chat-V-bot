/* presets-ui-core.js — core helpers for PresetsUI facade (H-B2b JS split)

esc, _date, _makeChip, _placePicker, refreshAll, _parseResult,
escText, _importRow, onFileResult, onImportPreview.

Design: ≤200 LOC.
*/

'use strict';

const PresetsUICore = {
  esc(s) { return window.UIHelpers.esc(s); },

  _date(iso) {
    if (!iso) return '';
    try { return new Date(iso).toLocaleString(); } catch (e) { return iso; }
  },

  _makeChip(a, b, c, d) {
    const opts = (a && typeof a === 'object') ? a : { title: a, meta: b, onLoad: c, onDelete: d };
    return window.UIHelpers.chip(opts);
  },

  _placePicker(picker, anchorBtn) {
    picker.classList.toggle('hidden');
    if (!picker.classList.contains('hidden')) {
      const r = anchorBtn.getBoundingClientRect();
      const w = picker.offsetWidth || 340;
      let left = r.left;
      if (left + w > window.innerWidth - 8) left = Math.max(8, window.innerWidth - w - 8);
      picker.style.top = (r.bottom + 4) + 'px';
      picker.style.left = left + 'px';
    }
  },

  refreshAll() {
    if (!App.bridge) return;
    App.bridge.list_stack_presets((json) => this.setStackPresets(json));
    App.bridge.list_template_presets((json) => this.setTemplatePresets(json));
    App.bridge.list_custom_blocks((json) => this.setCustomBlocksJson(json));
  },

  _parseResult(res) {
    try { return JSON.parse(res); }
    catch (e) {
      LogConsole.log('❌ Bad result from the backend', 'error');
      return null;
    }
  },

  onFileResult(res) {
    const r = this._parseResult(res);
    if (!r) return;
    if (r.ok) LogConsole.log(`✅ Exported to ${r.path}`, 'success');
    else if (r.canceled) LogConsole.log('⏹ Export cancelled', 'info');
    else LogConsole.log(`❌ ${r.error}`, 'error');
  },

  onImportPreview(res) {
    const r = this._parseResult(res);
    if (!r) return;
    if (!r.ok) {
      LogConsole.log(r.canceled ? '⏹ Import cancelled' : `❌ ${r.error}`, r.canceled ? 'info' : 'error');
      return;
    }
    this.showImportPreview(r);
  },

  escText(text, tag) {
    const node = document.createElement(tag || 'div');
    node.textContent = text;
    return node;
  },

  _importRow(idx, block, label) {
    const row = UIHelpers.el('div', 'ibl-row');
    row.appendChild(UIHelpers.el('span', 'ibl-idx', String(idx)));
    row.appendChild(UIHelpers.el('span', 'ibl-name', label || block.custom_name || block.block_id || 'block'));
    const meta = [];
    if (block.selector) meta.push(block.selector);
    if (block.match_text) meta.push(`match “${block.match_text}”`);
    if (block.text) meta.push(String(block.text).slice(0, 60));
    if (block.enabled === false) meta.push('disabled');
    row.appendChild(UIHelpers.el('span', 'ibl-meta', meta.join(' · ')));
    return row;
  },

  promptName(title, placeholder, okLabel, onOk) {
    window.Dialog.promptName(title, placeholder, okLabel, onOk);
  },

  confirmDelete(kindLabel, name, onYes) {
    window.Dialog.confirm(`Delete ${kindLabel}?`, `“${name}” will be permanently removed.`, 'Delete', onYes);
  },

  confirm(title, text, okLabel, onYes) {
    window.Dialog.confirm(title, text, okLabel, onYes);
  },
};

if (typeof window !== 'undefined') window.PresetsUICore = PresetsUICore;
