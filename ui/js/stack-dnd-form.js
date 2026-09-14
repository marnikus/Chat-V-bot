/* stack-dnd part — stack-dnd-form.js (Round H, H-A4)

   Three collaborating objects (H-A6, RULE 16 object cap):
     StackDnDConfigForm    the config panel behaviour (open / wire / save)
     StackDnDConfigRows    the per-control row builders (pure HTML)
     StackDnDSpeed         Speed Multiplier rows + live preview controls
   All merge onto the StackDnD facade — see ui/js/stack-dnd.js.
   */

const StackDnDConfigForm = {
  _showConfig(idx) {
    const form = document.getElementById('blockConfigForm');
    const block = this.stack[idx];
    if (!block) {
      // No block selected: an unpinned panel closes; a pinned panel stays
      // open and shows the empty-state hint until a block is chosen.
      this._updateConfigVisibility(null);
      return;
    }
    // Marks the panel as populated so its empty-state hint hides.
    this._updateConfigVisibility(block);
    form.innerHTML = this._configBodyHtml(block, this._meta(block.block_id));
    this._wireConfigForm(form, block);
    if (block.block_id === 'SPEED_MULTIPLIER') {
      this._wireSpeedControls(form, block);
    }
    // Keep the close handler bound even when _showConfig is called without a
    // full init (defensive; the pin setup also binds it once at startup).
    const closeBtn = document.getElementById('closeConfigBtn');
    if (closeBtn) closeBtn.onclick = this._configCloseHandler();
    this._wireCustomBlockActions(block);
  },

  _configBodyHtml(block, meta) {
    let html = this._configHeadHtml(block, meta);
    if (block.block_id === 'CUSTOM_FIND') html += this._configConstructorHint();
    // Zebra counter for two-column field rows (even rows get a slightly
    // lighter tone so each label-value pair reads as one group). The header
    // row, the stacked CUSTOM_FIND constructor rows and the On/Off bar are
    // not striped — they keep their own distinct styling.
    let zebra = 0;
    for (const key of this._configKeys(block, meta)) {
      if (key === 'block_id') continue;
      // Never render retired controls (e.g. the old use_panel_filters
      // checkbox) even if a block somehow still carries the key.
      if (RETIRED_KEYS.includes(key)) continue;
      html += this._configRowHtml(key, block[key], block, meta, (zebra++) % 2);
    }
    return html;
  },

  _configKeys(block, meta) {
    const byKey = {};
    const entries = Object.keys(block);
    entries.forEach((k) => { byKey[k] = block[k]; });
    const order = meta.defaults ? Object.keys(meta.defaults) : [];
    const ordered = [];
    order.forEach((k) => { if (k in byKey && k !== 'block_id') ordered.push(k); });
    entries.forEach((k) => { if (k !== 'block_id' && !ordered.includes(k)) ordered.push(k); });
    return ordered;
  },

  _wireConfigForm(form, block) {
    // NOTE: must include select[data-key] and textarea[data-key] — the
    // tri-state filter dropdowns are <select> and the Type Message text is
    // a <textarea>; binding only inputs would silently drop their edits.
    form.querySelectorAll('input[data-key], select[data-key], textarea[data-key]').forEach(inp => {
      const handler = () => {
        const k = inp.dataset.key;
        if (inp.tagName === 'SELECT') block[k] = inp.value;
        else if (inp.type === 'checkbox') block[k] = inp.checked;
        else block[k] = inp.type === 'number' ? Number(inp.value) : inp.value;
        this._renderStack();
        this.pushHistory();
        this.notifyEdited();
        if (k === 'enabled') {
          const name = this._displayName(block);
          if (typeof LogConsole !== 'undefined') {
            LogConsole.log(block.enabled ? `✅ Enabled “${name}”` : `⏸ Disabled “${name}” — will be skipped`, block.enabled ? 'success' : 'warn');
          }
        }
        // “Use Message Composer” toggles the own-text field: re-render the
        // panel so the textarea follows (enabled/disabled).
        if (block.block_id === 'TYPE_MESSAGE' && k === 'use_composer') {
          this._showConfig(this.selectedIdx);
        }
      };
      inp.addEventListener('change', handler);
      // also listen to input for text to update summary live? but history on change only
    });
  },

  _wireCustomBlockActions(block) {
    const actions = document.getElementById('customBlockActions');
    if (block.block_id === 'CUSTOM_FIND' && App.bridge) {
      actions.classList.remove('hidden');
      const btn = document.getElementById('saveCustomBlockBtn');
      btn.onclick = () => this._saveBlockPreset(block);
      this._refreshSaveLabel();
    } else {
      actions.classList.add('hidden');
    }
  },
};

const StackDnDConfigRows = {
  _configHeadHtml(block, meta) {
    return `<div class="form-row form-row--head">
        <label>Block</label><span style="font-weight:600">${meta.icon || ''} ${this._esc(this._displayName(block))}</span>
      </div>`;
  },

  _configConstructorHint() {
    return `<p class="form-hint">Configurable search-and-click constructor:
        field ① finds the clickable element (the box / rectangle);
        field ② is the separate element inside it whose text confirms the
        match. Give it a name, then save it as a preset for reuse.</p>`;
  },

  // ── Row-builder table (H-A4) ─────────────────────────────────
  // One dispatcher, one row builder per control kind. Adding a new control
  // type = adding one builder + one line here — the giant per-key if-chain
  // that used to live inside _showConfig is gone.,

  _configRowHtml(key, val, block, meta, zebra) {
    const labelText = meta.labels[key] || key;
    const safeVal = String(val).replace(/"/g, '&quot;');
    const stripe = ` zebra-${zebra}`;
    // Block-specific custom rows carry extra controls the generic row
    // cannot: Speed Multiplier presets/preview, Type Message textarea.
    if (block.block_id === 'SPEED_MULTIPLIER' && key === 'multiplier') {
      return this._speedRowHtml(labelText, safeVal, block, stripe);
    }
    if (block.block_id === 'TYPE_MESSAGE' && key === 'message') {
      return this._messageRowHtml(labelText, val, block, stripe);
    }
    const radioOpts = (meta.radios && meta.radios[key]) || null;
    if (radioOpts) {
      return this._radioRowHtml(key, labelText, val, radioOpts, meta, stripe);
    }
    if (typeof val === 'boolean') {
      return this._checkboxRowHtml(key, labelText, val, stripe);
    }
    const choices = (meta.options && meta.options[key]) || null;
    if (choices) {
      return this._selectRowHtml(key, labelText, val, choices, stripe);
    }
    return this._inputRowHtml(key, labelText, val, stripe, block);
  },

  _speedRowHtml(labelText, safeVal, block, stripe) {
    // Speed Multiplier: stepped coefficient input, quick presets and a
    // live faster/slower preview (the generic number row cannot carry
    // buttons, hence the custom row — same as TYPE_MESSAGE above).
    return `<div class="form-row${stripe}">
      <label>${labelText}</label>
      <input data-key="multiplier" value="${safeVal}" type="number"
        step="0.1" min="0.1" max="10">
    </div>
    <div class="form-row">
      <label>Quick presets</label>
      <div class="speed-presets">
        <button type="button" data-speed="0.5">0.5×</button>
        <button type="button" data-speed="1">1×</button>
        <button type="button" data-speed="2">2×</button>
        <button type="button" data-speed="3">3×</button>
      </div>
    </div>
    <div class="form-row">
      <label>Effect</label>
      <div data-speed-preview>${this._speedPreviewHtml(block.multiplier)}</div>
    </div>`;
  },

  _messageRowHtml(labelText, val, block, stripe) {
    // Type Message's own text is a real multi-line textarea; with the
    // “use composer” checkbox on it is disabled because the Message
    // Composer window supplies the text at run time.
    const fromComposer = !!block.use_composer;
    return `<div class="form-row form-row--stack${stripe}">
      <label>${labelText}${fromComposer ? ' — disabled: text comes from the Message Composer window' : ''}</label>
      <textarea data-key="message" rows="3"${fromComposer ? ' disabled' : ''}
        placeholder="Message text — or tick “Use Message Composer” above">${this._esc(String(val || ''))}</textarea>
    </div>`;
  },

  _radioRowHtml(key, labelText, val, radioOpts, meta, stripe) {
    const rlabels = (meta.radio_labels && meta.radio_labels[key]) || {};
    const optsHtml = radioOpts.map((o) => {
      const checked = String(val) === String(o) ? ' checked' : '';
      return `<label class="radio-opt"><input type="radio" data-key="${key}"
        value="${this._esc(o)}"${checked}> ${this._esc(rlabels[o] || o)}</label>`;
    }).join('');
    return `<div class="form-row form-row-check${stripe}">
      <label>${labelText}</label>
      <div class="radio-group">${optsHtml}</div>
    </div>`;
  },

  _checkboxRowHtml(key, labelText, val, stripe) {
    if (key === 'enabled') {
      // On/Off toggle bar: a disabled block stays in the stack but is
      // skipped at run time.
      return `<div class="form-row form-row-check form-row-enabled">
        <label>${labelText} — On/Off toggle bar (skipped when off)</label>
        <label class="toggle-switch"><input data-key="${key}" type="checkbox" ${val ? 'checked' : ''}><span class="toggle-slider"></span></label>
      </div>`;
    }
    return `<div class="form-row form-row-check${stripe}">
      <label>${labelText}</label>
      <input data-key="${key}" type="checkbox" ${val ? 'checked' : ''}>
    </div>`;
  },

  _selectRowHtml(key, labelText, val, choices, stripe) {
    const opts = choices.map((o) => {
      const sel = String(val) === String(o) ? ' selected' : '';
      return `<option value="${this._esc(o)}"${sel}>${this._esc(o)}</option>`;
    }).join('');
    return `<div class="form-row${stripe}">
      <label>${labelText}</label>
      <select data-key="${key}">${opts}</select>
    </div>`;
  },

  _inputRowHtml(key, labelText, val, stripe, block) {
    const safeVal = String(val).replace(/"/g, '&quot;');
    const inputType = typeof val === 'number' ? 'number' : 'text';
    const isConstructor = block.block_id === 'CUSTOM_FIND';
    const rowCls = isConstructor ? 'form-row form-row--stack' : 'form-row';
    return `<div class="${rowCls}${isConstructor ? '' : stripe}">
      <label>${labelText}</label>
      <input data-key="${key}" value="${safeVal}" type="${inputType}">
    </div>`;
  },
};


const StackDnDSpeed = {
  _speedValue(v) {
    const m = Number(v);
    if (!isFinite(m) || m <= 0) return 1.0;
    return Math.min(10, Math.max(0.1, m));
  },

  _speedCoef(m) {
    if (Number.isInteger(m)) return m.toFixed(1);
    return String(Math.round(m * 100) / 100);
  },

  _speedDesc(v) {
    const m = this._speedValue(v);
    const coef = this._speedCoef(m);
    if (m === 1) return `×${coef} (normal speed)`;
    if (m < 1) return `×${coef} (${Math.round(100 / m) / 100}× faster)`;
    return `×${coef} (${Math.round(m * 100) / 100}× slower)`;
  },

  _speedPreviewHtml(v) {
    const m = this._speedValue(v);
    const mark = m < 1 ? '🐇' : (m > 1 ? '🐢' : '➖');
    const color = m < 1 ? '#2e7d32' : (m > 1 ? '#e65100' : 'inherit');
    const desc = this._speedDesc(m);
    return `<span style="color:${color};font-weight:600">${mark} All waits ${desc}</span>`;
  },

  _wireSpeedControls(form, block) {
    const input = form.querySelector('input[data-key="multiplier"]');
    const preview = form.querySelector('[data-speed-preview]');
    const refresh = () => {
      if (preview) {
        preview.innerHTML = this._speedPreviewHtml(block.multiplier);
      }
    };
    form.querySelectorAll('[data-speed]').forEach((btn) => {
      btn.addEventListener('click', (ev) => {
        ev.preventDefault();
        block.multiplier = Number(btn.dataset.speed);
        if (input) input.value = block.multiplier;
        refresh();
        this._renderStack();
        this.pushHistory();
        this.notifyEdited();
      });
    });
    if (input) {
      input.addEventListener('input', () => {
        block.multiplier = Number(input.value);
        refresh();
      });
      input.addEventListener('change', refresh);
    }
  },
};
