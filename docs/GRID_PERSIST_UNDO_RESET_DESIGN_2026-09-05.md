# Flexible grid — backend persistence, undo/redo, and Reset to default

Date: 2026-09-05
Status: design, written before implementation

Follow-up to `docs/SASH_LAYOUT_DESIGN_2026-09-05.md`, merged from
`arena/01a07253-chat-v-bot`. Four requirements:

1. the grid layout must be **storable** (survive a restart);
2. the grid must participate in the **undo system**;
3. add a **Reset to default** button;
4. the **default layout must show every window**.

---

## 1. What the merged branch already does

| Concern | Shipped state |
| --- | --- |
| Tree model | `ui/js/sash-core.js` — pure, tested (`tests/test_sash_core.js`, 28 checks) |
| Interaction | `ui/js/sash-grid.js` — drag, split, join, sash resize |
| Persistence | `localStorage` only, key `STORAGE_KEY` |
| Presets | Default / A / B / C via the 📐 menu |
| Undo | none — layout changes are outside the Ctrl+Z history |
| Reset | only "Default" in the preset menu, and a per-sash double-click |

So (1) is half-done (browser-local, not in `config.json`), (2) and (3) are
missing, and (4) needs checking.

## 2. Requirement 4 — "default with all windows visible"

`SashCore.defaultTree()` already contains **all seven** leaves: `stats`,
`filters`, `stack`, `config`, `composer`, `people`, `log`. But `config`
(`#blockConfigPanel`) ships with `class="… hidden"` and is only revealed when a
block is opened, and `_panelIsHidden()` makes a hidden panel *release its grid
space*. So "reset to default" currently yields six visible windows, not seven.

That hidden-panel behaviour is correct and must stay — it is the fix from
`d818320` ("grid left a fixed empty gap when a window was hidden"). The
resolution is therefore **not** to change the grid, but to make the reset
action explicitly *unhide* every window it restores:

```
resetToDefault():
  root = SashCore.defaultTree()
  for each leaf id: un-hide the backing panel
  render(); persist; push to history
```

`#blockConfigPanel` gets an empty-state message so an unhidden-but-unused
config panel does not look broken (RULE 4: empty ≠ broken).

## 3. Requirement 1 — storable in `config.json`

`localStorage` is per-profile browser state; the rest of this app's session
lives in `config.json` via `ConfigManager`. The layout should live there too,
so it travels with the config file and survives a profile reset.

* `config_manager.py` — add `"grid_layout": None` and `"grid_layout_history"`
  / `"grid_layout_history_index"` to the `state` defaults.
* `bridge.py` — new slots:
  * `get_grid_layout() -> str` (serialized tree or `""`)
  * `save_grid_layout(json_str)` — validate, persist, push history
  * `undo_grid_layout() / redo_grid_layout() -> str` (`"null"` when at an end)
  * `reset_grid_layout() -> str` — returns the default tree, pushes history
* `sash-grid.js` — `_save()` writes **both** `localStorage` (instant, offline)
  and the bridge (authoritative). `_loadTree()` prefers the backend value and
  falls back to `localStorage`, then to `defaultTree()`.

Writing both is deliberate: the bridge is asynchronous and may be absent (the
grid must work in a plain browser and in the Node tests), while `localStorage`
is synchronous but profile-local. The backend wins on load because it is the
one the user can actually back up.

**Validation on the way in.** `save_grid_layout` must not store a tree it
cannot read back. It parses with the same rules `SashCore.deserialize` uses —
at minimum: valid JSON, `v === 1`, and a `tree` that is a well-formed
leaf/split structure. An invalid payload is rejected and logged, leaving the
previous layout intact, so a bug in the front end cannot brick the user's
layout on every start.

## 4. Requirement 2 — the undo system

The existing undo (`stack_history`) is for the **action stack**. Layout and
stack are different kinds of state and must not share one history: undoing a
mis-drag of a window should not silently revert a block edit, and vice versa.

Decision: a **separate, parallel history** with the same shape and the same
100-step cap, reusing the proven push/dedup/truncate logic. `Bridge._push_history`
is generalised into `_push_history_generic(kind, value)` so both histories get
identical semantics (dedup, truncate-on-branch, cap) with no copy-paste.

Keyboard: the stack owns Ctrl+Z / Ctrl+Y. The grid gets **Ctrl+Shift+Z** /
**Ctrl+Shift+Y**, plus ↶/↷ buttons in the 📐 layout menu, so the two are never
ambiguous.

What counts as one undoable layout step:

| Action | Pushed? |
| --- | --- |
| Drag a window to a new position | yes |
| Split / join | yes |
| Apply a preset (Default/A/B/C) | yes |
| **Reset to default** | yes |
| Sash drag (resize) | yes, on pointer-up only — not per mouse-move |
| Double-click sash → even sizes | yes |
| A panel hiding/showing itself | **no** — that is a consequence of opening a block, not a layout edit |

## 5. Requirement 3 — the Reset button

Added to the 📐 layout menu, visually separated below the presets:

```
↺ Reset to default      Restore the classic layout with every window visible
```

It differs from the existing "Default" preset entry in one way that matters:
**it also unhides every window** (§2). The old entry stays for people who want
the default arrangement without forcing the config panel open.

The reset is itself undoable, so a mis-click is recoverable.

## 6. Edge cases

| Case | Behaviour |
| --- | --- |
| No bridge (plain browser / tests) | `localStorage` only; everything still works |
| Stored tree references an unknown window id | Rejected by `deserialize`; fall back to default |
| Stored tree is missing a known window | Rejected — a window would be unreachable |
| `config.json` unwritable | Log a warning; in-memory + `localStorage` still work |
| Undo with empty history | `"null"`, a `⚠ Nothing to undo` log line, no change |
| Reset while at the default already | Still pushes a step (harmless, keeps redo honest) |

## 7. Test plan

`tests/test_grid_persistence.py` (Python, backend):

* the new `state` keys default correctly and survive a save/load round-trip;
* `save_grid_layout` rejects malformed JSON, wrong `v`, and unknown window ids,
  leaving the previous value intact;
* history: push, dedup, truncate-on-branch, 100-step cap;
* `undo_grid_layout` / `redo_grid_layout` walk the history and return `"null"`
  at the ends;
* `reset_grid_layout` returns a tree containing **all seven** windows;
* stack history and grid history are independent — pushing one never moves the
  other's index.

`tests/test_sash_core.js` (Node, extends the shipped suite):

* `defaultTree()` contains every id in `SashCore.WINDOWS`;
* the default tree validates and survives serialize → deserialize.

Existing suites must stay green.
