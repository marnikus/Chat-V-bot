/* app-history.js — the one global undo/redo timeline (App part, Round H)

   Owns the chronological history shared by the action stack, the sash
   grid, the people list, labels, the archive and the DB connection.
   The backend is the authoritative store; this mirror keeps the UI
   responsive and drives the undo/redo buttons.

   Part pattern: members bind onto the App facade
   (UIHelpers.mergeParts in app.js), so `this` is App and the shared
   state (globalHistory, globalHistoryIndex, bridge) lives on the host.
   Loaded before the facade — see ui/index.html.
   */
'use strict';

const AppHistory = {
  _copy(value) {
    try { return JSON.parse(JSON.stringify(value)); }
    catch (e) { return value; }
  },

  loadGlobalHistory(state) {
    state = state || {};
    let history = Array.isArray(state.undo_history) ? state.undo_history : [];
    if (!history.length && Array.isArray(state.stack_history)) {
      history = state.stack_history.map((value) => ({ kind: 'stack', value }));
      if (state.grid_layout) history.push({ kind: 'grid', value: state.grid_layout });
    }
    this.globalHistory = history.filter((entry) =>
      entry && (entry.kind === 'stack' || entry.kind === 'grid' ||
                entry.kind === 'people'))
      .map((entry) => ({ kind: entry.kind, value: this._copy(entry.value) }));
    const idx = Number.isInteger(state.undo_history_index)
      ? state.undo_history_index
      : this.globalHistory.length - 1;
    this.globalHistoryIndex = Math.max(-1,
      Math.min(idx, this.globalHistory.length - 1));
    this._updateUndoButtons();
  },

  _same(a, b) {
    try { return JSON.stringify(a) === JSON.stringify(b); }
    catch (e) { return a === b; }
  },

  recordGlobal(kind, value, options) {
    options = options || {};
    const entry = { kind, value: this._copy(value) };
    const current = this.globalHistory[this.globalHistoryIndex];
    if (current && this._same(current, entry)) return;
    if (this.globalHistoryIndex < this.globalHistory.length - 1) {
      this.globalHistory = this.globalHistory.slice(0, this.globalHistoryIndex + 1);
    }
    this.globalHistory.push(entry);
    this.globalHistoryIndex = this.globalHistory.length - 1;
    if (this.globalHistory.length > 100) {
      this.globalHistory.splice(0, this.globalHistory.length - 100);
      this.globalHistoryIndex = this.globalHistory.length - 1;
    }
    this._updateUndoButtons();
    if (!options.localOnly && this.bridge && this.bridge.push_global_history) {
      try { this.bridge.push_global_history(kind, JSON.stringify(value)); }
      catch (e) { /* local history still keeps the UI responsive */ }
    }
  },

  /** Entry kinds the local mirror understands (the backend owns the list). */
  UNDO_KINDS: ['stack', 'grid', 'people', 'labels', 'archive', 'dbconn'],

  _peopleRowsOf(value) {
    // People entries carry {"before": rows, "after": rows}; undo/redo return
    // the matching half. A bare array is accepted too (defensive).
    if (Array.isArray(value)) return value;
    if (value && Array.isArray(value.after)) return value.after;
    return null;
  },

  _applyGlobalResult(raw) {
    if (!raw || raw === 'null') return false;
    let result;
    try { result = JSON.parse(raw); } catch (e) { return false; }
    if (!result || !result.kind) return false;
    if (Number.isInteger(result.index)) this.globalHistoryIndex = result.index;
    else if (result.kind) {
      // Old bridges did not return an index.
      this.globalHistoryIndex = Math.max(-1, this.globalHistoryIndex - 1);
    }
    this._applyGlobalKind(result);
    this._updateUndoButtons();
    return true;
  },

  _applyGlobalKind(result) {
    if (result.kind === 'stack' && typeof StackDnD !== 'undefined') {
      StackDnD._isRestoringHistory = true;
      StackDnD.setStack(result.value, { silent: true });
      StackDnD._isRestoringHistory = false;
    } else if (result.kind === 'grid' && typeof SashGrid !== 'undefined') {
      SashGrid._applySerialized(result.value, false);
    } else if (result.kind === 'people' && typeof UserTable !== 'undefined') {
      const rows = this._peopleRowsOf(result.value);
      if (rows) {
        UserTable.render(rows);
        // The backend applies the snapshot asynchronously and re-emits
        // users_updated + stats_updated; a refresh keeps every panel in sync.
        if (this.bridge && this.bridge.refresh_users) this.bridge.refresh_users();
      }
    } else if (result.kind === 'labels' && typeof Labels !== 'undefined') {
      // The backend already re-emitted labels_changed; refreshing keeps the
      // pills right even if that signal was missed.
      Labels.refresh();
    } else if (result.kind === 'archive') {
      if (typeof HistoryDb !== 'undefined') HistoryDb.onChanged();
      if (typeof HistoryStore !== 'undefined' && HistoryStore.reloadCurrent)
        HistoryStore.reloadCurrent();
      if (this.bridge && this.bridge.refresh_users) this.bridge.refresh_users();
    } else if (result.kind === 'dbconn' && typeof DbPanel !== 'undefined') {
      DbPanel.onChanged('{}');
    }
  },

  /** Re-sync the local history mirror from the backend's authoritative
      timeline (the backend records people-list edits itself). */
  _syncGlobalHistory() {
    if (!this.bridge || !this.bridge.get_undo_history) return;
    this.bridge.get_undo_history((json) => {
      try {
        const state = JSON.parse(json);
        if (state && Array.isArray(state.history)) {
          this.globalHistory = state.history
            .filter((e) => e && App.UNDO_KINDS.indexOf(e.kind) >= 0)
            .map((e) => ({ kind: e.kind, value: this._copy(e.value) }));
          this.globalHistoryIndex = Number.isInteger(state.index)
            ? state.index : this.globalHistory.length - 1;
          this._updateUndoButtons();
        }
      } catch (e) { /* ignore */ }
    });
  },

  undoGlobal() {
    if (!this.bridge || !this.bridge.undo) return false;
    this.bridge.undo((raw) => {
      if (!this._applyGlobalResult(raw)) LogConsole.log('⚠ Nothing to undo', 'warn');
    });
    return true;
  },

  redoGlobal() {
    if (!this.bridge || !this.bridge.redo) return false;
    this.bridge.redo((raw) => {
      if (!raw || raw === 'null') LogConsole.log('⚠ Nothing to redo', 'warn');
      else this._applyGlobalResult(raw);
    });
    return true;
  },

  _updateUndoButtons() {
    const undo = document.getElementById('undoBtn');
    const redo = document.getElementById('redoBtn');
    const canUndo = this.globalHistoryIndex > 0;
    // Redo is available whenever an entry exists past the pointer. Index -1
    // (e.g. after undoing a sole people-list edit) still has entry 0 to
    // re-apply, so it must count.
    const canRedo = this.globalHistory.length > 0 &&
                    this.globalHistoryIndex < this.globalHistory.length - 1;
    if (undo) {
      undo.disabled = !canUndo;
      undo.title = canUndo ? 'Undo (Ctrl+Z) — global history' : 'Nothing to undo';
    }
    if (redo) {
      redo.disabled = !canRedo;
      redo.title = canRedo ? 'Redo (Ctrl+Y) — global history' : 'Nothing to redo';
    }
  },
};
