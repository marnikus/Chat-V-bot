# Scroll & Parse: remove the duplicate "use_panel_filters" checkbox + add
# "Only scroll, no people adding" mode — design & fix

Date: 2026-09-05

## 1. Problems reported

### BUG #1 — Duplicate filter controls
The **Scroll & Parse** block's Tune panel shows two ways to control filtering:

1. Four tri-state selects — `Female`, `Registered`, `Guest`, `Anonymous`
   (`any` / `yes` / `no`) — the block's own criteria, stored as block params
   so they travel with presets.
2. A leftover **`use_panel_filters`** checkbox ("Apply Filter panel
   criteria") that used to *also* apply the global Filter-panel criteria on
   top of the block's own rules.

Two sources of truth for one filtering decision is redundant and confusing.
The checkbox must disappear; the four selects are the single control.

### Feature — "Scroll Only, No Adding" mode (find existing person)
The user sometimes needs to scroll the live list **without harvesting new
people**, just to *locate* a person who is **already in the local People
Memory list but not yet messaged** — so the run stops with that person on
screen for the subsequent Click User / Type Message blocks to work through.

Required behaviour:

* New checkbox: **"🔎 Only scroll, no people adding (find existing
  un-messaged person)"**.
* When enabled, the Scroll & Parse block:
  1. Reads People Memory for persons with status **not messaged**;
  2. scrolls the web list to find one of them on the live page;
  3. **stops on the first match that also passes the filter criteria**;
  4. **adds no new users** to People Memory (and purges nobody).
* If People Memory contains **no** un-messaged persons, it falls through to
  **normal collection** (add new people as usual) — the mode is therefore
  *not* a permanent off-switch. Re-running the loop after the backlog is
  drained keeps respecting the rule: each cycle seeks first, harvests only
  when nobody is waiting.

## 2. Research / what was already in place

Auditing the tree showed the **backend contract for both changes already
exists and is fully covered by tests** (they pass):

* `actions/scroll_parse.py`
  * Constructor pops the retired keys `use_panel_filters`,
    `skip_if_backlog`, `backlog_threshold` from kwargs so old presets load
    and the keys are never written back by `to_dict()`.
  * `build_filter()` ignores `panel_criteria` (kept for call-compatibility);
    the four block rules are the only filter.
  * New `scroll_only: bool` param, round-tripped through `to_dict()` (via
    `vars(self)`) and exposed in `config_schema()` as a checkbox.
  * `run_pipeline()` — STEP 0 mode decision: when `scroll_only` and the
    engine reports un-messaged nicks (`engine.unmessaged_nicks()`), it runs
    the parser in **seek** mode; with an empty target set it logs the
    fall-through and collects normally.
* `backend/scroll_parser.py` — `collect(..., seek_nicks=...)`:
  * seek mode tracks rendered people for stall detection but only *stops* on
    a nick that is in `seek_nicks` **and** passes the filter;
  * a seek target that fails the filter is skipped (never purged);
  * on a hit it records `result.found`, sets `stopped_early`, and calls
    **no** `on_collect`/`on_reject` hooks — nothing is written;
  * the end-of-list / stall / stop logic is shared with normal collection.
* `backend/action_engine.py`
  * `unmessaged_nicks()` reads People Memory (fails open → empty set →
    normal collection);
  * `_run_collect_phase()` persists only `result.collected` (the found seek
    person already exists in memory, so the idempotent `upsert_user` safety
    net is harmless) and returns the seek hit as the one-person queue.
* Tests: `tests/test_scroll_only_seek.py` (34 tests),
  `tests/test_scroll_parse_pipeline.py` (31),
  `tests/test_merge_undo_enabled.py` (16) — all green.

**The gap was the frontend migration layer.** The Tune panel
(`ui/js/stack-dnd.js` `_showConfig()`) renders *every key present on the
loaded block object*. Blocks persisted in older `config.json` sessions /
stack presets / undo history still carry `use_panel_filters: true/false` and
do **not** carry `scroll_only` (nor the other newer keys such as
`person_selector`, `purge_rejected`). So on those legacy stacks the user
still sees the dead checkbox and never sees the new one — exactly the
screenshot in the report.

The frontend had a single place (`_normalizeBlock`) that only defaulted
`enabled`/`pre_delay_ms`; it never stripped retired keys and never merged
missing settings from the block's current `BUILTIN_BLOCKS` defaults.

## 3. Design of the fix (frontend, one migration chokepoint)

Introduce a per-block **schema migration** in `ui/js/stack-dnd.js`, applied
everywhere raw block dicts enter the editor:

* `RETIRED_KEYS` — explicit denylist of settings that no longer exist for
  any block: `use_panel_filters`, `skip_if_backlog`, `backlog_threshold`
  (mirrors the Python constructor's retired list in
  `actions/scroll_parse.py`). They are deleted from every migrated block,
  so the Tune panel, the stack-card summary, snapshots, presets and history
  all stop carrying them.
* `_migrateBlock(b)`:
  1. drop anything that is not a plain object;
  2. look up `BUILTIN_BLOCKS` metadata for `b.block_id`;
  3. for a **known built-in**, start from a copy of `meta.defaults` (this
     re-introduces settings added after the block was saved — e.g.
     `scroll_only:false`, `purge_rejected:true`, `person_selector` …) and
     overlay the block's own saved values on top (user's saved choices win,
     missing settings take the current default);
  4. delete every `RETIRED_KEYS` entry;
  5. normalise `enabled` (default `true`, coerced to boolean);
  6. preserve unknown keys (e.g. CUSTOM_FIND's user fields) untouched.
* All existing entry points route through it:
  * `_normalizeBlock` (history + stack normalisation),
  * `setStack` (session restore, preset load, undo/redo, backend pushes),
  * `addBlockConfig` (new blocks from the + menu and custom presets).
* **Defence in depth** in `_showConfig()`: the render loop skips any
  `RETIRED_KEYS` key even if a block somehow still carries one, so the dead
  checkbox can never render again.

Because migration runs before the first snapshot, the cleaned stack is
re-saved to `config.json` / history on the next `notifyEdited()`/history
push — old stores self-heal on first use. The backend already ignores the
retired kwargs, so behaviour is consistent on both sides.

`BUILTIN_BLOCKS` for `SCROLL_PARSE` already declares `scroll_only:false`
with the label
"🔎 Only scroll, no people adding (find existing un-messaged person)".

**Backend safety net (merged in as well):** a Python twin of the denylist
(`RETIRED_BLOCK_KEYS`) plus `normalize_blocks()` in `backend/action_engine.py`
scrubs retired keys — and defaults `enabled` to true — wherever a stack
enters the backend: `load_stack()`, the bridge's run/snapshot/history
(save, undo, redo, push) and stack-preset save/load paths, and on every
history read-back. Dead keys therefore cannot round-trip from a legacy
`config.json` back to the Tune panel through the server side either; the
checked-in `config.json` in this tree was cleaned of the retired keys.

## 4. Acceptance

* A legacy stack containing `use_panel_filters` (e.g. the current
  `config.json`) opens with **no** "use_panel_filters" row in the Tune panel
  and **with** the new "Only scroll, no people adding" checkbox.
* Toggling the checkbox persists `scroll_only:true` in the block and it
  round-trips through save/load, presets and undo/redo.
* Backend behaviour (seek → stop on first un-messaged filter-passing
  person, add nobody; fall through to normal harvesting when the backlog is
  empty) is covered by `tests/test_scroll_only_seek.py`.
* New JS unit test
  (`tests/test_stack_dnd_migration.js`, run with node) covers:
  retired keys stripped, missing defaults (incl. `scroll_only`) added,
  saved values preserved, unknown keys kept, `setStack`/`addBlockConfig`
  migration, and the render skip-list.
