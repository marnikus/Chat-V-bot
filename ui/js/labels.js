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
        this.person = e.target.value || '';
        this.renderAssign();
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

  /** One compact rounded pill: bright translucent background + ✕. */
  pill(label, nick, options) {
    options = options || {};
    const color = String((label && label.color) || '#8892a6');
    const pill = document.createElement('span');
    pill.className = 'label-pill';
    pill.dataset.labelId = String((label && label.id) || '');
    pill.style.background = this.tint(color, 0.22);
    pill.style.borderColor = color;
    pill.style.color = '#fff';
    pill.title = (label && label.name ? label.name : '') +
      (options.removable === false ? '' : ' — ✕ removes it from this person only');
    const dot = document.createElement('span');
    dot.className = 'label-pill-dot';
    dot.style.background = color;
    pill.appendChild(dot);
    const text = document.createElement('span');
    text.className = 'label-pill-text';
    text.textContent = (label && label.name) || '';
    pill.appendChild(text);
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

  recolor(id, anchor) {
    const label = this.byId(id);
    ColorPicker.open({
      anchor: anchor,
      color: label ? label.color : '',
      title: 'Pick Color' + (label ? ' — ' + label.name : ''),
      onPick: (hex) => {
        const bridge = this._bridge('label_update');
        if (bridge) bridge.label_update(id, '', hex);
      },
    });
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

  /** The Label Manager follows whichever person the user is looking at. */
  setPerson(nick, options) {
    const clean = String(nick == null ? '' : nick).trim();
    if (!clean || clean === this.person) {
      if (clean) this.renderAssign();
      return;
    }
    this.person = clean;
    this.renderAssign();
    if (options && options.focus && typeof SashGrid !== 'undefined' &&
        SashGrid.openWindow) {
      SashGrid.openWindow('labels');
    }
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
  },

  _notice(text) {
    const note = document.createElement('div');
    note.className = 'label-notice';
    note.textContent = text;
    return note;
  },

  renderActive() {
    const host = this._els.active;
    if (!host) return;
    const nodes = [];
    if (!this.defs.length) {
      nodes.push(this._notice(
        'No labels yet — type a name below, pick a colour and press “+ Add Label”.'));
    }
    this.defs.forEach((label) => {
      const wrap = document.createElement('span');
      wrap.className = 'label-manage-item';
      const pill = this.pill(label, '', { removable: false });
      pill.title = label.name + ' — click the dot to recolour';
      pill.addEventListener('click', () => this.recolor(label.id, pill));
      wrap.appendChild(pill);
      const count = this.countFor(label.id);
      const badge = document.createElement('span');
      badge.className = 'label-count';
      badge.textContent = count ? String(count) : '0';
      badge.title = count + ' person(s) carry this label';
      wrap.appendChild(badge);
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
        ? 'Assigning to “' + this.person + '” — tick the labels, then press Assign'
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
