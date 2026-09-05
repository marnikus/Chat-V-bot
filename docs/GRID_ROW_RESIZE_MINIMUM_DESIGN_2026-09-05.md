# Grid row-resize stability and edge-control design

Date: 2026-09-05  
Status: implementation design, written before the corrective code changes

## 1. Problem and reproduction

The remaining BUG #3 is visible in the default layout when the Message
Composer is resized vertically. Dragging either horizontal sash bordering the
Composer can cause the neighboring upper or lower row to collapse to a sliver
or disappear. When the pointer is dragged beyond the top/bottom edge, the sash
can also appear to lose its effective control position.

Reproduction:

1. Open the default layout.
2. Locate the horizontal sash immediately above or below Message Composer.
3. Drag it toward the top or bottom edge of the grid.
4. Continue moving outside the grid bounds and then release.
5. Observe that a neighboring row may become invisible and the persisted layout
   can retain an unusably small allocation.

## 2. Research/audit findings

The resize code in `ui/js/sash-grid.js` measures the two active neighbors in
pixels, then assigns those pixel values to `flexGrow` while the other direct
children keep the original percentage-like `flexGrow` values from render:

```js
child.style.flex = node.sizes[i] + ' 1 0%';
// during resize only the active pair receives flexGrow = pixelValue
```

`flex-grow` values are unitless relative weights, not pixel lengths. Mixing
pixel measurements such as `380` and `220` with remaining weights such as `30`
means the remaining row receives only a tiny fraction of the flex space. This
is why a non-active upper or lower row can shrink even though the active pair
was clamped.

The current code also listens on `document`, but does not capture the pointer
on the sash. Pointer capture is needed to keep the same sash as the control
when the pointer crosses the grid boundary or moves over a neighboring panel.

## 3. Corrected layout contract

During an active resize, every direct child of the affected split must use the
same unit system: fixed pixel extents along the split axis. The requested pair
is clamped to a legal interval:

```text
minimum = 96 px
availablePair = splitExtent - sashExtent - unchangedSiblingExtents
first = clamp(pointerBoundary - pairStart, minimum,
              availablePair - minimum)
second = availablePair - first
```

Unchanged siblings retain their measured pixel extents. Therefore the active
resize cannot transfer flex weight away from unrelated rows/columns.

On release:

1. Read the measured fixed pixel extents.
2. Convert all children to percentages of the split's usable extent.
3. Pass the percentages through `SashCore.setSplitSizesByPath()`, which applies
   the persisted minimum-size normalization.
4. Re-render the split, removing temporary inline pixel styles.
5. Persist the canonical tree through the existing global grid history path.

If the pair has less than two minimum panels available, the move is ignored
rather than allowing a child to collapse.

## 4. Pointer-edge behavior

The sash calls `setPointerCapture(pointerId)` at resize start when supported
and releases it at completion/cancellation. Document-level listeners remain as
a fallback for WebEngine implementations that do not expose pointer capture.
The pointer coordinate is always clamped to the legal interval, so dragging
outside the grid stops at the minimum boundary instead of changing the split
or losing the sash control.

The active resize stores the pointer id and removes the capture during both
`pointerup` and `pointercancel`. Escape cancellation is not a commit and
leaves the persisted model unchanged.

## 5. Implementation order

1. Add this design/research document before modifying implementation code.
2. Add an axis-size snapshot for every direct child at resize start.
3. Replace mixed `flexGrow` pixel weights with fixed pixel flex values for all
   children during live resize.
4. Add pointer capture/release and keep the legal edge clamp.
5. Add regression tests for vertical and horizontal resize calculations,
   including out-of-bounds pointer positions and non-active siblings.
6. Run the SashCore suite, JavaScript syntax checks, focused grid tests, and
   the available Python checks.

## 6. Verification matrix

- Resizing the Composer's top sash leaves the bottom sibling at its measured
  minimum or larger; it cannot collapse due to a flex-weight mismatch.
- Resizing the Composer's bottom sash has the same guarantee for the upper
  sibling.
- Pointer positions above the grid and below the grid produce exactly the
  minimum legal pair allocation, not negative or zero sizes.
- The persisted tree contains only canonical `t` nodes and every split size is
  at least 4 percent after commit.
- A canceled resize does not add a global undo entry; a committed resize adds
  exactly one grid entry.
