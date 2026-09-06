# Block Config pin (keep-open) — design

Date: 2026-09-06
Files: `ui/index.html`, `ui/js/stack-dnd.js`, `ui/css/stack.css`,
`tests/test_config_panel_pin.js`

## Problem

The Block Config / Tune panel closes whenever no Action Block is selected.
That makes it annoying to compare/edit settings while clicking back and forth
between blocks or while the stack is replaced (session restore, preset load,
undo/redo), because the panel disappears just because the selection was lost.

## Requirement

- Add a 📌 **Pin** button in the corner of the Block Config title bar.
- While pinned, the panel stays open even with no block selected and shows the
  existing empty-state hint.
- Clicking Pin again unpins it and restores default close-on-deselect.
- The explicit **×** close button always closes the panel and also unpins.

## Behaviour

| State | Panel visible? | Shows |
|---|---|---|
| Block selected, unpinned | yes | config form |
| Block selected, pinned | yes | config form |
| No block selected, unpinned | no (hidden) | — |
| No block selected, pinned | yes | empty-state hint |

Pin is UI-local state (`StackDnD.configPinned`) and is intentionally not
persisted: it is a transient editing convenience.

## Implementation

- The pin button lives in the Block Config title bar next to **×**, with
  `aria-pressed` for accessibility and a `.pin-active` highlight when on.
- `_updateConfigVisibility(block)` is the single visibility chokepoint:
  - pinned or `block` present → show;
  - unpinned and no block → hide;
  - no block → clear the form and hide the custom-block actions so the
    empty-state hint is shown instead of a stale block.
- `_showConfig`, `setStack`, `deselectBlock`, `removeBlock`, the pin toggle
  and the close button all route through that chokepoint.
- `removeBlock()` also keeps the selected block selected when a block before
  it is deleted, and lands on the neighbour (or `-1`) when the selected block
  itself is removed.

## Tests

`tests/test_config_panel_pin.js` executes the real shipped
`ui/js/stack-dnd.js` against the same minimal DOM stub as the other stack-dnd
tests. It covers:

- pin button markup and initial `aria-pressed` state;
- real click wiring (pin toggles and announces state);
- pinned panel staying visible and empty after a stack reset/deselect;
- pinned empty panel accepting a later block selection;
- unpinning an empty panel closing it;
- explicit close unpinning;
- pin behaviour when the last selected block is removed.

Run with `node tests/test_config_panel_pin.js`.
