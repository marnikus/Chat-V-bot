/* ═══════════════════════════════════════════════════════════════
   labels.js — person labels: model, pills, and the Label Manager window

   Labels are custom coloured tags the user attaches to a person
   ("Rude", "Ignoring", "Short answering", …). They live in config.json
   (one store, joined to a row by nick at read time) and show up as small
   pills next to the nick in BOTH tables — People (User Memory) and
   Storage (Full User Database) — rendered by the ONE renderer below so
   the two can never drift apart.

   Every mutation goes through the bridge, which records it as a single
   entry of the global undo timeline (Ctrl+Z reverses it).

   Nodes are created with createElement/textContent only: a label name is
   user text and must never become markup.
   ═══════════════════════════════════════════════════════════════ */

'use strict';

const Labels = {
  defs: [],
  assign: {},                       // nick -> [label id]
  filterRule: { include: [], exclude: [] },
  palette: [],
  selected: new Set(),              // ticked labels in the filter section
  person: '',                       // the person section 4 works on
  draftColor: '',
  editing: '',                      // label id currently open in the inline editor
  editName: '',                     // editor drafts (name / colour)
  editColor: '',
  _wired: false,
  _els: {},

  // ── bootstrap ───────────────────────────────────────────────
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
        // The dropdown is only a mirror — the quick-assign funnel is the
        // same one the table row clicks use, minus the window auto-open.
        this.setPerson(e.target.value || '', { focus: false });
      });
    }
    if (this._els.assignBtn)
      this._els.assignBtn.addEventListener('click', () => this.assignSelected());

    this.setDraftColor(this.draftColor || '#ff3b30');
    this.refresh();
  },

  /** Ask the backend for the authoritative state. */
  refresh() {
    if (typeof App === 'undefined' || !App.bridge || !App.bridge.get_labels) {
      this.render();
      return;
    }
    App.bridge.get_labels((json) => this.applyState(json));
  },

  /** Accept a JSON string or an object from get_labels / labels_changed. */
  applyState(payload) {
    let state = payload;
    if (typeof payload === 'string') {
      try { state = JSON.parse(payload); } catch (e) { state = null; }
    }
    if (!state || typeof state !== 'object') return;
    this.defs = Array.isArray(state.defs) ? state.defs : [];
    this.assign = (state.assign && typeof state.assign === 'object')
      ? state.assign : {};
    const rule = state.filter || {};
    this.filterRule = {
      include: Array.isArray(rule.include) ? rule.include.slice() : [],
      exclude: Array.isArray(rule.exclude) ? rule.exclude.slice() : [],
    };
    this.palette = Array.isArray(state.palette) ? state.palette : this.palette;
    // drop ticks for labels that no longer exist
    const live = new Set(this.defs.map((d) => d.id));
    Array.from(this.selected).forEach((id) => {
      if (!live.has(id)) this.selected.delete(id);
    });
    // and close the inline editor when its label disappeared
    if (this.editing && !live.has(this.editing)) this.editing = '';
    this.render();
    this.repaintTables();
  },

  // ── model helpers ───────────────────────────────────────────
  byId(id) { return this.defs.find((d) => d.id === id) || null; },

  idsFor(nick) {
    const ids = this.assign[String(nick == null ? '' : nick).trim()];
    return Array.isArray(ids) ? ids : [];
  },

  /** Full label objects of one person, assignment order preserved. */
  forNick(nick) {
    return this.idsFor(nick).map((id) => this.byId(id)).filter(Boolean);
  },

  get filterActive() {
    return !!(this.filterRule.include.length || this.filterRule.exclude.length);
  },

  /**
   * Mirror of LabelStore.allows(): exclusion always wins, a non-empty
   * include set is a whitelist, no filter = everybody passes.
   */
  allows(nick) {
    if (!this.filterActive) return true;
    const mine = new Set(this.idsFor(nick));
    if (this.filterRule.exclude.some((id) => mine.has(id))) return false;
    if (this.filterRule.include.length)
      return this.filterRule.include.some((id) => mine.has(id));
    return true;
  },

  roleOf(id) {
    if (this.filterRule.exclude.indexOf(id) >= 0) return 'exclude';
    if (this.filterRule.include.indexOf(id) >= 0) return 'include';
    return '';
  },

  // ── the shared pill renderer (People + Storage rows) ────────
  /**
   * A `<span class="label-pills">` with one pill per label of this person.
   * Each pill carries a ✕ that removes the label FROM THIS PERSON only —
   * deleting a label everywhere is the Label Manager's job.
   */
  pills(nick, options) {
    options = options || {};
    const host = document.createElement('span');
    host.className = 'label-pills';
    host.dataset.nick = String(nick == null ? '' : nick);
    const items = options.labels || this.forNick(nick);
    if (!items.length) {
      if (options.emptyText) {
        const empty = document.createElement('span');
        empty.className = 'label-empty';
        empty.textContent = options.emptyText;
        host.appendChild(empty);
      }
      return host;
    }
    items.forEach((label) => {
      host.appendChild(this.pill(label, nick, options));
    });
    return host;
  },

  /** One compact rounded pill: bright translucent background + ✕.
   *
   *  options.title    — full tooltip override (the Label Manager badge
   *                     explains the click action + how many people carry it)
   *  options.marked   — prepend a ✓ (the target person carries this label)
   *  options.assigned — stronger fill + colour ring, the "on" state of the
   *                     quick-assign toggle in the Label Manager
   */
  pill(label, nick, options) {
    options = options || {};
    const color = String((label && label.color) || '#8892a6');
    const pill = document.createElement('span');
    pill.className = 'label-pill';
    pill.dataset.labelId = String((label && label.id) || '');
    pill.style.background = this.tint(color, 0.22);
    pill.style.borderColor = color;
    pill.style.color = '#fff';
    pill.title = options.title || ((label && label.name ? label.name : '') +
      (options.removable === false ? '' : ' — ✕ removes it from this person only'));
    if (options.marked) {
      const check = document.createElement('span');
      check.className = 'label-pill-check';
      check.textContent = '✓';
      pill.appendChild(check);
    }
    const dot = document.createElement('span');
    dot.className = 'label-pill-dot';
    dot.style.background = color;
    pill.appendChild(dot);
    const text = document.createElement('span');
    text.className = 'label-pill-text';
    text.textContent = (label && label.name) || '';
    pill.appendChild(text);
    if (options.assigned) {
      pill.classList.add('assigned');
      pill.style.background = this.tint(color, 0.42);
      pill.style.boxShadow = '0 0 0 1.5px ' + color;
    }
    if (options.removable !== false) {
      const x = document.createElement('button');
      x.type = 'button';
      x.className = 'label-pill-x';
      x.textContent = '✕';
      x.title = 'Remove “' + ((label && label.name) || '') + '” from ' +
        (nick || 'this person');
      x.addEventListener('click', (event) => {
        if (event && event.stopPropagation) event.stopPropagation();
        if (event && event.preventDefault) event.preventDefault();
        if (typeof options.onRemove === 'function')
          options.onRemove(label.id, nick);
        else this.unassign(nick, label.id);
      });
      pill.appendChild(x);
    }
    return pill;
  },

  /** '#rrggbb' → 'rgba(r,g,b,a)' so a pill stays readable on dark panels. */
  tint(hex, alpha) {
    const clean = String(hex || '').replace('#', '');
    const full = clean.length === 3
      ? clean.split('').map((c) => c + c).join('') : clean;
    const num = parseInt(full || '888888', 16);
    const r = (num >> 16) & 255, g = (num >> 8) & 255, b = num & 255;
    return 'rgba(' + r + ',' + g + ',' + b + ',' + (alpha == null ? 0.22 : alpha) + ')';
  },

  // ── mutations (each one is a single undo step) ──────────────
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
      if (typeof LogConsole !== 'undefined')
        LogConsole.log('⚠ Type a label name first', 'warn');
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

  // ── quick assign: badge click = assign to the current target ──
  /**
   * The badge click in Active Labels. With no target it only warns — the
   * chip and the section flash, nothing reaches the backend. With a target
   * it is a TOGGLE: a second click takes the label away again, so the
   * badge doubles as an instant undo (RULE 12 covers the backend entry).
   */
  toggleAssign(id) {
    if (!this.person) {
      this.flashNoTarget();
      if (typeof LogConsole !== 'undefined')
        LogConsole.log('⚠ Click a person first (People, Storage or Person ' +
          'History) — then click the badge to assign it', 'warn');
      return;
    }
    if (this.idsFor(this.person).indexOf(id) >= 0)
      this.unassign(this.person, id);
    else this.assignTo(this.person, id);
  },

  /** Draw the eye to the Active Labels section + the target chip. */
  flashNoTarget() {
    const flash = (el, cls) => {
      if (!el || !el.classList) return;
      el.classList.remove(cls);
      void el.offsetWidth;               // restart the animation
      el.classList.add(cls);
    };
    const host = this._els.active;
    flash(host && host.closest ? host.closest('.label-section') : null,
          'label-section-flash');
    flash(this._els.target, 'flash');
  },

  // ── inline editor (rename + recolour, inside Active Labels) ──
  startEdit(id) {
    const label = this.byId(id);
    if (!label) return;
    this.editing = id;
    this.editName = label.name;
    this.editColor = label.color;
    this.renderActive();
    const input = this._els.active
      ? this._els.active.querySelector('.label-edit-input') : null;
    if (input) {
      if (typeof input.focus === 'function') input.focus();
      if (typeof input.select === 'function') input.select();
    }
  },

  cancelEdit() {
    this.editing = '';
    this.renderActive();
  },

  saveEdit() {
    const label = this.byId(this.editing);
    if (!label) { this.cancelEdit(); return; }
    const name = String(this.editName || '').trim();
    if (!name) {
      if (typeof LogConsole !== 'undefined')
        LogConsole.log('⚠ A label needs a name', 'warn');
      return;
    }
    const color = String(this.editColor || '');
    const bridge = this._bridge('label_update');
    if (!bridge) { this.cancelEdit(); return; }
    // send only the fields that actually changed; '' = keep (backend rule)
    const nameChanged = name !== label.name ? name : '';
    const colorChanged = color && color !== label.color ? color : '';
    if (!nameChanged && !colorChanged) { this.cancelEdit(); return; }
    bridge.label_update(label.id, nameChanged, colorChanged);
    this.cancelEdit();
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
      if (allOn) target.delete(id);            // pressing again clears them
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

  setDraftColor(hex) {
    this.draftColor = hex || '#ff3b30';
    if (this._els.colorBtn) {
      this._els.colorBtn.style.background = this.draftColor;
      this._els.colorBtn.title = 'Label colour ' + this.draftColor +
        ' — click to pick another';
    }
  },

  /**
   * The single funnel for "this person is now the label target" — every
   * person click in the app (People row, Storage row, 🏷 buttons, the
   * Section 4 dropdown) ends up here. It
   *
   *   1. re-renders the manager (badge rings + target chip follow);
   *   2. opens the Label Manager window so the badge click can land —
   *      openWindow() never steals focus and is a no-op when already open;
   *   3. moves the target highlight in BOTH tables.
   *
   * options.focus === false skips the window open (Section 4 dropdown).
   */
  setPerson(nick, options) {
    options = options || {};
    const clean = String(nick == null ? '' : nick).trim();
    this.person = clean;
    this.renderAssign();
    this.renderActive();
    this.renderTarget();
    if (clean && options.focus !== false && typeof SashGrid !== 'undefined' &&
        SashGrid.openWindow) {
      SashGrid.openWindow('labels');
    }
    if (typeof UserTable !== 'undefined' && UserTable.markLabelTarget)
      UserTable.markLabelTarget(clean);
    if (typeof HistoryDb !== 'undefined' && HistoryDb.markLabelTarget)
      HistoryDb.markLabelTarget(clean);
  },

  assignSelected() {
    if (!this.person) {
      if (typeof LogConsole !== 'undefined')
        LogConsole.log('⚠ Choose a person first', 'warn');
      return;
    }
    const host = this._els.assignList;
    if (!host) return;
    const ids = Array.from(host.querySelectorAll('input[type="checkbox"]'))
      .filter((cb) => cb.checked).map((cb) => cb.value);
    this.setLabelsOf(this.person, ids);
  },

  // ── rendering ───────────────────────────────────────────────
  render() {
    this.renderActive();
    this.renderFilter();
    this.renderAssign();
    this.renderTarget();
  },

  _notice(text) {
    const note = document.createElement('div');
    note.className = 'label-notice';
    note.textContent = text;
    return note;
  },

  /**
   * Active Labels — one entry per label with THREE separate click zones
   * (visual spec): the badge ASSIGNS to the current person, the small
   * "edit" text opens the inline editor, the ✕ deletes the label
   * everywhere. No listener sits on the wrapper, so the zones can never
   * bleed into each other.
   */
  renderActive() {
    const host = this._els.active;
    if (!host) return;
    const nodes = [];
    if (!this.defs.length) {
      nodes.push(this._notice(
        'No labels yet — type a name below, pick a colour and press “+ Add Label”.'));
    }
    this.defs.forEach((label) => {
      if (this.editing === label.id) {
        nodes.push(this._editRow(label));
        return;
      }
      const assigned = !!this.person &&
        this.idsFor(this.person).indexOf(label.id) >= 0;

      const wrap = document.createElement('span');
      wrap.className = 'label-manage-item';
      if (assigned) wrap.classList.add('assigned');

      // Zone 1 — the badge: click = assign (or take away) on the target.
      const pill = this.pill(label, '', {
        removable: false,
        title: this._badgeTitle(label),
        marked: assigned,
        assigned: assigned,
      });
      pill.classList.add('label-manage-badge');
      pill.setAttribute('role', 'button');
      pill.setAttribute('tabindex', '0');
      pill.addEventListener('click', () => this.toggleAssign(label.id));
      pill.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          if (e.preventDefault) e.preventDefault();
          this.toggleAssign(label.id);
        }
      });
      wrap.appendChild(pill);

      // Zone 2 — "edit": rename / recolour in place.
      const edit = document.createElement('button');
      edit.type = 'button';
      edit.className = 'label-manage-edit';
      edit.textContent = 'edit';
      edit.title = 'Rename or recolour “' + label.name + '” — ' +
        this.countFor(label.id) + ' person(s) carry this label';
      edit.addEventListener('click', () => this.startEdit(label.id));
      wrap.appendChild(edit);

      // Zone 3 — ✕: delete from the whole system.
      const del = document.createElement('button');
      del.type = 'button';
      del.className = 'label-del';
      del.textContent = '✕';
      del.title = 'Delete “' + label.name +
        '” from the whole system (and from every person)';
      del.addEventListener('click', () => this.deleteLabel(label.id));
      wrap.appendChild(del);

      nodes.push(wrap);
    });
    host.replaceChildren.apply(host, nodes);
  },

  /** Badge tooltip: what the click will do + how many people carry it. */
  _badgeTitle(label) {
    const n = this.countFor(label.id);
    const count = (n ? n : 'No') + ' person(s) carry “' + label.name + '”.';
    if (!this.person)
      return 'Click a person in People first — then click this badge to ' +
        'assign “' + label.name + '”. ' + count;
    return this.idsFor(this.person).indexOf(label.id) >= 0
      ? '✓ assigned to ' + this.person + ' — click to take “' +
        label.name + '” away. ' + count
      : 'Click to assign “' + label.name + '” to ' + this.person + '. ' + count;
  },

  /** The inline editor that replaces a label entry while it is edited. */
  _editRow(label) {
    const row = document.createElement('span');
    row.className = 'label-edit-row';

    const input = document.createElement('input');
    input.type = 'text';
    input.className = 'label-edit-input';
    input.value = this.editName || label.name;
    input.spellcheck = false;
    input.maxLength = 40;
    input.title = 'Rename this label — Enter saves, Escape cancels';
    input.addEventListener('input', () => { this.editName = input.value; });
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        if (e.preventDefault) e.preventDefault();
        this.saveEdit();
      } else if (e.key === 'Escape') {
        if (e.preventDefault) e.preventDefault();
        this.cancelEdit();
      }
    });
    row.appendChild(input);

    const colorBtn = document.createElement('button');
    colorBtn.type = 'button';
    colorBtn.className = 'label-edit-color';
    colorBtn.style.background = this.editColor || label.color;
    colorBtn.title = 'Change the label colour';
    colorBtn.addEventListener('click', () => {
      ColorPicker.open({
        anchor: colorBtn,
        color: this.editColor || label.color,
        title: 'Pick Color — ' + label.name,
        onPick: (hex) => {
          this.editColor = hex;
          colorBtn.style.background = hex;
        },
      });
    });
    row.appendChild(colorBtn);

    const save = document.createElement('button');
    save.type = 'button';
    save.className = 'btn-small btn-primary label-edit-save';
    save.textContent = 'Save';
    save.title = 'Save the new name and colour';
    save.addEventListener('click', () => this.saveEdit());
    row.appendChild(save);

    const cancel = document.createElement('button');
    cancel.type = 'button';
    cancel.className = 'btn-small label-edit-cancel';
    cancel.textContent = 'Cancel';
    cancel.title = 'Discard the changes';
    cancel.addEventListener('click', () => this.cancelEdit());
    row.appendChild(cancel);

    return row;
  },

  /** The chip in the Active Labels title: who a badge click lands on. */
  renderTarget() {
    const chip = this._els.target;
    if (!chip) return;
    if (this.person) {
      chip.textContent = '🎯 ' + this.person;
      chip.classList.add('on');
      chip.title = 'Every badge below assigns to “' + this.person +
        '” — click again to take the label away';
    } else {
      chip.textContent = 'click a person to quick-assign';
      chip.classList.remove('on');
      chip.title = 'Click a person in People, Storage or Person History — ' +
        'then click a badge to assign it';
    }
  },

  countFor(id) {
    let n = 0;
    Object.keys(this.assign).forEach((nick) => {
      if ((this.assign[nick] || []).indexOf(id) >= 0) n++;
    });
    return n;
  },

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
      this._els.includeBtn.classList.toggle('active',
                                            !!this.filterRule.include.length);
    if (this._els.excludeBtn)
      this._els.excludeBtn.classList.toggle('active',
                                            !!this.filterRule.exclude.length);
    if (this._els.filterState) {
      const names = (ids) => ids.map((id) => (this.byId(id) || {}).name || id)
        .join(', ');
      const parts = [];
      if (this.filterRule.include.length)
        parts.push('only ' + names(this.filterRule.include));
      if (this.filterRule.exclude.length)
        parts.push('never ' + names(this.filterRule.exclude));
      this._els.filterState.textContent = parts.length
        ? 'Filter: ' + parts.join(' · ') +
          ' — applies to both tables and to the run queue'
        : 'No label filter — every person is shown and messaged';
      this._els.filterState.classList.toggle('on', parts.length > 0);
    }
  },

  /** Section 4 — the dropdown follows the currently selected person. */
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
        opt.textContent = nick + (mine.length
          ? '  [' + mine.map((l) => l.name).join(', ') + ']' : '');
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
        nodes.push(this._notice(
          'Click a nick in People, Storage or Person History — the person ' +
          'appears here with the labels they already carry.'));
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
        ? 'Target: “' + this.person + '” — click a badge above, or tick ' +
          'below and press Assign'
        : 'No person selected';
    }
    if (this._els.assignBtn) this._els.assignBtn.disabled = !this.person;
  },

  /** Nicks we know about: everyone in the People table + everyone labelled. */
  knownNicks() {
    const set = new Set(Object.keys(this.assign));
    if (typeof UserTable !== 'undefined' && Array.isArray(UserTable.users))
      UserTable.users.forEach((u) => { if (u && u.nick) set.add(u.nick); });
    if (typeof HistoryDb !== 'undefined' && Array.isArray(HistoryDb.rows))
      HistoryDb.rows.forEach((p) => { if (p && p.nick) set.add(p.nick); });
    return Array.from(set).sort((a, b) =>
      String(a).localeCompare(String(b), undefined, { sensitivity: 'base' }));
  },

  /** Redraw whatever shows pills after the label state changed. */
  repaintTables() {
    if (typeof UserTable !== 'undefined' && UserTable.render)
      UserTable.render(UserTable.users);
    if (typeof HistoryDb !== 'undefined' && HistoryDb.render)
      HistoryDb.render();
    if (typeof HistoryStore !== 'undefined' && HistoryStore.renderHeader)
      HistoryStore.renderHeader();
  },
};

if (typeof window !== 'undefined') window.Labels = Labels;
if (typeof module === 'object' && module.exports) module.exports = Labels;
