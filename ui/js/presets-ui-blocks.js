/* presets-ui-blocks.js — custom Find & Click block presets for PresetsUI facade (H-B2b JS split)

Design: ≤150 LOC.
*/

'use strict';

const PresetsUIBlocks = {
  customBlocks: [],

  setCustomBlocks(list) {
    this.customBlocks = Array.isArray(list) ? list.map((c) => ({ ...c, block: c.block ? { ...c.block } : {} })) : [];
    this.renderCustomChips();
  },

  setCustomBlocksJson(json) {
    try { this.setCustomBlocks(JSON.parse(json)); } catch (e) { this.setCustomBlocks([]); }
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

  exportBlock(name) {
    if (!App.bridge) { LogConsole.log('⚠ Not connected to backend', 'warn'); return; }
    App.bridge.export_custom_block(name, (res) => this.onFileResult(res));
  },
};

if (typeof window !== 'undefined') window.PresetsUIBlocks = PresetsUIBlocks;
