/* ═══════════════════════════════════════════════════════════════
   stack-drag.js — Dependency-free drag & drop reordering engine
   (FEATURE #6)

   Replaces the CDN-loaded SortableJS, which silently failed to load
   inside QWebEngineView on a file:// page (no onerror handler ⇒ drag
   simply did nothing, with no diagnostics).

   Built on Pointer Events + pointer capture:
     • the dragged card is lifted into a floating clone that follows
       the cursor 1:1 (scaled, tilted, glowing shadow)
     • the source position turns into a dashed "drop slot"
     • the other cards SLIDE apart (translateY) to open the gap at the
       prospective release position
     • a glowing insertion bar marks the exact landing slot
     • a badge next to the cursor shows "from → to"
     • edge auto-scroll, Escape to cancel, click-vs-drag disambiguation
     • indices come from data-idx, never from DOM child position
   ═══════════════════════════════════════════════════════════════ */

'use strict';

const StackDrag = {
  // ── configuration / live state ──────────────────────────────
  _cfg: null,
  _state: null,
  THRESHOLD: 4,          // px the pointer must travel before it is a drag
  SLIDE_MS: 180,

  /**
   * Attach the engine to a container.
   * @param {Object} cfg
   * @param {HTMLElement} cfg.container      scroll container holding the items
   * @param {string} cfg.itemSelector        e.g. '.stack-item'
   * @param {string} [cfg.handleSelector]    e.g. '.drag-handle' (null ⇒ whole card)
   * @param {string} [cfg.ignoreSelector]    controls that must not start a drag
   * @param {function(number,number)} cfg.onReorder   commit (from, to)
   * @param {function(number,number)} [cfg.onPreview] live preview (from, to)
   * @param {function(number):string} [cfg.labelOf]   label for the badge
   */
  attach(cfg) {
    this.detach();
    if (!cfg || !cfg.container) return;
    this._cfg = Object.assign({
      handleSelector: null,
      ignoreSelector: null,
      onPreview: null,
      labelOf: null,
    }, cfg);
    this._onPointerDown = this._pointerDown.bind(this);
    cfg.container.addEventListener('pointerdown', this._onPointerDown);
    cfg.container.classList.add('dnd-enabled');
  },

  detach() {
    if (this._cfg && this._cfg.container && this._onPointerDown) {
      this._cfg.container.removeEventListener('pointerdown', this._onPointerDown);
      this._cfg.container.classList.remove('dnd-enabled');
    }
    this._cancel(true);
    this._cfg = null;
  },

  get dragging() { return !!(this._state && this._state.active); },

  // ── pointer down: arm a potential drag ──────────────────────
  _pointerDown(ev) {
    if (this._state) return;
    if (ev.button !== undefined && ev.button !== 0) return;   // left button only
    const cfg = this._cfg;
    const item = ev.target.closest(cfg.itemSelector);
    if (!item || !cfg.container.contains(item)) return;
    if (cfg.ignoreSelector && ev.target.closest(cfg.ignoreSelector)) return;
    if (cfg.handleSelector && !ev.target.closest(cfg.handleSelector)) return;

    const items = this._items();
    const from = items.indexOf(item);
    if (from < 0 || items.length < 2) return;

    this._state = {
      active: false, item, from, to: from, items,
      startX: ev.clientX, startY: ev.clientY,
      pointerId: ev.pointerId, moved: false,
      clone: null, bar: null, badge: null,
      grabDX: 0, grabDY: 0, rects: null,
      scrollRAF: 0, scrollSpeed: 0,
    };

    this._onMove = this._pointerMove.bind(this);
    this._onUp = this._pointerUp.bind(this);
    this._onKey = (e) => { if (e.key === 'Escape') this._cancel(); };
    document.addEventListener('pointermove', this._onMove, { passive: false });
    document.addEventListener('pointerup', this._onUp);
    document.addEventListener('pointercancel', this._onUp);
    document.addEventListener('keydown', this._onKey, true);
    try { item.setPointerCapture(ev.pointerId); } catch (e) { /* ignore */ }
  },

  _items() {
    return Array.from(
      this._cfg.container.querySelectorAll(this._cfg.itemSelector));
  },

  // ── first real movement: build the drag visuals ─────────────
  _begin(ev) {
    const st = this._state;
    const cfg = this._cfg;
    st.active = true;

    // cache geometry BEFORE anything is transformed
    st.rects = st.items.map((el) => el.getBoundingClientRect());
    const r = st.rects[st.from];
    st.grabDX = st.startX - r.left;
    st.grabDY = st.startY - r.top;
    st.height = r.height;
    const style = getComputedStyle(st.item);
    st.gap = parseFloat(getComputedStyle(cfg.container).rowGap || '0') || 0;
    st.step = st.height + st.gap;

    // floating clone that follows the cursor
    const clone = st.item.cloneNode(true);
    clone.classList.add('dnd-clone');
    clone.classList.remove('active', 'block-running');
    clone.style.width = r.width + 'px';
    clone.style.height = r.height + 'px';
    clone.style.left = '0px';
    clone.style.top = '0px';
    clone.style.transform = `translate3d(${r.left}px, ${r.top}px, 0)`;
    document.body.appendChild(clone);
    st.clone = clone;

    // insertion bar (marks the slot that will be taken on release)
    const bar = document.createElement('div');
    bar.className = 'dnd-insert-bar';
    bar.innerHTML = '<span class="dnd-insert-cap"></span>' +
                    '<span class="dnd-insert-line"></span>' +
                    '<span class="dnd-insert-cap"></span>';
    document.body.appendChild(bar);
    st.bar = bar;

    // "3 → 5" badge that follows the cursor
    const badge = document.createElement('div');
    badge.className = 'dnd-badge';
    document.body.appendChild(badge);
    st.badge = badge;

    // source card becomes an empty, dashed drop slot
    st.item.classList.add('dnd-source');
    document.body.classList.add('dnd-active');
    cfg.container.classList.add('dnd-dragging');
    st.items.forEach((el) => el.classList.add('dnd-sliding'));
  },

  // ── pointer move ────────────────────────────────────────────
  _pointerMove(ev) {
    const st = this._state;
    if (!st) return;
    if (!st.active) {
      if (Math.abs(ev.clientX - st.startX) < this.THRESHOLD &&
          Math.abs(ev.clientY - st.startY) < this.THRESHOLD) return;
      this._begin(ev);
    }
    ev.preventDefault();
    st.moved = true;
    st.lastX = ev.clientX;
    st.lastY = ev.clientY;

    // clone follows the cursor exactly where it was grabbed
    st.clone.style.transform =
      `translate3d(${ev.clientX - st.grabDX}px, ${ev.clientY - st.grabDY}px, 0)`;

    this._updateTarget(ev.clientY);
    this._autoScroll(ev.clientY);
  },

  /** Decide which slot the block would take if released now. */
  _updateTarget(clientY) {
    const st = this._state;
    // target = number of *other* cards whose midpoint is above the pointer
    let to = 0;
    for (let i = 0; i < st.items.length; i++) {
      if (i === st.from) continue;
      const r = st.rects[i];
      if (clientY > r.top + r.height / 2) to++;
      else break;
    }
    to = Math.max(0, Math.min(st.items.length - 1, to));
    if (to !== st.to) {
      st.to = to;
      if (this._cfg.onPreview) this._cfg.onPreview(st.from, to);
    }
    this._applySlide();
    this._placeBar();
    this._placeBadge();
  },

  /** Slide the other cards to open a visible gap at the target slot. */
  _applySlide() {
    const st = this._state;
    for (let i = 0; i < st.items.length; i++) {
      if (i === st.from) continue;
      const el = st.items[i];
      let dy = 0;
      // moving down: cards between from+1..to shift UP by one step
      if (st.to > st.from && i > st.from && i <= st.to) dy = -st.step;
      // moving up: cards between to..from-1 shift DOWN by one step
      else if (st.to < st.from && i >= st.to && i < st.from) dy = st.step;
      el.style.transform = dy ? `translate3d(0, ${dy}px, 0)` : '';
      el.classList.toggle('dnd-shifted', dy !== 0);
    }
  },

  /**
   * Top edge (viewport px) of the slot the block will occupy on release.
   * Cards keep their pre-drag rects; the slide transforms are applied on top:
   *  · to > from → cards from+1..to shifted UP by one step, gap opens so the
   *    block's bottom lands exactly on rects[to].bottom
   *  · to < from → cards to..from-1 shifted DOWN, block lands on rects[to].top
   */
  _slotTop() {
    const st = this._state;
    if (st.to === st.from) return st.rects[st.from].top;
    if (st.to > st.from) return st.rects[st.to].bottom - st.height;
    return st.rects[st.to].top;
  },

  /** Glowing bar exactly where the block will land. */
  _placeBar() {
    const st = this._state;
    const cRect = this._cfg.container.getBoundingClientRect();
    const y = this._slotTop() - st.gap / 2;   // draw inside the opened gap
    // clamp inside the visible container
    const top = Math.max(cRect.top + 1, Math.min(cRect.bottom - 3, y));
    st.bar.style.transform = `translate3d(${cRect.left + 6}px, ${top}px, 0)`;
    st.bar.style.width = (cRect.width - 12) + 'px';
    st.bar.classList.toggle('dnd-insert-same', st.to === st.from);
  },

  _placeBadge() {
    const st = this._state;
    const label = this._cfg.labelOf ? this._cfg.labelOf(st.from) : '';
    st.badge.textContent =
      `${label ? label + '  ' : ''}${st.from + 1} → ${st.to + 1}`;
    st.badge.classList.toggle('dnd-badge-same', st.to === st.from);
    st.badge.style.transform =
      `translate3d(${st.lastX + 18}px, ${st.lastY + 18}px, 0)`;
  },

  // ── auto-scroll near the container edges ────────────────────
  _autoScroll(clientY) {
    const st = this._state;
    const c = this._cfg.container;
    const r = c.getBoundingClientRect();
    const zone = 42;
    let speed = 0;
    if (clientY < r.top + zone) speed = -Math.ceil((r.top + zone - clientY) / 4);
    else if (clientY > r.bottom - zone) speed = Math.ceil((clientY - (r.bottom - zone)) / 4);
    st.scrollSpeed = Math.max(-18, Math.min(18, speed));
    if (st.scrollSpeed && !st.scrollRAF) {
      const tick = () => {
        if (!this._state || !this._state.active || !this._state.scrollSpeed) {
          if (this._state) this._state.scrollRAF = 0;
          return;
        }
        const before = c.scrollTop;
        c.scrollTop += this._state.scrollSpeed;
        const delta = c.scrollTop - before;
        if (delta) {
          // rects are viewport-based → shift them with the scroll
          this._state.rects.forEach((rc) => {
            rc.y -= delta; rc.top -= delta; rc.bottom -= delta;
          });
          this._updateTarget(this._state.lastY);
        }
        this._state.scrollRAF = requestAnimationFrame(tick);
      };
      st.scrollRAF = requestAnimationFrame(tick);
    }
  },

  // ── release: animate home, then commit ──────────────────────
  _pointerUp() {
    const st = this._state;
    if (!st) return;
    if (!st.active) { this._teardownListeners(); this._state = null; return; }

    const { from, to } = st;
    // animate the clone into the resolved slot before committing
    const landY = this._slotTop();
    st.clone.classList.add('dnd-clone-landing');
    st.clone.style.transform =
      `translate3d(${st.rects[from].left}px, ${landY}px, 0)`;

    const finish = () => {
      this._cleanupVisuals();
      this._state = null;
      if (to !== from && this._cfg && this._cfg.onReorder) {
        this._cfg.onReorder(from, to);
      }
    };
    // suppress the click that follows a real drag
    if (st.moved) {
      const swallow = (e) => { e.stopPropagation(); e.preventDefault(); };
      document.addEventListener('click', swallow, true);
      setTimeout(() => document.removeEventListener('click', swallow, true), 0);
    }
    this._teardownListeners();
    setTimeout(finish, 130);
  },

  _cancel(silent) {
    const st = this._state;
    if (!st) return;
    this._teardownListeners();
    this._cleanupVisuals();
    this._state = null;
    if (!silent && typeof LogConsole !== 'undefined') {
      LogConsole.log('↩ Drag cancelled — order unchanged', 'warn');
    }
  },

  _teardownListeners() {
    document.removeEventListener('pointermove', this._onMove, { passive: false });
    document.removeEventListener('pointerup', this._onUp);
    document.removeEventListener('pointercancel', this._onUp);
    document.removeEventListener('keydown', this._onKey, true);
  },

  _cleanupVisuals() {
    const st = this._state;
    if (!st) return;
    if (st.scrollRAF) cancelAnimationFrame(st.scrollRAF);
    if (st.clone && st.clone.parentNode) st.clone.parentNode.removeChild(st.clone);
    if (st.bar && st.bar.parentNode) st.bar.parentNode.removeChild(st.bar);
    if (st.badge && st.badge.parentNode) st.badge.parentNode.removeChild(st.badge);
    (st.items || []).forEach((el) => {
      el.style.transform = '';
      el.classList.remove('dnd-sliding', 'dnd-shifted', 'dnd-source');
    });
    document.body.classList.remove('dnd-active');
    if (this._cfg && this._cfg.container) {
      this._cfg.container.classList.remove('dnd-dragging');
    }
  },

  /** Flash a freshly dropped item so the landing is unmistakable. */
  flashLanded(container, itemSelector, idx) {
    const el = container.querySelector(`${itemSelector}[data-idx="${idx}"]`);
    if (!el) return;
    el.classList.remove('dnd-landed');
    void el.offsetWidth;                 // restart the animation
    el.classList.add('dnd-landed');
    setTimeout(() => el.classList.remove('dnd-landed'), 700);
  },
};
