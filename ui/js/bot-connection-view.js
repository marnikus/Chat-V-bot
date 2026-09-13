/* ═══════════════════════════════════════════════════════════════
   bot-connection-view.js — drawing the "Choose AI connection" popup

   Everything that turns state into DOM for the connection picker: the
   left-hand rows, the readiness line, the preset card and the enabled or
   disabled state of the footer buttons. The controller (bot-settings.js)
   owns the state and the bridge calls and never builds an element itself.

   The split exists because the popup does two genuinely different jobs —
   deciding WHAT is true, and showing it — and together they were past
   RULE 18's 300-line band.

   The one rule this file encodes: a row's "viewed" highlight and a
   connection's "active" mark are different things and are drawn
   differently. Browsing is not choosing, so browsing must not look like
   choosing.

   ideal-size: 152 lines reason=one view = one module.
   ═══════════════════════════════════════════════════════════════ */

'use strict';

const BotConnView = {
  /** The left rail. Rows are buttons so the keyboard reaches them. */
  rows(host, state) {
    if (!host) return;
    host.textContent = '';
    state.connections.forEach((entry) => {
      host.appendChild(this._row(entry, state));
    });
  },

  _row(entry, state) {
    const row = document.createElement('button');
    row.type = 'button';
    row.className = 'bot-provider' +
      (entry.id === state.viewed ? ' viewed' : '') +
      (entry.id === state.active ? ' active' : '') +
      (entry.problem ? ' error' : '');
    row.dataset.provider = entry.id;
    row.setAttribute('role', 'option');
    row.setAttribute('aria-selected', entry.id === state.viewed ? 'true' : 'false');
    row.appendChild(this._rowName(entry, state));
    const tag = document.createElement('span');
    tag.className = 'bot-provider-tag';
    tag.textContent = this.rowTag(entry, state);
    row.appendChild(tag);
    return row;
  },

  _rowName(entry, state) {
    const name = document.createElement('span');
    name.className = 'bot-provider-name';
    const dot = document.createElement('i');
    dot.className = 'bot-dot ' + (entry.problem ? 'bad' : 'ok');
    name.appendChild(dot);
    const text = document.createElement('span');
    text.textContent = entry.title || '(unnamed)';
    name.appendChild(text);
    if (entry.id === state.active) {
      const mark = document.createElement('span');
      mark.className = 'bot-provider-active-mark';
      mark.textContent = '✓';
      name.appendChild(mark);
    }
    return name;
  },

  /** Words, never colour alone — "in use" is what makes active legible. */
  rowTag(entry, state) {
    const model = entry.model || 'no model';
    if (entry.problem) return '⚠ ' + entry.problem;
    return entry.id === state.active ? 'In use · ' + model : model;
  },

  /** Name + readiness at the top of the detail pane. */
  head(els, entry) {
    if (els.detailTitle) {
      els.detailTitle.textContent = entry.title ||
        (entry.id ? '(unnamed)' : 'New connection');
    }
    const ready = !entry.id ? 'Not saved yet'
      : (entry.problem ? entry.problem : 'Ready to use');
    const kind = !entry.id ? 'warn' : (entry.problem ? 'bad' : 'ok');
    if (els.readyText) els.readyText.textContent = ready;
    if (els.dot) els.dot.className = 'bot-dot ' + kind;
  },

  /** The preset card. Choosing an option only describes it; the Apply
   *  button (owned by the controller) is what writes the fields. */
  presets(els, list, chosen, appliedId) {
    if (els.presetOptions) {
      els.presetOptions.textContent = '';
      list.forEach((preset) => {
        els.presetOptions.appendChild(
          this._presetOpt(preset, chosen, appliedId));
      });
    }
    if (els.presetDesc) {
      els.presetDesc.textContent = chosen
        ? chosen.title + ' · ' + chosen.detail
        : 'Choose a preset to see what it would set.';
    }
    if (els.apply) els.apply.disabled = !chosen;
  },

  _presetOpt(preset, chosen, appliedId) {
    const opt = document.createElement('button');
    opt.type = 'button';
    opt.className = 'bot-preset-opt' +
      (chosen && chosen.id === preset.id ? ' chosen' : '') +
      (preset.id === appliedId ? ' applied' : '');
    opt.dataset.preset = preset.id;
    opt.setAttribute('role', 'option');
    opt.textContent = preset.title;
    return opt;
  },

  /** Which footer buttons are usable right now.
   *  Select is the only closing action, so it is the one that must refuse
   *  to be pressed while the connection could not actually run a prompt. */
  footer(els, state) {
    const entry = state.current() || {};
    const saved = !!entry.id;
    const usable = saved && !entry.problem;
    this._able(els.select, usable && !state.testing);
    this._able(els.test, saved && !state.testing);
    this._able(els.remove, saved);
  },

  _able(el, on) { if (el) el.disabled = !on; },

  /** The provider's recommended configuration IS the preset — the spec
   *  table already carries the model and endpoint most users want, so
   *  there is nothing extra to store and nothing to fall out of date.
   *  (These are PROVIDER presets; the prompt-preset library is separate.) */
  presetsFor(providers, providerId) {
    const spec = providers.filter((p) => p.id === providerId)[0];
    if (!spec) return [];
    return [{
      id: spec.id + ':default', title: spec.title + ' standard',
      detail: 'model ' + (spec.model || '—') + ', the vendor endpoint',
      model: spec.model || '', url: spec.url || '',
    }];
  },

  /** Write a connection into the form. The key field is always blanked:
   *  a stored secret is described, never echoed back into the DOM. */
  fill(els, entry) {
    if (els.key) els.key.value = '';
    if (els.title) els.title.value = entry.title || '';
    if (els.model) els.model.value = entry.model || '';
    if (els.url) els.url.value = entry.url || '';
    this.keyState(els.keyState, entry);
    this.head(els, entry);
  },

  /** Read the form back. What is on screen is what gets saved. */
  read(els, providerId) {
    const val = (el) => (el ? String(el.value || '') : '');
    return {
      title: val(els.title), provider: providerId,
      api_key: val(els.key), model: val(els.model), url: val(els.url),
    };
  },

  /** Same arithmetic the layout menu uses: right-aligned, clamped. */
  place(panel, anchor) {
    if (!anchor || !panel || !anchor.getBoundingClientRect) return;
    const at = anchor.getBoundingClientRect();
    const width = panel.offsetWidth || 760;
    const left = Math.max(8, Math.min(at.right - width,
                                      window.innerWidth - width - 8));
    panel.style.left = left + 'px';
    panel.style.top = (at.bottom + 6) + 'px';
  },

  /** The key field: a saved secret is described, never echoed back. */
  keyState(el, entry) {
    if (!el) return;
    el.textContent = entry.has_key
      ? 'A key is saved (' + (entry.masked || 'set') +
        ') — leave blank to keep it'
      : 'No key saved yet';
  },
};

if (typeof window !== 'undefined') window.BotConnView = BotConnView;
if (typeof module !== 'undefined' && module.exports)
  module.exports = BotConnView;
