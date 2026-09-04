/* ═══════════════════════════════════════════════════════════════
   presets-ui.js — Saved stack presets + message template presets:
   always-visible chip list (small load buttons) + folder-button
   picker lists with Load / Delete. (BUG #1)
   ═══════════════════════════════════════════════════════════════ */

'use strict';

const PresetsUI = {
  stackPresets: [],
  templatePresets: [],

  // ── escaping / tiny helpers ─────────────────────────────────
  esc(s) {
    const d = document.createElement('div');
    d.textContent = (s === null || s === undefined) ? '' : String(s);
    return d.innerHTML;
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
    App.bridge.load_stack_preset(name, (payload) => {
      if (!payload || payload === 'null') return;
      try {
        const blocks = JSON.parse(payload);
        if (StackDnD && typeof StackDnD.setStack === 'function') StackDnD.setStack(blocks);
        LogConsole.log(`✅ Preset “${name}” restored — ${blocks.length} block(s)`, 'success');
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

  // ── shared ──────────────────────────────────────────────────
  _makeChip(title, meta, onLoad, onDelete) {
    const chip = document.createElement('span');
    chip.className = 'chip';
    const t = document.createElement('span');
    t.className = 'chip-title';
    t.textContent = title;
    t.title = title;
    const m = document.createElement('span');
    m.className = 'chip-meta';
    m.textContent = meta || '';
    const x = document.createElement('span');
    x.className = 'chip-x';
    x.textContent = '×';
    x.title = 'Delete';
    chip.appendChild(t);
    chip.appendChild(m);
    chip.appendChild(x);
    chip.addEventListener('click', onLoad);
    x.addEventListener('click', (ev) => {
      ev.stopPropagation();
      onDelete();
    });
    return chip;
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
  },

  // ── modals (Qt WebEngine doesn't support prompt()/confirm()) ──
  promptName(title, placeholder, okLabel, onOk) {
    const modal = document.getElementById('nameModal');
    const input = document.getElementById('nameModalInput');
    const ok = document.getElementById('nameModalOk');
    document.getElementById('nameModalTitle').textContent = title || 'Preset name';
    input.placeholder = placeholder || 'Enter a name…';
    input.value = '';
    ok.textContent = okLabel || 'Save';
    modal.classList.remove('hidden');
    input.focus();

    const cleanup = () => {
      modal.classList.add('hidden');
      ok.onclick = null;
      document.getElementById('nameModalCancel').onclick = null;
      input.onkeydown = null;
    };
    ok.onclick = () => {
      const name = input.value.trim();
      if (!name) { input.focus(); return; }
      cleanup();
      onOk(name);
    };
    document.getElementById('nameModalCancel').onclick = cleanup;
    input.onkeydown = (e) => {
      if (e.key === 'Enter') ok.click();
      else if (e.key === 'Escape') cleanup();
    };
  },

  confirmDelete(kindLabel, name, onYes) {
    const modal = document.getElementById('confirmModal');
    document.getElementById('confirmModalTitle').textContent = `Delete ${kindLabel}?`;
    document.getElementById('confirmModalText').textContent =
      `“${name}” will be permanently removed.`;
    modal.classList.remove('hidden');

    const cleanup = () => {
      modal.classList.add('hidden');
      document.getElementById('confirmModalYes').onclick = null;
      document.getElementById('confirmModalNo').onclick = null;
    };
    document.getElementById('confirmModalYes').onclick = () => { cleanup(); onYes(); };
    document.getElementById('confirmModalNo').onclick = cleanup;
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
