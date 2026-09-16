'use strict';
/* Shared loader for the standalone Node suites (RULE 8: the suites execute
   the REAL shipped sources; this helper holds zero behavior of its own).

   Round H (2026-09) split the big ui/js panels into a facade file plus
   "<name>-<part>.js" parts that the facade merges via UIHelpers.mergeParts.
   index.html guarantees script order; a suite that evals one file at a time
   must load the parts first and let them share one scope, exactly like the
   browser does. The facade header documents its parts ("Parts loaded before
   this one"), and loadModule follows that list. */
const fs = require('fs');
const path = require('path');

const UI_DIR = path.join(__dirname, '..', 'ui');
const ROOT_DIR = path.join(__dirname, '..');

function readUi(rel) {
  // 'backend/…' modules (Round II Area A: chat_agent) live at repo root,
  // not under ui/ — same parts convention, different directory.
  const base = rel.startsWith('backend/') ? ROOT_DIR : UI_DIR;
  return fs.readFileSync(path.join(base, rel), 'utf8');
}

/** Part files named by the facade header, in index.html order. */
function partsOf(rel) {
  const head = readUi(rel).slice(0, 1200);
  const block = head.match(/Parts loaded before this one[^:]*:([\s\S]*?)\*\//);
  if (!block) return [];
  return [...block[1].matchAll(/[\w.-]+\.js/g)].map(
      (m) => path.posix.join(path.posix.dirname(rel), m[0])
          .replace(/^\.\//, ''));
}

/** Top-level `const NAME =` / `var NAME =` declarations and
    `function NAME(` declarations of a file — the names later files would
    resolve by bare name in the browser (global lexical scope + global
    object across <script> tags). */
function exportNames(src) {
  const out = [];
  for (const m of src.matchAll(/^(?:const|var) ([A-Za-z_$][\w$]*) =/gm))
    out.push(m[1]);
  for (const m of src.matchAll(/^function ([A-Za-z_$][\w$]*)\s*\(/gm))
    out.push(m[1]);
  return out;
}

/** Insert export code before the coverage mirror's trailing sourceURL
    pragma, which V8 honours only in tail position — so every file keeps
    its own coverage attribution (see tests/js_family.js for the same
    mechanism, hand-stamped; here the export set is derived, not stamped). */
function insertBeforePragma(src, extra) {
  const pragma = src.match(/\/\/\# sourceURL=cvb:\/\/[^\n]*\n?$/);
  return pragma
    ? src.slice(0, -pragma[0].length) + extra + '\n' + pragma[0]
    : src + extra;
}

/** Load rel (e.g. 'js/db-panel.js') after UIHelpers and its own parts.
    Every file evaluates as its OWN script in a fresh function scope bound
    to globalThis (`new Function(src).call(globalThis)`): the top-level
    `this` stays the global like a classic <script> tag, but nothing is
    left in Node's persistent script-lexical scope — so a suite can reload
    a module for a fresh page env and get FRESH objects, while earlier
    loads can never be resolved by stale name bindings (vm.runInThisContext
    left `const`s pinned in script scope: reloads collided, and the
    rewritten fallback still resolved to the FIRST load's bindings).
    Names cross files exactly once, through globalThis — the same surface
    the browser exposes across <script> tags. Per-file evaluation keeps
    each part's coverage attribution intact (a concatenated eval
    attributes every line to the last pragma — the facade).
    ui/js modules load js/core/ui-helpers.js first (index.html order);
    backend modules have no prelude.
    Returns the facade: window[name], else the CamelCase-of-filename
    binding, else globalThis's. */
function loadModule(rel, window, document, name) {
  // The files reference bare `window` like the page does; guarantee one
  // exists (suites with a stub env assign their own first).
  if (!globalThis.window) globalThis.window = {};
  const prelude = rel.startsWith('backend/') ? [] : ['js/core/ui-helpers.js'];
  const files = prelude.concat(partsOf(rel)).concat([rel]);
  for (const f of files) {
    let src = readUi(f);
    const exp = exportNames(src).map((n) => `;globalThis.${n} = ${n};`);
    // ui-helpers.js attaches window.UIHelpers instead of declaring a const;
    // index.html promotes window members to globals — mirror it here so the
    // facade's bare UIHelpers resolves before its own script runs.
    if (path.basename(f) === 'ui-helpers.js')
      exp.push(';globalThis.UIHelpers = window.UIHelpers;');
    if (exp.length) src = insertBeforePragma(src, exp.join('') + '\n');
    // eslint-disable-next-line no-new-func -- the point: per-file script
    new Function(src).call(globalThis);
  }
  window = window || {};
  if (window.UIHelpers && !globalThis.UIHelpers)
    globalThis.UIHelpers = window.UIHelpers;
  const camel = path.basename(rel, '.js').replace(/(^|-)(\w)/g,
                                                  (m, d, c) => c.toUpperCase());
  return (name && (window[name] || globalThis[name])) || window[camel] ||
         globalThis[camel] || {};
}

/** Facade + its parts as one source string — for suites asserting on which
    file-family carries some markup/wiring (the H-B2b split moved the code
    out of the facade files these asserts historically read). */
function sourceBundle(rel) {
  return partsOf(rel).map(readUi).concat([readUi(rel)]).join('\n');
}

module.exports = {readUi, partsOf, loadModule, sourceBundle};
