/* labels-model.js — model helpers and state for Labels facade (H-B2b JS split)

State + pure model: defs, assign, filterRule, palette, selected, person,
draftColor, editing, plus byId, idsFor, forNick, filterActive, allows,
roleOf, countFor, knownNicks, _badgeTitle.

Design: docs/archive/2026-09-14-round-h/AREA_H_FINAL_VALIDATION_2026-09-14.md §6.4
*/

'use strict';

const LabelsModel = {
  defs: [],
  assign: {},
  filterRule: { include: [], exclude: [] },
  palette: [],
  selected: new Set(),
  person: '',
  draftColor: '',
  editing: '',
  editName: '',
  editColor: '',

  byId(id) { return this.defs.find((d) => d.id === id) || null; },

  idsFor(nick) {
    const ids = this.assign[String(nick == null ? '' : nick).trim()];
    return Array.isArray(ids) ? ids : [];
  },

  forNick(nick) {
    return this.idsFor(nick).map((id) => this.byId(id)).filter(Boolean);
  },

  get filterActive() {
    return !!(this.filterRule.include.length || this.filterRule.exclude.length);
  },

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

  countFor(id) {
    let n = 0;
    Object.keys(this.assign).forEach((nick) => {
      if ((this.assign[nick] || []).indexOf(id) >= 0) n++;
    });
    return n;
  },

  knownNicks() {
    const set = new Set(Object.keys(this.assign));
    if (typeof UserTable !== 'undefined' && Array.isArray(UserTable.users))
      UserTable.users.forEach((u) => { if (u && u.nick) set.add(u.nick); });
    if (typeof HistoryDb !== 'undefined' && Array.isArray(HistoryDb.rows))
      HistoryDb.rows.forEach((p) => { if (p && p.nick) set.add(p.nick); });
    return Array.from(set).sort((a, b) =>
      String(a).localeCompare(String(b), undefined, { sensitivity: 'base' }));
  },

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
};

if (typeof window !== 'undefined') window.LabelsModel = LabelsModel;
