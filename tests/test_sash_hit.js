/* Tests for reaching the between-rows drop target (K4, issue 4).

   Dropping a window between two rows already worked in the MODEL -- the root
   is a column, so its children are the rows, and a {kind:'sash'} drop inserts
   a new full-width row. The UI could almost never deliver that spec:

     * a sash is `flex: 0 0 6px`, so the pointer had to hit 6 physical px;
     * _computeSpec iterated window rectangles first and returned on the first
       hit, so the sash loop was only reached when the pointer was inside no
       window at all -- which, between two adjacent rows, it never is.

   Executes the REAL shipped module (ui/js/core/sash-hit.js) in node,
   per AGENT_RULES RULE 6.

   Run:  node tests/test_sash_hit.js
*/
'use strict';
const path = require('path');
const H = require(path.join(__dirname, '..', 'ui', 'js', 'core', 'sash-hit.js'));

let passed = 0, failed = 0;
function t(name, fn) {
  try { fn(); passed++; }
  catch (e) { failed++; console.error('FAIL ' + name + '\n   ' + (e && e.stack || e)); }
}
function eq(a, b, msg) {
  const x = JSON.stringify(a), y = JSON.stringify(b);
  if (x !== y) throw new Error((msg || 'not equal') + '\n   got  ' + x + '\n   want ' + y);
}
function ok(v, msg) { if (!v) throw new Error(msg || 'expected truthy'); }

const rect = (l, t_, w, h) => ({ left: l, top: t_, right: l + w,
                                 bottom: t_ + h, width: w, height: h });

// A 1200x700 column of three stacked rows, 6px horizontal sashes between.
// Rows: 0..228, sash 228..234, 234..462, sash 462..468, 468..700
function rowStack() {
  return [
    { leftId: 'a', rightId: 'b', inserts: 'row',
      rect: rect(0, 228, 1200, 6), room: { before: 228, after: 228 } },
    { leftId: 'b', rightId: 'c', inserts: 'row',
      rect: rect(0, 462, 1200, 6), room: { before: 228, after: 232 } },
  ];
}

// ── THE BUG: the target must be reachable ──────────────────────────
t('the painted 6px sash is still a hit', () => {
  const s = H.hitSash(rowStack(), 600, 231);
  ok(s, 'dead centre of the sash missed');
  eq(s.leftId, 'a');
});

t('a near miss above the sash now hits -- it used to be the window', () => {
  const s = H.hitSash(rowStack(), 600, 222);
  ok(s, '6px off the sash still missed; the target is unreachable');
  eq(s.leftId, 'a');
});

t('a near miss below the sash hits too', () => {
  const s = H.hitSash(rowStack(), 600, 240);
  ok(s, 'below the sash missed');
  eq(s.leftId, 'a');
});

t('the band is roughly 14px each side, not 3', () => {
  ok(H.hitSash(rowStack(), 600, 228 - 12), 'should hit 12px above');
  ok(H.hitSash(rowStack(), 600, 234 + 12), 'should hit 12px below');
  ok(!H.hitSash(rowStack(), 600, 228 - 40), 'must NOT hit 40px away');
  ok(!H.hitSash(rowStack(), 600, 234 + 40), 'must NOT hit 40px away');
});

t('well inside a window is not a sash hit', () => {
  ok(!H.hitSash(rowStack(), 600, 100), 'middle of the first row');
  ok(!H.hitSash(rowStack(), 600, 350), 'middle of the second row');
  ok(!H.hitSash(rowStack(), 600, 600), 'middle of the third row');
});

t('outside the split entirely is not a hit', () => {
  ok(!H.hitSash(rowStack(), -50, 231), 'left of the grid');
  ok(!H.hitSash(rowStack(), 1400, 231), 'right of the grid');
});

// ── first / middle / last insertion points ─────────────────────────
t('every sash in the stack is individually reachable', () => {
  const first = H.hitSash(rowStack(), 600, 231);
  const last = H.hitSash(rowStack(), 600, 465);
  eq([first.leftId, first.rightId], ['a', 'b'], 'first insertion point');
  eq([last.leftId, last.rightId], ['b', 'c'], 'last insertion point');
});

t('a five-row stack exposes all four insertion points', () => {
  const sashes = [];
  for (let i = 0; i < 4; i++) {
    const y = 140 * (i + 1) + 6 * i;
    sashes.push({ leftId: 'w' + i, rightId: 'w' + (i + 1), inserts: 'row',
                  rect: rect(0, y, 1200, 6), room: { before: 140, after: 140 } });
  }
  sashes.forEach((s, i) => {
    const hit = H.hitSash(sashes, 600, s.rect.top + 3);
    ok(hit, 'insertion point ' + i + ' unreachable');
    eq(hit.leftId, 'w' + i, 'wrong sash for point ' + i);
  });
});

// ── overlapping bands must resolve, not flicker ────────────────────
t('when two bands overlap the nearer sash wins', () => {
  // two sashes only 20px apart: their 14px bands overlap in the middle
  const tight = [
    { leftId: 'a', rightId: 'b', inserts: 'row',
      rect: rect(0, 100, 1200, 6), room: { before: 300, after: 300 } },
    { leftId: 'b', rightId: 'c', inserts: 'row',
      rect: rect(0, 120, 1200, 6), room: { before: 300, after: 300 } },
  ];
  eq(H.hitSash(tight, 600, 104).leftId, 'a', 'nearest to the first');
  eq(H.hitSash(tight, 600, 122).leftId, 'b', 'nearest to the second');
});

t('the choice is stable -- the same point always gives the same sash', () => {
  const s = rowStack();
  const first = H.hitSash(s, 600, 226).leftId;
  for (let i = 0; i < 20; i++) eq(H.hitSash(s, 600, 226).leftId, first);
});

// ── the band must not swallow a thin panel ─────────────────────────
t('a thin neighbour keeps most of itself droppable', () => {
  // a 21px row: a blind 14px band would claim two thirds of it
  const thin = [{ leftId: 'a', rightId: 'b', inserts: 'row',
                  rect: rect(0, 100, 1200, 6),
                  room: { before: 21, after: 400 } }];
  const band = H.bandOf(thin[0]);
  const claimed = thin[0].rect.top - band.top;
  ok(claimed <= 7 + 0.01, 'claimed ' + claimed + 'px of a 21px panel');
  // the panel spans 79..100; the band may claim only its lowest 7px
  ok(!H.hitSash(thin, 600, 90), 'must leave the thin panel reachable');
  ok(!H.hitSash(thin, 600, 80), 'the far end of the panel is certainly safe');
  ok(H.hitSash(thin, 600, 100 + 3), 'the sash itself must still work');
});

t('a roomy neighbour gets the full band', () => {
  const band = H.bandOf(rowStack()[0]);
  eq(rowStack()[0].rect.top - band.top, H.BAND);
});

t('a zero-extent neighbour contributes no band', () => {
  const collapsed = [{ leftId: 'a', rightId: 'b', inserts: 'row',
                       rect: rect(0, 100, 1200, 6),
                       room: { before: 0, after: 0 } }];
  const band = H.bandOf(collapsed[0]);
  eq(band.top, 100);
  eq(band.bottom, 106);
});

// ── vertical sashes (columns) work the same way, on the other axis ─
t('a vertical sash expands horizontally, not vertically', () => {
  const vertical = { leftId: 'a', rightId: 'b', inserts: 'column',
                     rect: rect(400, 0, 6, 700), room: { before: 400, after: 400 } };
  const band = H.bandOf(vertical);
  eq(band.top, 0, 'must not grow along its length');
  eq(band.bottom, 700);
  eq(band.left, 400 - H.BAND);
  eq(band.right, 406 + H.BAND);
  ok(H.hitSash([vertical], 394, 350), 'left of a column sash');
  ok(!H.hitSash([vertical], 300, 350), 'far away must miss');
});

// ── the preview bar spans the whole split ──────────────────────────
t('a horizontal sash previews a full-width bar', () => {
  const bar = H.insertionBar(rect(0, 228, 1200, 6), rect(0, 0, 1200, 700), 3);
  eq(bar.width, 1200, 'the bar must span the split');
  eq(bar.height, 3);
  eq(bar.top, 231 - 1.5, 'centred on the sash');
  eq(bar.left, 0);
});

t('a vertical sash previews a full-height bar', () => {
  const bar = H.insertionBar(rect(400, 0, 6, 700), rect(0, 0, 1200, 700), 3);
  eq(bar.height, 700, 'the bar must span the split');
  eq(bar.width, 3);
  eq(bar.left, 403 - 1.5, 'centred on the sash');
});

// ── hostile input ──────────────────────────────────────────────────
t('a malformed sash list does not throw', () => {
  eq(H.hitSash(null, 10, 10), null);
  eq(H.hitSash([], 10, 10), null);
  eq(H.hitSash([null, {}, { rect: null }], 10, 10), null);
});

// ── end to end: the drop really does create a row ──────────────────
// Proves the target the widened band now reaches produces the insertion the
// ticket asks for, at the first, a middle, and the last position.
const SashCore = require(path.join(__dirname, '..', 'ui', 'js', 'sash-core.js'));

function rowsOf(tree) {
  return tree.children.map(
    (c) => (c.t === 'leaf' ? c.id : SashCore.leafIds(c).join('+')));
}

t('a between-rows drop inserts a new full-width row', () => {
  const before = SashCore.defaultTree();
  const rows = rowsOf(before);
  const after = SashCore.moveWindow(before, 'composer',
    { kind: 'sash', left: 'labels', right: 'botchat' });
  eq(after.dir, 'col', 'the root stays a column of rows');
  ok(after.children.length === before.children.length,
     'composer left its own row and gained a new one');
  ok(rowsOf(after).includes('composer'),
     'composer must be its own full-width row: ' + rowsOf(after).join(' | '));
  ok(rows.length > 0);
});

t('insertion works at the first, middle and last position', () => {
  const places = [
    ['stats', 'composer'],      // first sash in the root column
    ['people', 'history'],      // a middle one
    ['labels', 'botchat'],      // the last one
  ];
  places.forEach(([left, right]) => {
    const tree = SashCore.moveWindow(SashCore.defaultTree(), 'userdb',
                                     { kind: 'sash', left, right });
    const ids = SashCore.leafIds(tree).slice().sort();
    eq(ids, SashCore.WINDOW_IDS.slice().sort(),
       'no window may be lost inserting between ' + left + ' and ' + right);
    ok(rowsOf(tree).includes('userdb'),
       'userdb did not become its own row between ' + left + ' and ' + right +
       ': ' + rowsOf(tree).join(' | '));
  });
});

t('the inserted row lands between the two windows that were flanked', () => {
  const tree = SashCore.moveWindow(SashCore.defaultTree(), 'composer',
    { kind: 'sash', left: 'labels', right: 'botchat' });
  const rows = rowsOf(tree);
  const at = rows.indexOf('composer');
  ok(at > 0, 'composer row not found');
  ok(rows[at - 1].includes('labels'), 'must sit after the left neighbour: ' +
     rows.join(' | '));
  ok(rows[at + 1].includes('botchat'), 'must sit before the right neighbour: ' +
     rows.join(' | '));
});

console.log('sash hit: ' + passed + ' passed, ' + failed + ' failed');
if (failed) process.exit(1);
console.log('OK');
