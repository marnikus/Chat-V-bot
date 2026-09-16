/* Shared loader for the shipped UI JS "families".
 *
 * Round H split the two god objects (SashGrid, StackDnD) into a facade plus
 * named part files, and app.js into a facade + part files. The load order is
 * a real dependency (each part expects the previous file's globals), so the
 * ONE place that names it is here, mirroring the <script> order in
 * ui/index.html.
 *
 * loadFamily(family) evaluates each file as its OWN top-level script (like a
 * <script> tag), then publishes that file's top-level consts to globalThis —
 * mirroring the browser's global lexical scope across scripts. Two reasons
 * the per-script + export form (not one concatenated eval):
 *   1. V8 coverage (tools/metrics/js_coverage.py) mirrors the repo with a
 *      trailing `//# sourceURL=cvb://<rel>` pragma per file and attributes
 *      each eval'd script to the LAST pragma in it. One concatenated family
 *      would attribute every part's lines to the facade. The export is
 *      inserted BEFORE the pragma so each file keeps its own attribution.
 *   2. It is the shape the browser actually runs (separate script tags).
 *
 * Usage:
 *   const { loadFamily, FAMILIES } = require('./js_family');
 *   loadFamily(FAMILIES.sashGrid);
 *   const SashGrid = global.SashGrid;
 */
'use strict';
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const UI = path.join(__dirname, '..', 'ui', 'js');

// Load order mirrors ui/index.html. Facade is always last.
// core/ui-helpers.js first: every facade binds its parts via
// UIHelpers.mergeParts at load time.
const FAMILIES = {
  // sash-grid facade + its four parts (+ the DOM-free model they all need).
  sashGrid: [
    'core/ui-helpers.js',
    'sash-core.js',
    'sash-grid-tree.js',
    'sash-grid-windows.js',
    'sash-grid-presets.js',
    // Issue 4 split (2026-09): the drag part became three real parts plus
    // an empty compat file; the order mirrors the index.html script tags.
    'sash-grid-drag-core.js',
    'sash-grid-drag-spec.js',
    'sash-grid-drag-resize.js',
    'sash-grid-drag.js',
    'sash-grid.js',
  ],
  // stack-dnd facade + its parts (+ the StackDrag engine it drives).
  stackDnd: [
    'core/ui-helpers.js',
    // StackDrag engine itself split (2026-09) into core/visual/scroll;
    // order mirrors the index.html script tags.
    'stack-drag-core.js',
    'stack-drag-visual.js',
    'stack-drag-scroll.js',
    'stack-drag.js',
    'stack-dnd-history.js',
    'stack-dnd-render.js',
    'stack-dnd-menu.js',
    'stack-dnd-config.js',
    'stack-dnd-form.js',
    'stack-dnd.js',
  ],
  // app facade + its parts. Loaded after the panels it wires.
  app: [
    'core/ui-helpers.js',
    'app-bridge.js',
    'app-history.js',
    'app-session.js',
    'app.js',
  ],
};

// Top-level consts per file that later files resolve by name. core/*.js and
// sash-core.js self-register (window.UIHelpers / UMD root) — no exports.
const FILE_EXPORTS = {
  'sash-grid-tree.js': ['SashGridTree'],
  'sash-grid-windows.js': ['SashGridWindowStore', 'SashGridWindows', 'SashGridMenus'],
  'sash-grid-presets.js': ['SashGridPresets'],
  'sash-grid-drag-core.js': ['SashGridDrag'],
  'sash-grid-drag-spec.js': ['SashGridSpec'],
  'sash-grid-drag-resize.js': ['SashGridResize'],
  'sash-grid.js': ['SashGrid'],
  'stack-drag-core.js': ['StackDragCore'],
  'stack-drag-visual.js': ['StackDragVisual'],
  'stack-drag-scroll.js': ['StackDragScroll'],
  'stack-drag.js': ['StackDrag'],
  'stack-dnd-history.js': ['StackDnDMigration', 'StackDnDHistory'],
  'stack-dnd-render.js': ['StackDnDRender', 'StackDnDListOps'],
  'stack-dnd-menu.js': ['StackDnDMenu'],
  'stack-dnd-config.js': ['StackDnDConfig'],
  'stack-dnd-form.js': ['StackDnDConfigRows', 'StackDnDSpeed'],
  'stack-dnd.js': ['StackDnD', 'BUILTIN_BLOCKS', 'RETIRED_KEYS'],
  'app-bridge.js': ['AppBridge'],
  'app-history.js': ['AppHistory'],
  'app-session.js': ['AppSession'],
  'app.js': ['App'],
};

// Evaluate the family file-by-file against the real (stubbed) DOM globals
// already on globalThis, publishing each file's consts (see FILE_EXPORTS) so
// the next file resolves them by name.
function loadFamily(family, opts = {}) {
  const files = opts.except
    ? family.filter((f) => !opts.except.includes(f)) : family.slice();
  for (const f of files) {
    let src = fs.readFileSync(path.join(UI, f), 'utf8');
    const names = FILE_EXPORTS[f] || [];
    if (names.length) {
      const exportCode = names.map((n) => `;globalThis.${n} = ${n};`).join('');
      // The coverage mirror appends `//# sourceURL=cvb://<rel>` as the final
      // line of each file; V8 only honours the pragma in tail position, so
      // insert the exports BEFORE it (per-file coverage attribution).
      const pragma = src.match(/\/\/# sourceURL=cvb:\/\/[^\n]*\n?$/);
      src = pragma
        ? src.slice(0, -pragma[0].length) + exportCode + '\n' + pragma[0]
        : src + exportCode;
    }
    vm.runInThisContext(src);
  }
}

// Evaluate ONE shipped file as its own top-level script (like a <script>
// tag), optionally publishing its top-level const under `name`. Same
// pragma-tail surgery as loadFamily (per-file V8 attribution).
function loadSingle(rel, name) {
  let src = fs.readFileSync(path.join(UI, rel), 'utf8');
  if (name) {
    const exportCode = `;globalThis.${name} = ${name};`;
    const pragma = src.match(/\/\/# sourceURL=cvb:\/\/[^\n]*\n?$/);
    src = pragma
      ? src.slice(0, -pragma[0].length) + exportCode + '\n' + pragma[0]
      : src + exportCode;
  }
  vm.runInThisContext(src);
}

// Legacy one-shot concatenation (kept for reference); prefer loadFamily — a
// single concatenated eval loses per-file V8 coverage attribution.
function sourceOf(family, opts = {}) {
  const files = opts.except
    ? family.filter((f) => !opts.except.includes(f)) : family.slice();
  return files
    .map((f) => fs.readFileSync(path.join(UI, f), 'utf8'))
    .join('\n');
}

module.exports = { UI, FAMILIES, sourceOf, loadFamily, loadSingle };
