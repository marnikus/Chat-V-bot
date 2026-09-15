/* presets-ui-import.js — import/export preview for PresetsUI facade (H-B2b JS split)

Portable export / import: importStack, importBlock, showImportPreview,
_wireImportButtons, closeImportPreview, applyImported.

Design: ≤250 LOC.
*/

'use strict';

const PresetsUIImport = {
  _importPreview: null,
  _importKeyHandler: null,

  importStack() {
    if (!App.bridge) { LogConsole.log('⚠ Not connected to backend', 'warn'); return; }
    LogConsole.log('📥 Import stack — choose a .json preset file', 'info');
    App.bridge.import_file('stack', (res) => this.onImportPreview(res));
  },

  importBlock() {
    if (!App.bridge) { LogConsole.log('⚠ Not connected to backend', 'warn'); return; }
    App.bridge.import_file('block', (res) => this.onImportPreview(res));
  },

  showImportPreview(preview) {
    this._importPreview = preview;
    const modal = document.getElementById('importPreviewModal');
    if (!modal) return;
    const isStack = preview.kind === 'stack';
    document.getElementById('importPreviewTitle').textContent = (isStack ? 'Import stack ' : 'Import block ') + `“${preview.name}”`;
    const meta = [];
    if (preview.exported_at) meta.push(`exported ${preview.exported_at}`);
    if (preview.app_version) meta.push(`app ${preview.app_version}`);
    if (isStack) meta.push(`${(preview.stack || []).length} step(s), ${(preview.custom_blocks || []).length} custom block(s)`);
    document.getElementById('importPreviewMeta').textContent = meta.join(' · ');
    const warnEl = document.getElementById('importPreviewWarnings');
    warnEl.innerHTML = '';
    (preview.warnings || []).forEach((w) => { warnEl.appendChild(this.escText('⚠ ' + w, 'div')); });
    warnEl.classList.toggle('hidden', !(preview.warnings || []).length);
    const list = document.getElementById('importPreviewBlocks');
    list.innerHTML = '';
    if (isStack) {
      (preview.stack || []).forEach((b, i) => { list.appendChild(this._importRow(i + 1, b)); });
    } else if (preview.block) {
      list.appendChild(this._importRow(1, preview.block, preview.name));
    }
    document.getElementById('importPreviewMerge').classList.toggle('hidden', !isStack);
    document.getElementById('importPreviewReplace').classList.toggle('hidden', !isStack);
    document.getElementById('importPreviewAdd').classList.toggle('hidden', isStack);
    modal.classList.remove('hidden');
    this._wireImportButtons();
  },

  _wireImportButtons() {
    document.getElementById('importPreviewCancel').onclick = () => {
      this.closeImportPreview();
      LogConsole.log('⏹ Import cancelled — nothing changed', 'warn');
    };
    document.getElementById('importPreviewMerge').onclick = () => this.applyImported('merge');
    document.getElementById('importPreviewReplace').onclick = () => this.applyImported('replace');
    document.getElementById('importPreviewAdd').onclick = () => this.applyImported('add');
    this._importKeyHandler = (e) => { if (e.key === 'Escape') this.closeImportPreview(); };
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
    if (preview.kind === 'stack' && StackDnD && typeof StackDnD.pushHistory === 'function' && StackDnD.stack && StackDnD.stack.length) {
      StackDnD.pushHistory(StackDnD.stack, { force: false });
    }
    const stackJson = (StackDnD && StackDnD.stack) ? JSON.stringify(StackDnD.stack) : '[]';
    App.bridge.apply_imported(JSON.stringify(preview), mode, stackJson, (res) => {
      const r = this._parseResult(res);
      if (!r) return;
      if (!r.ok) { LogConsole.log(`❌ Import failed: ${r.error}`, 'error'); return; }
      if (preview.kind === 'stack' && StackDnD && typeof StackDnD.setStack === 'function' && Array.isArray(r.stack)) {
        StackDnD.setStack(r.stack);
      }
      if (preview.kind === 'stack') {
        const savedNote = r.preset_saved ? `; saved as preset “${r.preset_saved}”` : '';
        LogConsole.log(`✅ Imported “${preview.name}” (${mode}) — ${r.stack.length} block(s) in the stack, ${r.blocks_added || 0} custom block(s) added, ${r.blocks_replaced || 0} replaced${savedNote} (↩ Undo to return)`, 'success');
      } else {
        LogConsole.log(`✅ Block “${r.name}” imported into the Custom Blocks library`, 'success');
      }
    });
  },
};

if (typeof window !== 'undefined') window.PresetsUIImport = PresetsUIImport;
