/* presets-ui-templates.js — template presets for PresetsUI facade (H-B2b JS split)

Template presets: setTemplatePresets, renderTemplateChips, loadTemplate,
deleteTemplate, toggleTemplatePicker.

Design: ≤150 LOC.
*/

'use strict';

const PresetsUITemplates = {
  templatePresets: [],

  setTemplatePresets(json) {
    try { this.templatePresets = JSON.parse(json); } catch (e) { this.templatePresets = []; }
    this.renderTemplateChips();
  },

  renderTemplateChips() {
    const el = document.getElementById('templateChips');
    if (!el) return;
    if (!this.templatePresets.length) {
      el.innerHTML = '<span class="preset-row-empty">none yet — click “Save Template”</span>';
      return;
    }
    el.innerHTML = '';
    this.templatePresets.forEach((t) => {
      el.appendChild(this._makeChip(`💬 ${t.name}`, `(${t.len || 0} ch)`, () => this.loadTemplate(t.name), () => this.deleteTemplate(t.name)));
    });
  },

  loadTemplate(name) {
    if (!App.bridge) { LogConsole.log('⚠ Not connected to backend', 'warn'); return; }
    App.bridge.load_template_preset(name, (body) => {
      if (typeof Composer !== 'undefined' && typeof Composer.setMessage === 'function') {
        Composer.setMessage(body || '');
        LogConsole.log(`💬 Template “${name}” loaded into composer`, 'success');
      }
    });
  },

  deleteTemplate(name) {
    if (!App.bridge) return;
    this.confirmDelete('template', name, () => App.bridge.delete_template_preset(name));
  },

  toggleTemplatePicker(anchorBtn) {
    const picker = document.getElementById('templatePicker');
    const html = this.templatePresets.map((t) =>
      `<div class="preset-picker-row">\n         <span class="pp-name" title="${this.esc(t.name)}">💬 ${this.esc(t.name)}</span>\n         <span class="pp-meta">${t.len || 0} ch · ${this.esc(this._date(t.updated_at))}</span>\n         <button class="pp-load" data-name="${this.esc(t.name)}">Load</button>\n         <span class="pp-del material-icons" data-name="${this.esc(t.name)}" title="Delete">delete</span>\n       </div>`).join('')
      || '<div class="pp-empty">No saved templates yet. Click “Save Template” to create one.</div>';
    picker.innerHTML = `<div class="picker-title">Message templates — click Load to insert</div>${html}`;
    this._placePicker(picker, anchorBtn);
    picker.querySelectorAll('.pp-load').forEach((b) => {
      b.addEventListener('click', () => { picker.classList.add('hidden'); this.loadTemplate(b.dataset.name); });
    });
    picker.querySelectorAll('.pp-del').forEach((b) => {
      b.addEventListener('click', (ev) => { ev.stopPropagation(); this.deleteTemplate(b.dataset.name); });
    });
  },
};

if (typeof window !== 'undefined') window.PresetsUITemplates = PresetsUITemplates;
