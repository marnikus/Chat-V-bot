/* ═══════════════════════════════════════════════════════════════
   preset-reconcile.js — fit a saved window preset to the live window set

   Owns ONE decision: a preset was written by some build of the app, and the
   build loading it may not have the same windows. What layout should the
   user actually get?

   Why this is its own module. Restore used to be all-or-nothing. Three
   separate checks in sash-grid.js reject a document outright when the window
   list differs at all:

       doc.windows.length !== SashCore.WINDOW_IDS.length   -> reject
       !SashCore.WINDOW_IDS.includes(item.id)              -> reject
       grid.window_count !== SashCore.WINDOW_IDS.length    -> reject

   so a preset from a build with one extra or one fewer window is unusable,
   even though the rest of the arrangement is perfectly applicable. Loosening
   those checks would be the wrong fix: they are the reason a corrupt
   document is caught. The document is instead ADAPTED to the live set here,
   before the tree is applied, and validation stays strict about structure.

   The rules, in order:

     1. MATCH by exact id. Ids are the stable key. No fuzzy title matching --
        a renamed window is a different window, and guessing would silently
        move a user's layout somewhere they never put it.
     2. SKIP saved ids that are not live: drop the leaf and collapse any split
        left holding a single child.
     3. GRAFT live ids the document never mentions, as new full-width rows at
        the root, so a new window is always visible and usable -- never
        off-screen and never silently missing.
     4. RENORMALISE every split's sizes back to 100.
     5. REPORT matched / skipped / extra so the UI can tell the user what
        happened instead of leaving them to notice.

   Reconciliation is a no-op when the sets already agree, which is the
   overwhelmingly common case: same build, same windows, byte-identical tree.

   DOM-free on purpose: the UI loads it with a <script> tag and
   tests/test_preset_reconcile.js executes this exact file in node
   (AGENT_RULES RULE 6).
   ═══════════════════════════════════════════════════════════════ */

(function (root, factory) {
  'use strict';
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.PresetReconcile = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  const MIN_SIZE = 5;

  function isLeaf(n) { return !!n && n.t === 'leaf'; }
  function isSplit(n) {
    return !!n && n.t === 'split' && Array.isArray(n.children);
  }

  /** Sizes that sum to exactly 100, integers where they can be. */
  function evenSizes(count) {
    const base = Math.floor(100 / count);
    const out = new Array(count).fill(base);
    out[0] += 100 - base * count;
    return out;
  }

  /** Scale `sizes` to sum 100, falling back to an even share. */
  function normalize(sizes, count) {
    const clean = [];
    for (let i = 0; i < count; i++) {
      const v = Number(sizes && sizes[i]);
      clean.push(Number.isFinite(v) && v > 0 ? v : MIN_SIZE);
    }
    const total = clean.reduce((s, v) => s + v, 0);
    if (!(total > 0)) return evenSizes(count);
    // Already correct: return the values untouched rather than dividing and
    // re-multiplying, which turns a clean 28 into 28.000000000000004 and
    // makes a round trip look like a change when nothing moved.
    if (Math.abs(total - 100) < 1e-9) return clean;
    return clean.map((v) => (v / total) * 100);
  }

  /** Every leaf id in `node`, in document order, duplicates included. */
  function collectIds(node, out) {
    const ids = out || [];
    if (isLeaf(node)) ids.push(node.id);
    else if (isSplit(node)) node.children.forEach((c) => collectIds(c, ids));
    return ids;
  }

  /**
   * Rule 1 + 2: keep leaves whose id is live and not already used, drop the
   * rest, collapse a split left with one child, and renormalise what stays.
   *
   * Returns null when nothing under `node` survived -- the caller splices it
   * out, which is what makes the collapse propagate upward.
   */
  function prune(node, live, seen) {
    if (isLeaf(node)) {
      const id = node.id;
      if (typeof id !== 'string' || !live.has(id) || seen.has(id)) return null;
      seen.add(id);
      return { t: 'leaf', id };
    }
    if (!isSplit(node)) return null;
    const kids = [], sizes = [];
    node.children.forEach((child, i) => {
      const kept = prune(child, live, seen);
      if (!kept) return;
      kids.push(kept);
      sizes.push(Number(node.sizes && node.sizes[i]));
    });
    if (!kids.length) return null;
    if (kids.length === 1) return kids[0];       // collapse
    return { t: 'split', dir: node.dir === 'col' ? 'col' : 'row',
             children: kids, sizes: normalize(sizes, kids.length) };
  }

  /** The node holding the windows to graft: one leaf, or a row of them. */
  function graftNode(ids) {
    if (ids.length === 1) return { t: 'leaf', id: ids[0] };
    return { t: 'split', dir: 'row', children: ids.map((id) => ({ t: 'leaf', id })),
             sizes: evenSizes(ids.length) };
  }

  /**
   * Rule 3: append the missing windows as a new row along the bottom.
   *
   * The share is proportional to how many are being added but capped, so
   * grafting one window onto a full layout does not shove the user's
   * arrangement into a sliver.
   */
  function graft(tree, missing) {
    if (!missing.length) return tree;
    if (!tree) return graftNode(missing);
    const share = Math.min(40, Math.max(MIN_SIZE, missing.length * 9));
    return { t: 'split', dir: 'col',
             children: [tree, graftNode(missing)],
             sizes: [100 - share, share] };
  }

  /** The window ids a document's tree refers to, de-duplicated. */
  function treeIds(tree) {
    return Array.from(new Set(collectIds(tree).filter(
      (id) => typeof id === 'string')));
  }

  /**
   * Adapt `tree` to `liveIds`.
   *
   * Returns { tree, matched, skipped, extra, changed }:
   *   matched  saved windows that are live and kept, in saved order
   *   skipped  saved windows this build does not have, so they were dropped
   *   extra    live windows the preset never mentioned, so they were added
   *   changed  false when the preset already fits -- the common case
   *
   * `tree` is null only when `liveIds` is empty; there is nothing to show.
   */
  function reconcile(tree, liveIds) {
    const live = new Set(liveIds || []);
    const saved = treeIds(tree);
    const matched = saved.filter((id) => live.has(id));
    const skipped = saved.filter((id) => !live.has(id));
    const kept = new Set(matched);
    const extra = (liveIds || []).filter((id) => !kept.has(id));
    const pruned = prune(tree, live, new Set());
    return { tree: graft(pruned, extra), matched, skipped, extra,
             changed: skipped.length > 0 || extra.length > 0 };
  }

  /** One human-readable line for the preview, or '' when nothing changed. */
  function summarize(result) {
    if (!result || !result.changed) return '';
    const parts = [];
    if (result.skipped.length) {
      parts.push('skipped ' + result.skipped.length + ' window' +
                 (result.skipped.length === 1 ? '' : 's') +
                 ' this build does not have (' + result.skipped.join(', ') + ')');
    }
    if (result.extra.length) {
      parts.push('added ' + result.extra.length + ' new window' +
                 (result.extra.length === 1 ? '' : 's') +
                 ' (' + result.extra.join(', ') + ')');
    }
    return 'Adapted to this build: ' + parts.join('; ') + '.';
  }

  return { reconcile, summarize, prune, graft, treeIds, normalize, evenSizes };
});
