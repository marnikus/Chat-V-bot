/* ═══════════════════════════════════════════════════════════════
   color-picker.js — the movable "Pick Color" popup

   A small dark floating window (≈280×320) with a 5×4 grid of 20 bright
   preset colours. It is DRAGGABLE by its title bar, closes on pick,
   Cancel, ✕ or Escape, and remembers where the user parked it for the
   rest of the session.

   Built with createElement/textContent only — a label name never becomes
   markup (same discipline as ui/js/history-view.js).
   ═══════════════════════════════════════════════════════════════ */

'use strict';

const ColorPicker = {
  /** Row-major 5×4 grid, exactly the palette the backend validates against. */
  COLORS: [
    { hex: '#ff3b30', name: 'Red' },      { hex: '#ff9500', name: 'Orange' },
    { hex: '#ffcc00', name: 'Yellow' },   { hex: '#a3e635', name: 'Lime' },
    { hex: '#34c759', name: 'Green' },
    { hex: '#14b8a6', name: 'Teal' },     { hex: '#22d3ee', name: 'Cyan' },
    { hex: '#38bdf8', name: 'Sky Blue' }, { hex: '#0a84ff', name: 'Blue' },
    { hex: '#5856d6', name: 'Indigo' },
    { hex: '#7c3aed', name: 'Violet' },   { hex: '#af52de', name: 'Purple' },
    { hex: '#e935c1', name: 'Magenta' },  { hex: '#ff2d95', name: 'Pink' },
    { hex: '#ff375f', name: 'Hot Pink' },
    { hex: '#ff7a5c', name: 'Coral' },    { hex: '#f59e0b', name: 'Amber' },
    { hex: '#7fff00', name: 'Chartreuse' },
    { hex: '#00ff7f', name: 'Spring Green' },
    { hex: '#00e5ff', name: 'Aqua' },
  ],

  WIDTH: 280,
  HEIGHT: 320,

  el: null,
  _opts: null,
  _pos: null,          // remembered between openings
  _drag: null,
  _onKey: null,

  /** Currently open? */
  get isOpen() { return !!this.el; },

  /**
   * Show the popup.
   * @param {object} opts
   *   color     — currently selected hex (gets the white ring)
   *   anchor    — element to appear next to (optional)
   *   title     — title-bar text (default "Pick Color")
   *   onPick    — fn(hex) called on selection, then the popup closes
   *   onCancel  — fn() called when dismissed without a choice
   */
  open(opts) {
    this.close(true);
    this._opts = opts || {};
    const doc = document;
    const box = doc.createElement('div');
    box.className = 'color-picker';
    box.setAttribute('role', 'dialog');
    box.setAttribute('aria-label', this._opts.title || 'Pick Color');
    box.style.width = this.WIDTH + 'px';

    // ── title bar (the drag handle) ──────────────────────────
    const bar = doc.createElement('div');
    bar.className = 'cp-bar';
    const grip = doc.createElement('span');
    grip.className = 'cp-grip material-icons';
    grip.textContent = 'drag_indicator';
    grip.title = 'Drag to move this picker anywhere';
    const title = doc.createElement('span');
    title.className = 'cp-title';
    title.textContent = this._opts.title || 'Pick Color';
    const close = doc.createElement('button');
    close.className = 'cp-close';
    close.type = 'button';
    close.title = 'Close';
    close.textContent = '✕';
    close.addEventListener('click', () => this.cancel());
    bar.appendChild(grip);
    bar.appendChild(title);
    bar.appendChild(close);
    bar.addEventListener('pointerdown', (e) => this._startDrag(e));
    box.appendChild(bar);

    // ── the 5×4 swatch grid ──────────────────────────────────
    const grid = doc.createElement('div');
    grid.className = 'cp-grid';
    const current = String(this._opts.color || '').toLowerCase();
    this.COLORS.forEach((entry) => {
      const dot = doc.createElement('button');
      dot.type = 'button';
      dot.className = 'cp-dot' +
        (entry.hex.toLowerCase() === current ? ' selected' : '');
      dot.style.background = entry.hex;
      dot.dataset.color = entry.hex;
      dot.title = entry.name + ' — ' + entry.hex;
      dot.setAttribute('aria-label', entry.name);
      dot.addEventListener('click', () => this.pick(entry.hex));
      grid.appendChild(dot);
    });
    box.appendChild(grid);

    // ── footer ───────────────────────────────────────────────
    const foot = doc.createElement('div');
    foot.className = 'cp-foot';
    const hint = doc.createElement('span');
    hint.className = 'cp-hint';
    hint.textContent = 'Click a colour to use it';
    const cancel = doc.createElement('button');
    cancel.type = 'button';
    cancel.className = 'cp-cancel btn-small';
    cancel.textContent = 'Cancel';
    cancel.addEventListener('click', () => this.cancel());
    foot.appendChild(hint);
    foot.appendChild(cancel);
    box.appendChild(foot);

    doc.body.appendChild(box);
    this.el = box;
    this._place(this._opts.anchor);

    this._onKey = (e) => { if (e.key === 'Escape') this.cancel(); };
    doc.addEventListener('keydown', this._onKey);
    return box;
  },

  /** Position: last parked spot, else next to the anchor, else centred. */
  _place(anchor) {
    const box = this.el;
    if (!box) return;
    let left, top;
    if (this._pos) {
      left = this._pos.left;
      top = this._pos.top;
    } else if (anchor && anchor.getBoundingClientRect) {
      const r = anchor.getBoundingClientRect();
      left = r.left;
      top = r.bottom + 6;
    } else {
      left = Math.max(12, (window.innerWidth - this.WIDTH) / 2);
      top = Math.max(12, (window.innerHeight - this.HEIGHT) / 2);
    }
    const clamped = this._clamp(left, top);
    box.style.left = clamped.left + 'px';
    box.style.top = clamped.top + 'px';
  },

  _clamp(left, top) {
    const w = window.innerWidth || 1200;
    const h = window.innerHeight || 800;
    const bw = (this.el && this.el.offsetWidth) || this.WIDTH;
    const bh = (this.el && this.el.offsetHeight) || this.HEIGHT;
    return {
      left: Math.min(Math.max(4, left), Math.max(4, w - bw - 4)),
      top: Math.min(Math.max(4, top), Math.max(4, h - bh - 4)),
    };
  },

  // ── dragging ────────────────────────────────────────────────
  _startDrag(event) {
    if (!this.el || (event.target && event.target.closest &&
                     event.target.closest('.cp-close'))) return;
    const rect = this.el.getBoundingClientRect();
    this._drag = {
      dx: event.clientX - rect.left,
      dy: event.clientY - rect.top,
      move: (e) => this._onDrag(e),
      up: () => this._endDrag(),
    };
    this.el.classList.add('dragging');
    document.addEventListener('pointermove', this._drag.move);
    document.addEventListener('pointerup', this._drag.up);
    if (event.preventDefault) event.preventDefault();
  },

  _onDrag(event) {
    if (!this._drag || !this.el) return;
    const spot = this._clamp(event.clientX - this._drag.dx,
                             event.clientY - this._drag.dy);
    this.el.style.left = spot.left + 'px';
    this.el.style.top = spot.top + 'px';
    this._pos = spot;
  },

  _endDrag() {
    if (!this._drag) return;
    document.removeEventListener('pointermove', this._drag.move);
    document.removeEventListener('pointerup', this._drag.up);
    this._drag = null;
    if (this.el) this.el.classList.remove('dragging');
  },

  // ── outcomes ────────────────────────────────────────────────
  pick(hex) {
    const opts = this._opts || {};
    // Show the ring before the popup goes away, so the click is visibly
    // acknowledged even on a slow frame.
    if (this.el) {
      this.el.querySelectorAll('.cp-dot').forEach((dot) => {
        dot.classList.toggle('selected', dot.dataset.color === hex);
      });
    }
    this.close(true);
    if (typeof opts.onPick === 'function') opts.onPick(hex);
    return hex;
  },

  cancel() {
    const opts = this._opts || {};
    this.close(true);
    if (typeof opts.onCancel === 'function') opts.onCancel();
  },

  close(silent) {
    this._endDrag();
    if (this._onKey) {
      document.removeEventListener('keydown', this._onKey);
      this._onKey = null;
    }
    if (this.el && this.el.parentNode) this.el.parentNode.removeChild(this.el);
    this.el = null;
    if (!silent) this._opts = null;
  },
};

if (typeof window !== 'undefined') window.ColorPicker = ColorPicker;
if (typeof module === 'object' && module.exports) module.exports = ColorPicker;
