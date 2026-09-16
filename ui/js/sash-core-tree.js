/* sash-core-tree.js — pure split-tree ops for the sash layout (Round II
   Area B).

   Split out of ui/js/sash-core.js; the facade lists its parts. A *split
   tree* describes the whole window arrangement:

       { t:'leaf',  id:'composer' }                        ← one window
       { t:'split', dir:'row'|'col',
         children:[ node, node, … ], sizes:[ 50, 50, … ] } ← N children in
         one direction, sizes = percent per child (sums to 100)

   DOM-free on purpose: the same files ship in the UI and execute under
   Node (AGENT_RULES RULE 6). Cross-part calls resolve at call time.
*/
'use strict';

const SashCoreTree = {
  // Persisted floor. The DOM layer additionally clamps to MIN_PX because
  // the usable percentage depends on the current window dimensions.
  MIN_SIZE: 4, // percent — prevents a child from becoming a sliver

  leaf(id) { return { t: 'leaf', id }; },

  split(dir, children, sizes) {
    if (dir !== 'row' && dir !== 'col') throw new Error('bad split dir: ' + dir);
    if (!Array.isArray(children) || children.length < 2)
      throw new Error('split needs at least 2 children');
    if (!Array.isArray(sizes) || sizes.length !== children.length)
      throw new Error('split sizes must match children');
    return { t: 'split', dir, children, sizes: this.normalizeSizes(sizes) };
  },

  clone(node) { return JSON.parse(JSON.stringify(node)); },

  /** Clamp every child to MIN_SIZE and scale the remaining space to 100. */
  normalizeSizes(sizes) {
    if (!Array.isArray(sizes) || !sizes.length) return sizes;
    const base = sizes.map((s) => {
      const n = Number(s);
      return Number.isFinite(n) && n > 0 ? n : this.MIN_SIZE;
    });
    const sum = base.reduce((a, b) => a + b, 0) || 1;
    if (Math.abs(sum - 100) < 1e-9 && base.every((s) => s >= this.MIN_SIZE))
      return base;
    const scaled = base.map((s) => (s / sum) * 100);
    if (scaled.every((s) => s >= this.MIN_SIZE)) return scaled;
    const floorTotal = this.MIN_SIZE * base.length;
    if (floorTotal >= 100) return base.map(() => 100 / base.length);
    const excess = base.map((s) => Math.max(0, s - this.MIN_SIZE));
    const excessTotal = excess.reduce((a, b) => a + b, 0);
    const remaining = 100 - floorTotal;
    if (!excessTotal) return base.map(() => 100 / base.length);
    return excess.map((s) => this.MIN_SIZE + (s / excessTotal) * remaining);
  },

  isLeaf(node) { return node && node.t === 'leaf'; },
  isSplit(node) { return node && node.t === 'split'; },

  /** First leaf id inside any node (a leaf → its own id). */
  firstLeafId(node) {
    if (this.isLeaf(node)) return node.id;
    return this.firstLeafId(node.children[0]);
  },

  /** Walk every leaf; cb(leaf, parentSplit|null, index) — return false to stop. */
  forEachLeaf(root, cb) {
    const self = this;
    const walk = (node, parent, index) => {
      if (self.isLeaf(node)) { if (cb(node, parent, index) === false) return; return; }
      if (self.isSplit(node)) node.children.forEach((c, i) => walk(c, node, i));
    };
    walk(root, null, -1);
  },

  leafIds(root) {
    const out = [];
    this.forEachLeaf(root, (l) => out.push(l.id));
    return out;
  },

  /** { node, parent, index } for the leaf with this id, or null. */
  findNode(root, id) {
    let found = null;
    this.forEachLeaf(root, (node, parent, index) => {
      if (node.id === id) { found = { node, parent, index }; return false; }
      return true;
    });
    return found;
  },

  /** Parent split of a leaf (or null when the leaf is the whole grid). */
  parentSplit(root, id) {
    const f = this.findNode(root, id);
    return f ? f.parent : null;
  },

  /**
   * SPLIT — replace leaf `targetId` with a split holding target and the
   * dragged-in window side by side (dir 'row') or stacked (dir 'col').
   * newFirst = true → the dragged window is first (left/top).
   * The parent keeps the same total space, so the drop "splits that
   * row/column in half".
   */
  splitLeaf(root, targetId, newId, dir, newFirst) {
    const f = this.findNode(root, targetId);
    if (!f) throw new Error('splitLeaf: unknown window ' + targetId);
    // note: `newId` is expected to be a window id that does NOT yet exist
    // here (the DOM layer / moveWindow removes the dragged leaf first);
    // duplicates are caught by validate() at persistence time
    const newSplit = this.split(dir,
      newFirst ? [this.leaf(newId), f.node] : [f.node, this.leaf(newId)],
      [50, 50]);
    if (f.parent) f.parent.children[f.index] = newSplit;
    else root = newSplit;
    return root;
  },

  /**
   * The workhorse insert: put `newId` at `index` inside the parent split of
   * leaf `refChildId` (ref may be any window whose parent is that split).
   * The *donor* child — `donorId` when given, else the neighbour adjacent
   * to the gap — gives up half of its size, so the new window and the donor
   * share the donor's former space. Returns the tree.
   */
  insertAtSplitIndex(root, refChildId, index, newId, donorId) {
    const f = this.findNode(root, refChildId);
    if (!f || !f.parent)
      throw new Error('insertAtSplitIndex: ' + refChildId + ' has no parent split');
    const p = f.parent;
    if (!Number.isInteger(index) || index < 0 || index > p.children.length)
      throw new Error('insertAtSplitIndex: bad index ' + index);
    let donorIdx = this.donorIndexFor(root, p, index, donorId);
    const half = p.sizes[donorIdx] / 2;
    p.children.splice(index, 0, this.leaf(newId));
    p.sizes.splice(index, 0, half);
    p.sizes[donorIdx >= index ? donorIdx + 1 : donorIdx] = half;
    p.sizes = this.normalizeSizes(p.sizes);
    return root;
  },

  /** The child that gives up half its size for an insert at `index`:
     `donorId` when given (must be adjacent to the gap), else the neighbour
     to the left of the gap (or to the right at the far left). */
  donorIndexFor(root, p, index, donorId) {
    if (!donorId) return index > 0 ? index - 1 : 0;
    const d = this.findNode(root, donorId);
    if (!d || d.parent !== p)
      throw new Error('insertAtSplitIndex: donor not in this split');
    if (d.index !== index && d.index !== index - 1)
      throw new Error('insertAtSplitIndex: donor not adjacent to the gap');
    return d.index;
  },

  /**
   * MERGE-INTO-ROW/COLUMN — insert `newId` as a sibling of `targetId`
   * (before/after it), sharing the target's size. If the target is the
   * whole grid (no parent), this splits the root along 'row'.
   */
  insertSibling(root, targetId, newId, side) {
    const f = this.findNode(root, targetId);
    if (!f) throw new Error('insertSibling: unknown window ' + targetId);
    if (!f.parent)
      return this.splitLeaf(root, targetId, newId, 'row', side !== 'after');
    const pos = side === 'before' ? f.index : f.index + 1;
    return this.insertAtSplitIndex(root, targetId, pos, newId, targetId);
  },

  /**
   * INSERT-BETWEEN — insert `newId` into the sash right after leaf
   * `leftId`, halving the size of the next sibling (the right neighbour).
   */
  insertBetween(root, leftId, newId) {
    const f = this.findNode(root, leftId);
    if (!f || !f.parent)
      throw new Error('insertBetween: ' + leftId + ' has no sibling');
    const p = f.parent;
    if (f.index >= p.children.length - 1)
      throw new Error('insertBetween: ' + leftId + ' is the last child');
    const rightId = this.firstLeafId(p.children[f.index + 1]);
    return this.insertAtSplitIndex(root, leftId, f.index + 1, newId, rightId);
  },

  /** Replace the sizes of the parent split of `childId` (resize commit). */
  setSplitSizes(root, childId, sizes) {
    const f = this.findNode(root, childId);
    if (!f || !f.parent) throw new Error('setSplitSizes: no parent split for ' + childId);
    if (sizes.length !== f.parent.children.length)
      throw new Error('setSplitSizes: size count mismatch');
    f.parent.sizes = this.normalizeSizes(sizes);
    return root;
  },

  // ── path-based ops (the DOM layer addresses splits by the data-path ─
  //    of their elements — a split's children may be sub-splits, so a leaf
  //    id is not always a valid reference) ────────────────────────────────

  /** Accepts [0,1] or "0-1" ("" = the root). */
  normalizePath(p) {
    if (Array.isArray(p)) return p.map(Number);
    return String(p == null ? '' : p).split('-').filter((s) => s !== '').map(Number);
  },

  /** The node at the given split path (or null). */
  nodeAtPath(root, path) {
    let n = root;
    for (const i of this.normalizePath(path)) {
      if (!this.isSplit(n) || !Array.isArray(n.children) || !n.children[i])
        return null;
      n = n.children[i];
    }
    return n;
  },

  /**
   * Insert `newId` at `index` into the split at `splitPath`.
   * `donorIdx` = child (within that split) that gives up half of its size;
   * it must be adjacent to the gap.
   */
  insertAtSplitPath(root, splitPath, index, newId, donorIdx) {
    const p = this.nodeAtPath(root, splitPath);
    if (!p || !this.isSplit(p))
      throw new Error('insertAtSplitPath: no split at path ' + JSON.stringify(splitPath));
    if (!Number.isInteger(index) || index < 0 || index > p.children.length)
      throw new Error('insertAtSplitPath: bad index ' + index);
    if (!Number.isInteger(donorIdx) || donorIdx < 0 || donorIdx >= p.children.length)
      throw new Error('insertAtSplitPath: bad donor index ' + donorIdx);
    if (donorIdx !== index && donorIdx !== index - 1)
      throw new Error('insertAtSplitPath: donor not adjacent to the gap');
    const half = p.sizes[donorIdx] / 2;
    p.children.splice(index, 0, this.leaf(newId));
    p.sizes.splice(index, 0, half);
    p.sizes[donorIdx >= index ? donorIdx + 1 : donorIdx] = half;
    p.sizes = this.normalizeSizes(p.sizes);
    return root;
  },

  /** Replace the sizes of the split at `splitPath` (resize commit). */
  setSplitSizesByPath(root, splitPath, sizes) {
    const p = this.nodeAtPath(root, splitPath);
    if (!p || !this.isSplit(p))
      throw new Error('setSplitSizesByPath: no split at path ' + JSON.stringify(splitPath));
    if (!Array.isArray(sizes) || sizes.length !== p.children.length)
      throw new Error('setSplitSizesByPath: size count mismatch');
    p.sizes = this.normalizeSizes(sizes);
    return root;
  },

  /** Path of the parent split of leaf `leafId` ([] = root split). */
  parentPath(root, leafId) {
    let out = null;
    const self = this;
    const walk = (node, path) => {
      if (out) return;
      if (self.isSplit(node)) node.children.forEach((c, i) => walk(c, path.concat(i)));
      else if (self.isLeaf(node) && node.id === leafId) out = path.slice(0, -1);
    };
    walk(root, []);
    return out;
  },

  /** Map every leaf id → its child-index path from the root, e.g. [2, 0]. */
  leafPaths(root) {
    const out = {};
    const self = this;
    const walk = (node, path) => {
      if (self.isLeaf(node)) { out[node.id] = path; return; }
      node.children.forEach((c, i) => walk(c, path.concat(i)));
    };
    walk(root, []);
    return out;
  },

  /**
   * Remove one exact node (by identity). A 2-child split that loses a
   * child collapses to the remaining child; a 3+-child split renormalises
   * its sizes. Returns the (possibly new) root.
   */
  removeNode(root, node) {
    const self = this;
    const removeFrom = (n) => {
      if (n === node) return undefined;
      if (self.isLeaf(n)) return n;
      for (let i = 0; i < n.children.length; i++) {
        const res = removeFrom(n.children[i]);
        if (res === undefined) {
          n.children.splice(i, 1);
          n.sizes.splice(i, 1);
          if (n.children.length === 1) return n.children[0]; // collapse
          n.sizes = self.normalizeSizes(n.sizes);
          return n;
        }
        n.children[i] = res;
      }
      return n;
    };
    const res = removeFrom(root);
    if (res === undefined) throw new Error('removeNode: node not in tree');
    return res;
  },

  /** Remove a leaf by id. */
  removeLeaf(root, id) {
    const f = this.findNode(root, id);
    if (!f) throw new Error('removeLeaf: unknown window ' + id);
    return this.removeNode(root, f.node);
  },

  /** Insert `newId` into a root that already splits in the wanted
     direction: share space with the edge child. */
  insertOuterEdge(root, newId, newFirst) {
    const idx = newFirst ? 0 : root.children.length;
    const donorIdx = newFirst ? 0 : root.children.length - 1;
    const half = root.sizes[donorIdx] / 2;
    root.children.splice(idx, 0, this.leaf(newId));
    root.sizes.splice(idx, 0, half);
    const donorPos = donorIdx >= idx ? donorIdx + 1 : donorIdx;
    root.sizes[donorPos] = half;
    root.sizes = this.normalizeSizes(root.sizes);
    return root;
  },

  /**
   * Insert `newId` as a new outer row/column around the whole grid.
   * Used for drag-to-edge row creation (top/bottom/left/right of the
   * grid). If root already splits in the desired direction, the new
   * window shares space with the edge child; otherwise the root is
   * wrapped in a new split.
   */
  insertOuter(root, newId, side) {
    const wantCol = side === 'top' || side === 'bottom';
    const wantDir = wantCol ? 'col' : 'row';
    const newFirst = side === 'top' || side === 'left';
    if (this.isLeaf(root)) {
      return this.split(wantDir,
        newFirst ? [this.leaf(newId), root] : [root, this.leaf(newId)],
        [20, 80]);
    }
    if (this.isSplit(root) && root.dir === wantDir)
      return this.insertOuterEdge(root, newId, newFirst);
    // root splits in the other direction → wrap it
    return this.split(wantDir,
      newFirst ? [this.leaf(newId), root] : [root, this.leaf(newId)],
      newFirst ? [20, 80] : [80, 20]);
  },
};
