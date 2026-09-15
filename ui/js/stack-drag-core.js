/* stack-drag-core.js — attach/detach + pointer down for StackDrag facade (H-B2b JS split)

Design: ≤200 LOC.
*/

'use strict';

const StackDragCore = {
  _cfg: null,
  _state: null,
  THRESHOLD: 4,
  SLIDE_MS: 180,

  attach(cfg) {
    this.detach();
    if (!cfg || !cfg.container) return;
    this._cfg = Object.assign({ handleSelector: null, ignoreSelector: null, onPreview: null, labelOf: null }, cfg);
    this._onPointerDown = this._pointerDown.bind(this);
    cfg.container.addEventListener('pointerdown', this._onPointerDown);
    cfg.container.classList.add('dnd-enabled');
  },

  detach() {
    if (this._cfg && this._cfg.container && this._onPointerDown) {
      this._cfg.container.removeEventListener('pointerdown', this._onPointerDown);
      this._cfg.container.classList.remove('dnd-enabled');
    }
    this._cancel(true); this._cfg = null;
  },

  get dragging() { return !!(this._state && this._state.active); },

  _pointerDown(ev) {
    if (this._state) return;
    if (ev.button !== undefined && ev.button !== 0) return;
    const cfg = this._cfg;
    const item = ev.target.closest(cfg.itemSelector);
    if (!item || !cfg.container.contains(item)) return;
    if (cfg.ignoreSelector && ev.target.closest(cfg.ignoreSelector)) return;
    if (cfg.handleSelector && !ev.target.closest(cfg.handleSelector)) return;
    const items = this._items();
    const from = items.indexOf(item);
    if (from < 0 || items.length < 2) return;
    this._state = { active: false, item, from, to: from, items, startX: ev.clientX, startY: ev.clientY, pointerId: ev.pointerId, moved: false, clone: null, bar: null, badge: null, grabDX: 0, grabDY: 0, rects: null, scrollRAF: 0, scrollSpeed: 0 };
    this._onMove = this._pointerMove.bind(this);
    this._onUp = this._pointerUp.bind(this);
    this._onKey = (e) => { if (e.key === 'Escape') this._cancel(); };
    document.addEventListener('pointermove', this._onMove, { passive: false });
    document.addEventListener('pointerup', this._onUp);
    document.addEventListener('pointercancel', this._onUp);
    document.addEventListener('keydown', this._onKey, true);
    try { item.setPointerCapture(ev.pointerId); } catch (e) {}
  },

  _items() { return Array.from(this._cfg.container.querySelectorAll(this._cfg.itemSelector)); },

  _teardownListeners() {
    document.removeEventListener('pointermove', this._onMove, { passive: false });
    document.removeEventListener('pointerup', this._onUp);
    document.removeEventListener('pointercancel', this._onUp);
    document.removeEventListener('keydown', this._onKey, true);
  },

  _cancel(silent) {
    const st = this._state; if (!st) return;
    this._teardownListeners(); this._cleanupVisuals(); this._state = null;
    if (!silent && typeof LogConsole !== 'undefined') LogConsole.log('↩ Drag cancelled — order unchanged', 'warn');
  },

  flashLanded(container, itemSelector, idx) {
    const el = container.querySelector(`${itemSelector}[data-idx=\"${idx}\"]`);
    if (!el) return;
    el.classList.remove('dnd-landed'); void el.offsetWidth; el.classList.add('dnd-landed'); setTimeout(() => el.classList.remove('dnd-landed'), 700);
  },
};

if (typeof window !== 'undefined') window.StackDragCore = StackDragCore;
