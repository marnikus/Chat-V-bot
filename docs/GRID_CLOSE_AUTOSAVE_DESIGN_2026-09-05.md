# Grid layout close-time autosave design

Date: 2026-09-05  
Status: implementation design, written before the corrective code changes

## 1. Problem statement

After loading a grid preset and then changing the arrangement, the application
can close without the latest window order and split dimensions being stored.
The next launch can therefore restore the older preset arrangement instead of
the user's final state. The affected data includes:

- the position/order of every grid window;
- nested row/column structure;
- the current width/height allocation of every split child;
- hidden/visible panel state as represented by the current grid tree.

The requested behavior is that closing the desktop window automatically saves
the currently rendered layout, including changes made after loading a preset.

## 2. Audit and root cause

The current tree is serialized by `SashGrid._save()` after completed drag,
resize, preset, and reset operations. However, `MainWindow.closeEvent()` only
saves Qt window geometry and immediately starts shutdown. It does not ask the
WebEngine page for the current grid tree.

This leaves two failure windows:

1. A final in-memory DOM/tree change can exist without a completed save call.
2. A QWebChannel save request can still be queued when the WebEngine page is
   destroyed by close, so the backend never receives it.

The authoritative data contract already exists: `state.grid_layout` stores a
versioned canonical tree, whose nested `children` order and `sizes` contain
all window positioning and width/height allocations. The fix should complete
that existing transaction rather than introduce a second layout store.

## 3. Close-time persistence contract

Add `SashGrid.flushPersistence()` as an idempotent finalizer. It will:

1. serialize the current `SashGrid.root` with `SashCore.serialize()`;
2. update localStorage as an immediate browser fallback;
3. call `App.bridge.save_grid_layout(payload)` when the backend is available;
4. return whether a backend acknowledgment is expected.

`Bridge.save_grid_layout()` emits a `grid_layout_persisted(bool)` signal only
after validation, `state.grid_layout`, and the global history state have been
written. The normal `_save()` path and close-time finalizer use the same
backend slot, so deduplication prevents a close from creating a duplicate
history entry.

A loaded built-in preset is not overwritten in source code. Its current,
possibly customized tree becomes the persisted `state.grid_layout`, which is
the last-session layout restored on the next launch. Optional metadata records
the last preset name for diagnostics, but the canonical tree remains the
source of truth for exact order and dimensions.

## 4. Qt/WebEngine close handshake

`MainWindow.closeEvent()` becomes a two-phase close:

1. On the first close request, save Qt window geometry, ignore the event, and
   run JavaScript that calls `SashGrid.flushPersistence()`.
2. If no bridge is present or the page reports that no backend save is needed,
   finish immediately.
3. If the bridge save is dispatched, wait for
   `grid_layout_persisted(bool)`. A bounded one-second timer is a safety
   fallback so an unresponsive page cannot prevent closing forever.
4. Finish close exactly once by calling `close()` again. The second
   `closeEvent()` accepts the event and emits the existing shutdown signal.

This ordering keeps the WebEngine page alive until the final grid payload has
reached Python/config.json, while preserving the existing geometry and async
backend shutdown behavior.

## 5. Failure handling and invariants

- Malformed or invalid payloads are rejected without replacing the previous
  layout; the close fallback still permits shutdown.
- A close request is idempotent; repeated window-manager close events cannot
  start multiple JavaScript flushes or shutdown coroutines.
- If the page is already unavailable, the last successfully persisted layout
  remains intact and the app closes after the timeout.
- The close flush records no extra undo entry when its payload equals the
  current global grid entry.
- All seven window ids, canonical `t` nodes, and minimum split sizes continue
  to be enforced by the existing bridge validator.

## 6. Implementation and verification order

1. Add this design document before changing implementation files.
2. Add the bridge acknowledgment signal and emit it after grid persistence.
3. Add the JavaScript finalizer and use it for close-time serialization.
4. Add the two-phase `MainWindow` close handshake and bounded fallback.
5. Add focused tests for finalizer dispatch, bridge acknowledgment, and
   idempotent close behavior; retain existing grid persistence tests.
6. Run Python compilation, JavaScript syntax checks, SashCore tests, focused
   grid tests, and the available runtime checks.

## 7. Verification matrix

- Load a preset, reorder all windows, resize multiple row and column splits,
  close, reopen, and compare the complete canonical tree before/after.
- Confirm nested `children` order and `sizes` survive, not only the preset name.
- Confirm close waits for a successful bridge acknowledgment when available.
- Confirm no-bridge and timeout paths still close without crashing.
- Confirm a second close request cannot duplicate persistence or shutdown.
