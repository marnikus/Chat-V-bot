/* sash-grid part — sash-grid-drag.js (Round H, H-A3) */

const SashGridDrag = {
  _pointerDown(ev) {
    if (ev.button !== 0) return;
    if (this._drag || this._resize) return;
    const sashEl = ev.target.closest('.sash');
    if (sashEl) { this._startResize(sashEl, ev); return; }
    const title = ev.target.closest('.win-title');
    if (!title || !this.gridEl.contains(title)) return;
    if (ev.target.closest('button, input, select, textarea, a, .chip, .win-controls, .win-btn')) return;
    const winEl = title.closest('.sash-window');
    if (!winEl) return;
    if (winEl.classList.contains('sash-win-hidden') || winEl.classList.contains('sash-win-closed')) return;
    this._startDrag(winEl, ev);
  },

  _startDrag(winEl, ev) {
    this._drag = {
      active: false, winEl, id: winEl.dataset.win,
      startX: ev.clientX, startY: ev.clientY, pointerId: ev.pointerId,
      lastX: ev.clientX, lastY: ev.clientY,
      clone: null, badge: null, indicator: null,
      rects: null, sashes: null,
      lastSpec: null, lastSpecKey: null, targetEl: null,
    };
    this._onDragMove = this._dragMove.bind(this);
    this._onDragUp = this._dragUp.bind(this);
    this._onDragKey = (e) => { if (e.key === 'Escape') this._cancelDrag(); };
    document.addEventListener('pointermove', this._onDragMove, { passive: false });
    document.addEventListener('pointerup', this._onDragUp);
    document.addEventListener('pointercancel', this._onDragCancel = this._cancelDrag.bind(this));
    document.addEventListener('keydown', this._onDragKey, true);
  },

  _beginDrag() {
    const d = this._drag;
    d.active = true;
    this._cacheDragRects();
    const rect = d.winEl.getBoundingClientRect();
    d.clone = this._buildDragVisual(d.winEl, d.id, rect);
    d.clone.style.transform = 'translate3d(' + rect.left + 'px,' + rect.top + 'px,0)';
    this._createDragVisuals();
    d.winEl.classList.add('sash-drag-source');
    document.body.classList.add('sash-dragging');
  },

  _cacheDragRects() {
    const d = this._drag;
    d.rects = {};
    this.gridEl.querySelectorAll('.sash-window').forEach((w) => {
      if (w.classList.contains('sash-win-hidden') || w.classList.contains('sash-win-closed')) return;
      if (!w.offsetWidth || !w.offsetHeight) return;
      d.rects[w.dataset.win] = w.getBoundingClientRect();
    });
    d.sashes = [];
    this.gridEl.querySelectorAll('.sash').forEach((s) => {
      if (!s.offsetWidth && !s.offsetHeight) return;
      if (s.classList.contains('sash-hidden')) return;
      d.sashes.push({
        el: s, rect: s.getBoundingClientRect(),
        leftId: this._winIdOf(s.parentElement.children[+s.dataset.idx * 2]),
        rightId: this._winIdOf(s.parentElement.children[+s.dataset.idx * 2 + 2]),
      });
    });
  },

  _createDragVisuals() {
    const d = this._drag;
    d.badge = document.createElement('div');
    d.badge.className = 'sash-drag-badge';
    document.body.appendChild(d.badge);
    d.indicator = document.createElement('div');
    d.indicator.className = 'sash-drop-indicator';
    d.indicator.style.display = 'none';
    document.body.appendChild(d.indicator);
  },

  _buildDragVisual(winEl, id, rect) {
    if (winEl.querySelectorAll('*').length < 350) {
      const c = winEl.cloneNode(true);
      c.classList.add('sash-drag-clone');
      c.style.width = rect.width + 'px';
      c.style.height = rect.height + 'px';
      document.body.appendChild(c);
      return c;
    }
    const g = document.createElement('div');
    g.className = 'sash-drag-ghost';
    g.innerHTML = '<span style=\"font-size:18px\">◫</span><span>' + (SashCore.WINDOW_TITLES[id] || id) + '</span>';
    document.body.appendChild(g);
    return g;
  },

  _winIdOf(el) {
    if (!el) return null;
    if (el.dataset && el.dataset.win) return el.dataset.win;
    const inner = el && el.querySelector ? el.querySelector('.sash-window') : null;
    return inner ? inner.dataset.win : null;
  },

  _dragMove(ev) {
    const d = this._drag;
    if (!d) return;
    if (!d.active) {
      if (Math.abs(ev.clientX - d.startX) < this.THRESHOLD && Math.abs(ev.clientY - d.startY) < this.THRESHOLD) return;
      this._beginDrag();
    }
    ev.preventDefault();
    d.lastX = ev.clientX;
    d.lastY = ev.clientY;
    if (d.clone.classList.contains('sash-drag-ghost')) {
      d.clone.style.transform = 'translate3d(' + (ev.clientX + 14) + 'px,' + (ev.clientY + 14) + 'px,0)';
    } else {
      const r = d.winEl.getBoundingClientRect();
      const dx = d.startX - r.left, dy = d.startY - r.top;
      d.clone.style.transform = 'translate3d(' + (ev.clientX - dx) + 'px,' + (ev.clientY - dy) + 'px,0)';
    }
    const spec = this._computeSpec(ev.clientX, ev.clientY);
    const key = spec ? JSON.stringify(spec) : '';
    if (key !== d.lastSpecKey) {
      d.lastSpecKey = key;
      d.lastSpec = spec;
      this._showSpec(spec);
    }
  },

  _dragUp() {
    const d = this._drag;
    if (!d) return;
    const spec = d.active ? d.lastSpec : null;
    this._cleanupDrag();
    if (spec) {
      this._applyDrop(d.id, spec);
      this.render();
      this._save();
      this._flashLanded(d.id);
      if (typeof LogConsole !== 'undefined') LogConsole.log('🧩 ' + (SashCore.WINDOW_TITLES[d.id] || d.id) + ' → ' + this._specText(spec) + ' (grid updated)', 'info');
    } else if (d.active) {
      if (typeof LogConsole !== 'undefined') LogConsole.log('↩ Window drag cancelled — layout unchanged', 'warn');
    }
  },

  _cancelDrag() {
    const d = this._drag;
    if (!d) return;
    this._cleanupDrag();
    if (d.active && typeof LogConsole !== 'undefined') LogConsole.log('↩ Window drag cancelled — layout unchanged', 'warn');
  },

  _cleanupDrag() {
    const d = this._drag;
    if (!d) return;
    document.removeEventListener('pointermove', this._onDragMove, { passive: false });
    document.removeEventListener('pointerup', this._onDragUp);
    document.removeEventListener('pointercancel', this._onDragCancel);
    document.removeEventListener('keydown', this._onDragKey, true);
    if (d.clone && d.clone.parentNode) d.clone.parentNode.removeChild(d.clone);
    if (d.badge && d.badge.parentNode) d.badge.parentNode.removeChild(d.badge);
    if (d.indicator && d.indicator.parentNode) d.indicator.parentNode.removeChild(d.indicator);
    if (d.targetEl) d.targetEl.classList.remove('sash-drag-target');
    this.gridEl.querySelectorAll('.sash-target').forEach((s) => s.classList.remove('sash-target'));
    if (d.winEl && d.winEl.isConnected) d.winEl.classList.remove('sash-drag-source');
    document.body.classList.remove('sash-dragging');
    this._drag = null;
  },

  _flashLanded(winId) {
    const el = this.gridEl.querySelector('.sash-window[data-win=\"' + winId + '\"]');
    if (!el) return;
    el.classList.remove('sash-landed');
    void el.offsetWidth;
    el.classList.add('sash-landed');
    setTimeout(() => el.classList.remove('sash-landed'), 700);
  },

  simulateDrop(draggedId, targetId, zone) {
    const drop =
      zone === 'before' ? { kind: 'sibling', target: targetId, side: 'before' } :
      zone === 'after'  ? { kind: 'sibling', target: targetId, side: 'after' } :
      zone === 'left'   ? { kind: 'edge', target: targetId, dir: 'row', newFirst: true } :
      zone === 'right'  ? { kind: 'edge', target: targetId, dir: 'row', newFirst: false } :
      zone === 'top'    ? { kind: 'edge', target: targetId, dir: 'col', newFirst: true } :
      zone === 'bottom' ? { kind: 'edge', target: targetId, dir: 'col', newFirst: false } :
                          (() => { throw new Error('simulateDrop: bad zone ' + zone); })();
    this.root = SashCore.moveWindow(this.root, draggedId, drop);
    this.render();
    this._save();
    return this.getTree();
  },
};


const SashGridSpec = {
  _computeSpec(x, y) {
    const d = this._drag;
    for (const id of Object.keys(d.rects)) {
      if (id === d.id) continue;
      const r = d.rects[id];
      if (x < r.left || x >= r.right || y < r.top || y >= r.bottom) continue;
      const edge = this._edgeZoneSpec(id, r, x, y);
      if (edge) return edge;
      return this._centerSpec(id, r, x, y);
    }
    return this._sashSpec(x, y);
  },

  _edgeZoneSpec(id, r, x, y) {
    const Z = Math.min(44, Math.max(20, 0.22 * Math.min(r.width, r.height)));
    let zone = 'center';
    if (x < r.left + Z) zone = 'left';
    else if (x > r.right - Z) zone = 'right';
    else if (y < r.top + Z) zone = 'top';
    else if (y > r.bottom - Z) zone = 'bottom';
    if (zone === 'center') return null;
    const dir = (zone === 'left' || zone === 'right') ? 'row' : 'col';
    return { kind: 'edge', target: id, zone, dir, newFirst: (zone === 'left' || zone === 'top') };
  },

  _centerSpec(id, r, x, y) {
    const tEl = this.gridEl.querySelector('.sash-window[data-win="' + id + '"]');
    const pEl = tEl && tEl.parentElement;
    if (!pEl || !pEl.classList.contains('sash-split')) {
      const midX = r.left + r.width / 2, midY = r.top + r.height / 2;
      const dir = Math.abs(x - midX) / (r.width / 2) >= Math.abs(y - midY) / (r.height / 2) ? 'row' : 'col';
      const newFirst = dir === 'row' ? x < midX : y < midY;
      return { kind: 'edge', target: id, zone: dir === 'row' ? (newFirst ? 'left' : 'right') : (newFirst ? 'top' : 'bottom'), dir, newFirst };
    }
    const isRow = pEl.classList.contains('sash-row');
    const side = isRow ? (x < r.left + r.width / 2 ? 'before' : 'after') : (y < r.top + r.height / 2 ? 'before' : 'after');
    return { kind: 'sibling', target: id, side, zone: side === 'before' ? (isRow ? 'left' : 'top') : (isRow ? 'right' : 'bottom') };
  },

  _sashSpec(x, y) {
    for (const s of this._drag.sashes) {
      const r = s.rect;
      if (x < r.left || x >= r.right || y < r.top || y >= r.bottom) continue;
      return { kind: 'sash', left: s.leftId, right: s.rightId };
    }
    return null;
  },

  _showSpec(spec) {
    const d = this._drag;
    if (d.targetEl) d.targetEl.classList.remove('sash-drag-target');
    d.targetEl = null;
    if (!spec) {
      d.indicator.style.display = 'none';
      d.badge.style.display = 'none';
      d.badge.textContent = '';
      return;
    }
    d.badge.style.display = '';
    const g = this._specGeometry(spec);
    d.targetEl = g.targetEl;
    if (g.sashEl) g.sashEl.classList.add('sash-target');
    const draggedTitle = SashCore.WINDOW_TITLES[d.id] || d.id;
    d.badge.textContent = draggedTitle + ' → ' + this._specText(spec);
    d.badge.style.transform = 'translate3d(' + (d.lastX + 16) + 'px,' + (d.lastY + 18) + 'px,0)';
    this._placeIndicator(g.bar);
  },

  _specGeometry(spec) {
    const d = this._drag;
    let targetEl = null, sashEl = null, bar = null;
    if (spec.kind === 'edge') {
      const r = d.rects[spec.target];
      const tEl = this.gridEl.querySelector('.sash-window[data-win="' + spec.target + '"]');
      if (tEl) { tEl.classList.add('sash-drag-target'); targetEl = tEl; }
      if (spec.dir === 'row') bar = { left: r.left + r.width / 2 - 1.5, top: r.top, width: 3, height: r.height };
      else bar = { left: r.left, top: r.top + r.height / 2 - 1.5, width: r.width, height: 3 };
    } else if (spec.kind === 'sibling') {
      const r = d.rects[spec.target];
      const tEl = this.gridEl.querySelector('.sash-window[data-win="' + spec.target + '"]');
      const pEl = tEl && tEl.parentElement;
      if (tEl) { tEl.classList.add('sash-drag-target'); targetEl = tEl; }
      const pRect = pEl ? pEl.getBoundingClientRect() : r;
      bar = this._siblingBar(r, pEl, pRect, spec.zone);
    } else if (spec.kind === 'sash') {
      const hit = d.sashes.find((s) => s.leftId === spec.left && s.rightId === spec.right);
      sashEl = hit && hit.el;
      if (sashEl) {
        const pEl = sashEl.parentElement;
        const sr = hit.rect;
        const pRect = pEl.getBoundingClientRect();
        if (pEl.classList.contains('sash-row')) bar = { left: sr.left + sr.width / 2 - 1.5, top: pRect.top, width: 3, height: pRect.height };
        else bar = { left: pRect.left, top: sr.top + sr.height / 2 - 1.5, width: pRect.width, height: 3 };
      }
    }
    return { targetEl, sashEl, bar };
  },

  _siblingBar(r, pEl, pRect, zone) {
    if (!pEl) return null;
    if (pEl.classList.contains('sash-row')) {
      const x = zone === 'left' ? r.left : r.right;
      return { left: x - 1.5, top: pRect.top, width: 3, height: pRect.height };
    }
    const y = zone === 'top' ? r.top : r.bottom;
    return { left: pRect.left, top: y - 1.5, width: pRect.width, height: 3 };
  },

  _placeIndicator(bar) {
    const d = this._drag;
    if (!bar) { d.indicator.style.display = 'none'; return; }
    d.indicator.style.display = '';
    d.indicator.style.left = bar.left + 'px';
    d.indicator.style.top = bar.top + 'px';
    d.indicator.style.width = bar.width + 'px';
    d.indicator.style.height = bar.height + 'px';
  },

  _specText(spec) {
    if (spec.kind === 'sash') return 'between ' + (SashCore.WINDOW_TITLES[spec.left] || spec.left) + ' and ' + (SashCore.WINDOW_TITLES[spec.right] || spec.right);
    return spec.zone + ' of ' + (SashCore.WINDOW_TITLES[spec.target] || spec.target);
  },

  _applyDrop(draggedId, spec) {
    this.root = SashCore.moveWindow(this.root, draggedId, {
      kind: spec.kind, target: spec.target, dir: spec.dir, newFirst: spec.newFirst, side: spec.side, left: spec.left, right: spec.right,
    });
    return this.root;
  },
};


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
