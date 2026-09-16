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
const vm = require('vm');

const UI_DIR = path.join(__dirname, '..', 'ui');

function readUi(rel) {
  return fs.readFileSync(path.join(UI_DIR, rel), 'utf8');
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

/** Top-level `const NAME =` declarations of a file — the names later files
    resolve by bare name (the browser's global lexical scope across
    <script> tags). */
function exportNames(src) {
  const out = [];
  for (const m of src.matchAll(/^const ([A-Za-z_$][\w$]*) =/gm)) out.push(m[1]);
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
    Every file evaluates as its OWN top-level script, exactly like the
    browser's <script> tags: js/core/ui-helpers.js first (it attaches
    window.UIHelpers, which index.html makes a global), then each part
    (its top-level consts are exported to globalThis so the next file
    resolves them by bare name), finally the facade. Per-file evaluation
    keeps each part's coverage attribution intact (a concatenated eval
    attributes every line to the last pragma — the facade).
    Returns the facade: window[name], else the CamelCase-of-filename
    binding, else globalThis's. */
function loadModule(rel, window, document, name) {
  const files = ['js/core/ui-helpers.js'].concat(partsOf(rel)).concat([rel]);
  for (const f of files) {
    let src = readUi(f);
    const base = path.basename(f);
    const exp = exportNames(src).map((n) => `;globalThis.${n} = ${n};`);
    // ui-helpers.js attaches window.UIHelpers instead of declaring a const;
    // index.html promotes window members to globals — mirror it here so the
    // facade's bare UIHelpers resolves before its own script runs.
    if (base === 'ui-helpers.js') exp.push(';globalThis.UIHelpers = window.UIHelpers;');
    if (exp.length) src = insertBeforePragma(src, exp.join('') + '\n');
    try {
      vm.runInThisContext(src);
    } catch (e) {
      // A suite may reload the same module inside one test (a
      // per-session-state contract): Node's shared context forbids a
      // second `const`. Rewriting top-level declarations to globalThis
      // assignments builds a fresh facade object, as the test intends.
      if (!/already been declared/.test(String(e))) throw e;
      const reassigned = src.replace(/^(?:const|let) ([A-Za-z_$][\w$]*) =/gm,
                                     'globalThis.$1 =');
      vm.runInThisContext(reassigned);
    }
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
