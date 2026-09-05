/* ═══════════════════════════════════════════════════════════════
   sash-grid.js — DOM layer for the flexible grid ("sash layout")

   Renders the SashCore split tree into the #sashGrid container:
     • .sash-split  — flex row/column of children with .sash gaps
     • .sash-window — frame around ONE persistent panel element
     • .sash        — 6px draggable separator (col-resize / row-resize)

   The panels themselves (#winStats, #blockConfigPanel, …) are moved in the
   DOM, never re-created, so composer text, table rows and log entries
   survive every rearrangement.

   Interactions
     • drag a window by its title bar (h3.win-title) —
         drop on an EDGE of a window  → splits that window in half
         drop on the CENTER of a window → joins its row/column (insert
         as sibling, new window takes half of the hovered window's size)
         drop on a SASH → inserts between the two neighbours
     • drag a sash → resizes its two neighbours; the rest of the grid
       adapts proportionally (flex normalisation), structure preserved
     • double-click a sash → that split resets to even sizes
     • Escape cancels a drag
     • 📐 menu in the header → preset layouts (Default / A / B / C)
     • every change persists to localStorage (validated on restore)
   ═══════════════════════════════════════════════════════════════ */

'use strict';

const SashGrid = {
  STORAGE_KEY: 'chatbot.sashLayout.v1',

  THRESHOLD: 4,   // px before a title-bar drag becomes a real drag
  MIN_PX: 64,     // smallest a window can be shrunk to
  SASH_W: 6,      // px occupied by each sash in the layout math

  gridEl: null,
  root: null,     // current split tree (SashCore model)
  winEls: {},     // window id → persistent panel element
  _drag: null,
  _resize: null,

  /** window id → title-bar icon (for the drag ghost card) */
  WIN_ICONS: {
    stats: 'bar_chart', filters: 'filter_list', stack: 'view_list',
    config: 'tune', composer: 'chat', people: 'people', log: 'terminal',
  },

  // ── bootstrap ────────────────────────────────────────────────

  init() {
    this.gridEl = document.getElementById('sashGrid');
    if (!this.gridEl) { console.warn('sash-grid: #sashGrid missing'); return; }

    const winElIds = {
      stats: 'winStats', filters: 'winFilters', stack: 'winStack',
      config: 'blockConfigPanel', composer: 'winComposer',
      people: 'winPeople', log: 'winLog',
    };
    for (const w of SashCore.WINDOWS) {
      const el = document.getElementById(winElIds[w.id]);
      if (!el) { console.warn('sash-grid: panel for "' + w.id + '" missing'); continue; }
      this.winEls[w.id] = el;
    }

    this.root = this._loadTree() || SashCore.defaultTree();
    this.render();

    this.gridEl.addEventListener('pointerdown', this._onDown = this._pointerDown.bind(this));
    this.gridEl.addEventListener('dblclick', this._onDbl = this._onDblClick.bind(this));
    this._setupLayoutMenu();
    this._setupVisibilityWatch();
  },

  // ── tree persistence ─────────────────────────────────────────

  _loadTree() {
    try {
      const raw = localStorage.getItem(this.STORAGE_KEY);
      if (!raw) return null;
      const res = SashCore.deserialize(raw);
      if (res.ok) return res.tree;
      console.warn('sash-grid: persisted layout rejected (' + res.error + ') — using default');
      return null;
    } catch (e) {
      return null; // storage unavailable → default
    }
  },

  _save() {
    try { localStorage.setItem(this.STORAGE_KEY, SashCore.serialize(this.root)); }
    catch (e) { /* private profile without storage — in-memory only */ }
  },

  /** Apply a preset layout (Default / A / B / C). */
  setLayout(name) {
    const fn = SashCore.PRESETS[name];
    if (!fn) return false;
    this.root = fn();
    this.render();
    this._save();
    if (typeof LogConsole !== 'undefined') {
      const label = { default: 'Default', a: 'A — stacked rows',
                      b: 'B — split top row', c: 'C — side column' }[name] || name;
      LogConsole.log('📐 Layout "' + label + '" applied', 'info');
    }
    return true;
  },

  // ── rendering ───────────────────────────────────────────────

  /** Rebuild the wrapper skeleton, re-parenting the persistent panels. */
  render() {
    const frag = this._buildNode(this.root, []);
    // The root node must always FILL the grid container. Without an explicit
    // flex grow the split sizes to its content width and — once a window with
    // a small natural width (or a hidden window) is the only wide child — a
    // fixed empty gap appears on the right. (flex-basis 0% + grow 1)
    frag.style.flex = '1 1 0%';
    this.gridEl.replaceChildren(frag);
    this._syncHidden();
  },

  _buildNode(node, path) {
    if (SashCore.isLeaf(node)) {
      const win = document.createElement('div');
      win.className = 'sash-window';
      win.dataset.win = node.id;
      const panel = this.winEls[node.id];
      if (panel) win.appendChild(panel);   // move the persistent panel
      return win;
    }
    const el = document.createElement('div');
    el.className = 'sash-split sash-' + node.dir;
    el.dataset.path = path.join('-');
    const n = node.children.length;
    node.children.forEach((child, i) => {
      el.appendChild(this._buildNode(child, path.concat(i)));
      const childEl = el.children[i * 2];
      childEl.style.flex = node.sizes[i] + ' 1 0%';
      if (i < n - 1) {
        const sash = document.createElement('div');
        sash.className = 'sash ' + (node.dir === 'row' ? 'sash-v' : 'sash-h');
        sash.dataset.idx = String(i);
        el.appendChild(sash);
      }
    });
    return el;
  },

  _parsePath(p) {
    return String(p == null ? '' : p).split('-').filter((s) => s !== '').map(Number);
  },

  // ── hidden windows (e.g. Block Config before its first open) ─────
  // A window whose panel is currently hidden must RELEASE its grid space:
  // the visible siblings expand to fill it, and the sashes touching it
  // disappear. The size stays in the tree, so showing the window later
  // restores the arrangement exactly. Managed by class (not :has()) so it
  // works on every Chromium version.

  _panelIsHidden(panel) {
    if (!panel) return false;
    if (panel.classList.contains('hidden')) return true;
    if (panel.style.display === 'none') return true;
    try { return getComputedStyle(panel).display === 'none'; }
    catch (e) { return false; }
  },

  _syncHidden() {
    if (!this.gridEl) return;
    this.gridEl.querySelectorAll('.sash-window').forEach((winEl) => {
      const panel = winEl.querySelector(':scope > .panel');
      winEl.classList.toggle('sash-win-hidden', this._panelIsHidden(panel));
    });
    this.gridEl.querySelectorAll('.sash-split').forEach((pEl) => {
      const kids = Array.from(pEl.children);
      kids.forEach((el, i) => {
        if (!el.classList || !el.classList.contains('sash')) return;
        const prev = kids[i - 1], next = kids[i + 1];
        const nearHidden = (prev && prev.classList.contains('sash-win-hidden')) ||
                           (next && next.classList.contains('sash-win-hidden'));
        el.classList.toggle('sash-hidden', !!nearHidden);
      });
    });
  },

  _setupVisibilityWatch() {
    // The app shows/hides Block Config by toggling its class/style — keep
    // the grid in sync whenever that happens (no re-render needed: the
    // siblings expand purely through flexbox).
    const mo = new MutationObserver(() => {
      let changed = false;
      this.gridEl.querySelectorAll('.sash-window').forEach((winEl) => {
        const panel = winEl.querySelector(':scope > .panel');
        const hidden = this._panelIsHidden(panel);
        // note: toggle(cls, force) returns false when REMOVING the class,
        // so track the transition explicitly
        if (winEl.classList.contains('sash-win-hidden') !== hidden) changed = true;
        winEl.classList.toggle('sash-win-hidden', hidden);
      });
      if (changed) this._syncHidden();
    });
    Object.values(this.winEls).forEach((el) => {
      mo.observe(el, { attributes: true, attributeFilter: ['class', 'style'] });
    });
  },

  // ── unified pointerdown (sash resize vs. window drag) ────────

  _pointerDown(ev) {
    if (ev.button !== 0) return;
    if (this._drag || this._resize) return;
    const sashEl = ev.target.closest('.sash');
    if (sashEl) { this._startResize(sashEl, ev); return; }
    const title = ev.target.closest('.win-title');
    if (!title || !this.gridEl.contains(title)) return;
    if (ev.target.closest('button, input, select, textarea, a, .chip')) return;
    const winEl = title.closest('.sash-window');
    if (!winEl) return;
    this._startDrag(winEl, ev);
  },

  // ── window drag & drop ───────────────────────────────────────

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

    // cache geometry — the grid never scrolls, so it stays valid
    d.rects = {};
    this.gridEl.querySelectorAll('.sash-window').forEach((w) => {
      if (!w.offsetWidth || !w.offsetHeight) return; // hidden (Block Config)
      d.rects[w.dataset.win] = w.getBoundingClientRect();
    });
    d.sashes = [];
    this.gridEl.querySelectorAll('.sash').forEach((s) => {
      if (!s.offsetWidth && !s.offsetHeight) return;
      d.sashes.push({
        el: s, rect: s.getBoundingClientRect(),
        leftId: this._winIdOf(s.parentElement.children[+s.dataset.idx * 2]),
        rightId: this._winIdOf(s.parentElement.children[+s.dataset.idx * 2 + 2]),
      });
    });

    const rect = d.winEl.getBoundingClientRect();
    d.clone = this._buildDragVisual(d.winEl, d.id, rect);
    d.clone.style.transform = 'translate3d(' + rect.left + 'px,' + rect.top + 'px,0)';

    d.badge = document.createElement('div');
    d.badge.className = 'sash-drag-badge';
    document.body.appendChild(d.badge);

    d.indicator = document.createElement('div');
    d.indicator.className = 'sash-drop-indicator';
    d.indicator.style.display = 'none';
    document.body.appendChild(d.indicator);

    d.winEl.classList.add('sash-drag-source');
    document.body.classList.add('sash-dragging');
  },

  _buildDragVisual(winEl, id, rect) {
    // Big windows (full table, long log) get a compact ghost card instead of
    // a full clone — keeps the drag smooth.
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
    g.innerHTML = '<span class="material-icons">' + (this.WIN_ICONS[id] || 'view_in_carousel') +
                  '</span><span>' + (SashCore.WINDOW_TITLES[id] || id) + '</span>';
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
      if (Math.abs(ev.clientX - d.startX) < this.THRESHOLD &&
          Math.abs(ev.clientY - d.startY) < this.THRESHOLD) return;
      this._beginDrag();
    }
    ev.preventDefault();
    d.lastX = ev.clientX;
    d.lastY = ev.clientY;

    // clone follows the cursor 1:1 (ghost: offset from it)
    if (d.clone.classList.contains('sash-drag-ghost')) {
      d.clone.style.transform = 'translate3d(' + (ev.clientX + 14) + 'px,' + (ev.clientY + 14) + 'px,0)';
    } else {
      const r = d.winEl.getBoundingClientRect(); // stable: layout unchanged during drag
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

  /** Map the pointer position to a drop spec (see design doc §3.2). */
  _computeSpec(x, y) {
    const d = this._drag;

    // 1) over another window?
    for (const id of Object.keys(d.rects)) {
      if (id === d.id) continue;
      const r = d.rects[id];
      if (x < r.left || x >= r.right || y < r.top || y >= r.bottom) continue;
      const Z = Math.min(44, Math.max(20, 0.22 * Math.min(r.width, r.height)));
      let zone = 'center';
      if (x < r.left + Z) zone = 'left';
      else if (x > r.right - Z) zone = 'right';
      else if (y < r.top + Z) zone = 'top';
      else if (y > r.bottom - Z) zone = 'bottom';

      if (zone !== 'center') {
        const dir = (zone === 'left' || zone === 'right') ? 'row' : 'col';
        return { kind: 'edge', target: id, zone,
                 dir, newFirst: (zone === 'left' || zone === 'top') };
      }
      // center of T → insert as sibling in T's parent split
      const tEl = this.gridEl.querySelector('.sash-window[data-win="' + id + '"]');
      const pEl = tEl && tEl.parentElement;
      if (!pEl || !pEl.classList.contains('sash-split')) {
        // T is the whole grid: split it along the dominant axis
        const midX = r.left + r.width / 2, midY = r.top + r.height / 2;
        const dir = Math.abs(x - midX) / (r.width / 2) >= Math.abs(y - midY) / (r.height / 2)
                    ? 'row' : 'col';
        const newFirst = dir === 'row' ? x < midX : y < midY;
        return { kind: 'edge', target: id,
                 zone: dir === 'row' ? (newFirst ? 'left' : 'right')
                                     : (newFirst ? 'top' : 'bottom'),
                 dir, newFirst };
      }
      const isRow = pEl.classList.contains('sash-row');
      const side = isRow ? (x < r.left + r.width / 2 ? 'before' : 'after')
                         : (y < r.top + r.height / 2 ? 'before' : 'after');
      return { kind: 'sibling', target: id, side,
               zone: side === 'before' ? (isRow ? 'left' : 'top')
                                       : (isRow ? 'right' : 'bottom') };
    }

    // 2) over a sash? → insert between its two neighbours
    for (const s of d.sashes) {
      const r = s.rect;
      if (x < r.left || x >= r.right || y < r.top || y >= r.bottom) continue;
      return { kind: 'sash', left: s.leftId, right: s.rightId };
    }
    return null;
  },

  /** Live highlight: target outline + drop line + cursor badge. */
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
    const draggedTitle = SashCore.WINDOW_TITLES[d.id] || d.id;

    let text, bar = null;
    if (spec.kind === 'edge') {
      const r = d.rects[spec.target];
      const tEl = this.gridEl.querySelector('.sash-window[data-win="' + spec.target + '"]');
      if (tEl) { tEl.classList.add('sash-drag-target'); d.targetEl = tEl; }
      text = draggedTitle + ' → ' + spec.zone + ' of ' + (SashCore.WINDOW_TITLES[spec.target] || spec.target);
      if (spec.dir === 'row') {
        bar = { left: r.left + r.width / 2 - 1.5, top: r.top, width: 3, height: r.height };
      } else {
        bar = { left: r.left, top: r.top + r.height / 2 - 1.5, width: r.width, height: 3 };
      }
    } else if (spec.kind === 'sibling') {
      const r = d.rects[spec.target];
      const tEl = this.gridEl.querySelector('.sash-window[data-win="' + spec.target + '"]');
      const pEl = tEl && tEl.parentElement;
      if (tEl) { tEl.classList.add('sash-drag-target'); d.targetEl = tEl; }
      const pRect = pEl ? pEl.getBoundingClientRect() : r;
      text = draggedTitle + ' → ' + spec.zone + ' of ' + (SashCore.WINDOW_TITLES[spec.target] || spec.target);
      if (!pEl) {
        bar = null; // T is the whole grid — handled as an edge spec anyway
      } else if (pEl.classList.contains('sash-row')) {
        const x = spec.zone === 'left' ? r.left : r.right;
        bar = { left: x - 1.5, top: pRect.top, width: 3, height: pRect.height };
      } else {
        const y = spec.zone === 'top' ? r.top : r.bottom;
        bar = { left: pRect.left, top: y - 1.5, width: pRect.width, height: 3 };
      }
    } else if (spec.kind === 'sash') {
      const hit = d.sashes.find((s) => s.leftId === spec.left && s.rightId === spec.right);
      const sEl = hit && hit.el;
      if (sEl) {
        sEl.classList.add('sash-target');
        const pEl = sEl.parentElement;
        const sr = hit.rect;
        const pRect = pEl.getBoundingClientRect();
        if (pEl.classList.contains('sash-row')) {
          bar = { left: sr.left + sr.width / 2 - 1.5, top: pRect.top, width: 3, height: pRect.height };
        } else {
          bar = { left: pRect.left, top: sr.top + sr.height / 2 - 1.5, width: pRect.width, height: 3 };
        }
      }
      text = draggedTitle + ' → between ' +
             (SashCore.WINDOW_TITLES[spec.left] || spec.left) + ' and ' +
             (SashCore.WINDOW_TITLES[spec.right] || spec.right);
    }

    d.badge.textContent = text;
    d.badge.style.transform = 'translate3d(' + (d.lastX + 16) + 'px,' + (d.lastY + 18) + 'px,0)';
    if (bar) {
      d.indicator.style.display = '';
      d.indicator.style.left = bar.left + 'px';
      d.indicator.style.top = bar.top + 'px';
      d.indicator.style.width = bar.width + 'px';
      d.indicator.style.height = bar.height + 'px';
    } else {
      d.indicator.style.display = 'none';
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
      if (typeof LogConsole !== 'undefined')
        LogConsole.log('🧩 ' + (SashCore.WINDOW_TITLES[d.id] || d.id) + ' → ' +
                       this._specText(spec) + ' (grid updated)', 'info');
    } else if (d.active) {
      if (typeof LogConsole !== 'undefined')
        LogConsole.log('↩ Window drag cancelled — layout unchanged', 'warn');
    }
  },

  _cancelDrag() {
    const d = this._drag;
    if (!d) return;
    this._cleanupDrag();
    if (d.active && typeof LogConsole !== 'undefined')
      LogConsole.log('↩ Window drag cancelled — layout unchanged', 'warn');
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

  _specText(spec) {
    if (spec.kind === 'sash')
      return 'between ' + (SashCore.WINDOW_TITLES[spec.left] || spec.left) + ' and ' +
             (SashCore.WINDOW_TITLES[spec.right] || spec.right);
    return spec.zone + ' of ' + (SashCore.WINDOW_TITLES[spec.target] || spec.target);
  },

  _flashLanded(winId) {
    const el = this.gridEl.querySelector('.sash-window[data-win="' + winId + '"]');
    if (!el) return;
    el.classList.remove('sash-landed');
    void el.offsetWidth; // restart the animation
    el.classList.add('sash-landed');
    setTimeout(() => el.classList.remove('sash-landed'), 700);
  },

  /** Apply a drop spec to the tree (atomic move). Returns the new root. */
  _applyDrop(draggedId, spec) {
    this.root = SashCore.moveWindow(this.root, draggedId, {
      kind: spec.kind,
      target: spec.target,
      dir: spec.dir,
      newFirst: spec.newFirst,
      side: spec.side,
      left: spec.left,
      right: spec.right,
    });
    return this.root;
  },

  // ── sash resize ──────────────────────────────────────────────

  _startResize(sashEl, ev) {
    const pEl = sashEl.parentElement;
    if (!pEl || !pEl.classList.contains('sash-split')) return;
    const sIdx = parseInt(sashEl.dataset.idx, 10);
    const isRow = pEl.classList.contains('sash-row');

    const childEls = [];
    for (let i = 0; i * 2 < pEl.children.length; i++) childEls.push(pEl.children[i * 2]);

    const z = {
      pEl, sashEl, sIdx, isRow, childEls, pointerId: ev.pointerId,
      otherWidths: {},
    };
    // the non-resized children keep their absolute px size
    for (let i = 0; i < childEls.length; i++) {
      if (i === sIdx || i === sIdx + 1) continue;
      const r = childEls[i].getBoundingClientRect();
      z.otherWidths[i] = isRow ? r.width : r.height;
    }
    this._resize = z;
    sashEl.classList.add('sash-active');
    document.body.classList.add(isRow ? 'sash-resizing-row' : 'sash-resizing-col');
    this._onResizeMove = this._resizeMove.bind(this);
    this._onResizeUp = this._resizeUp.bind(this);
    document.addEventListener('pointermove', this._onResizeMove, { passive: false });
    document.addEventListener('pointerup', this._onResizeUp);
    document.addEventListener('pointercancel', this._onResizeCancel = this._cancelResize.bind(this));
    ev.preventDefault();
  },

  _resizeMove(ev) {
    const z = this._resize;
    if (!z) return;
    ev.preventDefault();
    const rect = z.pEl.getBoundingClientRect();
    const n = z.childEls.length;
    const sashTotal = (n - 1) * this.SASH_W;
    let others = 0;
    for (const k of Object.keys(z.otherWidths)) others += z.otherWidths[k];
    const span = (z.isRow ? rect.width : rect.height) - others - sashTotal;
    if (span <= this.MIN_PX * 2) return;

    // absolute px position where child sIdx starts
    let prefix = 0;
    for (let i = 0; i < z.sIdx; i++) prefix += (z.otherWidths[i] || 0) + this.SASH_W;
    const start = (z.isRow ? rect.left : rect.top) + prefix;
    const pos = z.isRow ? ev.clientX : ev.clientY;
    const wA = Math.min(Math.max(pos - start, this.MIN_PX), span - this.MIN_PX);
    const wB = span - wA;

    // live: only the two siblings change their flex-grow; flexbox normalises
    // the rest, so neighbours adapt proportionally and structure is preserved
    z.childEls[z.sIdx].style.flexGrow = String(wA);
    z.childEls[z.sIdx + 1].style.flexGrow = String(wB);
  },

  _resizeUp() {
    const z = this._resize;
    if (!z) return;
    this._cancelResize();
    // commit: convert measured px to percents (hidden child keeps its share)
    const rect = z.pEl.getBoundingClientRect();
    const total = z.isRow ? rect.width : rect.height;
    const sashTotal = (z.childEls.length - 1) * this.SASH_W;
    const denom = Math.max(1, total - sashTotal);
    const path = this._parsePath(z.pEl.dataset.path);
    const p = SashCore.nodeAtPath(this.root, path);
    const prev = p ? p.sizes : null;
    const sizes = z.childEls.map((el, i) => {
      const r = el.getBoundingClientRect();
      const w = z.isRow ? r.width : r.height;
      if (w > 1) return (w / denom) * 100;
      return prev ? prev[i] : 100 / z.childEls.length; // hidden (display:none)
    });
    this.root = SashCore.setSplitSizesByPath(this.root, path, sizes);
    this.render();
    this._save();
    if (typeof LogConsole !== 'undefined')
      LogConsole.log('📏 Grid resized', 'info');
  },

  _cancelResize() {
    const z = this._resize;
    if (!z) return;
    document.removeEventListener('pointermove', this._onResizeMove, { passive: false });
    document.removeEventListener('pointerup', this._onResizeUp);
    document.removeEventListener('pointercancel', this._onResizeCancel);
    z.sashEl.classList.remove('sash-active');
    document.body.classList.remove('sash-resizing-row', 'sash-resizing-col');
    this._resize = null;
  },

  /** Double-click a sash → reset that split to even sizes. */
  _onDblClick(ev) {
    const sashEl = ev.target.closest('.sash');
    if (!sashEl) return;
    const pEl = sashEl.parentElement;
    if (!pEl || !pEl.classList.contains('sash-split')) return;
    const n = (pEl.children.length + 1) / 2; // children interleaved with sashes
    const path = this._parsePath(pEl.dataset.path);
    this.root = SashCore.setSplitSizesByPath(this.root, path,
      new Array(n).fill(100 / n));
    this.render();
    this._save();
    if (typeof LogConsole !== 'undefined')
      LogConsole.log('📏 Split reset to even sizes', 'info');
  },

  // ──  layout menu (pinned header) ───────────────────────────

  _setupLayoutMenu() {
    const btn = document.getElementById('layoutMenuBtn');
    const menu = document.getElementById('layoutMenu');
    if (!btn || !menu) return;
    const place = () => {
      if (menu.classList.contains('hidden')) return;
      const r = btn.getBoundingClientRect();
      let left = r.right - 240;
      left = Math.max(8, Math.min(left, window.innerWidth - 248));
      menu.style.left = left + 'px';
      menu.style.top = (r.bottom + 6) + 'px';
    };
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      menu.classList.toggle('hidden');
      place();
    });
    menu.querySelectorAll('button[data-layout]').forEach((b) => {
      b.addEventListener('click', () => {
        menu.classList.add('hidden');
        this.setLayout(b.dataset.layout);
      });
    });
    document.addEventListener('click', (e) => {
      if (!e.target.closest('#layoutMenu') && !e.target.closest('#layoutMenuBtn'))
        menu.classList.add('hidden');
    });
  },

  // ── test / programmatic API (also used by the WebEngine tests) ─

  getTree() { return SashCore.clone(this.root); },

  /** Apply a drop without pointer simulation. zone: left|right|top|bottom|before|after */
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

  /** Simulate a sash drag commit: resize the two neighbours of the given
   *  sash so the first child takes `firstPct` percent of the split. */
  simulateResize(pathStr, firstPct) {
    const path = this._parsePath(pathStr);
    const p = SashCore.nodeAtPath(this.root, path);
    if (!p) throw new Error('simulateResize: bad path ' + pathStr);
    const sizes = p.sizes.slice();
    sizes[0] = firstPct;
    // redistribute the rest of the space to the other children proportionally
    const rest = 100 - firstPct;
    const restSum = sizes.slice(1).reduce((a, b) => a + b, 0) || 1;
    for (let i = 1; i < sizes.length; i++) sizes[i] = rest * (sizes[i] / restSum);
    this.root = SashCore.setSplitSizesByPath(this.root, path, sizes);
    this.render();
    this._save();
    return this.getTree();
  },
};

document.addEventListener('DOMContentLoaded', () => SashGrid.init());
