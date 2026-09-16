/* ═══════════════════════════════════════════════════════════════
   sash-core.js — SashCore facade: the pure model for the flexible grid
   ("sash layout"), assembled from its parts (Round II Area B split,
   684→~50).

   Part families: SashCoreTree (pure split-tree ops), SashCoreLayouts
   (window registry + presets), SashCoreMove (the drop operation),
   SashCoreValidate (validation / migrate / (de)serialise). The public API
   is the original flat object — call sites must not notice the split.

   Parts loaded before this one — see ui/index.html:
     sash-core-tree.js, sash-core-layouts.js, sash-core-move.js,
     sash-core-validate.js

   DOM-free on purpose: the same files ship in the UI and execute under
   Node (AGENT_RULES RULE 6).
   ═══════════════════════════════════════════════════════════════ */

(function (root, factory) {
  'use strict';
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.SashCore = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  /** Merge the parts into one flat API object. Methods keep their PART as
     receiver (`this`), so a method and the helpers it calls stay on one
     object even after flattening — call sites see the unchanged flat API. */
  function flatten(parts) {
    const out = {};
    for (const part of parts) {
      for (const k of Object.keys(part)) {
        const v = part[k];
        out[k] = typeof v === 'function' ? v.bind(part) : v;
      }
    }
    return out;
  }

  const all = flatten([SashCoreLayouts, SashCoreTree, SashCoreMove,
                       SashCoreValidate]);

  // The original public key set, in its original order — nothing more,
  // nothing less (internal part helpers like treeError stay internal).
  return publicApi(all);

  /** The public key subset of the merged parts (original order kept). */
  function publicApi(all) {
    return {
    WINDOWS: all.WINDOWS, WINDOW_IDS: all.WINDOW_IDS,
    WINDOW_TITLES: all.WINDOW_TITLES,
    V1_WINDOW_IDS: all.V1_WINDOW_IDS, V2_WINDOW_IDS: all.V2_WINDOW_IDS,
    V3_WINDOW_IDS: all.V3_WINDOW_IDS, VERSION: all.VERSION,
    MAX_DEPTH: all.MAX_DEPTH, MIN_SIZE: all.MIN_SIZE,
    pruneTree: all.pruneTree, migrate: all.migrate,
    leaf: all.leaf, split: all.split, clone: all.clone,
    firstLeafId: all.firstLeafId,
    defaultTree: all.defaultTree, layoutA: all.layoutA, layoutB: all.layoutB,
    layoutC: all.layoutC, PRESETS: all.PRESETS,
    normalizeSizes: all.normalizeSizes,
    isLeaf: all.isLeaf, isSplit: all.isSplit, forEachLeaf: all.forEachLeaf,
    leafIds: all.leafIds, findNode: all.findNode, parentSplit: all.parentSplit,
    splitLeaf: all.splitLeaf, insertAtSplitIndex: all.insertAtSplitIndex,
    insertSibling: all.insertSibling, insertBetween: all.insertBetween,
    setSplitSizes: all.setSplitSizes,
    normalizePath: all.normalizePath, nodeAtPath: all.nodeAtPath,
    insertAtSplitPath: all.insertAtSplitPath,
    setSplitSizesByPath: all.setSplitSizesByPath,
    parentPath: all.parentPath, leafPaths: all.leafPaths,
    removeLeaf: all.removeLeaf, moveWindow: all.moveWindow,
    validate: all.validate, serialize: all.serialize,
    deserialize: all.deserialize,
    };
  }
});
