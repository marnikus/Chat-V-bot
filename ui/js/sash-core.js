/* ═══════════════════════════════════════════════════════════════
   sash-core.js — Pure model for the flexible grid ("sash layout")

   A *split tree* describes the whole window arrangement:

       { t:'leaf',  id:'composer' }                        ← one window
       { t:'split', dir:'row'|'col',
         children:[ node, node, … ], sizes:[ 50, 50, … ] } ← N children in one
         direction, sizes = percent per child (sums to 100)

   dir 'row' = side-by-side (vertical sash), 'col' = stacked (horizontal
   sash).  A window "spans" rows/columns simply by sitting next to a
   sub-split — the nesting *is* the span (see Layout C in the design doc).

   This module is DOM-free on purpose: the same file ships in the UI and is
   executed by tests/test_sash_core.py through node (AGENT_RULES RULE 6).
   ═══════════════════════════════════════════════════════════════ */

(function (root, factory) {
  'use strict';
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.SashCore = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  /** The fixed set of windows the grid always contains (id → title). */
  const WINDOWS = [
    { id: 'stats',    title: 'Stats' },
    { id: 'filters',  title: 'Filters' },
    { id: 'stack',    title: 'Action Stack' },
    { id: 'config',   title: 'Block Config' },
    { id: 'composer', title: 'Message Composer' },
    { id: 'people',   title: 'User Memory' },
    { id: 'log',      title: 'Log Console' },
  ];
  const WINDOW_IDS = WINDOWS.map((w) => w.id);
  const WINDOW_TITLES = Object.fromEntries(WINDOWS.map((w) => [w.id, w.title]));

  const MAX_DEPTH = 12;
  const MIN_SIZE = 0.5; // percent — a child may never take (near) zero space

  // ── constructors ─────────────────────────────────────────────

  const leaf = (id) => ({ t: 'leaf', id });

  function split(dir, children, sizes) {
    if (dir !== 'row' && dir !== 'col') throw new Error('bad split dir: ' + dir);
    if (!Array.isArray(children) || children.length < 2)
      throw new Error('split needs at least 2 children');
    if (!Array.isArray(sizes) || sizes.length !== children.length)
      throw new Error('split sizes must match children');
    return { t: 'split', dir, children, sizes: normalizeSizes(sizes) };
  }

  const clone = (node) => JSON.parse(JSON.stringify(node));

  // ── preset trees ─────────────────────────────────────────────

  /**
   * Mirrors the legacy static layout:
   *   [ [stats/filters | stack/config] , composer , [people | log] ]
   */
  function defaultTree() {
    return split('col', [
      split('row', [
        split('col', [leaf('stats'), leaf('filters')], [35, 65]),
        split('col', [leaf('stack'), leaf('config')], [72, 28]),
      ], [17, 83]),
      leaf('composer'),
      split('row', [leaf('people'), leaf('log')], [70, 30]),
    ], [46, 24, 30]);
  }

  /**
   * Spec "Layout A" — stacked rows, 1 column each.
   * Composer / People / Log are each a full-width row.
   */
  function layoutA() {
    return split('col', [
      leaf('stats'), leaf('filters'), leaf('stack'), leaf('config'),
      leaf('composer'), leaf('people'), leaf('log'),
    ], [8, 8, 20, 16, 18, 18, 12]);
  }

  /**
   * Spec "Layout B" — row 1 split: [Composer | People], row 2 Log full width.
   */
  function layoutB() {
    return split('col', [
      split('row', [leaf('composer'), leaf('people')], [50, 50]),
      leaf('log'),
      split('row', [
        split('row', [leaf('stats'), leaf('filters')], [45, 55]),
        split('col', [leaf('stack'), leaf('config')], [72, 28]),
      ], [25, 75]),
    ], [38, 26, 36]);
  }

  /**
   * Spec "Layout C" — Log Console is a tall right-side column spanning both
   * hero rows (Composer above People in the left column).
   */
  function layoutC() {
    return split('col', [
      split('row', [
        split('col', [leaf('composer'), leaf('people')], [45, 55]),
        leaf('log'),
      ], [70, 30]),
      split('row', [
        split('row', [leaf('stats'), leaf('filters')], [45, 55]),
        split('col', [leaf('stack'), leaf('config')], [72, 28]),
      ], [25, 75]),
    ], [58, 42]);
  }

  const PRESETS = {
    default: defaultTree,
    a: layoutA,
    b: layoutB,
    c: layoutC,
  };

  // ── sizes ───────────────────────────────────────────────────

  /** Clamp each size ≥ MIN_SIZE and scale so the array sums to 100. */
  function normalizeSizes(sizes) {
    if (!Array.isArray(sizes) || !sizes.length) return sizes;
    const clamped = sizes.map((s) => {
      const n = Number(s);
      return Number.isFinite(n) && n > 0 ? n : MIN_SIZE;
    });
    const sum = clamped.reduce((a, b) => a + b, 0) || 1;
    return clamped.map((s) => Math.max(MIN_SIZE, (s / sum) * 100));
  }

  // ── traversal ────────────────────────────────────────────────

  function isLeaf(node) { return node && node.t === 'leaf'; }
  function isSplit(node) { return node && node.t === 'split'; }

  /** First leaf id inside any node (a leaf → its own id). */
  function firstLeafId(node) {
    if (isLeaf(node)) return node.id;
    return firstLeafId(node.children[0]);
  }

  /** Walk every leaf; cb(leaf, parentSplit|null, index) — return false to stop. */
  function forEachLeaf(root, cb) {
    const walk = (node, parent, index) => {
      if (isLeaf(node)) { if (cb(node, parent, index) === false) return; return; }
      if (isSplit(node)) node.children.forEach((c, i) => walk(c, node, i));
    };
    walk(root, null, -1);
  }

  const leafIds = (root) => {
    const out = [];
    forEachLeaf(root, (l) => out.push(l.id));
    return out;
  };

  /** { node, parent, index } for the leaf with this id, or null. */
  function findNode(root, id) {
    let found = null;
    forEachLeaf(root, (node, parent, index) => {
      if (node.id === id) { found = { node, parent, index }; return false; }
      return true;
    });
    return found;
  }

  /** Parent split of a leaf (or null when the leaf is the whole grid). */
  const parentSplit = (root, id) => {
    const f = findNode(root, id);
    return f ? f.parent : null;
  };

  // ── structure mutations (in place, return the tree) ──────────

  /**
   * SPLIT — replace leaf `targetId` with a split holding target and the
   * dragged-in window side by side (dir 'row') or stacked (dir 'col').
   * newFirst = true → the dragged window is first (left/top).
   * The parent keeps the same total space, so the drop "splits that
   * row/column in half".
   */
  function splitLeaf(root, targetId, newId, dir, newFirst) {
    const f = findNode(root, targetId);
    if (!f) throw new Error('splitLeaf: unknown window ' + targetId);
    // note: `newId` is expected to be a window id that does NOT yet exist
    // here (the DOM layer / moveWindow removes the dragged leaf first);
    // duplicates are caught by validate() at persistence time
    const newSplit = split(dir,
      newFirst ? [leaf(newId), f.node] : [f.node, leaf(newId)],
      [50, 50]);
    if (f.parent) f.parent.children[f.index] = newSplit;
    else root = newSplit;
    return root;
  }

  /**
   * The workhorse insert: put `newId` at `index` inside the parent split of
   * leaf `refChildId` (ref may be any window whose parent is that split).
   * The *donor* child — `donorId` when given, else the neighbour adjacent to
   * the gap — gives up half of its size, so the new window and the donor
   * share the donor's former space. Returns the tree.
   */
  function insertAtSplitIndex(root, refChildId, index, newId, donorId) {
    const f = findNode(root, refChildId);
    if (!f || !f.parent)
      throw new Error('insertAtSplitIndex: ' + refChildId + ' has no parent split');
    const p = f.parent;
    if (!Number.isInteger(index) || index < 0 || index > p.children.length)
      throw new Error('insertAtSplitIndex: bad index ' + index);
    let donorIdx;
    if (donorId) {
      const d = findNode(root, donorId);
      if (!d || d.parent !== p)
        throw new Error('insertAtSplitIndex: donor not in this split');
      donorIdx = d.index;
      if (donorIdx !== index && donorIdx !== index - 1)
        throw new Error('insertAtSplitIndex: donor not adjacent to the gap');
    } else {
      donorIdx = index > 0 ? index - 1 : 0;
    }
    const half = p.sizes[donorIdx] / 2;
    p.children.splice(index, 0, leaf(newId));
    p.sizes.splice(index, 0, half);
    p.sizes[donorIdx >= index ? donorIdx + 1 : donorIdx] = half;
    return root;
  }

  /**
   * MERGE-INTO-ROW/COLUMN — insert `newId` as a sibling of `targetId`
   * (before/after it), sharing the target's size. If the target is the whole
   * grid (no parent), this splits the root along `dir`.
   */
  function insertSibling(root, targetId, newId, side) {
    const f = findNode(root, targetId);
    if (!f) throw new Error('insertSibling: unknown window ' + targetId);
    if (!f.parent)
      return splitLeaf(root, targetId, newId, 'row', side !== 'after');
    const pos = side === 'before' ? f.index : f.index + 1;
    return insertAtSplitIndex(root, targetId, pos, newId, targetId);
  }

  /**
   * INSERT-BETWEEN — insert `newId` into the sash right after leaf `leftId`,
   * halving the size of the next sibling (the right neighbour).
   */
  function insertBetween(root, leftId, newId) {
    const f = findNode(root, leftId);
    if (!f || !f.parent)
      throw new Error('insertBetween: ' + leftId + ' has no sibling');
    const p = f.parent;
    if (f.index >= p.children.length - 1)
      throw new Error('insertBetween: ' + leftId + ' is the last child');
    const rightId = firstLeafId(p.children[f.index + 1]);
    return insertAtSplitIndex(root, leftId, f.index + 1, newId, rightId);
  }

  /** Replace the sizes of the parent split of `childId` (commit of a resize). */
  function setSplitSizes(root, childId, sizes) {
    const f = findNode(root, childId);
    if (!f || !f.parent) throw new Error('setSplitSizes: no parent split for ' + childId);
    if (sizes.length !== f.parent.children.length)
      throw new Error('setSplitSizes: size count mismatch');
    f.parent.sizes = normalizeSizes(sizes);
    return root;
  }

  // ── path-based ops (used by the DOM layer, which addresses splits
  //    by the data-path of their elements — a split's children may be
  //    sub-splits, so a leaf id is not always a valid reference) ──────

  /** Accepts [0,1] or "0-1" ("" = the root). */
  function normalizePath(p) {
    if (Array.isArray(p)) return p.map(Number);
    return String(p == null ? '' : p).split('-').filter((s) => s !== '').map(Number);
  }

  /** The node at the given split path (or null). */
  function nodeAtPath(root, path) {
    let n = root;
    for (const i of normalizePath(path)) {
      if (!isSplit(n) || !Array.isArray(n.children) || !n.children[i]) return null;
      n = n.children[i];
    }
    return n;
  }

  /**
   * Insert `newId` at `index` into the split located at `splitPath`.
   * `donorIdx` = index of the child (within that split) that gives up half
   * of its size; it must be adjacent to the gap.
   */
  function insertAtSplitPath(root, splitPath, index, newId, donorIdx) {
    const p = nodeAtPath(root, splitPath);
    if (!p || !isSplit(p))
      throw new Error('insertAtSplitPath: no split at path ' + JSON.stringify(splitPath));
    if (!Number.isInteger(index) || index < 0 || index > p.children.length)
      throw new Error('insertAtSplitPath: bad index ' + index);
    if (!Number.isInteger(donorIdx) || donorIdx < 0 || donorIdx >= p.children.length)
      throw new Error('insertAtSplitPath: bad donor index ' + donorIdx);
    if (donorIdx !== index && donorIdx !== index - 1)
      throw new Error('insertAtSplitPath: donor not adjacent to the gap');
    const half = p.sizes[donorIdx] / 2;
    p.children.splice(index, 0, leaf(newId));
    p.sizes.splice(index, 0, half);
    p.sizes[donorIdx >= index ? donorIdx + 1 : donorIdx] = half;
    return root;
  }

  /** Replace the sizes of the split at `splitPath` (commit of a resize). */
  function setSplitSizesByPath(root, splitPath, sizes) {
    const p = nodeAtPath(root, splitPath);
    if (!p || !isSplit(p))
      throw new Error('setSplitSizesByPath: no split at path ' + JSON.stringify(splitPath));
    if (!Array.isArray(sizes) || sizes.length !== p.children.length)
      throw new Error('setSplitSizesByPath: size count mismatch');
    p.sizes = normalizeSizes(sizes);
    return root;
  }

  /** Path of the parent split of leaf `leafId` ([] = root split). */
  function parentPath(root, leafId) {
    let out = null;
    const walk = (node, path) => {
      if (out) return;
      if (isSplit(node)) node.children.forEach((c, i) => walk(c, path.concat(i)));
      else if (isLeaf(node) && node.id === leafId) out = path.slice(0, -1);
    };
    walk(root, []);
    return out;
  }

  /** Map every leaf id → its child-index path from the root, e.g. [2, 0]. */
  function leafPaths(root) {
    const out = {};
    const walk = (node, path) => {
      if (isLeaf(node)) { out[node.id] = path; return; }
      node.children.forEach((c, i) => walk(c, path.concat(i)));
    };
    walk(root, []);
    return out;
  }

  /**
   * Remove one exact node (by identity). A 2-child split that loses a child
   * collapses to the remaining child; a 3+-child split renormalises its
   * sizes. Returns the (possibly new) root.
   */
  function removeNode(root, node) {
    const removeFrom = (n) => {
      if (n === node) return undefined;
      if (isLeaf(n)) return n;
      for (let i = 0; i < n.children.length; i++) {
        const res = removeFrom(n.children[i]);
        if (res === undefined) {
          n.children.splice(i, 1);
          n.sizes.splice(i, 1);
          if (n.children.length === 1) return n.children[0]; // collapse
          n.sizes = normalizeSizes(n.sizes);
          return n;
        }
        n.children[i] = res;
      }
      return n;
    };
    const res = removeFrom(root);
    if (res === undefined) throw new Error('removeNode: node not in tree');
    return res;
  }

  /** Remove a leaf by id. */
  function removeLeaf(root, id) {
    const f = findNode(root, id);
    if (!f) throw new Error('removeLeaf: unknown window ' + id);
    return removeNode(root, f.node);
  }

  /**
   * THE drop operation — move `draggedId` to a new place atomically.
   *
   * drop:
   *   { kind:'edge',    target, dir, newFirst }
   *       split window `target` in half; the dragged window takes the new half
   *   { kind:'sibling', target, side }         // side: 'before' | 'after'
   *       join the row/column of `target` (share its size)
   *   { kind:'sash',    left, right }
   *       land between the two windows flanking the hovered sash
   *       (left/right are window ids — groups; they may be sub-splits)
   *
   * Order matters: the window is INSERTED at the drop spot FIRST (all
   * targets are located in the pre-removal tree, where they are stable),
   * then the original node is removed BY IDENTITY. This makes every drop a
   * move, never a copy — including "drag a window onto its own sibling",
   * where the shared row survives instead of collapsing.
   */
  function moveWindow(root, draggedId, drop) {
    if (drop.target && drop.target === draggedId)
      throw new Error('moveWindow: dropping a window on itself');
    const orig = findNode(root, draggedId);
    if (!orig) throw new Error('moveWindow: unknown window ' + draggedId);
    const origNode = orig.node;

    // 1) insert the window at the drop spot (target located pre-removal)
    if (drop.kind === 'edge') {
      root = splitLeaf(root, drop.target, draggedId, drop.dir, drop.newFirst);
    } else if (drop.kind === 'sibling') {
      const f = findNode(root, drop.target);
      if (!f) throw new Error('moveWindow: unknown target ' + drop.target);
      if (!f.parent) {
        root = splitLeaf(root, drop.target, draggedId, 'row', drop.side !== 'after');
      } else {
        const pos = drop.side === 'before' ? f.index : f.index + 1;
        root = insertAtSplitIndex(root, drop.target, pos, draggedId, drop.target);
      }
    } else if (drop.kind === 'sash') {
      const paths = leafPaths(root);
      const a = paths[drop.left], b = paths[drop.right];
      if (!a || !b)
        throw new Error('moveWindow: sash anchors not found (' + drop.left + '/' + drop.right + ')');
      let k = 0;
      while (k < a.length && k < b.length && a[k] === b[k]) k++;
      const lca = nodeAtPath(root, a.slice(0, k));
      const iA = a[k], iB = b[k];
      if (!lca || !isSplit(lca) || Math.abs(iA - iB) !== 1)
        throw new Error('moveWindow: sash anchors not adjacent');
      const insertIdx = Math.max(iA, iB);     // gap between the two groups
      const half = lca.sizes[insertIdx] / 2;  // the right group gives up half
      lca.children.splice(insertIdx, 0, leaf(draggedId));
      lca.sizes.splice(insertIdx, 0, half);
      lca.sizes[insertIdx + 1] = half;
    } else {
      throw new Error('moveWindow: unknown drop kind ' + drop.kind);
    }

    // 2) remove the ORIGINAL node (identity — never "first leaf with this id")
    return removeNode(root, origNode);
  }

  // ── validation / (de)serialisation ───────────────────────────

  /**
   * Full structural validation. Returns an error string, or null when the
   * tree is a usable arrangement of exactly `expectedIds`.
   */
  function validate(root, expectedIds) {
    const expect = (expectedIds || WINDOW_IDS).slice().sort();
    const check = (node, depth) => {
      if (depth > MAX_DEPTH) return 'tree too deep';
      if (isLeaf(node)) {
        if (typeof node.id !== 'string' || !node.id) return 'leaf without id';
        return null;
      }
      if (!isSplit(node)) return 'unknown node type';
      if (node.dir !== 'row' && node.dir !== 'col') return 'bad dir';
      if (!Array.isArray(node.children) || node.children.length < 2)
        return 'split needs ≥2 children';
      if (!Array.isArray(node.sizes) || node.sizes.length !== node.children.length)
        return 'sizes must match children';
      for (const s of node.sizes)
        if (!Number.isFinite(s) || s <= 0) return 'bad size value';
      const sum = node.sizes.reduce((a, b) => a + b, 0);
      if (sum < 99.5 || sum > 100.5) return 'sizes must sum to 100 (got ' + sum + ')';
      for (const c of node.children) {
        const err = check(c, depth + 1);
        if (err) return err;
      }
      return null;
    };
    const err = check(root, 0);
    if (err) return err;
    const got = leafIds(root).slice().sort();
    if (got.length !== expect.length) return 'leaf count mismatch';
    for (let i = 0; i < expect.length; i++)
      if (got[i] !== expect[i]) return 'leaf id mismatch (' + got[i] + ' ≠ ' + expect[i] + ')';
    return null;
  }

  const serialize = (tree) => JSON.stringify({ v: 1, tree });

  /** Parse + validate. Returns { ok:true, tree } or { ok:false, error }. */
  function deserialize(str, expectedIds) {
    try {
      const obj = JSON.parse(str);
      const tree = obj && obj.v === 1 ? obj.tree : obj;
      const err = validate(tree, expectedIds);
      return err ? { ok: false, error: err } : { ok: true, tree: clone(tree) };
    } catch (e) {
      return { ok: false, error: 'unparseable: ' + e.message };
    }
  }

  return {
    WINDOWS, WINDOW_IDS, WINDOW_TITLES,
    MAX_DEPTH, MIN_SIZE,
    leaf, split, clone, firstLeafId,
    defaultTree, layoutA, layoutB, layoutC, PRESETS,
    normalizeSizes,
    isLeaf, isSplit, forEachLeaf, leafIds, findNode, parentSplit,
    splitLeaf, insertAtSplitIndex, insertSibling, insertBetween,
    setSplitSizes,
    normalizePath, nodeAtPath, insertAtSplitPath, setSplitSizesByPath,
    parentPath, leafPaths, removeLeaf, moveWindow,
    validate, serialize, deserialize,
  };
});
