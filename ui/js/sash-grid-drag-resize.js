/* sash-grid part — sash-grid-drag-resize.js (bug5 sash fix)

Sash resize with pixel allocation, ≤250 LOC.
*/

const SashGridResize = {
  _startResize(sashEl, ev) {
    const pEl = sashEl.parentElement;
    if (!pEl || !pEl.classList.contains('sash-split')) return;
    const sIdx = parseInt(sashEl.dataset.idx, 10);
    const isRow = pEl.classList.contains('sash-row');
    const childEls = [];
    for (let i = 0; i * 2 < pEl.children.length; i++) childEls.push(pEl.children[i * 2]);
    const axisSize = (el) => { const r = el.getBoundingClientRect(); return isRow ? r.width : r.height; };
    const childSizes = childEls.map(axisSize);
    const sashSizes = Array.from(pEl.children).filter((el) => el.classList.contains('sash')).map(axisSize);
    const z = { pEl, sashEl, sIdx, isRow, childEls, pointerId: ev.pointerId, childSizes, sashSizes, otherWidths: {}, originalFlex: childEls.map((child) => child.style.flex), pointerCaptured: false };
    for (let i = 0; i < childSizes.length; i++) { if (i === sIdx || i === sIdx + 1) continue; z.otherWidths[i] = childSizes[i]; }
    this._resize = z;
    if (ev.pointerId != null && typeof sashEl.setPointerCapture === 'function') {
      try { sashEl.setPointerCapture(ev.pointerId); z.pointerCaptured = true; } catch (e) {}
    }
    sashEl.classList.add('sash-active');
    document.body.classList.add(isRow ? 'sash-resizing-row' : 'sash-resizing-col');
    this._onResizeMove = this._resizeMove.bind(this);
    this._onResizeUp = this._resizeUp.bind(this);
    document.addEventListener('pointermove', this._onResizeMove, { passive: false });
    document.addEventListener('pointerup', this._onResizeUp);
    document.addEventListener('pointercancel', this._onResizeCancel = () => this._cancelResize(true));
    document.addEventListener('keydown', this._onResizeKey = (keyEvent) => {
      if (keyEvent.key === 'Escape') { keyEvent.preventDefault(); this._cancelResize(true); }
    }, true);
    ev.preventDefault();
  },

  _resizePixelAllocation(z, pointer, rect) {
    const axis = z.isRow ? rect.width : rect.height;
    const sashTotal = z.sashSizes.reduce((sum, size) => sum + Math.max(0, size), 0);
    let others = 0;
    for (const k of Object.keys(z.otherWidths)) others += Math.max(0, z.otherWidths[k]);
    const span = axis - others - sashTotal;
    if (span < this.MIN_PX * 2) return null;
    let prefix = 0;
    for (let i = 0; i < z.sIdx; i++) { prefix += Math.max(0, z.childSizes[i]); prefix += Math.max(0, z.sashSizes[i] || 0); }
    const start = (z.isRow ? rect.left : rect.top) + prefix;
    const requested = pointer - start;
    const first = Math.min(Math.max(requested, this.MIN_PX), span - this.MIN_PX);
    const allocation = z.childSizes.slice();
    allocation[z.sIdx] = first;
    allocation[z.sIdx + 1] = span - first;
    return allocation;
  },

  _resizeMove(ev) {
    const z = this._resize;
    if (!z) return;
    ev.preventDefault();
    const rect = z.pEl.getBoundingClientRect();
    const allocation = this._resizePixelAllocation(z, z.isRow ? ev.clientX : ev.clientY, rect);
    if (!allocation) return;
    z.childEls.forEach((child, i) => { const px = allocation[i]; child.style.flex = px > 0 ? `0 0 ${px}px` : '0 0 0px'; });
  },

  _resizeUp() {
    const z = this._resize;
    if (!z) return;
    this._cancelResize(false);
    const rect = z.pEl.getBoundingClientRect();
    const total = z.isRow ? rect.width : rect.height;
    const sashTotal = z.sashSizes.reduce((sum, size) => sum + Math.max(0, size), 0);
    const denom = Math.max(1, total - sashTotal);
    const path = this._parsePath(z.pEl.dataset.path);
    const p = SashCore.nodeAtPath(this.root, path);
    const prev = p ? p.sizes : null;
    const sizes = z.childEls.map((el, i) => {
      const r = el.getBoundingClientRect();
      const w = z.isRow ? r.width : r.height;
      if (w > 1) return (Math.max(w, this.MIN_PX) / denom) * 100;
      return prev ? prev[i] : 100 / z.childEls.length;
    });
    this.root = SashCore.setSplitSizesByPath(this.root, path, sizes);
    this.render();
    this._save();
    if (typeof LogConsole !== 'undefined') LogConsole.log('📏 Grid resized', 'info');
  },

  _cancelResize(restore = true) {
    const z = this._resize;
    if (!z) return;
    document.removeEventListener('pointermove', this._onResizeMove, { passive: false });
    document.removeEventListener('pointerup', this._onResizeUp);
    document.removeEventListener('pointercancel', this._onResizeCancel);
    document.removeEventListener('keydown', this._onResizeKey, true);
    if (restore) z.childEls.forEach((child, i) => { child.style.flex = z.originalFlex[i]; });
    if (z.pointerCaptured && typeof z.sashEl.releasePointerCapture === 'function') {
      try { z.sashEl.releasePointerCapture(z.pointerId); } catch (e) {}
    }
    z.sashEl.classList.remove('sash-active');
    document.body.classList.remove('sash-resizing-row', 'sash-resizing-col');
    this._resize = null;
  },

  _onDblClick(ev) {
    const sashEl = ev.target.closest('.sash');
    if (!sashEl) return;
    const pEl = sashEl.parentElement;
    if (!pEl || !pEl.classList.contains('sash-split')) return;
    const n = (pEl.children.length + 1) / 2;
    const path = this._parsePath(pEl.dataset.path);
    this.root = SashCore.setSplitSizesByPath(this.root, path, new Array(n).fill(100 / n));
    this.render();
    this._save();
    if (typeof LogConsole !== 'undefined') LogConsole.log('📏 Split reset to even sizes', 'info');
  },

  simulateResize(pathStr, firstPct) {
    const path = this._parsePath(pathStr);
    const p = SashCore.nodeAtPath(this.root, path);
    if (!p) throw new Error('simulateResize: bad path ' + pathStr);
    const sizes = p.sizes.slice();
    const min = SashCore.MIN_SIZE || 4;
    const maxFirst = 100 - min * (sizes.length - 1);
    sizes[0] = Math.max(min, Math.min(Number(firstPct) || min, maxFirst));
    const rest = 100 - sizes[0];
    const restSum = sizes.slice(1).reduce((a, b) => a + b, 0) || 1;
    for (let i = 1; i < sizes.length; i++) sizes[i] = rest * (sizes[i] / restSum);
    this.root = SashCore.setSplitSizesByPath(this.root, path, sizes);
    this.render();
    this._save();
    return this.getTree();
  },
};
