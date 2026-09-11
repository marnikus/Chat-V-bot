/* ═══════════════════════════════════════════════════════════════
   presets-ui.js — Saved stack presets + message template presets:
   always-visible chip list (small load buttons) + folder-button
   picker lists with Load / Delete. (BUG #1)
   ═══════════════════════════════════════════════════════════════ */

'use strict';

const PresetsUI = {
  stackPresets: [],
  templatePresets: [],
  customBlocks: [],
  // the parsed, not-yet-applied file behind the import preview modal
  _importPreview: null,
  _importKeyHandler: null,

  // ── escaping / tiny helpers ─────────────────────────────────
  // the implementations live in js/core/ui-helpers.js; these thin
  // delegates keep every historical PresetsUI.esc(...) call site
  esc(s) {
    return window.UIHelpers.esc(s);
  },

  _date(iso) {
    if (!iso) return '';
    try { return new Date(iso).toLocaleString(); } catch (e) { return iso; }
  },

  // ── stack presets ───────────────────────────────────────────
  setStackPresets(json) {
    try { this.stackPresets = JSON.parse(json); } catch (e) { this.stackPresets = []; }
    this.renderStackChips();
  },

  renderStackChips() {
    const el = document.getElementById('presetChips');
    if (!el) return;
    if (!this.stackPresets.length) {
      el.innerHTML = '<span class="preset-row-empty">none yet — click 💾 Save and give the preset a name</span>';
      return;
    }
    el.innerHTML = '';
    this.stackPresets.forEach((p) => {
      el.appendChild(this._makeChip(
        `📄 ${p.name}`, `(${p.blocks || 0})`,
        () => this.loadStack(p.name),
        () => this.deleteStack(p.name)
      ));
    });
  },

  loadStack(name) {
    if (!App.bridge) { LogConsole.log('⚠ Not connected to backend', 'warn'); return; }
    LogConsole.log(`📂 Loading preset “${name}”…`, 'info');
    // Push current stack to history before overwriting, so undo returns to previous custom settings
    if (StackDnD && typeof StackDnD.pushHistory === 'function' && StackDnD.stack && StackDnD.stack.length) {
      StackDnD.pushHistory(StackDnD.stack, {force:false});
    }
    App.bridge.load_stack_preset(name, (payload) => {
      if (!payload || payload === 'null') return;
      try {
        const blocks = JSON.parse(payload);
        if (StackDnD && typeof StackDnD.setStack === 'function') {
          // setStack will auto-push history (new preset becomes new tip, undo returns to previous)
          StackDnD.setStack(blocks);
        }
        LogConsole.log(`✅ Preset “${name}” restored — ${blocks.length} block(s) (↩ Undo to return)`, 'success');
      } catch (e) {
        LogConsole.log(`❌ Preset “${name}” could not be parsed`, 'error');
      }
    });
  },

  deleteStack(name) {
    if (!App.bridge) return;
    this.confirmDelete('preset', name, () => App.bridge.delete_stack_preset(name));
  },

  toggleStackPicker(anchorBtn) {
    const picker = document.getElementById('presetPicker');
    const html = this.stackPresets.map((p) =>
      `<div class="preset-picker-row">
         <span class="pp-name" title="${this.esc(p.name)}">📄 ${this.esc(p.name)}</span>
         <span class="pp-meta">${p.blocks || 0} blk · ${this.esc(this._date(p.updated_at))}</span>
         <button class="pp-load" data-name="${this.esc(p.name)}">Load</button>
         <button class="pp-export" data-name="${this.esc(p.name)}" title="Export this preset to a .json file">Export</button>
         <span class="pp-del material-icons" data-name="${this.esc(p.name)}" title="Delete">delete</span>
       </div>`).join('')
      || '<div class="pp-empty">No saved presets yet. Click 💾 Save to create one.</div>';
    picker.innerHTML = `<div class="picker-title">Saved presets — click Load to restore</div>${html}`;
    this._placePicker(picker, anchorBtn);
    picker.querySelectorAll('.pp-load').forEach((b) => {
      b.addEventListener('click', () => {
        picker.classList.add('hidden');
        this.loadStack(b.dataset.name);
      });
    });
    picker.querySelectorAll('.pp-export').forEach((b) => {
      b.addEventListener('click', (ev) => {
        ev.stopPropagation();
        picker.classList.add('hidden');
        this.exportPreset(b.dataset.name);
      });
    });
    picker.querySelectorAll('.pp-del').forEach((b) => {
      b.addEventListener('click', (ev) => {
        ev.stopPropagation();
        this.deleteStack(b.dataset.name);
      });
    });
  },

  // ── message template presets ────────────────────────────────
  setTemplatePresets(json) {
    try { this.templatePresets = JSON.parse(json); } catch (e) { this.templatePresets = []; }
    this.renderTemplateChips();
  },

  renderTemplateChips() {
    const el = document.getElementById('templateChips');
    if (!el) return;
    if (!this.templatePresets.length) {
      el.innerHTML = '<span class="preset-row-empty">none yet — click “Save Template”</span>';
      return;
    }
    el.innerHTML = '';
    this.templatePresets.forEach((t) => {
      el.appendChild(this._makeChip(
        `💬 ${t.name}`, `(${t.len || 0} ch)`,
        () => this.loadTemplate(t.name),
        () => this.deleteTemplate(t.name)
      ));
    });
  },

  loadTemplate(name) {
    if (!App.bridge) { LogConsole.log('⚠ Not connected to backend', 'warn'); return; }
    App.bridge.load_template_preset(name, (body) => {
      if (typeof Composer !== 'undefined' && typeof Composer.setMessage === 'function') {
        Composer.setMessage(body || '');
        LogConsole.log(`💬 Template “${name}” loaded into composer`, 'success');
      }
    });
  },

  deleteTemplate(name) {
    if (!App.bridge) return;
    this.confirmDelete('template', name, () => App.bridge.delete_template_preset(name));
  },

  toggleTemplatePicker(anchorBtn) {
    const picker = document.getElementById('templatePicker');
    const html = this.templatePresets.map((t) =>
      `<div class="preset-picker-row">
         <span class="pp-name" title="${this.esc(t.name)}">💬 ${this.esc(t.name)}</span>
         <span class="pp-meta">${t.len || 0} ch · ${this.esc(this._date(t.updated_at))}</span>
         <button class="pp-load" data-name="${this.esc(t.name)}">Load</button>
         <span class="pp-del material-icons" data-name="${this.esc(t.name)}" title="Delete">delete</span>
       </div>`).join('')
      || '<div class="pp-empty">No saved templates yet. Click “Save Template” to create one.</div>';
    picker.innerHTML = `<div class="picker-title">Message templates — click Load to insert</div>${html}`;
    this._placePicker(picker, anchorBtn);
    picker.querySelectorAll('.pp-load').forEach((b) => {
      b.addEventListener('click', () => {
        picker.classList.add('hidden');
        this.loadTemplate(b.dataset.name);
      });
    });
    picker.querySelectorAll('.pp-del').forEach((b) => {
      b.addEventListener('click', (ev) => {
        ev.stopPropagation();
        this.deleteTemplate(b.dataset.name);
      });
    });
  },

  // ── custom Find & Click block presets (FEATURE) ─────────────
  setCustomBlocks(list) {
    this.customBlocks = Array.isArray(list)
      ? list.map((c) => ({ ...c, block: c.block ? { ...c.block } : {} }))
      : [];
    this.renderCustomChips();
  },

  setCustomBlocksJson(json) {
    try { this.setCustomBlocks(JSON.parse(json)); }
    catch (e) { this.setCustomBlocks([]); }
  },

  renderCustomChips() {
    const el = document.getElementById('customBlockChips');
    if (!el) return;
    if (!this.customBlocks.length) {
      el.innerHTML = '<span class="preset-row-empty">no saved blocks — add a “Find &amp; Click” block, configure it, and press “Save Block as Preset”</span>';
      return;
    }
    el.innerHTML = '';
    this.customBlocks.forEach((c) => {
      const blk = c.block || {};
      const label = blk.custom_name || c.name || 'Custom block';
      const icon = '🔎';
      const chip = this._makeChip({
        title: `${icon} ${label}`, meta: '',
        onLoad: () => this.addCustomBlock(c),
        onDelete: () => this.deleteCustomBlock(c.name || label),
        onExport: () => this.exportBlock(c.name || label),
        exportTitle: 'Export this block to a .json file',
      });
      chip.title = 'Add this Find & Click block to the stack';
      el.appendChild(chip);
    });
  },

  addCustomBlock(entry) {
    if (!entry || !entry.block) return;
    if (StackDnD && typeof StackDnD.addBlockConfig === 'function') {
      StackDnD.addBlockConfig(entry.block);
      LogConsole.log(`🔎 Custom block “${entry.block.custom_name || entry.name}” added to the stack`, 'success');
    }
  },

  deleteCustomBlock(name) {
    if (!App.bridge) return;
    this.confirmDelete('block preset', name, () => App.bridge.delete_custom_block(name));
  },

  // ── shared ──────────────────────────────────────────────────
  _makeChip(a, b, c, d) {
    // one chip implementation for every panel (js/core/ui-helpers.js);
    // accepts the historical (title, meta, onLoad, onDelete) tuple or
    // one opts object (chips that also export need the extra keys)
    const opts = (a && typeof a === 'object')
      ? a
      : { title: a, meta: b, onLoad: c, onDelete: d };
    return window.UIHelpers.chip(opts);
  },

  _placePicker(picker, anchorBtn) {
    picker.classList.toggle('hidden');
    if (!picker.classList.contains('hidden')) {
      const r = anchorBtn.getBoundingClientRect();
      // keep inside viewport
      const w = picker.offsetWidth || 340;
      let left = r.left;
      if (left + w > window.innerWidth - 8) left = Math.max(8, window.innerWidth - w - 8);
      picker.style.top = (r.bottom + 4) + 'px';
      picker.style.left = left + 'px';
    }
  },

  refreshAll() {
    if (!App.bridge) return;
    App.bridge.list_stack_presets((json) => this.setStackPresets(json));
    App.bridge.list_template_presets((json) => this.setTemplatePresets(json));
    App.bridge.list_custom_blocks((json) => this.setCustomBlocksJson(json));
  },

  // ── portable export / import (FEATURE) ───────────────────────
  // The backend owns the file format and validation (services/preset_io);
  // the UI only moves JSON across the bridge and shows what it got back.
  exportCurrentStack() {
    if (!App.bridge) { LogConsole.log('⚠ Not connected to backend', 'warn'); return; }
    if (!StackDnD || !StackDnD.stack || !StackDnD.stack.length) {
      LogConsole.log('⚠ Stack is empty — nothing to export', 'warn');
      return;
    }
    LogConsole.log('📤 Exporting stack + custom blocks… choose the location in the dialog', 'info');
    App.bridge.export_stack(JSON.stringify(StackDnD.stack), (res) => this.onFileResult(res));
  },

  exportPreset(name) {
    if (!App.bridge) { LogConsole.log('⚠ Not connected to backend', 'warn'); return; }
    App.bridge.export_stack_preset(name, (res) => this.onFileResult(res));
  },

  exportBlock(name) {
    if (!App.bridge) { LogConsole.log('⚠ Not connected to backend', 'warn'); return; }
    App.bridge.export_custom_block(name, (res) => this.onFileResult(res));
  },

  importStack() {
    if (!App.bridge) { LogConsole.log('⚠ Not connected to backend', 'warn'); return; }
    LogConsole.log('📥 Import stack — choose a .json preset file', 'info');
    App.bridge.import_file('stack', (res) => this.onImportPreview(res));
  },

  importBlock() {
    if (!App.bridge) { LogConsole.log('⚠ Not connected to backend', 'warn'); return; }
    App.bridge.import_file('block', (res) => this.onImportPreview(res));
  },

  _parseResult(res) {
    try { return JSON.parse(res); }
    catch (e) {
      LogConsole.log('❌ Bad result from the backend', 'error');
      return null;
    }
  },

  onFileResult(res) {
    const r = this._parseResult(res);
    if (!r) return;
    if (r.ok) LogConsole.log(`✅ Exported to ${r.path}`, 'success');
    else if (r.canceled) LogConsole.log('⏹ Export cancelled', 'info');
    else LogConsole.log(`❌ ${r.error}`, 'error');
  },

  onImportPreview(res) {
    const r = this._parseResult(res);
    if (!r) return;
    if (!r.ok) {
      LogConsole.log(r.canceled ? '⏹ Import cancelled' : `❌ ${r.error}`,
                    r.canceled ? 'info' : 'error');
      return;
    }
    this.showImportPreview(r);
  },

  showImportPreview(preview) {
    this._importPreview = preview;
    const modal = document.getElementById('importPreviewModal');
    if (!modal) return;
    const isStack = preview.kind === 'stack';
    document.getElementById('importPreviewTitle').textContent =
      (isStack ? 'Import stack ' : 'Import block ') + `“${preview.name}”`;
    const meta = [];
    if (preview.exported_at) meta.push(`exported ${preview.exported_at}`);
    if (preview.app_version) meta.push(`app ${preview.app_version}`);
    if (isStack) meta.push(`${(preview.stack || []).length} step(s), ` +
                            `${(preview.custom_blocks || []).length} custom block(s)`);
    document.getElementById('importPreviewMeta').textContent = meta.join(' · ');
    const warnEl = document.getElementById('importPreviewWarnings');
    warnEl.innerHTML = '';
    (preview.warnings || []).forEach((w) => {
      warnEl.appendChild(this.escText('⚠ ' + w, 'div'));
    });
    warnEl.classList.toggle('hidden', !(preview.warnings || []).length);
    const list = document.getElementById('importPreviewBlocks');
    list.innerHTML = '';
    if (isStack) {
      (preview.stack || []).forEach((b, i) => {
        list.appendChild(this._importRow(i + 1, b));
      });
    } else if (preview.block) {
      list.appendChild(this._importRow(1, preview.block, preview.name));
    }
    document.getElementById('importPreviewMerge')
      .classList.toggle('hidden', !isStack);
    document.getElementById('importPreviewReplace')
      .classList.toggle('hidden', !isStack);
    document.getElementById('importPreviewAdd')
      .classList.toggle('hidden', isStack);
    modal.classList.remove('hidden');
    this._wireImportButtons();
  },

  _importRow(idx, block, label) {
    const row = UIHelpers.el('div', 'ibl-row');
    row.appendChild(UIHelpers.el('span', 'ibl-idx', String(idx)));
    row.appendChild(UIHelpers.el('span', 'ibl-name',
      label || block.custom_name || block.block_id || 'block'));
    const meta = [];
    if (block.selector) meta.push(block.selector);
    if (block.match_text) meta.push(`match “${block.match_text}”`);
    if (block.text) meta.push(String(block.text).slice(0, 60));
    if (block.enabled === false) meta.push('disabled');
    row.appendChild(UIHelpers.el('span', 'ibl-meta', meta.join(' · ')));
    return row;
  },

  escText(text, tag) {
    const node = document.createElement(tag || 'div');
    node.textContent = text;
    return node;
  },

  _wireImportButtons() {
    document.getElementById('importPreviewCancel').onclick = () => {
      this.closeImportPreview();
      LogConsole.log('⏹ Import cancelled — nothing changed', 'warn');
    };
    document.getElementById('importPreviewMerge').onclick =
      () => this.applyImported('merge');
    document.getElementById('importPreviewReplace').onclick =
      () => this.applyImported('replace');
    document.getElementById('importPreviewAdd').onclick =
      () => this.applyImported('add');
    this._importKeyHandler = (e) => {
      if (e.key === 'Escape') this.closeImportPreview();
    };
    document.addEventListener('keydown', this._importKeyHandler, true);
  },

  closeImportPreview() {
    const modal = document.getElementById('importPreviewModal');
    if (modal) modal.classList.add('hidden');
    if (this._importKeyHandler) {
      document.removeEventListener('keydown', this._importKeyHandler, true);
      this._importKeyHandler = null;
    }
    this._importPreview = null;
  },

  applyImported(mode) {
    const preview = this._importPreview;
    this.closeImportPreview();
    if (!preview || !App.bridge) return;
    // Record the pre-import stack first, exactly like loadStack does —
    // one Undo step must return to it (RULE 12, one global history).
    if (preview.kind === 'stack' && StackDnD &&
        typeof StackDnD.pushHistory === 'function' &&
        StackDnD.stack && StackDnD.stack.length) {
      StackDnD.pushHistory(StackDnD.stack, {force: false});
    }
    const stackJson = (StackDnD && StackDnD.stack)
      ? JSON.stringify(StackDnD.stack) : '[]';
    App.bridge.apply_imported(JSON.stringify(preview), mode, stackJson,
      (res) => {
        const r = this._parseResult(res);
        if (!r) return;
        if (!r.ok) {
          LogConsole.log(`❌ Import failed: ${r.error}`, 'error');
          return;
        }
        if (preview.kind === 'stack' &&
            StackDnD && typeof StackDnD.setStack === 'function' &&
            Array.isArray(r.stack)) {
          StackDnD.setStack(r.stack);
        }
        if (preview.kind === 'stack') {
          const savedNote = r.preset_saved
            ? `; saved as preset “${r.preset_saved}”` : '';
          LogConsole.log(
            `✅ Imported “${preview.name}” (${mode}) — ${r.stack.length} ` +
            `block(s) in the stack, ${r.blocks_added || 0} custom block(s) ` +
            `added, ${r.blocks_replaced || 0} replaced${savedNote} ` +
            '(↩ Undo to return)',
            'success');
        } else {
          LogConsole.log(`✅ Block “${r.name}” imported into the ` +
                         'Custom Blocks library', 'success');
        }
      });
  },

  // ── modals (Qt WebEngine doesn't support prompt()/confirm()) ──
  // The implementation lives in js/core/dialog.js; these delegates
  // keep the historical PresetsUI.confirm(...) call sites working.
  promptName(title, placeholder, okLabel, onOk) {
    window.Dialog.promptName(title, placeholder, okLabel, onOk);
  },

  confirmDelete(kindLabel, name, onYes) {
    window.Dialog.confirm(`Delete ${kindLabel}?`,
      `“${name}” will be permanently removed.`, 'Delete', onYes);
  },

  /** Generic in-app confirmation (delegates to the shared Dialog). */
  confirm(title, text, okLabel, onYes) {
    window.Dialog.confirm(title, text, okLabel, onYes);
  },
};

document.addEventListener('click', (e) => {
  if (!e.target.closest('#presetPicker')) {
    const p1 = document.getElementById('presetPicker');
    if (p1 && !e.target.closest('#loadStackBtn')) p1.classList.add('hidden');
  }
  if (!e.target.closest('#templatePicker')) {
    const p2 = document.getElementById('templatePicker');
    if (p2 && !e.target.closest('#loadTemplateBtn')) p2.classList.add('hidden');
  }
});
