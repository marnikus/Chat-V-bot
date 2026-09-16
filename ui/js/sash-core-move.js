/* sash-core-move.js — THE drop operation: move a window atomically
   (Round II Area B).

   Split out of ui/js/sash-core.js; the facade lists its parts.

   drop:
     { kind:'edge',    target, dir, newFirst }
         split window `target` in half; the dragged window takes the new half
     { kind:'sibling', target, side }         // side: 'before' | 'after'
         join the row/column of `target` (share its size)
     { kind:'sash',    left, right }
         land between the two windows flanking the hovered sash
     { kind:'outer',   side }                 // side: 'top'|'bottom'|'left'|'right'
         new row/column around the whole grid

   Order matters: the window is INSERTED at the drop spot FIRST (all
   targets are located in the pre-removal tree, where they are stable),
   then the original node is removed BY IDENTITY. This makes every drop a
   move, never a copy — including "drag a window onto its own sibling",
   where the shared row survives instead of collapsing.
   Outer is the exception: it removes first, then inserts around the
   remaining tree, because its target is the whole grid.
*/
'use strict';

const SashCoreMove = {
  /** Insert the dragged leaf into the sash right between the two anchors
     of a 'sash' drop (they must be neighbours of one split). */
  insertAtSashGap(root, draggedId, drop) {
    const T = SashCoreTree;
    const paths = T.leafPaths(root);
    const a = paths[drop.left], b = paths[drop.right];
    if (!a || !b)
      throw new Error('moveWindow: sash anchors not found (' +
                      drop.left + '/' + drop.right + ')');
    let k = 0;
    while (k < a.length && k < b.length && a[k] === b[k]) k++;
    const lca = T.nodeAtPath(root, a.slice(0, k));
    const iA = a[k], iB = b[k];
    if (!lca || !T.isSplit(lca) || Math.abs(iA - iB) !== 1)
      throw new Error('moveWindow: sash anchors not adjacent');
    const insertIdx = Math.max(iA, iB);
    const half = lca.sizes[insertIdx] / 2;
    lca.children.splice(insertIdx, 0, T.leaf(draggedId));
    lca.sizes.splice(insertIdx, 0, half);
    lca.sizes[insertIdx + 1] = half;
    lca.sizes = T.normalizeSizes(lca.sizes);
    return root;
  },

  /** Insert `draggedId` at the drop spot (targets located pre-removal). */
  insertForDrop(root, draggedId, drop) {
    const T = SashCoreTree;
    if (drop.kind === 'edge')
      return T.splitLeaf(root, drop.target, draggedId, drop.dir, drop.newFirst);
    if (drop.kind === 'sash')
      return this.insertAtSashGap(root, draggedId, drop);
    if (drop.kind !== 'sibling')
      throw new Error('moveWindow: unknown drop kind ' + drop.kind);
    const f = T.findNode(root, drop.target);
    if (!f) throw new Error('moveWindow: unknown target ' + drop.target);
    if (!f.parent)
      return T.splitLeaf(root, drop.target, draggedId, 'row',
                         drop.side !== 'after');
    const pos = drop.side === 'before' ? f.index : f.index + 1;
    return T.insertAtSplitIndex(root, drop.target, pos, draggedId, drop.target);
  },

  moveWindow(root, draggedId, drop) {
    const T = SashCoreTree;
    if (drop.target && drop.target === draggedId)
      throw new Error('moveWindow: dropping a window on itself');
    const orig = T.findNode(root, draggedId);
    if (!orig) throw new Error('moveWindow: unknown window ' + draggedId);
    const origNode = orig.node;
    if (drop.kind === 'outer') {
      const side = drop.side;
      if (!['top', 'bottom', 'left', 'right'].includes(side))
        throw new Error('moveWindow: bad outer side ' + side);
      const without = T.removeNode(root, origNode);
      return T.insertOuter(without, draggedId, side);
    }
    root = this.insertForDrop(root, draggedId, drop);
    // 2) remove the ORIGINAL node (identity — never "first leaf with this id")
    return T.removeNode(root, origNode);
  },
};
