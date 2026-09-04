/* ═══════════════════════════════════════════════════════════════
   criteria-editor.js — Criteria filter management
   ═══════════════════════════════════════════════════════════════ */

'use strict';

const CriteriaEditor = {
  criteria: [],

  loadFromJson(json) {
    try { this.criteria = JSON.parse(json); } catch(e) { this.criteria = []; }
  },

  renderDisplay() {
    const container = document.getElementById('criteriaDisplay');
    container.innerHTML = this.criteria.map((c, i) => {
      const icon = c.enabled ? 'check_circle' : 'cancel';
      const cls = c.enabled ? 'enabled' : 'disabled';
      return `<div class="filter-row ${cls}">
        <span class="material-icons">${icon}</span>
        <span class="filter-label">${c.label}</span>
      </div>`;
    }).join('');
    document.getElementById('editCriteriaBtn').onclick = () => this.openEditor();
  },

  openEditor() {
    const modal = document.getElementById('criteriaModal');
    modal.classList.remove('hidden');
    this._renderEditorForm();
    document.getElementById('criteriaSaveBtn').onclick = () => {
      this._collectFromForm();
      if (App.bridge) App.bridge.save_criteria(JSON.stringify(this.criteria));
      this.renderDisplay();
      modal.classList.add('hidden');
    };
    document.getElementById('criteriaCancelBtn').onclick = () => {
      modal.classList.add('hidden');
    };
  },

  _renderEditorForm() {
    const editor = document.getElementById('criteriaEditor');
    editor.innerHTML = this.criteria.map((c, i) => `
      <div class="form-row" style="margin-bottom:8px;flex-wrap:wrap;gap:8px">
        <input type="checkbox" data-idx="${i}" data-field="enabled" ${c.enabled ? 'checked' : ''}>
        <input value="${c.label}" data-idx="${i}" data-field="label" style="flex:2" placeholder="Label">
        <input value="${c.selector}" data-idx="${i}" data-field="selector" style="flex:2" placeholder="CSS Selector">
        <input value="${c.class_name}" data-idx="${i}" data-field="class_name" style="flex:1" placeholder="Class">
        <select data-idx="${i}" data-field="check_type">
          <option value="MUST_HAVE_CLASS" ${c.check_type==='MUST_HAVE_CLASS'?'selected':''}>Must Have</option>
          <option value="MUST_NOT_HAVE_CLASS" ${c.check_type==='MUST_NOT_HAVE_CLASS'?'selected':''}>Must NOT Have</option>
        </select>
        <button class="btn-icon-sm" onclick="CriteriaEditor.removeCriterion(${i})" title="Remove">
          <span class="material-icons" style="font-size:14px;color:var(--red)">delete</span>
        </button>
      </div>
    `).join('') + `<button class="btn-small" style="margin-top:8px" onclick="CriteriaEditor.addCriterion()">+ Add Criterion</button>`;
  },

  addCriterion() {
    this.criteria.push({
      label: 'New criterion', enabled: false,
      selector: '.avatar-wrapper', class_name: '', check_type: 'MUST_HAVE_CLASS',
    });
    this._renderEditorForm();
  },

  removeCriterion(idx) {
    this.criteria.splice(idx, 1);
    this._renderEditorForm();
  },

  _collectFromForm() {
    const editor = document.getElementById('criteriaEditor');
    editor.querySelectorAll('[data-idx]').forEach(el => {
      const i = parseInt(el.dataset.idx);
      const f = el.dataset.field;
      if (!this.criteria[i]) return;
      if (f === 'enabled') this.criteria[i].enabled = el.checked;
      else this.criteria[i][f] = el.value;
    });
  },
};
