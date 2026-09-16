/* sash-core-layouts.js — the window registry and the preset trees
   (Round II Area B).

   Split out of ui/js/sash-core.js; the facade lists its parts. Owns the
   layout-version facts: VERSION, the per-version window id sets (used by
   migrate) and the id → title registry. Cross-part calls resolve at call
   time (tree ops come from SashCoreTree).
*/
'use strict';

const SashCoreLayouts = {
  /** The fixed set of windows the grid always contains (id → title). */
  WINDOWS: [
    { id: 'stats',    title: 'Stats' },
    { id: 'filters',  title: 'Filters' },
    { id: 'stack',    title: 'Action Stack' },
    { id: 'config',   title: 'Block Config' },
    { id: 'composer', title: 'Message Composer' },
    { id: 'people',   title: 'User Memory' },
    { id: 'log',      title: 'Log Console' },
    // Message archive windows (added in layout version 2)
    { id: 'history',   title: 'Person History' },
    { id: 'userdb',    title: 'Full User Database' },
    { id: 'collector', title: 'Chat Message Collector' },
    // Labels + database management (added in layout version 3)
    { id: 'labels',    title: 'Label Manager' },
    { id: 'dbconn',    title: 'DB Connection' },
    // AI assistant windows (added in layout version 4)
    { id: 'botchat',   title: 'AI Bot Chat' },
    { id: 'botprompt', title: 'Grok Prompt Editor' },
  ],

  /** Windows that existed in layout version 1 — used by migrate(). */
  V1_WINDOW_IDS: ['stats', 'filters', 'stack', 'config', 'composer',
                  'people', 'log'],

  /** Current serialisation version. Older layouts are migrated on load. */
  VERSION: 4,

  /**
   * Mirrors the legacy static layout:
   *   [ [stats/filters | stack/config] , composer , [people | log] ]
   */
  defaultTree() {
    const split = SashCoreTree.split.bind(SashCoreTree);
    const leaf = SashCoreTree.leaf;
    return split('col', [
      split('row', [
        split('col', [leaf('stats'), leaf('filters')], [35, 65]),
        split('col', [leaf('stack'), leaf('config')], [72, 28]),
      ], [17, 83]),
      leaf('composer'),
      split('row', [leaf('people'), leaf('log')], [70, 30]),
      split('row', [leaf('history'), leaf('userdb'), leaf('collector')],
            [40, 35, 25]),
      split('row', [leaf('labels'), leaf('dbconn')], [55, 45]),
      split('row', [leaf('botchat'), leaf('botprompt')], [62, 38]),
    ], [26, 13, 18, 17, 12, 14]);
  },

  /**
   * Spec "Layout A" — stacked rows, 1 column each.
   * Composer / People / Log are each a full-width row.
   */
  layoutA() {
    const split = SashCoreTree.split.bind(SashCoreTree);
    const leaf = SashCoreTree.leaf;
    return split('col', [
      leaf('stats'), leaf('filters'), leaf('stack'), leaf('config'),
      leaf('composer'), leaf('people'), leaf('log'),
      leaf('history'), leaf('userdb'), leaf('collector'),
      leaf('labels'), leaf('dbconn'),
      leaf('botchat'), leaf('botprompt'),
    ], [5, 5, 12, 9, 9, 9, 7, 8, 7, 6, 5, 5, 8, 5]);
  },

  /**
   * Spec "Layout B" — row 1 split: [Composer | People], row 2 Log full
   * width.
   */
  layoutB() {
    const split = SashCoreTree.split.bind(SashCoreTree);
    const leaf = SashCoreTree.leaf;
    return split('col', [
      split('row', [leaf('composer'), leaf('people')], [50, 50]),
      leaf('log'),
      split('row', [
        split('row', [leaf('stats'), leaf('filters')], [45, 55]),
        split('col', [leaf('stack'), leaf('config')], [72, 28]),
      ], [25, 75]),
      split('row', [
        split('col', [leaf('history'), leaf('collector')], [65, 35]),
        leaf('userdb'),
      ], [55, 45]),
      split('row', [leaf('labels'), leaf('dbconn')], [55, 45]),
      split('row', [leaf('botchat'), leaf('botprompt')], [62, 38]),
    ], [22, 15, 21, 16, 12, 14]);
  },

  /**
   * Spec "Layout C" — Log Console is a tall right-side column spanning
   * both hero rows (Composer above People in the left column).
   */
  layoutC() {
    const split = SashCoreTree.split.bind(SashCoreTree);
    const leaf = SashCoreTree.leaf;
    return split('col', [
      split('row', [
        split('col', [leaf('composer'), leaf('people')], [45, 55]),
        leaf('log'),
      ], [70, 30]),
      split('row', [
        split('row', [leaf('stats'), leaf('filters')], [45, 55]),
        split('col', [leaf('stack'), leaf('config')], [72, 28]),
      ], [25, 75]),
      split('row', [leaf('history'), leaf('userdb'), leaf('collector')],
            [38, 34, 28]),
      split('row', [leaf('labels'), leaf('dbconn')], [55, 45]),
      split('row', [leaf('botchat'), leaf('botprompt')], [62, 38]),
    ], [29, 21, 22, 13, 15]);
  },
};

// Version family + derived lookups + presets (computed after the literal —
// object literals cannot self-reference at creation time).
SashCoreLayouts.V2_WINDOW_IDS = SashCoreLayouts.V1_WINDOW_IDS.concat(
  ['history', 'userdb', 'collector']);
SashCoreLayouts.V3_WINDOW_IDS = SashCoreLayouts.V2_WINDOW_IDS.concat(
  ['labels', 'dbconn']);
SashCoreLayouts.WINDOW_IDS = SashCoreLayouts.WINDOWS.map((w) => w.id);
SashCoreLayouts.WINDOW_TITLES = Object.fromEntries(
  SashCoreLayouts.WINDOWS.map((w) => [w.id, w.title]));
SashCoreLayouts.PRESETS = {
  default: SashCoreLayouts.defaultTree,
  a: SashCoreLayouts.layoutA,
  b: SashCoreLayouts.layoutB,
  c: SashCoreLayouts.layoutC,
};
