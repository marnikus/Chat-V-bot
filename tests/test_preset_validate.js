/* Tests for structural vs environmental preset validation (K3, issue 2).

   The bug: one validator answered two different questions, so a file
   imported from another build passed the preview and was then rejected by
   the SAME check on the way to disk -- the user accepted an import and got a
   late failure instead of a saved preset.

   Structural validity is a property of the FILE. Whether this build can show
   the windows it names is environmental, and belongs to reconcile().

   Executes the REAL shipped module (ui/js/core/preset-validate.js) in node,
   per AGENT_RULES RULE 6.

   Run:  node tests/test_preset_validate.js
*/
'use strict';
const path = require('path');
const V = require(path.join(__dirname, '..', 'ui', 'js', 'core',
                            'preset-validate.js'));

let passed = 0, failed = 0;
function t(name, fn) {
  try { fn(); passed++; }
  catch (e) { failed++; console.error('FAIL ' + name + '\n   ' + (e && e.stack || e)); }
}
function eq(a, b, msg) {
  if (a !== b) throw new Error((msg || 'not equal') + ': ' + JSON.stringify(a) +
                               ' !== ' + JSON.stringify(b));
}
function ok(v, msg) { if (!v) throw new Error(msg || 'expected truthy'); }

// a tree checker that accepts any well-shaped tree, as the grid model does
const SPEC = {
  format: 'chat-v-bot.window-preset',
  schemaVersion: 1,
  checkTree(tree) {
    if (!tree || typeof tree !== 'object') {
      return { ok: false, error: 'unknown node type' };
    }
    return { ok: true, tree };
  },
};

function bounds(x, y, w, h) { return { x, y, width: w, height: h }; }

function doc(over) {
  const base = {
    format: 'chat-v-bot.window-preset',
    schema_version: 1,
    app_version: '0.1.0',
    name: 'Desk',
    created_at: '2026-09-14T00:00:00.000Z',
    updated_at: '2026-09-14T00:00:00.000Z',
    grid: {
      type: 'sash-tree', version: 4, window_count: 2, sizes_unit: 'percent',
      tree: { t: 'split', dir: 'col',
              children: [{ t: 'leaf', id: 'chat' }, { t: 'leaf', id: 'log' }],
              sizes: [60, 40] },
    },
    windows: [
      { id: 'chat', title: 'Chat', state: 'open', bounds: bounds(0, 0, 1, 0.6) },
      { id: 'log', title: 'Log', state: 'open', bounds: bounds(0, 0.6, 1, 0.4) },
    ],
    window_states: { closed: [], minimized: [] },
    screen: { width: 1920, height: 1080, device_pixel_ratio: 1 },
  };
  return Object.assign(base, over || {});
}
const check = (d) => V.structural(d, SPEC);

// ── THE BUG: a foreign window set is structurally fine ─────────────
t('a document naming windows this build lacks is STRUCTURALLY valid', () => {
  const d = doc();
  d.grid.tree.children[0].id = 'retired-window';
  d.windows[0].id = 'retired-window';
  const r = check(d);
  ok(r.ok, 'must be storable, got: ' + r.error);
});

t('a document with a different window COUNT is structurally valid', () => {
  const d = doc();
  d.grid.window_count = 99;
  ok(check(d).ok, 'window_count must not be compared to this build');
});

t('the same document survives a save-shaped round trip', () => {
  const d = doc();
  d.windows[0].id = 'retired-window';
  d.grid.tree.children[0].id = 'retired-window';
  const first = check(d);
  ok(first.ok, first.error);
  // what _persistDocument writes, re-read as an import would
  const second = check(JSON.stringify(first.document));
  ok(second.ok, 'a document it just accepted must not be rejected on reload: ' +
     second.error);
  eq(JSON.stringify(second.document), JSON.stringify(first.document),
     'structural validation must be idempotent');
});

// ── still strict about the things that make it a preset ────────────
t('a wrong format or schema is rejected', () => {
  ok(!check(doc({ format: 'something-else' })).ok);
  ok(!check(doc({ schema_version: 2 })).ok);
});

t('unparseable JSON is rejected with a readable reason', () => {
  const r = check('{not json');
  ok(!r.ok);
  ok(/bad JSON/.test(r.error), r.error);
});

t('a non-object document is rejected', () => {
  ['[]', '3', '"x"', 'null'].forEach((raw) => {
    ok(!check(raw).ok, 'accepted ' + raw);
  });
});

t('a missing or oversized name is rejected', () => {
  ok(!check(doc({ name: '' })).ok);
  ok(!check(doc({ name: '   ' })).ok);
  ok(!check(doc({ name: 'x'.repeat(V.MAX_NAME + 1) })).ok);
  ok(check(doc({ name: 'x'.repeat(V.MAX_NAME) })).ok, 'the limit itself is fine');
});

t('a name is trimmed on the way through', () => {
  const r = check(doc({ name: '  Desk  ' }));
  ok(r.ok);
  eq(r.document.name, 'Desk');
});

t('a missing app_version is rejected', () => {
  ok(!check(doc({ app_version: '' })).ok);
  ok(!check(doc({ app_version: 7 })).ok);
});

t('broken grid metadata is rejected', () => {
  ok(!check(doc({ grid: null })).ok);
  const d = doc(); d.grid.type = 'other';
  ok(!check(d).ok);
  const e = doc(); e.grid.sizes_unit = 'px';
  ok(!check(e).ok);
  const f = doc(); f.grid.window_count = 0;
  ok(!check(f).ok, 'a zero-window preset shows nothing');
});

t('a malformed tree is rejected via the injected checker', () => {
  const d = doc(); d.grid.tree = 'nope';
  const r = check(d);
  ok(!r.ok);
  ok(/grid tree/.test(r.error), r.error);
});

// ── bounds arithmetic ──────────────────────────────────────────────
t('bounds must be normalised 0-1 and stay inside the grid', () => {
  ok(V.validBounds(bounds(0, 0, 1, 1)));
  ok(V.validBounds(bounds(0.5, 0.5, 0.5, 0.5)));
  ok(!V.validBounds(bounds(-0.1, 0, 1, 1)), 'negative origin');
  ok(!V.validBounds(bounds(0, 0, 1.5, 1)), 'width over 1');
  ok(!V.validBounds(bounds(0.6, 0, 0.6, 1)), 'overflows the right edge');
  ok(!V.validBounds(bounds(0, 0.6, 1, 0.6)), 'overflows the bottom edge');
  ok(!V.validBounds(null));
  ok(!V.validBounds({ x: '0', y: 0, width: 1, height: 1 }), 'strings');
  ok(!V.validBounds(bounds(NaN, 0, 1, 1)));
});

t('a window with bad bounds is rejected', () => {
  const d = doc(); d.windows[0].bounds = bounds(0, 0, 2, 1);
  ok(!check(d).ok);
});

// ── the window list must agree with itself ─────────────────────────
t('a window state contradicting window_states is rejected', () => {
  const d = doc(); d.windows[0].state = 'closed';   // not in the closed list
  ok(!check(d).ok);
});

t('a state list agreeing with the windows is accepted', () => {
  const d = doc();
  d.window_states.closed = ['log'];
  d.windows[1].state = 'closed';
  ok(check(d).ok, 'consistent states must pass');
});

t('duplicate ids are rejected', () => {
  const d = doc(); d.windows[1].id = 'chat';
  ok(!check(d).ok);
});

t('a nameless id is rejected', () => {
  const d = doc(); d.windows[1].id = '';
  ok(!check(d).ok);
});

t('an empty window list is rejected', () => {
  ok(!check(doc({ windows: [] })).ok);
  ok(!check(doc({ windows: 'nope' })).ok);
});

t('overlapping closed and minimized states are rejected', () => {
  const d = doc();
  d.window_states = { closed: ['chat'], minimized: ['chat'] };
  ok(!check(d).ok);
});

t('a duplicate inside a state list is rejected', () => {
  const d = doc();
  d.window_states = { closed: ['chat', 'chat'], minimized: [] };
  ok(!check(d).ok);
});

t('missing state lists are rejected', () => {
  ok(!check(doc({ window_states: null })).ok);
  ok(!check(doc({ window_states: { closed: [] } })).ok);
});

// ── screen metadata ────────────────────────────────────────────────
t('screen metadata must be positive numbers', () => {
  ok(!check(doc({ screen: { width: '1920', height: 1080 } })).ok);
  ok(!check(doc({ screen: { width: 0, height: 1080 } })).ok);
  ok(!check(doc({ screen: { width: 1920, height: -5 } })).ok);
  ok(!check(doc({ screen: null })).ok);
});

t('a missing device_pixel_ratio defaults to 1', () => {
  const r = check(doc({ screen: { width: 1920, height: 1080 } }));
  ok(r.ok, r.error);
  eq(r.document.screen.device_pixel_ratio, 1);
});

t('a zero device_pixel_ratio is rejected', () => {
  ok(!check(doc({ screen: { width: 1, height: 1, device_pixel_ratio: 0 } })).ok);
});

// ── no mutation of the caller's object ─────────────────────────────
t('validation does not mutate the document it was given', () => {
  const d = doc({ name: '  Desk  ' });
  const before = JSON.stringify(d);
  check(d);
  eq(JSON.stringify(d), before, 'input must be left alone');
});

console.log('preset validate: ' + passed + ' passed, ' + failed + ' failed');
if (failed) process.exit(1);
console.log('OK');
