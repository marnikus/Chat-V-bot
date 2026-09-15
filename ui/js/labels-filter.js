/* labels-filter.js — filter rendering and role logic for Labels facade (H-B2b JS split)

Filter section: renderFilter, applyRole, clearFilter.

Design: AREA_H §6.4 — ≤200 LOC.
*/

'use strict';

const LabelsFilter = {
  renderFilter() {
    const host = this._els.filterList;
    if (!host) return;
    const nodes = [];
    if (!this.defs.length) {
      nodes.push(this._notice('Create a label to filter by it.'));
    }
    this.defs.forEach((label) => {
      const row = document.createElement('label');
      row.className = 'label-filter-row';
      const cb = document.createElement('input');
      cb.type = 'checkbox';
      cb.value = label.id;
      cb.checked = this.selected.has(label.id);
      cb.addEventListener('change', () => {
        if (cb.checked) this.selected.add(label.id);
        else this.selected.delete(label.id);
      });
      row.appendChild(cb);
      row.appendChild(this.pill(label, '', { removable: false }));
      const role = this.roleOf(label.id);
      if (role) {
        const tag = document.createElement('span');
        tag.className = 'label-role ' + role;
        tag.textContent = role === 'include' ? '✓ include' : '✕ ignore';
        row.appendChild(tag);
      }
      nodes.push(row);
    });
    host.replaceChildren.apply(host, nodes);
    if (this._els.includeBtn)
      this._els.includeBtn.classList.toggle('active', !!this.filterRule.include.length);
    if (this._els.excludeBtn)
      this._els.excludeBtn.classList.toggle('active', !!this.filterRule.exclude.length);
    if (this._els.filterState) {
      const names = (ids) => ids.map((id) => (this.byId(id) || {}).name || id).join(', ');
      const parts = [];
      if (this.filterRule.include.length) parts.push('only ' + names(this.filterRule.include));
      if (this.filterRule.exclude.length) parts.push('never ' + names(this.filterRule.exclude));
      this._els.filterState.textContent = parts.length
        ? 'Filter: ' + parts.join(' · ') + ' — applies to both tables and to the run queue'
        : 'No label filter — every person is shown and messaged';
      this._els.filterState.classList.toggle('on', parts.length > 0);
    }
  },

  applyRole(role) {
    const picked = Array.from(this.selected);
    if (!picked.length) {
      if (typeof LogConsole !== 'undefined')
        LogConsole.log('⚠ Tick the labels you want to ' + role + ' first', 'warn');
      return;
    }
    const include = new Set(this.filterRule.include);
    const exclude = new Set(this.filterRule.exclude);
    const target = role === 'exclude' ? exclude : include;
    const other = role === 'exclude' ? include : exclude;
    const allOn = picked.every((id) => target.has(id));
    picked.forEach((id) => {
      other.delete(id);
      if (allOn) target.delete(id);
      else target.add(id);
    });
    const bridge = this._bridge('label_set_filter');
    if (!bridge) return;
    bridge.label_set_filter(JSON.stringify({
      include: Array.from(include), exclude: Array.from(exclude),
    }));
  },

  clearFilter() {
    const bridge = this._bridge('label_clear_filter');
    if (bridge) bridge.label_clear_filter();
  },
};

if (typeof window !== 'undefined') window.LabelsFilter = LabelsFilter;
