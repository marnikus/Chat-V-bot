/* stack-dnd part — stack-dnd-config.js (Round H, H-A4) */

const StackDnDConfig = {
  _loadConfigPin() {
    let pinned = false;
    try {
      pinned = String(localStorage.getItem(this.CONFIG_PIN_STORAGE_KEY)) === '1';
    } catch (e) { /* storage unavailable -> default unpinned */ }
    this.configPinned = pinned;
  },

  _applyConfigPin(pinned) {
    this.configPinned = !!pinned;
    this._updateConfigPinButton();
    this._updateConfigVisibility(this.stack[this.selectedIdx]);
  },

  applyConfigPin(pinned) {
    this._applyConfigPin(pinned);
  },

  _persistConfigPin() {
    try {
      localStorage.setItem(this.CONFIG_PIN_STORAGE_KEY,
                           this.configPinned ? '1' : '0');
    } catch (e) { /* storage unavailable -> backend still persists it */ }
    try {
      if (typeof App !== 'undefined' && App.bridge &&
          typeof App.bridge.set_block_config_pinned === 'function') {
        App.bridge.set_block_config_pinned(this.configPinned);
      }
    } catch (e) { /* backend absent -> localStorage copy stands */ }
  },

  flushPersistence() {
    this._persistConfigPin();
  },

  _setupConfigPin() {
    const btn = document.getElementById('pinConfigBtn');
    if (btn) {
      btn.onclick = (ev) => {
        if (ev) { ev.stopPropagation(); ev.preventDefault(); }
        this._toggleConfigPin();
        if (typeof LogConsole !== 'undefined') {
          LogConsole.log(this.configPinned
            ? '📌 Block Config pinned — stays open when no block is selected'
            : '📌 Block Config unpinned — closes when no block is selected',
            'info');
        }
      };
    }
    this._wireConfigCloseButton();
  },

  _wireConfigCloseButton() {
    // The close button is also wired here (not only inside _showConfig) so it
    // works in every state, including a pinned-but-empty panel that was never
    // populated by a block.
    const closeBtn = document.getElementById('closeConfigBtn');
    if (closeBtn) closeBtn.onclick = this._configCloseHandler();
  },

  _configCloseHandler() {
    return () => {
      // Explicit close always wins: unpin too, so the next deselect returns
      // to the default close-on-deselect behaviour.
      this.configPinned = false;
      this._updateConfigPinButton();
      this._updateConfigVisibility(null);
      if (typeof SashGrid !== 'undefined' && SashGrid.closeWindow) {
        SashGrid.closeWindow('config');
      }
    };
  },

  _toggleConfigPin() {
    this.configPinned = !this.configPinned;
    this._updateConfigPinButton();
    this._persistConfigPin();
    // Apply immediately: pinning an empty panel keeps it visible, unpinning
    // an empty panel restores the default close-on-deselect behaviour.
    this._updateConfigVisibility(this.stack[this.selectedIdx]);
  },

  _updateConfigPinButton() {
    const btn = document.getElementById('pinConfigBtn');
    if (!btn) return;
    btn.classList.toggle('pin-active', this.configPinned);
    btn.setAttribute('aria-pressed', this.configPinned ? 'true' : 'false');
    btn.title = this.configPinned
      ? 'Unpin Block Config — close when no block is selected'
      : 'Pin Block Config — keep open when no block is selected';
    const icon = btn.querySelector('.material-icons');
    if (icon) icon.textContent = 'push_pin';
  },

  _clearConfigPanel() {
    const form = document.getElementById('blockConfigForm');
    if (form) form.innerHTML = '';
    const actions = document.getElementById('customBlockActions');
    if (actions) actions.classList.add('hidden');
  },

  _updateConfigVisibility(block) {
    const panel = document.getElementById('blockConfigPanel');
    if (!panel) return;
    const hasBlock = !!block;
    if (this.configPinned || hasBlock) {
      panel.classList.remove('hidden');
      // If Block Config was closed via the generic window close, selecting a block should reopen it
      if (hasBlock && typeof SashGrid !== 'undefined' && SashGrid.isClosed && SashGrid.isClosed('config')) {
        if (SashGrid.openWindow) SashGrid.openWindow('config');
      }
    } else {
      panel.classList.add('hidden');
    }
    panel.classList.toggle('has-block', hasBlock);
    if (!hasBlock) this._clearConfigPanel();
    if (typeof SashGrid !== 'undefined' && typeof SashGrid._syncHidden === 'function') {
      SashGrid._syncHidden();
    }
  },
};
