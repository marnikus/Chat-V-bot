/* ═══════════════════════════════════════════════════════════════
   preset-validate.js — is this preset FILE well-formed?

   Owns ONE decision, and deliberately not a second one. There are two very
   different questions to ask about a window preset:

     STRUCTURAL    Is this a preset document at all? Right format, right
                   schema, parseable JSON, a name, sane normalised bounds,
                   a well-shaped tree. A property of the FILE.
     ENVIRONMENTAL Can THIS build show the windows it names? A property of
                   the file AND the app it happens to be opened in.

   They were one check, and conflating them caused the reported bug: a file
   imported from another build passed the preview, and was then rejected by
   the SAME validator when _persistDocument re-ran it on the way to disk. The
   user accepted an import and got a late, confusing failure instead of a
   saved file.

   Structural validity is the one that decides whether a document can be
   STORED: a file is worth keeping whether or not today's app can display
   every window in it -- tomorrow's build may well be able to. Environmental
   fitting is preset-reconcile.js's job and happens on the way to the screen,
   not on the way to disk.

   The tree check is injected rather than imported so this module stays
   independent of the grid model.

   DOM-free on purpose: the UI loads it with a <script> tag and
   tests/test_preset_validate.js executes this exact file in node
   (AGENT_RULES RULE 6).
   ═══════════════════════════════════════════════════════════════ */

(function (root, factory) {
  'use strict';
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.PresetValidate = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  const MAX_NAME = 80;
  const fail = (error) => ({ ok: false, error });

  /** Parse a string document, or deep-copy an object one. */
  function parse(raw) {
    try {
      const doc = typeof raw === 'string' ? JSON.parse(raw)
                                          : JSON.parse(JSON.stringify(raw));
      if (!doc || typeof doc !== 'object' || Array.isArray(doc)) {
        return fail('document must be an object');
      }
      return { ok: true, document: doc };
    } catch (e) {
      return fail('bad JSON: ' + e.message);
    }
  }

  /** Format, schema, app version and name: the document's own identity. */
  function checkIdentity(doc, spec) {
    if (doc.format !== spec.format || doc.schema_version !== spec.schemaVersion) {
      return fail('unsupported window preset format or schema version');
    }
    if (typeof doc.app_version !== 'string' || !doc.app_version.trim()) {
      return fail('app_version is required');
    }
    const name = typeof doc.name === 'string' ? doc.name.trim() : '';
    if (!name || name.length > MAX_NAME) {
      return fail('preset name must be 1–' + MAX_NAME + ' characters');
    }
    return { ok: true };
  }

  /** Normalised 0–1 bounds that stay inside the grid. */
  function validBounds(bounds) {
    if (!bounds || typeof bounds !== 'object') return false;
    const values = ['x', 'y', 'width', 'height'].map((k) => bounds[k]);
    if (!values.every((v) => typeof v === 'number' && Number.isFinite(v) &&
                             v >= 0 && v <= 1)) return false;
    return bounds.x + bounds.width <= 1.001 && bounds.y + bounds.height <= 1.001;
  }

  /**
   * The window list and the state lists must agree with each other.
   *
   * Note what is NOT checked: whether the ids are windows this build has.
   * That is environmental, and reconcile() handles it.
   */
  function checkWindows(doc) {
    const state = doc.window_states;
    if (!state || !Array.isArray(state.closed) || !Array.isArray(state.minimized)) {
      return fail('window_states must contain closed and minimized lists');
    }
    const named = (id) => typeof id === 'string' && id !== '';
    if (!state.closed.every(named) || !state.minimized.every(named)) {
      return fail('window_states contains a nameless window');
    }
    if (new Set(state.closed).size !== state.closed.length ||
        new Set(state.minimized).size !== state.minimized.length) {
      return fail('window_states contains a duplicate window');
    }
    if (state.closed.some((id) => state.minimized.includes(id))) {
      return fail('closed and minimized window states overlap');
    }
    return checkWindowList(doc, state);
  }

  function checkWindowList(doc, state) {
    if (!Array.isArray(doc.windows) || !doc.windows.length) {
      return fail('windows must be a non-empty list');
    }
    const seen = new Set();
    for (const item of doc.windows) {
      if (!item || typeof item.id !== 'string' || !item.id || seen.has(item.id)) {
        return fail('windows contain a nameless or duplicate id');
      }
      const wanted = state.closed.includes(item.id) ? 'closed'
        : (state.minimized.includes(item.id) ? 'minimized' : 'open');
      if (item.state !== wanted || !validBounds(item.bounds)) {
        return fail('window state or normalized bounds are invalid');
      }
      seen.add(item.id);
    }
    return { ok: true };
  }

  /** Grid metadata. window_count must be sane, not equal to today's count. */
  function checkGrid(doc) {
    const grid = doc.grid;
    if (!grid || grid.type !== 'sash-tree' || grid.sizes_unit !== 'percent' ||
        !Number.isInteger(grid.window_count) || grid.window_count < 1) {
      return fail('grid metadata is invalid');
    }
    return { ok: true };
  }

  /** Source screen, used only to explain re-projection to the user. */
  function checkScreen(doc) {
    const screen = doc.screen;
    if (!screen || typeof screen !== 'object') return fail('screen metadata is invalid');
    const dpr = screen.device_pixel_ratio === undefined ? 1 : screen.device_pixel_ratio;
    const positive = (v) => typeof v === 'number' && Number.isFinite(v) && v > 0;
    if (!positive(screen.width) || !positive(screen.height) || !positive(dpr)) {
      return fail('screen metadata is invalid');
    }
    return { ok: true, dpr };
  }

  /**
   * Full structural check.
   *
   * `spec` supplies { format, schemaVersion, checkTree } -- checkTree(tree,
   * version) returns { ok, tree } or { ok:false, error } and is injected so
   * this module needs no knowledge of the grid model.
   *
   * On success returns { ok:true, document } with the document normalised:
   * trimmed strings, an explicit device_pixel_ratio, and the parsed tree.
   */
  function structural(raw, spec) {
    const parsed = parse(raw);
    if (!parsed.ok) return parsed;
    const doc = parsed.document;
    for (const step of [() => checkIdentity(doc, spec), () => checkGrid(doc),
                        () => checkWindows(doc)]) {
      const result = step();
      if (!result.ok) return result;
    }
    const screen = checkScreen(doc);
    if (!screen.ok) return screen;
    const tree = spec.checkTree(doc.grid.tree, doc.grid.version);
    if (!tree.ok) return fail('invalid grid tree: ' + tree.error);
    doc.name = doc.name.trim();
    doc.app_version = doc.app_version.trim();
    doc.screen.device_pixel_ratio = screen.dpr;
    doc.grid.tree = tree.tree;
    return { ok: true, document: doc };
  }

  return { structural, parse, checkIdentity, checkGrid, checkWindows,
           checkScreen, validBounds, MAX_NAME };
});
