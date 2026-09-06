/* Tests for the grid's v2 window set and the v1 → v2 layout migration.

   The archive adds three windows (Person History, User Database, Chat
   Message Collector). The saved layout is validated against the window
   set and REJECTED on mismatch, so every user upgrading the app would
   lose their arrangement unless the stored v1 tree is migrated.

   Run:  node tests/test_sash_core_v2.js
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

const LEGACY = ['stats', 'filters', 'stack', 'config', 'composer', 'people', 'log'];
const NEW = ['history', 'userdb', 'collector'];
const ALL = LEGACY.concat(NEW).slice().sort();
const sorted = (tree) => S.leafIds(tree).slice().sort();

const v1Tree = () => S.split('col', LEGACY.map(S.leaf),
                             [16, 14, 14, 14, 14, 14, 14]);
const v1Nested = () => S.split('row', [
  S.leaf('stats'),
  S.split('col', [S.leaf('filters'), S.leaf('stack'), S.leaf('config')],
          [34, 33, 33]),
  S.split('col', [S.leaf('composer'), S.leaf('people'), S.leaf('log')],
          [34, 33, 33]),
], [20, 40, 40]);

// ── the window set ───────────────────────────────────────────────

t('the window set has the three archive windows', () => {
  eq(S.WINDOW_IDS.slice().sort(), ALL);
  for (const id of NEW) ok(S.WINDOW_TITLES[id], 'a title for ' + id);
});

t('window titles say what the windows are', () => {
  ok(/history/i.test(S.WINDOW_TITLES.history), 'history title');
  ok(/(database|users?)/i.test(S.WINDOW_TITLES.userdb), 'userdb title');
  ok(/collector/i.test(S.WINDOW_TITLES.collector), 'collector title');
});

t('the default tree and every preset show all ten windows', () => {
  eq(sorted(S.defaultTree()), ALL);
  ok(S.validate(S.defaultTree()) === null, S.validate(S.defaultTree()));
  for (const key of Object.keys(S.PRESETS)) {
    eq(sorted(S.PRESETS[key]()), ALL, 'preset ' + key);
    ok(S.validate(S.PRESETS[key]()) === null, 'preset ' + key + ' invalid');
  }
});

t('the serialised version is 2', () => {
  eq(S.VERSION, 2);
  eq(JSON.parse(S.serialize(S.defaultTree())).v, 2);
});

// ── migration ────────────────────────────────────────────────────

t('migrate appends the missing windows', () => {
  const out = S.migrate(v1Tree());
  eq(sorted(out), ALL);
  ok(S.validate(out) === null, S.validate(out));
});

t('migrate keeps the existing arrangement', () => {
  const before = S.leafIds(v1Nested());
  const after = S.leafIds(S.migrate(v1Nested())).filter((i) => LEGACY.includes(i));
  eq(after, before, 'the old windows keep their order');
});

t('migrate keeps relative sizes of the old windows', () => {
  const out = S.migrate(v1Nested());
  const node = S.findNode(out, 'filters');
  ok(node.parent.sizes.every((s) => s > 0), 'no zero-sized pane');
  const sum = node.parent.sizes.reduce((a, b) => a + b, 0);
  ok(Math.abs(sum - 100) < 0.5, 'sizes still sum to 100');
});

t('migrate is idempotent', () => {
  const once = S.migrate(v1Tree());
  eq(S.migrate(once), once, 'migrating twice must change nothing');
});

t('migrate drops windows that no longer exist', () => {
  const stale = S.split('row', [S.leaf('stats'), S.leaf('ghost')], [50, 50]);
  const out = S.migrate(stale);
  eq(sorted(out), ALL);
  ok(!JSON.stringify(out).includes('ghost'), 'the stale window is gone');
});

t('migrate repairs a duplicated window', () => {
  const dup = S.split('row', LEGACY.concat(['stats']).map(S.leaf),
                      [13, 13, 12, 12, 12, 12, 13, 13]);
  eq(sorted(S.migrate(dup)), ALL, 'duplicates collapse to one');
});

t('migrating rubbish falls back to the default tree', () => {
  eq(sorted(S.migrate(null)), ALL);
  eq(sorted(S.migrate({ t: 'leaf' })), ALL);
  eq(sorted(S.migrate(S.leaf('stats'))), ALL);
});

// ── deserialize ──────────────────────────────────────────────────

t('a stored v1 layout deserialises into a valid v2 tree', () => {
  const res = S.deserialize(JSON.stringify({ v: 1, tree: v1Nested() }));
  ok(res.ok, 'v1 must be accepted: ' + res.error);
  eq(sorted(res.tree), ALL);
  ok(res.migrated === true, 'the caller must be told it was migrated');
});

t('a v2 layout round-trips untouched', () => {
  const res = S.deserialize(S.serialize(S.defaultTree()));
  ok(res.ok, res.error);
  eq(res.tree, S.defaultTree());
  ok(!res.migrated, 'nothing to migrate');
});

t('a future version is refused', () => {
  const res = S.deserialize(JSON.stringify({ v: 3, tree: S.defaultTree() }));
  ok(!res.ok, 'v3 must not be accepted');
  ok(/version/i.test(res.error), 'the error must mention the version');
});

t('an unparseable layout is refused, not thrown', () => {
  const res = S.deserialize('{not json');
  ok(!res.ok && /unparseable/i.test(res.error), res.error);
});

t('a structurally broken v1 tree is refused rather than half-migrated', () => {
  const res = S.deserialize(JSON.stringify(
    { v: 1, tree: { t: 'split', dir: 'row', children: [S.leaf('stats')],
                    sizes: [100] } }));
  ok(!res.ok, 'a one-child split is not a layout');
});

// ── reporting ────────────────────────────────────────────────────

console.log('sash_core_v2: ' + passed + ' passed, ' + failed + ' failed');
if (failed) process.exit(1);
console.log('OK');
