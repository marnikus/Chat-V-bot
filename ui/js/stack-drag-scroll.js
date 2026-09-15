/* stack-drag-scroll.js — auto-scroll for StackDrag facade (H-B2b JS split)

Design: ≤150 LOC.
*/

'use strict';

const StackDragScroll = {
  _autoScroll(clientY) {
    const st = this._state; const c = this._cfg.container; const r = c.getBoundingClientRect(); const zone = 42; let speed = 0;
    if (clientY < r.top + zone) speed = -Math.ceil((r.top + zone - clientY) / 4);
    else if (clientY > r.bottom - zone) speed = Math.ceil((clientY - (r.bottom - zone)) / 4);
    st.scrollSpeed = Math.max(-18, Math.min(18, speed));
    if (st.scrollSpeed && !st.scrollRAF) {
      const tick = () => {
        if (!this._state || !this._state.active || !this._state.scrollSpeed) { if (this._state) this._state.scrollRAF = 0; return; }
        const before = c.scrollTop; c.scrollTop += this._state.scrollSpeed; const delta = c.scrollTop - before;
        if (delta) { this._state.rects.forEach((rc) => { rc.y -= delta; rc.top -= delta; rc.bottom -= delta; }); this._updateTarget(this._state.lastY); }
        this._state.scrollRAF = requestAnimationFrame(tick);
      };
      st.scrollRAF = requestAnimationFrame(tick);
    }
  },
};

if (typeof window !== 'undefined') window.StackDragScroll = StackDragScroll;
