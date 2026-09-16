/* sash-core-validate.js — structural validation, v1→v2 migration, and
   (de)serialisation for the sash layout (Round II Area B).

   Split out of ui/js/sash-core.js; the facade lists its parts. The wire
   format is pinned by python-side persistence tests
   (tests/test_grid_persistence.py, test_grid_layout_v2_migration.py):
   `serialize` writes { v: <VERSION>, tree }, `deserialize` accepts v1 bare
   trees up to the current VERSION and migrates them. Cross-part calls
   resolve at call time.
*/
'use strict';

const SashCoreValidate = {
  MAX_DEPTH: 12,

  /** Structural error string of one node subtree, or null when sound. */
  treeError(node, depth) {
    const T = SashCoreTree;
    if (depth > this.MAX_DEPTH) return 'tree too deep';
    if (T.isLeaf(node)) {
      if (typeof node.id !== 'string' || !node.id) return 'leaf without id';
      return null;
    }
    if (!T.isSplit(node)) return 'unknown node type';
    if (node.dir !== 'row' && node.dir !== 'col') return 'bad dir';
    if (!Array.isArray(node.children) || node.children.length < 2)
      return 'split needs ≥2 children';
    if (!Array.isArray(node.sizes) || node.sizes.length !== node.children.length)
      return 'sizes must match children';
    for (const s of node.sizes)
      if (!Number.isFinite(s) || s < T.MIN_SIZE)
        return 'bad size value (panel below minimum size)';
    const sum = node.sizes.reduce((a, b) => a + b, 0);
    if (sum < 99.5 || sum > 100.5) return 'sizes must sum to 100 (got ' + sum + ')';
    for (const c of node.children) {
      const err = this.treeError(c, depth + 1);
      if (err) return err;
    }
    return null;
  },

  /**
   * Full structural validation. Returns an error string, or null when the
   * tree is a usable arrangement of exactly `expectedIds`.
   */
  validate(root, expectedIds) {
    const expect = (expectedIds || SashCoreLayouts.WINDOW_IDS).slice().sort();
    const err = this.treeError(root, 0);
    if (err) return err;
    const got = SashCoreTree.leafIds(root).slice().sort();
    if (got.length !== expect.length) return 'leaf count mismatch';
    for (let i = 0; i < expect.length; i++)
      if (got[i] !== expect[i]) return 'leaf id mismatch (' + got[i] + ' ≠ ' + expect[i] + ')';
    return null;
  },

  /**
   * Drop leaves that are not windows any more (and repeated ids),
   * collapsing splits that end up with a single child. Returns null when
   * nothing usable is left.
   */
  pruneTree(node, seen, allowed) {
    const T = SashCoreTree;
    seen = seen || new Set();
    allowed = allowed || new Set(SashCoreLayouts.WINDOW_IDS);
    if (T.isLeaf(node)) {
      if (typeof node.id !== 'string' || !allowed.has(node.id)) return null;
      if (seen.has(node.id)) return null;
      seen.add(node.id);
      return T.leaf(node.id);
    }
    if (!T.isSplit(node) || !Array.isArray(node.children)) return null;
    const kids = [], sizes = [];
    node.children.forEach((child, i) => {
      const kept = this.pruneTree(child, seen, allowed);
      if (!kept) return;
      kids.push(kept);
      const size = Array.isArray(node.sizes) ? Number(node.sizes[i]) : NaN;
      sizes.push(Number.isFinite(size) && size > 0 ? size : T.MIN_SIZE);
    });
    if (!kids.length) return null;
    if (kids.length === 1) return kids[0];
    return { t: 'split', dir: node.dir === 'col' ? 'col' : 'row',
             children: kids, sizes: T.normalizeSizes(sizes) };
  },

  /** Even sizes that always sum to exactly 100 (integers where possible). */
  evenSizes(count) {
    const base = Math.floor(100 / count);
    const out = new Array(count).fill(base);
    out[0] += 100 - base * count;
    return out;
  },

  /**
   * Upgrade an older arrangement to the current window set: unknown and
   * duplicated windows are dropped, missing ones are appended as a new row
   * along the bottom, and the user's existing arrangement is preserved.
   * Anything unusable falls back to the default tree. Idempotent.
   */
  migrate(tree) {
    const T = SashCoreTree, L = SashCoreLayouts;
    const pruned = this.pruneTree(tree);
    if (!pruned || !T.isSplit(pruned)) return L.defaultTree();
    const present = new Set(T.leafIds(pruned));
    const missing = L.WINDOW_IDS.filter((id) => !present.has(id));
    if (!missing.length) return this.validate(pruned) ? L.defaultTree() : pruned;
    const extra = missing.length === 1
      ? T.leaf(missing[0])
      : { t: 'split', dir: 'row', children: missing.map(T.leaf),
          sizes: this.evenSizes(missing.length) };
    const share = Math.min(40, Math.max(T.MIN_SIZE, missing.length * 9));
    const out = { t: 'split', dir: 'col', children: [pruned, extra],
                  sizes: [100 - share, share] };
    return this.validate(out) ? L.defaultTree() : out;
  },

  serialize(tree) {
    return JSON.stringify({ v: SashCoreLayouts.VERSION, tree });
  },

  /**
   * Parse + validate, migrating older versions.
   * Returns { ok:true, tree, migrated? } or { ok:false, error }.
   */
  deserialize(str, expectedIds) {
    const T = SashCoreTree;
    let obj;
    try {
      obj = JSON.parse(str);
    } catch (e) {
      return { ok: false, error: 'unparseable: ' + e.message };
    }
    const versioned = obj && typeof obj === 'object' && !obj.t;
    const version = versioned ? obj.v : 1;      // a bare tree is a v1 layout
    const tree = versioned ? obj.tree : obj;
    if (!Number.isInteger(version) || version < 1 || version > SashCoreLayouts.VERSION)
      return { ok: false, error: 'unsupported layout version ' + version };
    if (version === SashCoreLayouts.VERSION) {
      const err = this.validate(tree, expectedIds);
      return err ? { ok: false, error: err } : { ok: true, tree: T.clone(tree) };
    }
    // Older layout: refuse structural rubbish rather than half-migrating it,
    // then upgrade the arrangement so nobody loses their layout on update.
    const structural = this.validate(tree, T.leafIds(tree));
    if (structural) return { ok: false, error: structural };
    const upgraded = this.migrate(tree);
    const err = this.validate(upgraded, expectedIds);
    return err ? { ok: false, error: err }
               : { ok: true, tree: upgraded, migrated: true };
  },
};
