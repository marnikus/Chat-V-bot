/* stack-drag.js — StackDrag facade (H-B2b JS split, 356→~20)

Parts loaded before this one — see index.html:
  stack-drag-core.js, stack-drag-visual.js, stack-drag-scroll.js

Public API unchanged: window.StackDrag
*/

'use strict';

const StackDrag = {};

UIHelpers.mergeParts(StackDrag, StackDragCore, StackDragVisual, StackDragScroll);

if (typeof window !== 'undefined') window.StackDrag = StackDrag;
