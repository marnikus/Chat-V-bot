/* stack-dnd part — stack-dnd-history.js (Round H, H-A4)

   Three collaborating objects (H-A6, RULE 16 object cap):
     StackDnDMigration     block/stack normalization (retired keys, defaults)
     StackDnDHistory       the history state machine (push / undo / redo)
     StackDnDHistoryUI     button wiring, button paint, state restore
   All merge onto the StackDnD facade — see ui/js/stack-dnd.js.
   */

const StackDnDMigration = {
  _deepCopy(obj) {
    try {
      return JSON.parse(JSON.stringify(obj));
    } catch (e) {
      // fallback shallow
      if (Array.isArray(obj)) return obj.map(x => ({...x}));
      return {...obj};
    }
  },

  // One migration chokepoint for raw block dicts (session restore, preset
  // load, undo/redo, backend pushes, add-menu). It (a) strips retired keys
  // so dead controls never render, (b) back-fills settings added after the
  // block was saved from the block's current BUILTIN_BLOCKS defaults (e.g.
  // scroll_only / purge_rejected missing on old stacks), and (c) normalises
  // enabled. Unknown keys (CUSTOM_FIND fields) are preserved.,

  _normalizeBlock(b) {
    return this._migrateBlock(b);
  },

  _normalizeStack(stack) {
    if (!Array.isArray(stack)) return [];
    return stack.map(b => this._normalizeBlock(b)).filter(Boolean);
  },

  _stacksEqual(a, b) {
    try {
      return JSON.stringify(a) === JSON.stringify(b);
    } catch (e) {
      return false;
    }
  },

  _initDefaultStack() {
    // Built from BUILTIN_BLOCKS defaults (via migration) so every block —
    // including Scroll & Parse — starts with its full, current set of
    // settings (filters, scroll_only, etc.).
    this.stack = this._normalizeStack([
      { block_id:'CLICK_MAIN_TAB', pre_delay_ms:500, tab_name:'Гостиная' },
      { block_id:'SCROLL_PARSE',   pre_delay_ms:300, max_scrolls:50 },
      { block_id:'CONDITIONAL_SKIP',pre_delay_ms:0 },
      { block_id:'CLICK_USER',     pre_delay_ms:1000 },
      { block_id:'WAIT_PAGE_LOAD', pre_delay_ms:200, timeout_ms:5000 },
      { block_id:'TYPE_MESSAGE',   pre_delay_ms:500, message:'' },
      { block_id:'CLICK_SEND',     pre_delay_ms:300 },
      { block_id:'CLICK_BACK',     pre_delay_ms:800, tab_name:'Гостиная' },
    ]);
  },

  // ── History helpers ──────────────────────────────────────────,

  _getCurrentHistoryStack() {
    if (this.historyIndex >=0 && this.historyIndex < this.history.length) {
      return this.history[this.historyIndex];
    }
    return null;
  },
};


const StackDnDHistory = {
  pushHistory(stack, opts) {
    opts = opts || {};
    if (this._isRestoringHistory || this._restoring) return;
    if (this._running) return;
    const normalized = this._normalizeStack(stack || this.stack);
    if (this._historyTipEquals(normalized) && !opts.force) return;
    this._truncateHistoryFuture();
    this.history.push(this._deepCopy(normalized));
    this.historyIndex = this.history.length - 1;
    this._enforceMaxHistory();
    this.updateHistoryButtons();
    // StackDnD keeps a projection for compatibility, but App owns the only
    // undo timeline shared with sash-grid.
    if (typeof App !== 'undefined' && App.recordGlobal)
      App.recordGlobal('stack', normalized);
  },

  _historyTipEquals(normalized) {
    const current = this._getCurrentHistoryStack();
    return !!(current && this._stacksEqual(current, normalized));
  },

  _truncateHistoryFuture() {
    if (this.historyIndex < this.history.length - 1) {
      this.history = this.history.slice(0, this.historyIndex + 1);
    }
  },

  _enforceMaxHistory() {
    if (this.history.length > this.MAX_HISTORY) {
      const overflow = this.history.length - this.MAX_HISTORY;
      this.history = this.history.slice(overflow);
      this.historyIndex = Math.max(0, this.historyIndex - overflow);
    }
  },

  canUndo() {
    return this.historyIndex > 0;
  },

  canRedo() {
    return this.historyIndex >=0 && this.historyIndex < this.history.length - 1;
  },

  undo() {
    if (typeof App !== 'undefined' && App.undoGlobal && App.bridge) {
      return App.undoGlobal();
    }
    if (!this.canUndo()) {
      if (typeof LogConsole !== 'undefined') LogConsole.log('⚠ Nothing to undo', 'warn');
      return false;
    }
    this.historyIndex--;
    const prevStack = this._deepCopy(this.history[this.historyIndex]);
    this._isRestoringHistory = true;
    this.setStack(prevStack, {isHistory:true, silent:false});
    this._isRestoringHistory = false;
    this.updateHistoryButtons();
    this.saveHistoryToBackend();
    if (typeof LogConsole !== 'undefined') {
      LogConsole.log(`↩ Undo — restored ${prevStack.length} block(s) (${this.historyIndex+1}/${this.history.length})`, 'info');
    }
    // also tell backend to set last_stack and index
    if (App.bridge) {
      App.bridge.save_stack_history(JSON.stringify(this.history), this.historyIndex);
      App.bridge.snapshot_stack(JSON.stringify(prevStack));
    }
    return true;
  },

  redo() {
    if (typeof App !== 'undefined' && App.redoGlobal && App.bridge) {
      return App.redoGlobal();
    }
    if (!this.canRedo()) {
      if (typeof LogConsole !== 'undefined') LogConsole.log('⚠ Nothing to redo', 'warn');
      return false;
    }
    this.historyIndex++;
    const nextStack = this._deepCopy(this.history[this.historyIndex]);
    this._isRestoringHistory = true;
    this.setStack(nextStack, {isHistory:true, silent:false});
    this._isRestoringHistory = false;
    this.updateHistoryButtons();
    this.saveHistoryToBackend();
    if (typeof LogConsole !== 'undefined') {
      LogConsole.log(`↪ Redo — restored ${nextStack.length} block(s) (${this.historyIndex+1}/${this.history.length})`, 'info');
    }
    if (App.bridge) {
      App.bridge.save_stack_history(JSON.stringify(this.history), this.historyIndex);
      App.bridge.snapshot_stack(JSON.stringify(nextStack));
    }
    return true;
  },

  saveHistoryToBackend() {
    // Retained as a no-op compatibility hook. App.recordGlobal() persists
    // every stack edit in the single global history immediately.
  },
};


const StackDnDHistoryUI = {
  updateHistoryButtons() {
    if (typeof App !== 'undefined' && App._updateUndoButtons) {
      App._updateUndoButtons();
      return;
    }
    const undoBtn = document.getElementById('undoBtn');
    const redoBtn = document.getElementById('redoBtn');
    if (undoBtn) {
      undoBtn.disabled = !this.canUndo();
      undoBtn.title = this.canUndo() ? `Undo (Ctrl+Z) — ${this.historyIndex}/${this.history.length-1} steps` : 'Nothing to undo';
    }
    if (redoBtn) {
      redoBtn.disabled = !this.canRedo();
      redoBtn.title = this.canRedo() ? `Redo (Ctrl+Y) — ${this.historyIndex+1}/${this.history.length-1}` : 'Nothing to redo';
    }
  },

  loadHistoryFromState(state) {
    if (!state) return;
    let hist = state.stack_history;
    let idx = state.stack_history_index;
    if (Array.isArray(hist) && hist.length) {
      // normalize each stack
      this.history = hist.map(s => this._normalizeStack(s));
      this.historyIndex = typeof idx === 'number' ? idx : this.history.length - 1;
      // clamp
      if (this.historyIndex < 0) this.historyIndex = 0;
      if (this.historyIndex >= this.history.length) this.historyIndex = this.history.length - 1;
      this.updateHistoryButtons();
      // console.log(`[History] loaded from state: ${this.history.length} entries, idx ${this.historyIndex}`);
    } else {
      // if no history but we have last_stack, seed history with it
      const lastStack = state.last_stack;
      if (Array.isArray(lastStack) && lastStack.length) {
        const norm = this._normalizeStack(lastStack);
        this.history = [this._deepCopy(norm)];
        this.historyIndex = 0;
        this.updateHistoryButtons();
        this.saveHistoryToBackend();
      }
    }
  },

  _setupHistoryButtons() {
    const undoBtn = document.getElementById('undoBtn');
    const redoBtn = document.getElementById('redoBtn');
    if (undoBtn) {
      undoBtn.addEventListener('click', () => App.undoGlobal());
    }
    if (redoBtn) {
      redoBtn.addEventListener('click', () => App.redoGlobal());
    }
  },
};
