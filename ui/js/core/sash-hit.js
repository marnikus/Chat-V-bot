/* ═══════════════════════════════════════════════════════════════
   sash-hit.js — which drop target is under the pointer?

   Owns ONE decision: given the pointer and the sashes on screen, is the user
   aiming AT a sash (drop between two rows) rather than at a window?

   Why this exists. Dropping a window onto the sash between two rows already
   inserts a new full-width row -- the root node is a column, so its children
   ARE the rows, and the model handles it. That path was simply unreachable
   from the UI:

     * a sash is `flex: 0 0 6px`, and the pointer must land inside those 6
       physical pixels;
     * worse, _computeSpec iterated window rectangles FIRST and returned on
       the first hit, so the sash loop was only reached when the pointer was
       inside no window at all.

   Both are fixed here: the sash is given a generous hit band around its
   painted 6px, and the caller tests sashes BEFORE windows. Widening the band
   is a hit-testing change only -- nothing about how the sash is drawn
   changes, so the layout does not shift.

   The band is only honoured where there is room for it: it never eats more
   than a third of either neighbouring window, so a narrow panel stays
   droppable on its own account.

   DOM-free on purpose: the UI loads it with a <script> tag and
   tests/test_sash_hit.js executes this exact file in node
   (AGENT_RULES RULE 6).
   ═══════════════════════════════════════════════════════════════ */

(function (root, factory) {
  'use strict';
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.SashHit = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  /** Half the full hit band, in px, added to each side of the painted sash. */
  const BAND = 14;

  /** Never claim more than this fraction of a neighbour's extent. */
  const MAX_SHARE = 1 / 3;

  function inside(rect, x, y) {
    return x >= rect.left && x < rect.right && y >= rect.top && y < rect.bottom;
  }

  /**
   * Grow `rect` along its short axis by up to `band` px per side.
   *
   * `room` is { before, after }: how much the neighbours can spare. Growing
   * past that would make a thin window impossible to drop onto, so the band
   * is clamped rather than applied blindly.
   */
  function expand(rect, band, room) {
    const vertical = rect.height >= rect.width;   // a sash in a row is tall
    const spare = room || {};
    const before = Math.max(0, Math.min(band, (spare.before || 0) * MAX_SHARE));
    const after = Math.max(0, Math.min(band, (spare.after || 0) * MAX_SHARE));
    if (vertical) {
      return { left: rect.left - before, right: rect.right + after,
               top: rect.top, bottom: rect.bottom };
    }
    return { left: rect.left, right: rect.right,
             top: rect.top - before, bottom: rect.bottom + after };
  }

  /** The hit rectangle for one entry of the sash list. */
  function bandOf(sash, band) {
    return expand(sash.rect, band === undefined ? BAND : band, sash.room);
  }

  /**
   * The first sash whose hit band contains the pointer, or null.
   *
   * When bands overlap -- narrow panels, several sashes close together --
   * the nearest sash centre wins, so the target never flickers between two
   * equally valid answers.
   */
  function hitSash(sashes, x, y, band) {
    let best = null, bestDistance = Infinity;
    (sashes || []).forEach((sash) => {
      if (!sash || !sash.rect) return;
      if (!inside(bandOf(sash, band), x, y)) return;
      const distance = Math.abs(
        sash.rect.height >= sash.rect.width
          ? x - (sash.rect.left + sash.rect.width / 2)
          : y - (sash.rect.top + sash.rect.height / 2));
      if (distance < bestDistance) { best = sash; bestDistance = distance; }
    });
    return best;
  }

  /** A full-width/full-height insertion bar for the split holding a sash. */
  function insertionBar(sashRect, parentRect, thickness) {
    const t = thickness || 3;
    if (sashRect.height >= sashRect.width) {
      return { left: sashRect.left + sashRect.width / 2 - t / 2,
               top: parentRect.top, width: t, height: parentRect.height };
    }
    return { left: parentRect.left,
             top: sashRect.top + sashRect.height / 2 - t / 2,
             width: parentRect.width, height: t };
  }

  return { hitSash, expand, bandOf, insertionBar, inside, BAND, MAX_SHARE };
});
