/* ═══════════════════════════════════════════════════════════════
   log-console.js — Log console display with auto-scroll
   ═══════════════════════════════════════════════════════════════ */

'use strict';

const LogConsole = {
  _el: null,
  _maxEntries: 500,

  init() {
    this._el = document.getElementById('logConsole');
  },

  log(message, level = 'info') {
    if (!this._el) this._el = document.getElementById('logConsole');
    if (!this._el) return;
    const entry = document.createElement('div');
    entry.className = 'log-entry ' + (level || '');
    const now = new Date();
    const ts = `${String(now.getHours()).padStart(2,'0')}:${String(now.getMinutes()).padStart(2,'0')}:${String(now.getSeconds()).padStart(2,'0')}`;
    entry.textContent = `[${ts}] ${message}`;
    this._el.appendChild(entry);
    // auto-scroll
    this._el.scrollTop = this._el.scrollHeight;
    // trim old entries
    while (this._el.children.length > this._maxEntries) {
      this._el.removeChild(this._el.firstChild);
    }
  },

  clear() {
    if (this._el) this._el.innerHTML = '';
  },
};

document.addEventListener('DOMContentLoaded', () => LogConsole.init());
