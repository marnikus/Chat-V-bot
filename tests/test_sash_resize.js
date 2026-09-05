/* Regression tests for the live sash-resize pixel allocation.
 *
 * The test loads the shipped ui/js/sash-grid.js module. It deliberately does
 * not use a DOM implementation: _resizePixelAllocation is the pure geometry
 * part of the pointer handler and is where the row-collapse regression lived.
 */
'use strict';

const fs = require('fs');
const vm = require('vm');

global.document = { addEventListener() {} };
global.SashCore = {};
vm.runInThisContext(
  fs.readFileSync('ui/js/sash-grid.js', 'utf8') +
  '\nglobalThis.__SashGridForResizeTests = SashGrid;'
);
const SashGrid = global.__SashGridForResizeTests;

let passed = 0;
let failed = 0;
function test(name, fn) {
  try { fn(); passed++; }
  catch (error) {
    failed++;
    console.error('FAIL ' + name + '\n  ' + (error.stack || error));
  }
}
function eq(actual, expected, message) {
  const a = JSON.stringify(actual);
  const e = JSON.stringify(expected);
  if (a !== e) throw new Error((message || 'not equal') + `\n  got ${a}\n  want ${e}`);
}

// A vertical root split with three rows. The third row is not part of the
// active pair and must keep its 234px allocation during a Composer resize.
const rootRect = { left: 0, top: 100, width: 1200, height: 800 };
const base = {
  isRow: false,
  sIdx: 0,
  childSizes: [368, 192, 234],
  sashSizes: [6, 6],
  otherWidths: { 2: 234 },
};

function allocation(pointerY) {
  return SashGrid._resizePixelAllocation(
    { ...base, childSizes: base.childSizes.slice() }, pointerY, rootRect);
}

test('vertical resize keeps the non-active bottom row in the same pixel unit', () => {
  eq(allocation(650), [458, 96, 234]);
});

test('pointer above the grid clamps the upper row, without a negative size', () => {
  eq(allocation(-500), [96, 458, 234]);
});

test('pointer below the grid clamps the lower active row, without shrinking the neighbor', () => {
  eq(allocation(5000), [458, 96, 234]);
});

test('horizontal resize uses the same complete-pixel allocation', () => {
  const z = {
    isRow: true,
    sIdx: 1,
    childSizes: [180, 300, 220],
    sashSizes: [6, 6],
    otherWidths: { 0: 180 },
  };
  eq(SashGrid._resizePixelAllocation(z, 500,
    { left: 50, top: 0, width: 720, height: 500 }), [180, 264, 264]);
});

test('an impossible pair refuses to resize instead of collapsing a child', () => {
  const z = {
    isRow: false,
    sIdx: 0,
    childSizes: [40, 40, 700],
    sashSizes: [6, 6],
    otherWidths: { 2: 700 },
  };
  const result = SashGrid._resizePixelAllocation(z, 100, rootRect);
  if (result !== null) throw new Error('expected null allocation');
});

console.log(`sash_resize: ${passed} passed, ${failed} failed`);
if (failed) process.exitCode = 1;
