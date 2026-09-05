/* Tests for the sash-layout tree model (the flexible grid "sash layout").

Per AGENT_RULES RULE 6 the test executes the REAL shipped module
(ui/js/sash-core.js) in a real runtime (Node), not a stub.

API notes (as shipped):
  S.validate(tree)          → null when valid, else an error string
  S.findNode(tree, id)      → { node, parent, index } | null
  S.deserialize(str)        → { ok:true, tree } | { ok:false, error }
  mutators mutate in place and return the (possibly new) root

Run:  node tests/test_sash_core.js
Exits 0 + prints "OK" when every test passes.
*/
'use strict';
const fs = require('fs');
const path = require('path');

const src = fs.readFileSync(
  path.join(__dirname, '..', 'ui', 'js', 'sash-core.js'), 'utf8');
const module_ = { exports: {} };
new Function('module', 'exports', src)(module_, module_.exports);
const S = module_.exports;

let passed = 0, failed = 0;
function t(name, fn) {
  try { fn(); passed++; }
  catch (e) { failed++; console.error('FAIL ' + name + '\n   ' + (e && e.stack || e)); }
}
function eq(a, b, msg) {
  const ja = JSON.stringify(a), jb = JSON.stringify(b);
  if (ja !== jb) throw new Error((msg || 'eq') + '\n  got:  ' + ja + '\n  want: ' + jb);
}
function ok(cond, msg) { if (!cond) throw new Error(msg || 'ok'); }
function near(a, b, tol, msg) {
  if (Math.abs(a - b) > (tol == null ? 0.01 : tol))
    throw new Error((msg || 'near') + ': ' + a + ' !~ ' + b);
}
const ALL = ['stats', 'filters', 'stack', 'config', 'composer', 'people', 'log']
  .slice().sort(); // sorted — compared against sorted leaf lists
const sorted = (tree) => S.leafIds(tree).slice().sort();
const valid = (tree, ids) => ok(S.validate(tree, ids) === null,
  'validate: ' + S.validate(tree, ids));
/** the split that directly contains leaf `id` (or null) */
const parentOf = (tree, id) => S.findNode(tree, id).parent;
/** the split containing the split that contains leaf `id` (grandparent) */
const grandParentOf = (tree, id) =>
  S.nodeAtPath(tree, S.leafPaths(tree)[id].slice(0, -2));

// ── presets ──────────────────────────────────────────────────────

t('default tree validates & contains all 7 windows', () => {
  const d = S.defaultTree();
  valid(d);
  eq(sorted(d), ALL);
  // col [ top utility row | composer | people|log row ]
  ok(S.isSplit(d) && d.dir === 'col' && d.children.length === 3, 'root col, 3 children');
  eq(d.sizes, [46, 24, 30]);
  const top = d.children[0];
  ok(S.isSplit(top) && top.dir === 'row' && top.children.length === 2, 'top row, 2 groups');
  eq(top.sizes, [17, 83]);
  eq(S.leafIds(top.children[0]), ['stats', 'filters']);
  eq(S.leafIds(top.children[1]), ['stack', 'config']);
  ok(S.isLeaf(d.children[1]) && d.children[1].id === 'composer', 'composer own row');
  eq(S.leafIds(d.children[2]), ['people', 'log']);
  eq(d.children[2].sizes, [70, 30]);
});

t('layout A: 7 stacked rows in spec order', () => {
  const a = S.layoutA();
  valid(a);
  eq(sorted(a), ALL);
  ok(S.isSplit(a) && a.dir === 'col' && a.children.length === 7, '7 rows');
  eq(a.children.map((c) => c.id), ['stats', 'filters', 'stack', 'config',
                                    'composer', 'people', 'log']);
  eq(a.sizes, [8, 8, 20, 16, 18, 18, 12]);
});

t('layout B: [composer|people] row, full-width log, utilities row', () => {
  const b = S.layoutB();
  valid(b);
  eq(sorted(b), ALL);
  ok(S.isSplit(b) && b.dir === 'col' && b.children.length === 3, '3 rows');
  eq(b.sizes, [38, 26, 36]);
  const top = b.children[0];
  ok(S.isSplit(top) && top.dir === 'row' && top.children.length === 2, 'top row');
  eq(S.leafIds(top), ['composer', 'people']);
  eq(top.sizes, [50, 50]);
  ok(S.isLeaf(b.children[1]) && b.children[1].id === 'log', 'log full-width row');
  const util = b.children[2];
  ok(S.isSplit(util) && util.dir === 'row' && util.children.length === 2, 'util row');
  eq(util.sizes, [25, 75]);
  eq(S.leafIds(util.children[0]), ['stats', 'filters']);
  near(util.children[0].sizes[0], 45, 0.001);
  near(util.children[0].sizes[1], 55, 0.001);
  ok(S.isSplit(util.children[1]) && util.children[1].dir === 'col', 'stack/config col');
  eq(S.leafIds(util.children[1]), ['stack', 'config']);
  near(util.children[1].sizes[0], 72, 0.001);
  near(util.children[1].sizes[1], 28, 0.001);
});

t('layout C: log spans the full height of the hero row', () => {
  const c = S.layoutC();
  valid(c);
  eq(sorted(c), ALL);
  ok(S.isSplit(c) && c.dir === 'col' && c.children.length === 2, '2 rows');
  near(c.sizes[0], 58, 0.001); near(c.sizes[1], 42, 0.001);
  const hero = c.children[0];
  ok(S.isSplit(hero) && hero.dir === 'row' && hero.children.length === 2, 'hero row');
  eq(hero.sizes, [70, 30]);
  ok(S.isSplit(hero.children[0]) && hero.children[0].dir === 'col', 'left col');
  eq(S.leafIds(hero.children[0]), ['composer', 'people']);
  ok(S.isLeaf(hero.children[1]) && hero.children[1].id === 'log', 'log = side column');
  eq(S.leafIds(c.children[1]), ['stats', 'filters', 'stack', 'config']);
});

// ── splitLeaf (edge drop = "splits in half" semantics) ───────────

t('splitLeaf: left-edge drop → [new, target] row 50/50', () => {
  const d = S.defaultTree();
  S.splitLeaf(d, 'people', 'composer', 'row', true);
  const p = parentOf(d, 'people');
  ok(S.isSplit(p) && p.dir === 'row', 'row split');
  eq(p.children.map((c) => c.id), ['composer', 'people']);
  eq(p.sizes, [50, 50]);
});

t('splitLeaf: right-edge drop → [target, new]', () => {
  const d = S.defaultTree();
  S.splitLeaf(d, 'people', 'composer', 'row', false);
  const p = parentOf(d, 'people');
  eq(p.children.map((c) => c.id), ['people', 'composer']);
});

t('splitLeaf: col edge drop', () => {
  const d = S.defaultTree();
  S.splitLeaf(d, 'stats', 'log', 'col', false);
  const p = parentOf(d, 'stats');
  ok(p.dir === 'col', 'col split');
  eq(p.children.map((c) => c.id), ['stats', 'log']);
  eq(p.sizes, [50, 50]);
});

t('splitLeaf on a root-level leaf returns the NEW root', () => {
  const t0 = S.leaf('stats');
  const r = S.splitLeaf(t0, 'stats', 'log', 'row', true);
  ok(r !== t0, 'returns new root');
  ok(S.isSplit(r) && r.dir === 'row', 'root is now a split');
  eq(r.children.map((c) => c.id), ['log', 'stats']);
  eq(r.sizes, [50, 50]);
});

t('splitLeaf: unknown window throws', () => {
  const d = S.defaultTree();
  let threw = false;
  try { S.splitLeaf(d, 'bogus', 'log', 'row', true); }
  catch (e) { threw = true; }
  ok(threw, 'must throw');
});

// ── moveWindow (THE drop op: insert first, remove original by identity) ─

t('moveWindow: edge drop splits the target & removes the original row', () => {
  const d = S.defaultTree();
  S.moveWindow(d, 'composer',
    { kind: 'edge', target: 'people', dir: 'row', newFirst: true });
  valid(d);
  eq(sorted(d), ALL, 'still 7 windows (a move, not a copy)');
  const p = parentOf(d, 'people');
  eq(S.leafIds(p), ['composer', 'people'], 'composer landed in people\'s row');
  eq(p.sizes, [50, 50]);
  // composer\'s old full-width row is gone → root has 2 children, renormalised
  ok(d.children.length === 2, 'root now 2 children');
  near(d.sizes[0], 46 / 76 * 100, 0.1, 'top share renormalised');
  near(d.sizes[1], 30 / 76 * 100, 0.1, 'bottom share renormalised');
  // bottom row = [ row[composer,people] | log ] — log kept its slot
  ok(S.isLeaf(d.children[1].children[1]) &&
     d.children[1].children[1].id === 'log', 'log stayed in the bottom row');
});

t('moveWindow: center drop into a 2-child row → row survives', () => {
  const d = S.defaultTree();
  S.moveWindow(d, 'log', { kind: 'sibling', target: 'people', side: 'before' });
  valid(d);
  eq(sorted(d), ALL);
  const p = parentOf(d, 'people');
  eq(S.leafIds(p), ['log', 'people'], 'log joined the row before people');
  eq(p.sizes, [50, 50], 'shared the space');
});

t('moveWindow: center drop into a 2-child sub-split → 3 children, sizes stay sane', () => {
  const b = S.layoutB();
  S.moveWindow(b, 'log', { kind: 'sibling', target: 'stats', side: 'before' });
  valid(b);
  eq(sorted(b), ALL);
  const inner = parentOf(b, 'stats');          // [stats|filters] row
  eq(S.leafIds(inner), ['log', 'stats', 'filters']);
  near(inner.sizes[0], 22.5); near(inner.sizes[1], 22.5); near(inner.sizes[2], 55);
  // log left its full-width row → root now has 2 children
  ok(b.children.length === 2, 'root now 2 children');
  near(b.sizes[0], 38 / 74 * 100, 0.1);
});

t('moveWindow: sash drop lands between two sub-split groups', () => {
  const b = S.layoutB();
  S.moveWindow(b, 'log', { kind: 'sash', left: 'stats', right: 'stack' });
  valid(b);
  eq(sorted(b), ALL);
  const util = grandParentOf(b, 'stats');      // the utilities row
  eq(util.children.map((c) => (c.t === 'leaf' ? c.id : 'split')),
     ['split', 'log', 'split'], 'groups kept intact, log between them');
  eq(S.leafIds(util.children[0]), ['stats', 'filters']);
  eq(S.leafIds(util.children[2]), ['stack', 'config']);
  near(util.sizes[0], 25); near(util.sizes[1], 37.5); near(util.sizes[2], 37.5);
  ok(b.children.length === 2, 'log\'s old row collapsed away');
});

t('moveWindow: sash drop between non-adjacent anchors throws', () => {
  const d = S.defaultTree();
  // make the stats/filters col a 3-child split: [stats, composer, filters]
  S.moveWindow(d, 'composer', { kind: 'sibling', target: 'stats', side: 'after' });
  let threw = false;
  try {
    S.moveWindow(d, 'people', { kind: 'sash', left: 'stats', right: 'filters' });
  } catch (e) { threw = /not adjacent/.test(String(e.message)); }
  ok(threw, 'must throw "not adjacent"');
});

t('moveWindow: dropping a window on itself throws', () => {
  const d = S.defaultTree();
  let threw = false;
  try {
    S.moveWindow(d, 'people',
      { kind: 'edge', target: 'people', dir: 'row', newFirst: true });
  } catch (e) { threw = true; }
  ok(threw, 'must throw');
});

t('moveWindow: unknown window / target throws', () => {
  const d = S.defaultTree();
  let threw = 0;
  try { S.moveWindow(d, 'ghost', { kind: 'sibling', target: 'people', side: 'before' }); }
  catch (e) { threw++; }
  try { S.moveWindow(d, 'people', { kind: 'sibling', target: 'ghost', side: 'before' }); }
  catch (e) { threw++; }
  eq(threw, 2, 'both must throw');
});

// ── removal (collapsing & renormalising) ─────────────────────────

t('removeLeaf: 2-child split collapses to the remaining child', () => {
  const d = S.defaultTree();
  S.removeLeaf(d, 'config');
  valid(d, ['stats', 'filters', 'stack', 'composer', 'people', 'log']);
  const p = parentOf(d, 'stack');
  ok(p.dir === 'row', 'stack\'s parent is now the top row (col collapsed)');
  eq(p.sizes, [17, 83]);
});

t('removeLeaf: 3+-child split renormalises instead of collapsing', () => {
  const b = S.layoutB();
  S.moveWindow(b, 'log', { kind: 'sibling', target: 'stats', side: 'before' });
  // utilities row now: [log, stats, filters] | [stack/config]
  S.removeLeaf(b, 'log');
  valid(b, ['stats', 'filters', 'stack', 'config', 'composer', 'people']);
  const util = grandParentOf(b, 'stats');
  eq(S.leafIds(util.children[0]).slice().sort(), ['filters', 'stats']);
  const sum = util.sizes.reduce((a, x) => a + x, 0);
  near(sum, 100, 0.01, 'row sizes renormalise to 100');
});

// ── resize commits & paths ───────────────────────────────────────

t('setSplitSizes: resize commit on a leaf\'s parent split', () => {
  const d = S.defaultTree();
  S.setSplitSizes(d, 'stats', [50, 50]);
  eq(parentOf(d, 'stats').sizes, [50, 50]);
  valid(d);
});

t('setSplitSizes: count mismatch throws', () => {
  const d = S.defaultTree();
  let threw = false;
  try { S.setSplitSizes(d, 'stats', [50]); } catch (e) { threw = true; }
  ok(threw, 'must throw');
});

t('parentPath / nodeAtPath / setSplitSizesByPath round trip', () => {
  const d = S.defaultTree();
  const p = S.parentPath(d, 'log');
  eq(p, [2], 'log lives in the 3rd root child');
  const at = S.nodeAtPath(d, p);
  ok(S.isSplit(at) && S.leafIds(at).sort().join() === ['log', 'people'].sort().join());
  S.setSplitSizesByPath(d, p, [60, 40]);
  eq(S.nodeAtPath(d, p).sizes, [60, 40]);
  eq(S.nodeAtPath(d, ''), d, 'empty path = root');
});

t('leafPaths maps every window to its index path', () => {
  const d = S.defaultTree();
  const m = S.leafPaths(d);
  eq(Object.keys(m).sort(), ALL);
  eq(m.composer, [1]);
  eq(m.people, [2, 0]);
  eq(m.stats, [0, 0, 0]);
  eq(m.config, [0, 1, 1]);
});

t('insertAtSplitPath: inserts with a donor half', () => {
  const d = S.defaultTree();
  // into the top row (path [0]) at index 1, donor = index 1 (the stack/config group)
  S.insertAtSplitPath(d, [0], 1, 'composer', 1);
  const top = S.nodeAtPath(d, [0]);
  eq(top.children.length, 3);
  ok(S.isLeaf(top.children[1]) && top.children[1].id === 'composer');
  near(top.sizes[1], 41.5); near(top.sizes[2], 41.5); // 83/2 each
  near(top.sizes[0], 17);
});

// ── sizes ────────────────────────────────────────────────────────

t('normalizeSizes: clamps tiny values, scales to 100, keeps exact halves', () => {
  const s = S.normalizeSizes([1, 2, 0, 90]);
  near(s.reduce((a, b) => a + b, 0), 100, 0.001, 'sum 100');
  ok(s.every((x) => x >= S.MIN_SIZE), 'min 0.5: ' + s);
  eq(S.normalizeSizes([50, 50]), [50, 50]);
  const t3 = S.normalizeSizes([33, 33, 33]);
  near(t3[0], 100 / 3); near(t3[1], 100 / 3); near(t3[2], 100 / 3);
});

// ── (de)serialisation safety ─────────────────────────────────────

t('serialize → deserialize round trip is stable for all presets', () => {
  for (const name of ['default', 'a', 'b', 'c']) {
    const tree = S.PRESETS[name]();
    const s1 = S.serialize(tree);
    const r = S.deserialize(s1);
    ok(r.ok, name + ' round trip: ' + r.error);
    eq(S.serialize(r.tree), s1, name + ' stable');
    eq(sorted(r.tree), ALL);
  }
});

t('deserialize rejects: not JSON / bad version / bad trees', () => {
  ok(!S.deserialize('nonsense').ok, 'not json');
  ok(!S.deserialize(JSON.stringify({ v: 9, tree: S.defaultTree() })).ok, 'bad version');

  const bad = S.clone(S.defaultTree());
  bad.children[2].children[0].id = 'bogus';
  ok(!S.deserialize(S.serialize(bad)).ok, 'unknown window id');

  const dup = S.clone(S.defaultTree());
  dup.children[1].id = 'stats'; // duplicate id, composer missing
  ok(!S.deserialize(S.serialize(dup)).ok, 'duplicate id');

  const zero = S.layoutA();
  zero.sizes = [0, 0, 0, 0, 0, 0, 0];
  ok(!S.deserialize(S.serialize(zero)).ok, 'sizes do not sum to 100');
});

t('validate: rejects missing windows, depth, bad dirs', () => {
  ok(S.validate(S.leaf('stats')) !== null, 'single leaf misses windows');
  let deep = S.leaf('stats');
  for (let i = 0; i < 40; i++)
    deep = S.split('row', [deep, S.leaf('x')], [50, 50]);
  ok(/too deep/.test(S.validate(deep)), 'depth limit');
  ok(S.validate({ t: 'split', dir: 'diagonal', children: [S.leaf('a'), S.leaf('b')],
                  sizes: [50, 50] }) !== null, 'bad dir');
});

t('PRESETS is a list of the four layout builders', () => {
  ok(Array.isArray(S.PRESETS) || Object.keys(S.PRESETS).sort().join() ===
     ['a', 'b', 'c', 'default'].join(), 'preset keys');
});

// ── default layout must show EVERY window (grid reset requirement) ──

t('defaultTree contains every window exactly once', () => {
  const ids = S.leafIds(S.defaultTree()).slice().sort();
  const want = S.WINDOWS.map((w) => w.id).slice().sort();
  ok(ids.join() === want.join(),
     'default is missing windows: got [' + ids + '] want [' + want + ']');
});

t('defaultTree validates and survives a serialize round-trip', () => {
  ok(S.validate(S.defaultTree()) === null, 'default must validate');
  const res = S.deserialize(S.serialize(S.defaultTree()));
  ok(res.ok, 'default must round-trip');
  ok(S.leafIds(res.tree).slice().sort().join() ===
     S.leafIds(S.defaultTree()).slice().sort().join(), 'same windows back');
});

t('every preset shows every window', () => {
  const want = S.WINDOWS.map((w) => w.id).slice().sort().join();
  for (const key of Object.keys(S.PRESETS)) {
    const ids = S.leafIds(S.PRESETS[key]()).slice().sort().join();
    ok(ids === want, 'preset "' + key + '" is missing windows');
  }
});

// ── reporting ────────────────────────────────────────────────────

console.log('sash_core: ' + passed + ' passed, ' + failed + ' failed');
if (failed) process.exit(1);
console.log('OK');
