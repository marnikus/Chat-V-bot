/* Tests for adapting a saved preset to a different window set (K2).

   Ticket: "layouts should adapt: match by id, skip windows this build does
   not have, add ones it does, and say what happened." Restore was previously
   all-or-nothing -- any difference in the window list rejected the document.

   Executes the REAL shipped module (ui/js/core/preset-reconcile.js) in node,
   per AGENT_RULES RULE 6.

   Run:  node tests/test_preset_reconcile.js
*/
'use strict';
const path = require('path');
const R = require(path.join(__dirname, '..', 'ui', 'js', 'core',
                            'preset-reconcile.js'));

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

const leaf = (id) => ({ t: 'leaf', id });
const split = (dir, children, sizes) => ({
  t: 'split', dir, children,
  sizes: sizes || R.evenSizes(children.length),
});

// the shape a real preset has: a column of rows
function savedTree() {
  return split('col', [
    split('row', [leaf('chat'), leaf('people')], [60, 40]),
    leaf('composer'),
    leaf('log'),
  ], [50, 30, 20]);
}
function idsOf(tree) { return R.treeIds(tree); }
function sumSizes(node) {
  if (!node || node.t !== 'split') return;
  const total = node.sizes.reduce((s, v) => s + v, 0);
  if (Math.abs(total - 100) > 0.01) {
    throw new Error('split sizes sum to ' + total + ', not 100');
  }
  if (node.sizes.length !== node.children.length) {
    throw new Error('sizes/children length mismatch');
  }
  node.children.forEach(sumSizes);
}

// ── the common case must stay untouched ────────────────────────────
t('a preset from the same build is passed through unchanged', () => {
  const tree = savedTree();
  const r = R.reconcile(tree, ['chat', 'people', 'composer', 'log']);
  eq(r.skipped, []);
  eq(r.extra, []);
  eq(r.changed, false, 'must report no change');
  eq(idsOf(r.tree).sort(), ['chat', 'composer', 'log', 'people']);
});

t('an unchanged preset keeps its exact proportions', () => {
  const r = R.reconcile(savedTree(), ['chat', 'people', 'composer', 'log']);
  eq(r.tree.sizes, [50, 30, 20], 'root sizes must survive verbatim');
  eq(r.tree.children[0].sizes, [60, 40], 'nested sizes must survive');
});

t('reconcile is idempotent', () => {
  const live = ['chat', 'people', 'composer'];
  const once = R.reconcile(savedTree(), live);
  const twice = R.reconcile(once.tree, live);
  eq(twice.tree, once.tree, 'second pass must change nothing');
  eq(twice.changed, false);
});

// ── rule 2: skip what this build does not have ─────────────────────
t('a window this build lacks is dropped and reported', () => {
  const r = R.reconcile(savedTree(), ['chat', 'people', 'composer']);
  eq(r.skipped, ['log']);
  eq(r.extra, []);
  eq(r.changed, true);
  ok(!idsOf(r.tree).includes('log'), 'log must be gone from the tree');
  eq(idsOf(r.tree).sort(), ['chat', 'composer', 'people']);
});

t('a split left with one child collapses instead of nesting pointlessly', () => {
  // dropping 'people' leaves the inner row holding only 'chat'
  const r = R.reconcile(savedTree(), ['chat', 'composer', 'log']);
  eq(r.tree.children[0], leaf('chat'), 'the row must collapse to its leaf');
});

t('the collapse propagates through several dead levels', () => {
  const deep = split('col', [
    split('row', [split('col', [leaf('gone-a'), leaf('gone-b')]), leaf('chat')]),
    leaf('log'),
  ]);
  const r = R.reconcile(deep, ['chat', 'log']);
  eq(r.skipped.sort(), ['gone-a', 'gone-b']);
  eq(idsOf(r.tree).sort(), ['chat', 'log']);
  sumSizes(r.tree);
});

t('surviving siblings absorb the space, still summing to 100', () => {
  const r = R.reconcile(savedTree(), ['chat', 'people', 'composer']);
  sumSizes(r.tree);
});

// ── rule 3: add what the preset never knew about ───────────────────
t('a window the preset never mentioned is grafted and reported', () => {
  const r = R.reconcile(savedTree(),
                        ['chat', 'people', 'composer', 'log', 'bot']);
  eq(r.skipped, []);
  eq(r.extra, ['bot']);
  eq(r.changed, true);
  ok(idsOf(r.tree).includes('bot'), 'bot must be present');
  sumSizes(r.tree);
});

t('a grafted window is a real row, not a sliver', () => {
  const r = R.reconcile(savedTree(),
                        ['chat', 'people', 'composer', 'log', 'bot']);
  eq(r.tree.dir, 'col', 'graft appends a row along the bottom');
  const share = r.tree.sizes[r.tree.sizes.length - 1];
  ok(share >= 5, 'grafted row is invisible at ' + share + '%');
  ok(share <= 40, 'grafted row must not dominate: ' + share + '%');
});

t('several new windows share one grafted row', () => {
  const r = R.reconcile(savedTree(),
                        ['chat', 'people', 'composer', 'log', 'bot', 'stats']);
  eq(r.extra, ['bot', 'stats']);
  const added = r.tree.children[r.tree.children.length - 1];
  eq(added.dir, 'row');
  eq(idsOf(added), ['bot', 'stats']);
  sumSizes(r.tree);
});

// ── both at once ───────────────────────────────────────────────────
t('a preset from a divergent build both skips and adds', () => {
  const r = R.reconcile(savedTree(), ['chat', 'composer', 'bot']);
  eq(r.matched, ['chat', 'composer'], 'matched keeps saved order');
  eq(r.skipped, ['people', 'log']);
  eq(r.extra, ['bot']);
  eq(idsOf(r.tree).sort(), ['bot', 'chat', 'composer']);
  sumSizes(r.tree);
});

t('the live set is always exactly satisfied', () => {
  const cases = [
    ['chat'],
    ['chat', 'people'],
    ['bot'],
    ['bot', 'stats', 'extra'],
    ['chat', 'people', 'composer', 'log', 'bot', 'stats'],
  ];
  cases.forEach((live) => {
    const r = R.reconcile(savedTree(), live);
    eq(idsOf(r.tree).sort(), live.slice().sort(),
       'tree must hold exactly the live windows for ' + JSON.stringify(live));
    sumSizes(r.tree);
  });
});

// ── rule 1: match by id only ───────────────────────────────────────
t('ids match exactly -- a renamed window is a different window', () => {
  const r = R.reconcile(savedTree(), ['chat', 'people', 'composer', 'logs']);
  eq(r.skipped, ['log'], 'log must NOT be guessed as logs');
  eq(r.extra, ['logs'], 'logs must arrive as new');
});

// ── hostile input ──────────────────────────────────────────────────
t('a duplicated id in the saved tree is kept only once', () => {
  const dup = split('col', [leaf('chat'), leaf('chat'), leaf('log')]);
  const r = R.reconcile(dup, ['chat', 'log']);
  eq(idsOf(r.tree).sort(), ['chat', 'log']);
  eq(R.treeIds(r.tree).length, 2, 'no duplicate leaf may survive');
});

t('garbage sizes are replaced, never propagated', () => {
  const bad = split('col', [leaf('chat'), leaf('log')], [NaN, -20]);
  const r = R.reconcile(bad, ['chat', 'log', 'bot']);
  sumSizes(r.tree);
});

t('a malformed node does not throw', () => {
  [null, undefined, {}, { t: 'split' }, { t: 'leaf' }, 42, 'x'].forEach((bad) => {
    const r = R.reconcile(bad, ['chat', 'log']);
    eq(idsOf(r.tree).sort(), ['chat', 'log'], 'must rebuild from the live set');
  });
});

t('an empty live set yields no tree rather than a broken one', () => {
  const r = R.reconcile(savedTree(), []);
  eq(r.tree, null);
  eq(r.extra, []);
});

// ── rule 5: say what happened ──────────────────────────────────────
t('an unchanged preset says nothing', () => {
  const r = R.reconcile(savedTree(), ['chat', 'people', 'composer', 'log']);
  eq(R.summarize(r), '');
});

t('the summary names the skipped and added windows', () => {
  const r = R.reconcile(savedTree(), ['chat', 'composer', 'bot']);
  const s = R.summarize(r);
  ok(s.includes('people') && s.includes('log'), 'must name what was skipped: ' + s);
  ok(s.includes('bot'), 'must name what was added: ' + s);
});

t('the summary is singular for one window', () => {
  const r = R.reconcile(savedTree(), ['chat', 'people', 'composer']);
  const s = R.summarize(r);
  ok(s.includes('1 window '), 'expected singular wording, got: ' + s);
  ok(!s.includes('1 windows'), 'bad pluralisation: ' + s);
});

console.log('preset reconcile: ' + passed + ' passed, ' + failed + ' failed');
if (failed) process.exit(1);
console.log('OK');
