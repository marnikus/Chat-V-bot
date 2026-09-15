/* labels-assign.js — assign rendering and mutations for Labels facade (H-B2b JS split)

Assign section: renderAssign, renderTarget, setPerson, assignSelected,
toggleAssign, flashNoTarget, assignTo, unassign, setLabelsOf.

Design: AREA_H §6.4 — ≤250 LOC.
*/

'use strict';

const LabelsAssign = {
  renderTarget() {
    const chip = this._els.target;
    if (!chip) return;
    if (this.person) {
      chip.textContent = '🎯 ' + this.person;
      chip.classList.add('on');
      chip.title = 'Every badge below assigns to “' + this.person + '” — click again to take the label away';
    } else {
      chip.textContent = 'click a person to quick-assign';
      chip.classList.remove('on');
      chip.title = 'Click a person in People, Storage or Person History — then click a badge to assign it';
    }
  },

  renderAssign() {
    const select = this._els.personSelect;
    const host = this._els.assignList;
    if (select) {
      const nicks = this.knownNicks();
      if (this.person && nicks.indexOf(this.person) < 0) nicks.unshift(this.person);
      const options = [];
      const blank = document.createElement('option');
      blank.value = '';
      blank.textContent = nicks.length ? 'Select person…' : 'No person yet';
      options.push(blank);
      nicks.forEach((nick) => {
        const opt = document.createElement('option');
        opt.value = nick;
        const mine = this.forNick(nick);
        opt.textContent = nick + (mine.length ? '  [' + mine.map((l) => l.name).join(', ') + ']' : '');
        options.push(opt);
      });
      select.replaceChildren.apply(select, options);
      select.value = this.person || '';
    }
    if (host) {
      const nodes = [];
      if (!this.defs.length) {
        nodes.push(this._notice('No labels to assign yet.'));
      } else if (!this.person) {
        nodes.push(this._notice('Click a nick in People, Storage or Person History — the person appears here with the labels they already carry.'));
      } else {
        const mine = new Set(this.idsFor(this.person));
        this.defs.forEach((label) => {
          const row = document.createElement('label');
          row.className = 'label-filter-row';
          const cb = document.createElement('input');
          cb.type = 'checkbox';
          cb.value = label.id;
          cb.checked = mine.has(label.id);
          row.appendChild(cb);
          row.appendChild(this.pill(label, this.person, { removable: false }));
          nodes.push(row);
        });
      }
      host.replaceChildren.apply(host, nodes);
    }
    if (this._els.assignHint) {
      this._els.assignHint.textContent = this.person
        ? 'Target: “' + this.person + '” — click a badge above, or tick below and press Assign'
        : 'No person selected';
    }
    if (this._els.assignBtn) this._els.assignBtn.disabled = !this.person;
  },

  setPerson(nick, options) {
    options = options || {};
    const clean = String(nick == null ? '' : nick).trim();
    this.person = clean;
    this.renderAssign();
    this.renderActive();
    this.renderTarget();
    if (clean && options.focus !== false && typeof SashGrid !== 'undefined' && SashGrid.openWindow) {
      SashGrid.openWindow('labels');
    }
    if (typeof UserTable !== 'undefined' && UserTable.markLabelTarget)
      UserTable.markLabelTarget(clean);
    if (typeof HistoryDb !== 'undefined' && HistoryDb.markLabelTarget)
      HistoryDb.markLabelTarget(clean);
  },

  assignSelected() {
    if (!this.person) {
      if (typeof LogConsole !== 'undefined') LogConsole.log('⚠ Choose a person first', 'warn');
      return;
    }
    const host = this._els.assignList;
    if (!host) return;
    const ids = Array.from(host.querySelectorAll('input[type="checkbox"]'))
      .filter((cb) => cb.checked).map((cb) => cb.value);
    this.setLabelsOf(this.person, ids);
  },

  toggleAssign(id) {
    if (!this.person) {
      this.flashNoTarget();
      if (typeof LogConsole !== 'undefined')
        LogConsole.log('⚠ Click a person first (People, Storage or Person History) — then click the badge to assign it', 'warn');
      return;
    }
    if (this.idsFor(this.person).indexOf(id) >= 0) this.unassign(this.person, id);
    else this.assignTo(this.person, id);
  },

  flashNoTarget() {
    const flash = (el, cls) => {
      if (!el || !el.classList) return;
      el.classList.remove(cls);
      void el.offsetWidth;
      el.classList.add(cls);
    };
    const host = this._els.active;
    flash(host && host.closest ? host.closest('.label-section') : null, 'label-section-flash');
    flash(this._els.target, 'flash');
  },

  assignTo(nick, id) {
    const bridge = this._bridge('label_assign');
    if (bridge) bridge.label_assign(String(nick || ''), id);
  },

  unassign(nick, id) {
    const bridge = this._bridge('label_unassign');
    if (bridge) bridge.label_unassign(String(nick || ''), id);
  },

  setLabelsOf(nick, ids) {
    const bridge = this._bridge('label_set_for');
    if (bridge) bridge.label_set_for(String(nick || ''), JSON.stringify(ids || []));
  },
};

if (typeof window !== 'undefined') window.LabelsAssign = LabelsAssign;
