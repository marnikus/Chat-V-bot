/* stack-drag-visual.js — visuals + move + target for StackDrag facade (H-B2b JS split)

Design: ≤250 LOC.
*/

'use strict';

const StackDragVisual = {
  _begin(ev) {
    const st = this._state; const cfg = this._cfg; st.active = true;
    st.rects = st.items.map((el) => el.getBoundingClientRect());
    const r = st.rects[st.from]; st.grabDX = st.startX - r.left; st.grabDY = st.startY - r.top; st.height = r.height;
    st.gap = parseFloat(getComputedStyle(cfg.container).rowGap || '0') || 0; st.step = st.height + st.gap;
    const clone = st.item.cloneNode(true); clone.classList.add('dnd-clone'); clone.classList.remove('active', 'block-running');
    clone.style.width = r.width + 'px'; clone.style.height = r.height + 'px'; clone.style.left = '0px'; clone.style.top = '0px'; clone.style.transform = `translate3d(${r.left}px, ${r.top}px, 0)`; document.body.appendChild(clone); st.clone = clone;
    const bar = document.createElement('div'); bar.className = 'dnd-insert-bar'; bar.innerHTML = '<span class="dnd-insert-cap"></span><span class="dnd-insert-line"></span><span class="dnd-insert-cap"></span>'; document.body.appendChild(bar); st.bar = bar;
    const badge = document.createElement('div'); badge.className = 'dnd-badge'; document.body.appendChild(badge); st.badge = badge;
    st.item.classList.add('dnd-source'); document.body.classList.add('dnd-active'); cfg.container.classList.add('dnd-dragging'); st.items.forEach((el) => el.classList.add('dnd-sliding'));
  },

  _pointerMove(ev) {
    const st = this._state; if (!st) return;
    if (!st.active) { if (Math.abs(ev.clientX - st.startX) < this.THRESHOLD && Math.abs(ev.clientY - st.startY) < this.THRESHOLD) return; this._begin(ev); }
    ev.preventDefault(); st.moved = true; st.lastX = ev.clientX; st.lastY = ev.clientY;
    st.clone.style.transform = `translate3d(${ev.clientX - st.grabDX}px, ${ev.clientY - st.grabDY}px, 0)`;
    this._updateTarget(ev.clientY); this._autoScroll(ev.clientY);
  },

  _updateTarget(clientY) {
    const st = this._state; let to = 0;
    for (let i = 0; i < st.items.length; i++) { if (i === st.from) continue; const r = st.rects[i]; if (clientY > r.top + r.height / 2) to++; else break; }
    to = Math.max(0, Math.min(st.items.length - 1, to));
    if (to !== st.to) { st.to = to; if (this._cfg.onPreview) this._cfg.onPreview(st.from, to); }
    this._applySlide(); this._placeBar(); this._placeBadge();
  },

  _applySlide() {
    const st = this._state;
    for (let i = 0; i < st.items.length; i++) {
      if (i === st.from) continue; const el = st.items[i]; let dy = 0;
      if (st.to > st.from && i > st.from && i <= st.to) dy = -st.step;
      else if (st.to < st.from && i >= st.to && i < st.from) dy = st.step;
      el.style.transform = dy ? `translate3d(0, ${dy}px, 0)` : ''; el.classList.toggle('dnd-shifted', dy !== 0);
    }
  },

  _slotTop() {
    const st = this._state; if (st.to === st.from) return st.rects[st.from].top;
    if (st.to > st.from) return st.rects[st.to].bottom - st.height; return st.rects[st.to].top;
  },

  _placeBar() {
    const st = this._state; const cRect = this._cfg.container.getBoundingClientRect(); const y = this._slotTop() - st.gap / 2;
    const top = Math.max(cRect.top + 1, Math.min(cRect.bottom - 3, y));
    st.bar.style.transform = `translate3d(${cRect.left + 6}px, ${top}px, 0)`; st.bar.style.width = (cRect.width - 12) + 'px'; st.bar.classList.toggle('dnd-insert-same', st.to === st.from);
  },

  _placeBadge() {
    const st = this._state; const label = this._cfg.labelOf ? this._cfg.labelOf(st.from) : '';
    st.badge.textContent = `${label ? label + '  ' : ''}${st.from + 1} → ${st.to + 1}`; st.badge.classList.toggle('dnd-badge-same', st.to === st.from);
    st.badge.style.transform = `translate3d(${st.lastX + 18}px, ${st.lastY + 18}px, 0)`;
  },

  _pointerUp() {
    const st = this._state; if (!st) return; if (!st.active) { this._teardownListeners(); this._state = null; return; }
    const { from, to } = st; const landY = this._slotTop(); st.clone.classList.add('dnd-clone-landing'); st.clone.style.transform = `translate3d(${st.rects[from].left}px, ${landY}px, 0)`;
    const finish = () => { this._cleanupVisuals(); this._state = null; if (to !== from && this._cfg && this._cfg.onReorder) this._cfg.onReorder(from, to); };
    if (st.moved) { const swallow = (e) => { e.stopPropagation(); e.preventDefault(); }; document.addEventListener('click', swallow, true); setTimeout(() => document.removeEventListener('click', swallow, true), 0); }
    this._teardownListeners(); setTimeout(finish, 130);
  },

  _cleanupVisuals() {
    const st = this._state; if (!st) return;
    if (st.scrollRAF) cancelAnimationFrame(st.scrollRAF);
    if (st.clone && st.clone.parentNode) st.clone.parentNode.removeChild(st.clone);
    if (st.bar && st.bar.parentNode) st.bar.parentNode.removeChild(st.bar);
    if (st.badge && st.badge.parentNode) st.badge.parentNode.removeChild(st.badge);
    (st.items || []).forEach((el) => { el.style.transform = ''; el.classList.remove('dnd-sliding', 'dnd-shifted', 'dnd-source'); });
    document.body.classList.remove('dnd-active'); if (this._cfg && this._cfg.container) this._cfg.container.classList.remove('dnd-dragging');
  },
};

if (typeof window !== 'undefined') window.StackDragVisual = StackDragVisual;
