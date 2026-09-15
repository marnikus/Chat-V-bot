/* sash-grid part — sash-grid-drag-spec.js (Issue 4 row creation)

Drop spec computation with outer row/col zones, full-width preview, ≤250 LOC.
*/

const SashGridSpec = {
  _computeSpec(x, y) {
    const d = this._drag;
    const outer = this._outerSpec(x, y);
    if (outer) return outer;
    for (const id of Object.keys(d.rects)) {
      if (id === d.id) continue;
      const r = d.rects[id];
      if (x < r.left || x >= r.right || y < r.top || y >= r.bottom) continue;
      const edge = this._edgeZoneSpec(id, r, x, y);
      if (edge) return edge;
      return this._centerSpec(id, r, x, y);
    }
    const sash = this._sashSpec(x, y);
    if (sash) return sash;
    return this._outerSpec(x, y, true);
  },

  _outerSpec(x, y, includeInside) {
    const d = this._drag;
    if (!d.gridRect) return null;
    const g = d.gridRect;
    const EDGE = 36;
    const inside = x >= g.left && x < g.right && y >= g.top && y < g.bottom;
    if (!inside && !includeInside) {
      if (x < g.left - 24 || x > g.right + 24 || y < g.top - 24 || y > g.bottom + 24) return null;
    }
    if (y < g.top + EDGE) return { kind: 'outer', side: 'top', zone: 'top' };
    if (y > g.bottom - EDGE) return { kind: 'outer', side: 'bottom', zone: 'bottom' };
    if (x < g.left + EDGE) return { kind: 'outer', side: 'left', zone: 'left' };
    if (x > g.right - EDGE) return { kind: 'outer', side: 'right', zone: 'right' };
    return null;
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
    if (spec.kind === 'outer') {
      const g = d.gridRect;
      if (!g) return { targetEl: null, sashEl: null, bar: null };
      if (spec.side === 'top') bar = { left: g.left, top: g.top, width: g.width, height: 4 };
      else if (spec.side === 'bottom') bar = { left: g.left, top: g.bottom - 4, width: g.width, height: 4 };
      else if (spec.side === 'left') bar = { left: g.left, top: g.top, width: 4, height: g.height };
      else bar = { left: g.right - 4, top: g.top, width: 4, height: g.height };
    } else if (spec.kind === 'edge') {
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
    if (spec.kind === 'outer') return 'new row ' + spec.side;
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
