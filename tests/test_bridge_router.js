/* Contract: every App.bridge.<slot>( used by the UI must exist on the
   Python Router (bridge/router.py domain bridges). Catches dropped slots.

   Run: node tests/test_bridge_router.js
*/
'use strict';
const fs = require('fs');
const path = require('path');

const root = path.join(__dirname, '..');
let passed = 0, failed = 0;
function test(name, fn) {
  try { fn(); passed++; }
  catch (e) { failed++; console.error('FAIL', name, '\n ', e.message); }
}
function assert(c, m) { if (!c) throw new Error(m || 'assert'); }

function walk(dir, acc) {
  for (const ent of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, ent.name);
    if (ent.isDirectory()) walk(p, acc);
    else if (ent.name.endsWith('.js')) acc.push(p);
  }
  return acc;
}

const jsFiles = walk(path.join(root, 'ui/js'), []);
const callRe = /\b(?:App\.bridge|bridge)\.([A-Za-z_][A-Za-z0-9_]*)\s*\(/g;
const used = new Set();
for (const f of jsFiles) {
  const src = fs.readFileSync(f, 'utf8');
  let m;
  while ((m = callRe.exec(src))) used.add(m[1]);
}

const pyDir = path.join(root, 'bridge');
const pyFiles = fs.readdirSync(pyDir).filter((n) => n.endsWith('.py'))
  .map((n) => path.join(pyDir, n));
const py = pyFiles.map((f) => fs.readFileSync(f, 'utf8')).join('\n');

const defined = new Set();
const defRe = /(?:^|\n)\s*(?:async\s+)?def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(/g;
let m;
while ((m = defRe.exec(py))) defined.add(m[1]);
const slotRe = /@Slot[^\n]*\n\s*(?:async\s+)?def\s+([A-Za-z_][A-Za-z0-9_]*)/g;
while ((m = slotRe.exec(py))) defined.add(m[1]);

// Router also forwards attach_history / sync_world_state from main.py
defined.add('attach_history');
defined.add('sync_world_state');
defined.add('get_tabs'); // CdpBridge

test('UI calls at least one bridge slot', () => {
  assert(used.size >= 8, 'expected many App.bridge calls, got ' + used.size);
});

test('every UI bridge call has a Python def on a domain bridge', () => {
  const missing = [...used].filter((n) => !defined.has(n)).sort();
  assert(missing.length === 0, 'UI calls missing on Python: ' + missing.join(', '));
});

test('WebChannel object name is still "bridge"', () => {
  const main = fs.readFileSync(path.join(root, 'main.py'), 'utf8');
  assert(/registerObject\(\s*"bridge"/.test(main), 'main.py must registerObject("bridge")');
});

if (failed) {
  console.error(`bridge_router: ${passed} passed, ${failed} failed`);
  process.exit(1);
}
console.log(`bridge_router: ${passed} passed, 0 failed`);
console.log('OK');
