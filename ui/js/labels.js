/* labels.js — Labels facade (H-B2b JS split, 779→~150)

State lives in LabelsModel, rendering in LabelsRender, editing in
LabelsEdit, filter in LabelsFilter, assign in LabelsAssign. This file
keeps bootstrap, bridge, and thin lifecycle.

Parts loaded before this one — see index.html:
  labels-model.js, labels-render.js, labels-edit.js,
  labels-filter.js, labels-assign.js

Public API unchanged: window.Labels with all historical methods.
*/

'use strict';

const Labels = {
  _wired: false,
  _els: {},

  init() {
    if (this._wired) return;
    this._wired = true;
    const $ = (id) => document.getElementById(id);
    this._els = {
      panel: $('winLabels'),
      active: $('labelActiveList'),
      target: $('labelAssignTarget'),
      name: $('labelNameInput'),
      colorBtn: $('labelColorBtn'),
      addBtn: $('labelAddBtn'),
      filterList: $('labelFilterList'),
      includeBtn: $('labelIncludeBtn'),
      excludeBtn: $('labelExcludeBtn'),
      clearBtn: $('labelClearFilterBtn'),
      filterState: $('labelFilterState'),
      personSelect: $('labelPersonSelect'),
      assignList: $('labelAssignList'),
      assignBtn: $('labelAssignBtn'),
      assignHint: $('labelAssignHint'),
    };
    if (!this._els.panel) return;
    if (this._els.colorBtn) {
      this._els.colorBtn.addEventListener('click', () => {
        ColorPicker.open({
          anchor: this._els.colorBtn,
          color: this.draftColor,
          title: 'Pick Color',
          onPick: (hex) => this.setDraftColor(hex),
        });
      });
    }
    if (this._els.addBtn)
      this._els.addBtn.addEventListener('click', () => this.createFromForm());
    if (this._els.name) {
      this._els.name.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') { e.preventDefault(); this.createFromForm(); }
      });
    }
    if (this._els.includeBtn)
      this._els.includeBtn.addEventListener('click', () => this.applyRole('include'));
    if (this._els.excludeBtn)
      this._els.excludeBtn.addEventListener('click', () => this.applyRole('exclude'));
    if (this._els.clearBtn)
      this._els.clearBtn.addEventListener('click', () => this.clearFilter());
    if (this._els.personSelect) {
      this._els.personSelect.addEventListener('change', (e) => {
        this.setPerson(e.target.value || '', { focus: false });
      });
    }
    if (this._els.assignBtn)
      this._els.assignBtn.addEventListener('click', () => this.assignSelected());
    this.setDraftColor(this.draftColor || '#ff3b30');
    this.refresh();
  },

  refresh() {
    if (typeof App === 'undefined' || !App.bridge || !App.bridge.get_labels) {
      this.render();
      return;
    }
    App.bridge.get_labels((json) => this.applyState(json));
  },

  applyState(payload) {
    let state = payload;
    if (typeof payload === 'string') {
      try { state = JSON.parse(payload); } catch (e) { state = null; }
    }
    if (!state || typeof state !== 'object') return;
    this.defs = Array.isArray(state.defs) ? state.defs : [];
    this.assign = (state.assign && typeof state.assign === 'object') ? state.assign : {};
    const rule = state.filter || {};
    this.filterRule = {
      include: Array.isArray(rule.include) ? rule.include.slice() : [],
      exclude: Array.isArray(rule.exclude) ? rule.exclude.slice() : [],
    };
    this.palette = Array.isArray(state.palette) ? state.palette : this.palette;
    const live = new Set(this.defs.map((d) => d.id));
    Array.from(this.selected).forEach((id) => { if (!live.has(id)) this.selected.delete(id); });
    if (this.editing && !live.has(this.editing)) this.editing = '';
    this.render();
    this.repaintTables();
  },

  _bridge(method) {
    if (typeof App === 'undefined' || !App.bridge || !App.bridge[method]) {
      if (typeof LogConsole !== 'undefined')
        LogConsole.log('⚠ Not connected to backend — labels unchanged', 'warn');
      return null;
    }
    return App.bridge;
  },

  createFromForm() {
    const input = this._els.name;
    const name = input ? String(input.value || '').trim() : '';
    if (!name) {
      if (typeof LogConsole !== 'undefined') LogConsole.log('⚠ Type a label name first', 'warn');
      return;
    }
    const bridge = this._bridge('label_create');
    if (!bridge) return;
    bridge.label_create(name, this.draftColor || '');
    if (input) input.value = '';
  },

  deleteLabel(id) {
    const bridge = this._bridge('label_delete');
    if (!bridge) return;
    bridge.label_delete(id);
  },

  setDraftColor(hex) {
    this.draftColor = hex || '#ff3b30';
    if (this._els.colorBtn) {
      this._els.colorBtn.style.background = this.draftColor;
      this._els.colorBtn.title = 'Label colour ' + this.draftColor + ' — click to pick another';
    }
  },

  render() {
    this.renderActive();
    this.renderFilter();
    this.renderAssign();
    this.renderTarget();
  },

  renderActive() {
    const host = this._els.active;
    if (!host) return;
    const nodes = [];
    if (!this.defs.length) {
      nodes.push(this._notice('No labels yet — type a name below, pick a colour and press “+ Add Label”.'));
    }
    this.defs.forEach((label) => {
      if (this.editing === label.id) { nodes.push(this._editRow(label)); return; }
      const assigned = !!this.person && this.idsFor(this.person).indexOf(label.id) >= 0;
      const wrap = document.createElement('span');
      wrap.className = 'label-manage-item';
      if (assigned) wrap.classList.add('assigned');
      const pill = this.pill(label, '', { removable: false, title: this._badgeTitle(label), marked: assigned, assigned: assigned });
      pill.classList.add('label-manage-badge');
      pill.setAttribute('role', 'button');
      pill.setAttribute('tabindex', '0');
      pill.addEventListener('click', () => this.toggleAssign(label.id));
      pill.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') { if (e.preventDefault) e.preventDefault(); this.toggleAssign(label.id); }
      });
      wrap.appendChild(pill);
      const edit = document.createElement('button');
      edit.type = 'button'; edit.className = 'label-manage-edit'; edit.textContent = 'edit';
      edit.title = 'Rename or recolour “' + label.name + '” — ' + this.countFor(label.id) + ' person(s) carry this label';
      edit.addEventListener('click', () => this.startEdit(label.id));
      wrap.appendChild(edit);
      const del = document.createElement('button');
      del.type = 'button'; del.className = 'label-del'; del.textContent = '✕';
      del.title = 'Delete “' + label.name + '” from the whole system (and from every person)';
      del.addEventListener('click', () => this.deleteLabel(label.id));
      wrap.appendChild(del);
      nodes.push(wrap);
    });
    host.replaceChildren.apply(host, nodes);
  },
};

UIHelpers.mergeParts(Labels, LabelsModel, LabelsRender, LabelsEdit, LabelsFilter, LabelsAssign);

if (typeof window !== 'undefined') window.Labels = Labels;
if (typeof module === 'object' && module.exports) module.exports = Labels;
