/* ═══════════════════════════════════════════════════════════════
   preset-adapt.js — Adaptive window-preset restore (DOM-free)

   A portable preset document whose window set drifted from the live
   build (created before a window was added, or after one was removed)
   used to be refused wholesale. This module restores what matches and
   REPORTS the rest, per the 2026-09-14 acceptance criteria:

     • unknown ids anywhere (tree leaves, windows[], window_states)
       are pruned / skipped and explained;
     • live windows the preset does not have are appended by the
       SashCore migrators into a default bottom row and explained;
     • a known entry contradicting window_states is corrected from it
       (window_states is authoritative);
     • a known entry with corrupt bounds keeps its TREE placement and
       gets default bounds, explained.

   Structural corruption (non-lists, duplicates inside window_states,
   closed/minimized overlap, unparsable trees) still REFUSES — the
   I-11 invariant: never hand back a document that cannot be read back.

   Mirror: services/preset_adapt.py — the reason strings below are a
   shared contract, pinned by tests on both sides (AGENT_RULES RULE 3).

   Design: docs/archive/2026-09-14-grid-rows-adaptive-restore/GRID_ROWS_ADAPTIVE_RESTORE_DESIGN_2026-09-14.md
   ═══════════════════════════════════════════════════════════════ */

(function (root, factory) {
  'use strict';
  if (typeof module === 'object' && module.exports)
    module.exports = factory(require('./sash-core.js'));
  else root.PresetAdapt = factory(root.SashCore);
})(typeof self !== 'undefined' ? self : this, function (SashCore) {
  'use strict';

  /** Shared with services/preset_adapt.py — pinned on both sides. */
  const REASON = {
    unknown: 'unknown window in this build',
    duplicate: 'duplicate preset entry',
    bounds: 'invalid bounds; default position used',
    state: 'state corrected from window_states',
    added: 'not in the preset; added with default placement',
  };
  /** Neutral tile: valid, zero-height, never covers the real preview. */
  const DEFAULT_BOUNDS = { x: 0, y: 0, width: 1, height: 0 };

  const isKnown = (id) => typeof id === 'string' && SashCore.WINDOW_IDS.includes(id);

  function _unique(list) {
    const seen = new Set();
    return list.filter((item) => {
      const key = item.id + '|' + item.reason;
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    });
  }

  /** Structural tree check that ignores WHICH windows are present. */
  function _structuralError(tree) {
    const ids = SashCore.leafIds(tree).filter((id) => typeof id === 'string');
    return SashCore.validate(tree, ids);
  }

  function _treePruned(before) {
    const seen = new Set();
    const pruned = [];
    before.forEach((id) => {
      const dup = seen.has(id);
      seen.add(id);
      if (!isKnown(id) || dup) pruned.push({ id, reason: dup ? REASON.duplicate : REASON.unknown });
    });
    return _unique(pruned);
  }

  /**
   * Repair a preset tree to the CURRENT window set: prune unknown and
   * duplicate leaves, append whatever is missing (SashCore.migrate), and
   * report both sides. `version` gates like SashCore.deserialize.
   */
  function adaptTree(tree, version) {
    if (!Number.isInteger(version) || version < 1 || version > SashCore.VERSION)
      return { ok: false, error: 'unsupported layout version ' + version };
    const structural = _structuralError(tree);
    if (structural) return { ok: false, error: structural };
    const before = SashCore.leafIds(tree).filter((id) => typeof id === 'string');
    const repaired = SashCore.migrate(tree);
    return {
      ok: true, tree: repaired,
      pruned: _treePruned(before),
      added: SashCore.WINDOW_IDS.filter((id) => !before.includes(id))
        .map((id) => ({ id, reason: REASON.added })),
    };
  }

  /** window_states: unknown ids skip + report; duplicates/overlap refuse. */
  function adaptStates(states) {
    if (!states || !Array.isArray(states.closed) || !Array.isArray(states.minimized))
      return { ok: false, error: 'window_states must contain closed and minimized lists' };
    const skipped = [];
    const clean = (list) => {
      const out = [];
      for (const id of list) {
        if (!isKnown(id)) { skipped.push({ id: String(id), reason: REASON.unknown }); continue; }
        if (out.includes(id)) return null;
        out.push(id);
      }
      return out;
    };
    const closed = clean(states.closed);
    const minimized = clean(states.minimized);
    if (!closed || !minimized)
      return { ok: false, error: 'window_states contains a duplicate window' };
    if (closed.some((id) => minimized.includes(id)))
      return { ok: false, error: 'closed and minimized window states overlap' };
    return { ok: true, states: { closed, minimized }, skipped: _unique(skipped) };
  }

  function _entryState(id, entry, states, corrected) {
    const wanted = states.closed.includes(id) ? 'closed'
      : (states.minimized.includes(id) ? 'minimized' : 'open');
    if (entry.state !== wanted) corrected.push({ id, reason: REASON.state });
    return wanted;
  }

  function _entryBounds(entry, id, corrected) {
    const b = entry.bounds;
    const numeric = b && typeof b === 'object' && !Array.isArray(b) &&
      ['x', 'y', 'width', 'height'].every((k) =>
        typeof b[k] === 'number' && Number.isFinite(b[k]) && b[k] >= 0 && b[k] <= 1);
    if (numeric && b.x + b.width <= 1.001 && b.y + b.height <= 1.001)
      return { x: b.x, y: b.y, width: b.width, height: b.height };
    corrected.push({ id, reason: REASON.bounds });
    return Object.assign({}, DEFAULT_BOUNDS);
  }

  /**
   * windows[]: unknown/duplicate entries skip + report, corrupt fields of
   * KNOWN windows are corrected + reported, missing live windows are added
   * with default bounds and their state from window_states. The output is
   * the canonical CURRENT set in WINDOW_IDS order — re-saving it passes
   * strict validation.
   */
  function adaptWindows(entries, states) {
    if (!Array.isArray(entries)) return { ok: false, error: 'windows must be a list' };
    const skipped = [], corrected = [], byId = new Map();
    for (const entry of entries) {
      if (!entry || typeof entry !== 'object' || Array.isArray(entry))
        return { ok: false, error: 'each window entry must be an object' };
      const id = entry.id;
      if (!isKnown(id)) { skipped.push({ id: String(id), reason: REASON.unknown }); continue; }
      if (byId.has(id)) { skipped.push({ id, reason: REASON.duplicate }); continue; }
      byId.set(id, {
        id,
        title: typeof entry.title === 'string' ? entry.title : (SashCore.WINDOW_TITLES[id] || id),
        state: _entryState(id, entry, states, corrected),
        bounds: _entryBounds(entry, id, corrected),
      });
    }
    const added = [];
    SashCore.WINDOW_IDS.forEach((id) => {
      if (byId.has(id)) return;
      const state = states.closed.includes(id) ? 'closed'
        : (states.minimized.includes(id) ? 'minimized' : 'open');
      byId.set(id, { id, title: SashCore.WINDOW_TITLES[id] || id, state,
        bounds: Object.assign({}, DEFAULT_BOUNDS) });
      added.push({ id, reason: REASON.added });
    });
    return { ok: true, windows: SashCore.WINDOW_IDS.map((id) => byId.get(id)),
      skipped: _unique(skipped), added, corrected: _unique(corrected) };
  }

  /** The one report shape both mirrors return: every window accounted for. */
  function buildReport(treeRes, statesRes, winsRes, windows) {
    const added = _unique([].concat(treeRes.added, winsRes.added));
    const addedIds = new Set(added.map((a) => a.id));
    return {
      applied: windows.map((w) => w.id).filter((id) => !addedIds.has(id)),
      skipped: _unique([].concat(treeRes.pruned, statesRes.skipped, winsRes.skipped)),
      added,
      corrected: winsRes.corrected,
    };
  }

  /** One-line human summary for the status bar / log. */
  function reportSummary(report) {
    if (!report) return '';
    const parts = [];
    ['skipped', 'added', 'corrected'].forEach((kind) => {
      if (report[kind] && report[kind].length)
        parts.push(kind + ': ' + report[kind].map((r) => r.id + ' (' + r.reason + ')').join(', '));
    });
    return parts.length ? ' — ' + parts.join('; ') : '';
  }

  return { REASON, DEFAULT_BOUNDS, adaptTree, adaptStates, adaptWindows,
    buildReport, reportSummary };
});
