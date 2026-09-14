/* ═══════════════════════════════════════════════════════════════
   dark-select.js — a dropdown that matches the Bookmarks popup

   A native `<select>` cannot be themed: `background` styles the closed box,
   but the open list is drawn by the operating system, which is why those
   menus came out white on a black application. Every dark menu in this app
   is therefore a div panel — `#layoutMenu` (Grid view / Bookmarks) is the
   reference — and this file is that panel as a reusable control so the
   prompt-preset chooser and the provider chooser cannot drift apart.

   It builds the SAME structure the Bookmarks popup uses (a `.layout-menu`
   of `button` rows carrying a `.lm-sub` subtitle), so "matches Bookmarks"
   holds because it is the same CSS, not because two stylesheets were kept
   in step by hand.

   Keyboard: Enter/Space opens, ↑/↓ move, Enter picks, Escape closes and
   returns focus to the trigger — a mouse-only menu would put the API-key
   form behind a control some users cannot operate.

   ideal-size: 194 lines reason=one widget, one file, inside RULE 18's
   150-300 band. Roughly half of it is the keyboard contract, which is the
   part a reader most needs spelled out rather than inferred.
   ═══════════════════════════════════════════════════════════════ */

'use strict';

const DarkSelect = {
  _all: [],

  /**
   * Turn `host` (an empty div) into a dropdown.
   * `onPick(value)` fires only on a real user choice, never on setOptions.
   */
  attach(host, options) {
    if (!host) return null;
    const control = Object.create(this._proto);
    control.host = host;
    control.onPick = (options && options.onPick) || function () {};
    control.placeholder = (options && options.placeholder) || 'Select…';
    control.options = [];
    control.value = '';
    control._build();
    this._all.push(control);
    return control;
  },

  /** Close every open menu — the document-level click handler uses this. */
  closeAll(except) {
    this._all.forEach((c) => { if (c !== except) c.close(); });
  },

  _proto: {
    _build() {
      this.host.classList.add('dark-select');
      this.trigger = document.createElement('button');
      this.trigger.type = 'button';
      this.trigger.className = 'dark-select-trigger';
      this.trigger.setAttribute('aria-haspopup', 'listbox');
      this.trigger.setAttribute('aria-expanded', 'false');
      this.label = document.createElement('span');
      this.label.className = 'dark-select-label';
      this.label.textContent = this.placeholder;
      this.caret = document.createElement('span');
      this.caret.className = 'dark-select-caret';
      this.caret.textContent = '▾';
      this.trigger.appendChild(this.label);
      this.trigger.appendChild(this.caret);
      this.menu = document.createElement('div');
      // the Bookmarks popup's own classes — see the file header
      this.menu.className = 'layout-menu dark-select-menu hidden';
      this.menu.setAttribute('role', 'listbox');
      this.host.appendChild(this.trigger);
      this.host.appendChild(this.menu);
      this.trigger.addEventListener('click', (e) => {
        e.stopPropagation();
        this.toggle();
      });
      this.trigger.addEventListener('keydown', (e) => this._onKey(e));
      this.menu.addEventListener('keydown', (e) => this._onKey(e));
    },

    /** Replace the choices. Never fires `onPick`: this is not a user act. */
    setOptions(list, value) {
      this.options = (list || []).map((o) => ({
        value: String(o.value === undefined ? '' : o.value),
        title: String(o.title === undefined ? '' : o.title),
        sub: String(o.sub || ''), warn: !!o.warn,
      }));
      this.value = String(value === undefined ? this.value : value);
      this._renderMenu();
      this._renderLabel();
    },

    _renderMenu() {
      this.menu.textContent = '';
      if (!this.options.length) {
        const empty = document.createElement('div');
        empty.className = 'dark-select-empty';
        empty.textContent = this.placeholder;
        this.menu.appendChild(empty);
        return;
      }
      this.options.forEach((opt) => this.menu.appendChild(this._row(opt)));
    },

    _row(opt) {
      const row = document.createElement('button');
      row.type = 'button';
      row.className = 'dark-select-option' +
        (opt.value === this.value ? ' selected' : '') +
        (opt.warn ? ' warn' : '');
      row.setAttribute('role', 'option');
      row.dataset.value = opt.value;
      row.textContent = opt.title;
      if (opt.sub) {
        const sub = document.createElement('span');
        sub.className = 'lm-sub';          // the Bookmarks subtitle class
        sub.textContent = opt.sub;
        row.appendChild(sub);
      }
      row.addEventListener('click', (e) => {
        e.stopPropagation();
        this.pick(opt.value);
      });
      return row;
    },

    _renderLabel() {
      const found = this.options.filter((o) => o.value === this.value)[0];
      this.label.textContent = found ? found.title : this.placeholder;
      this.host.classList.toggle('warn', !!(found && found.warn));
    },

    /** Choose a value as the user would: updates, closes, notifies. */
    pick(value) {
      this.value = String(value);
      this._renderMenu();
      this._renderLabel();
      this.close();
      this.onPick(this.value);
    },

    /** Set the value without telling anyone — for restoring saved state. */
    select(value) {
      this.value = String(value);
      this._renderMenu();
      this._renderLabel();
    },

    open() {
      DarkSelect.closeAll(this);
      this.menu.classList.remove('hidden');
      this.trigger.setAttribute('aria-expanded', 'true');
    },

    close() {
      this.menu.classList.add('hidden');
      this.trigger.setAttribute('aria-expanded', 'false');
    },

    isOpen() { return !this.menu.classList.contains('hidden'); },

    toggle() { if (this.isOpen()) this.close(); else this.open(); },

    _onKey(event) {
      const key = event.key;
      if (key === 'Escape') { this.close(); this.trigger.focus(); return; }
      if (key === 'Enter' || key === ' ') {
        event.preventDefault();
        if (this.isOpen()) this.pick(this.value); else this.open();
        return;
      }
      if (key === 'ArrowDown' || key === 'ArrowUp') {
        event.preventDefault();
        this._step(key === 'ArrowDown' ? 1 : -1);
      }
    },

    _step(delta) {
      if (!this.options.length) return;
      this.open();
      const at = this.options.findIndex((o) => o.value === this.value);
      const next = Math.min(this.options.length - 1, Math.max(0, at + delta));
      this.select(this.options[next].value);
    },
  },
};

if (typeof document !== 'undefined' && document.addEventListener) {
  document.addEventListener('click', () => DarkSelect.closeAll(null));
}

if (typeof window !== 'undefined') window.DarkSelect = DarkSelect;
if (typeof module !== 'undefined') module.exports = DarkSelect;
