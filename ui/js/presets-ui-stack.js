/* presets-ui-stack.js — stack preset chip list for PresetsUI facade (H-B2b JS split)

Stack presets: setStackPresets, renderStackChips, loadStack, deleteStack,
toggleStackPicker, exportCurrentStack, exportPreset.

Design: ≤200 LOC.
*/

'use strict';

const PresetsUIStack = {
  stackPresets: [],

  setStackPresets(json) {
    try { this.stackPresets = JSON.parse(json); } catch (e) { this.stackPresets = []; }
    this.renderStackChips();
  },

  renderStackChips() {
    const el = document.getElementById('presetChips');
    if (!el) return;
    if (!this.stackPresets.length) {
      el.innerHTML = '<span class="preset-row-empty">none yet — click 💾 Save and give the preset a name</span>';
      return;
    }
    el.innerHTML = '';
    this.stackPresets.forEach((p) => {
      el.appendChild(this._makeChip(`📄 ${p.name}`, `(${p.blocks || 0})`, () => this.loadStack(p.name), () => this.deleteStack(p.name)));
    });
  },

  loadStack(name) {
    if (!App.bridge) { LogConsole.log('⚠ Not connected to backend', 'warn'); return; }
    LogConsole.log(`📂 Loading preset “${name}”…`, 'info');
    if (StackDnD && typeof StackDnD.pushHistory === 'function' && StackDnD.stack && StackDnD.stack.length) {
      StackDnD.pushHistory(StackDnD.stack, { force: false });
    }
    App.bridge.load_stack_preset(name, (payload) => {
      if (!payload || payload === 'null') return;
      try {
        const blocks = JSON.parse(payload);
        if (StackDnD && typeof StackDnD.setStack === 'function') StackDnD.setStack(blocks);
        LogConsole.log(`✅ Preset “${name}” restored — ${blocks.length} block(s) (↩ Undo to return)`, 'success');
      } catch (e) {
        LogConsole.log(`❌ Preset “${name}” could not be parsed`, 'error');
      }
    });
  },

  deleteStack(name) {
    if (!App.bridge) return;
    this.confirmDelete('preset', name, () => App.bridge.delete_stack_preset(name));
  },

  toggleStackPicker(anchorBtn) {
    const picker = document.getElementById('presetPicker');
    const html = this.stackPresets.map((p) =>
      `<div class="preset-picker-row">\n         <span class="pp-name" title="${this.esc(p.name)}">📄 ${this.esc(p.name)}</span>\n         <span class="pp-meta">${p.blocks || 0} blk · ${this.esc(this._date(p.updated_at))}</span>\n         <button class="pp-load" data-name="${this.esc(p.name)}">Load</button>\n         <button class="pp-export" data-name="${this.esc(p.name)}" title="Export this preset to a .json file">Export</button>\n         <span class="pp-del material-icons" data-name="${this.esc(p.name)}" title="Delete">delete</span>\n       </div>`).join('')
      || '<div class="pp-empty">No saved presets yet. Click 💾 Save to create one.</div>';
    picker.innerHTML = `<div class="picker-title">Saved presets — click Load to restore</div>${html}`;
    this._placePicker(picker, anchorBtn);
    picker.querySelectorAll('.pp-load').forEach((b) => {
      b.addEventListener('click', () => { picker.classList.add('hidden'); this.loadStack(b.dataset.name); });
    });
    picker.querySelectorAll('.pp-export').forEach((b) => {
      b.addEventListener('click', (ev) => { ev.stopPropagation(); picker.classList.add('hidden'); this.exportPreset(b.dataset.name); });
    });
    picker.querySelectorAll('.pp-del').forEach((b) => {
      b.addEventListener('click', (ev) => { ev.stopPropagation(); this.deleteStack(b.dataset.name); });
    });
  },

  exportCurrentStack() {
    if (!App.bridge) { LogConsole.log('⚠ Not connected to backend', 'warn'); return; }
    if (!StackDnD || !StackDnD.stack || !StackDnD.stack.length) {
      LogConsole.log('⚠ Stack is empty — nothing to export', 'warn'); return;
    }
    LogConsole.log('📤 Exporting stack + custom blocks… choose the location in the dialog', 'info');
    App.bridge.export_stack(JSON.stringify(StackDnD.stack), (res) => this.onFileResult(res));
  },

  exportPreset(name) {
    if (!App.bridge) { LogConsole.log('⚠ Not connected to backend', 'warn'); return; }
    App.bridge.export_stack_preset(name, (res) => this.onFileResult(res));
  },
};

if (typeof window !== 'undefined') window.PresetsUIStack = PresetsUIStack;
