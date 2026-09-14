/* ═══════════════════════════════════════════════════════════════
   sash-resize-math.js — how much room each child of a split may take

   Owns ONE decision: given the pixel size of a split, how many children it
   has and where the pointer is, what should the two children flanking the
   dragged sash measure?

   Why this is its own module. The rule it implements used to be three lines
   inside `SashGrid._resizePixelAllocation`, and those three lines contained
   the bug this file exists to fix:

       if (span < MIN_PX * 2) return null;   // resize silently does nothing

   `MIN_PX` is a flat 96 px floor held by every child. `span` is what is left
   for the dragged pair after every OTHER child has taken its floor, so span
   shrinks as children accumulate. Measured on a 700 px-tall column: 6
   children leave 286 px and resize works; 7 children leave 184 px and the
   guard trips, so the sash stops responding and the layout is frozen. A
   1200 px-wide row survives past 8, which is why the fault shows up after
   stacking ROWS specifically.

   The fix is to treat 96 px as a *preference*, not a law: when a split is
   too crowded to give everyone 96 px, every child's floor shrinks together
   (`effectiveMin`) so the split stays resizable instead of dying. The floor
   is only ever relaxed when it cannot be honoured.

   DOM-free on purpose: the UI loads it with a <script> tag and
   tests/test_sash_resize_math.js executes this exact file in node
   (AGENT_RULES RULE 6).
   ═══════════════════════════════════════════════════════════════ */

(function (root, factory) {
  'use strict';
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.SashResizeMath = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  /** The per-child floor this split can actually afford.
   *
   * `preferred` (96 px) whenever every child fits at that size, otherwise an
   * equal share of what exists. `count + 1` rather than `count` leaves the
   * dragged pair a sliver of travel at the extreme, so the sash never
   * becomes a no-op.
   */
  function effectiveMin(span, count, preferred) {
    const n = Math.max(1, count);
    if (span <= 0) return 0;
    if (span >= preferred * n) return preferred;
    return Math.max(1, Math.floor(span / (n + 1)));
  }

  /** `effectiveMin` for a split whose sashes also consume the axis.
   *
   * The children only ever share `axis - sashTotal`; measuring the floor
   * against the raw axis claims room the sashes already took, which shows up
   * as the pair silently absorbing the deficit.
   */
  function floorFor(axis, count, sashTotal, preferred) {
    return effectiveMin(axis - Math.max(0, sashTotal), count, preferred);
  }

  /** The CSS floor a split should publish, or '' to inherit the default.
   *
   * The resize maths relaxing its floor is not enough on its own: the browser
   * still enforces `--sash-min-panel` on every panel, so a crowded split
   * overflows instead of shrinking. Returns the value for that custom
   * property, keeping the decision here rather than in the DOM layer.
   */
  function cssFloorFor(count, crowdedAt, preferred) {
    if (count <= crowdedAt) return '';
    return Math.max(24, Math.floor(preferred / 2)) + 'px';
  }

  /** Room left for the two children flanking the sash, after the others. */
  function pairSpan(axis, otherSizes, sashTotal) {
    const others = otherSizes.reduce((sum, v) => sum + Math.max(0, v), 0);
    return axis - others - Math.max(0, sashTotal);
  }

  /** Pixels before the dragged sash: every earlier child plus its sash. */
  function prefixBefore(childSizes, sashSizes, index) {
    let prefix = 0;
    for (let i = 0; i < index; i++) {
      prefix += Math.max(0, childSizes[i] || 0);
      prefix += Math.max(0, sashSizes[i] || 0);
    }
    return prefix;
  }

  /** Split `span` between the two flanking children at `requested`.
   *
   * Returns the pair only; the caller keeps every other child unchanged.
   */
  function splitPair(span, requested, min) {
    const lo = Math.min(min, span / 2);
    const first = Math.min(Math.max(requested, lo), span - lo);
    return [first, span - first];
  }

  /** THE allocation: one array of pixel sizes, one per child.
   *
   * `null` is returned only when the split has no usable room at all (a
   * collapsed or unrendered parent), never merely because it is crowded —
   * that distinction is the bug this module fixes.
   */
  function allocate(input) {
    const { axis, childSizes, sashSizes, index, pointerOffset,
            preferredMin } = input;
    const others = childSizes.filter((_, i) => i !== index && i !== index + 1);
    const sashTotal = sashSizes.reduce((sum, v) => sum + Math.max(0, v), 0);
    const min = floorFor(axis, childSizes.length, sashTotal, preferredMin);
    // Re-floor the untouched children at the SAME relaxed minimum, so a
    // crowded split does not reserve 96 px each for children it cannot fit.
    const held = others.map((v) => Math.max(min, Math.max(0, v)));
    const span = pairSpan(axis, held, sashTotal);
    if (span <= 0) return null;
    const pair = splitPair(span, pointerOffset, min);
    const out = childSizes.slice();
    out[index] = pair[0];
    out[index + 1] = pair[1];
    return out;
  }

  return { effectiveMin, floorFor, cssFloorFor, pairSpan, prefixBefore, splitPair,
           allocate };
});
