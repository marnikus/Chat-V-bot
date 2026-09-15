/* db-panel-actions.js — create/load/remove/clean for DbPanel facade (H-B2b JS split)

Design: ≤150 LOC.
*/

'use strict';

const DbPanelActions = {
  create() {
    const input = this._els.nameInput; const name = input ? String(input.value || '').trim() : '';
    if (!name) { this.setStatus('Type a name for the new database first', true); if (input) input.focus(); return; }
    const bridge = this._bridge('db_create'); if (!bridge) return;
    this.busy = true; this.setStatus('Creating “' + name + '”…'); bridge.db_create(name); if (input) input.value = '';
  },

  load(path) {
    if (!path || path === this.activePath) return;
    const bridge = this._bridge('db_load'); if (!bridge) return;
    this.busy = true; this.setStatus('Connecting to ' + this.baseName(path) + '…'); bridge.db_load(path);
  },

  remove(path) {
    if (!path) return;
    const bridge = this._bridge('db_delete'); if (!bridge) return;
    const item = this.items.find((i) => i.path === path) || {};
    if (item.can_delete === false) { this.setStatus((item.delete_hint || 'Create a new database before deleting the last one') + '.', true); return; }
    window.Dialog.confirm('Delete database PERMANENTLY?', '“' + this.baseName(path) + '” is a complete world: its messages, people, labels, undo history and its images folder will be deleted for good. Nothing is copied anywhere and Ctrl+Z will NOT bring it back. Other databases are not touched.', 'Delete forever', () => { this.busy = true; this.setStatus('Permanently deleting ' + this.baseName(path) + '…'); bridge.db_delete(path); });
  },

  clean() {
    const bridge = this._bridge('db_clean'); if (!bridge) return;
    const name = this.baseName(this.activePath) || 'the current database';
    window.Dialog.confirm('Clean database?', 'Every message, person, queue entry and media record in “' + name + '” is removed. A full backup goes to db_trash first (along with the world’s images folder), so Ctrl+Z restores everything.', 'Clean', () => { this.busy = true; this.setStatus('Cleaning ' + name + '…'); bridge.db_clean(); });
  },
};

if (typeof window !== 'undefined') window.DbPanelActions = DbPanelActions;
