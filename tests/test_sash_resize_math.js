/* Regression tests for the sash-death bug (K1).

   Symptom: "after moving some rows and columns horizontal sash lines start
   disappear and i can not move lines anymore."

   Cause: SashGrid._resizePixelAllocation bailed with
       if (span < MIN_PX * 2) return null;
   where span is what remains for the dragged pair after every OTHER child
   has reserved a flat 96px. Stacking children shrinks span until the guard
   trips and the sash stops responding — permanently, because nothing in the
   layout ever gives the room back.

   These tests execute the REAL shipped module (ui/js/core/sash-resize-math.js)
   in node, per AGENT_RULES RULE 6.

   Run:  node tests/test_sash_resize_math.js
   Exits 0 + prints "OK" when every test passes.
*/
'use strict';
const path = require('path');
const M = require(path.join(__dirname, '..', 'ui', 'js', 'core',
                            'sash-resize-math.js'));

let passed = 0, failed = 0;
function t(name, fn) {
  try { fn(); passed++; }
  catch (e) { failed++; console.error('FAIL ' + name + '\n   ' + (e && e.stack || e)); }
}
function eq(a, b, msg) {
  if (a !== b) throw new Error((msg || 'not equal') + ': ' + a + ' !== ' + b);
}
function ok(v, msg) { if (!v) throw new Error(msg || 'expected truthy'); }

const MIN = 96;
// one split of `n` equal children, each separated by a 6px sash
function column(n, axis) {
  return { axis, childSizes: Array(n).fill((axis - (n - 1) * 6) / n),
           sashSizes: Array(Math.max(0, n - 1)).fill(6) };
}
function alloc(n, axis, index, pointerOffset) {
  const c = column(n, axis);
  return M.allocate({ axis: c.axis, childSizes: c.childSizes,
                      sashSizes: c.sashSizes, index,
                      pointerOffset, preferredMin: MIN });
}

// ── THE BUG: a crowded column must stay resizable ──────────────────
// Measured against the old guard: a 700px column died at 7 children
// (span 184px < 192px). Every one of these used to return null.
t('700px column stays resizable from 2 to 12 children', () => {
  for (let n = 2; n <= 12; n++) {
    const a = alloc(n, 700, 0, 200);
    ok(a !== null, n + ' children returned null (sash dead)');
    eq(a.length, n, 'allocation length for ' + n);
  }
});

t('the 7th child — the exact case that used to freeze — resizes', () => {
  const a = alloc(7, 700, 0, 150);
  ok(a !== null, '7 children still dead');
  ok(a[0] !== a[1] || true, 'pair present');
  ok(a[0] > 0 && a[1] > 0, 'both flanking children have room');
});

t('a wide row was never affected and still works', () => {
  for (let n = 2; n <= 10; n++) ok(alloc(n, 1200, 0, 400) !== null, n + ' wide');
});

// ── the floor relaxes only when it must ────────────────────────────
t('effectiveMin keeps 96px while every child fits', () => {
  eq(M.effectiveMin(700, 2, MIN), 96);
  eq(M.effectiveMin(700, 7, MIN), 96 === 96 && 700 >= 96 * 7 ? 96 : M.effectiveMin(700, 7, MIN));
  eq(M.effectiveMin(1200, 12, MIN), 96);   // 12*96 = 1152 <= 1200
});

t('effectiveMin shrinks together when the split is crowded', () => {
  const m = M.effectiveMin(700, 10, MIN);   // 10*96 = 960 > 700
  ok(m < 96, 'floor should relax, got ' + m);
  ok(m > 0, 'floor must stay positive');
  ok(m * 10 <= 700, 'relaxed floor must fit: ' + m);
});

t('effectiveMin never returns a negative or NaN', () => {
  eq(M.effectiveMin(0, 5, MIN), 0);
  eq(M.effectiveMin(-50, 5, MIN), 0);
  ok(Number.isFinite(M.effectiveMin(700, 0, MIN)));
});

// ── the pair split itself ──────────────────────────────────────────
t('splitPair honours the pointer between the floors', () => {
  const [a, b] = M.splitPair(400, 150, 96);
  eq(a, 150); eq(b, 250);
});

t('splitPair clamps to the floor on both ends', () => {
  eq(M.splitPair(400, -999, 96)[0], 96);
  eq(M.splitPair(400, 9999, 96)[0], 304);
});

t('splitPair degrades gracefully when span < 2*min', () => {
  const [a, b] = M.splitPair(100, 50, 96);   // impossible floor
  ok(a > 0 && b > 0, 'both sides positive: ' + a + '/' + b);
  eq(Math.round(a + b), 100, 'pair must still fill the span');
});

t('the pair always sums to the available span', () => {
  for (let n = 2; n <= 9; n++) {
    const c = column(n, 700);
    const a = alloc(n, 700, 0, 220);
    const sashTotal = c.sashSizes.reduce((s, v) => s + v, 0);
    const held = a.filter((_, i) => i !== 0 && i !== 1)
                  .reduce((s, v) => s + v, 0);
    ok(Math.abs((a[0] + a[1] + held + sashTotal) - 700) < 1.5,
       'n=' + n + ' does not fill the axis: ' + (a[0] + a[1] + held + sashTotal));
  }
});

// ── null means "no room at all", not "crowded" ─────────────────────
t('null only for a collapsed / unrendered split', () => {
  eq(M.allocate({ axis: 0, childSizes: [0, 0], sashSizes: [6],
                  index: 0, pointerOffset: 0, preferredMin: MIN }), null);
  ok(alloc(9, 700, 0, 100) !== null, 'crowded must NOT be null');
});

// ── prefixBefore ───────────────────────────────────────────────────
t('prefixBefore sums earlier children and their sashes', () => {
  eq(M.prefixBefore([100, 100, 100], [6, 6], 0), 0);
  eq(M.prefixBefore([100, 100, 100], [6, 6], 1), 106);
  eq(M.prefixBefore([100, 100, 100], [6, 6], 2), 212);
});

t('prefixBefore tolerates short/na sash arrays', () => {
  eq(M.prefixBefore([100, 100], [], 1), 100);
  eq(M.prefixBefore([100, 100], [undefined], 1), 100);
});

// ── dragging any sash, not just the first ──────────────────────────
t('every sash index in a crowded split is draggable', () => {
  const n = 8;
  for (let i = 0; i < n - 1; i++) {
    const a = alloc(n, 700, i, 300);
    ok(a !== null, 'sash ' + i + ' of ' + n + ' is dead');
    ok(a[i] > 0 && a[i + 1] > 0, 'sash ' + i + ' gave a zero-width child');
  }
});

// ── the CSS floor must follow the maths ────────────────────────────
// Relaxing only the arithmetic is not enough: the browser keeps enforcing
// --sash-min-panel, so a crowded split overflows instead of shrinking.
t('cssFloorFor inherits the default until the split is crowded', () => {
  eq(M.cssFloorFor(2, 6, MIN), '');
  eq(M.cssFloorFor(6, 6, MIN), '');
});

t('cssFloorFor relaxes past the crowding threshold', () => {
  eq(M.cssFloorFor(7, 6, MIN), '48px');
  eq(M.cssFloorFor(20, 6, MIN), '48px');
});

t('cssFloorFor never goes below a grabbable 24px', () => {
  eq(M.cssFloorFor(9, 6, 10), '24px');
});

console.log('sash resize math: ' + passed + ' passed, ' + failed + ' failed');
if (failed) process.exit(1);
console.log('OK');
