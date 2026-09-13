"""The four read modes and the slice-retry budget — the vocabulary every
other module in this package is written against.

Owns: constants only, no behaviour. Imports nothing from `backend.*`, so it
can be imported from any phase without a cycle.
"""

from __future__ import annotations

#: A virtualised pane can drop its message nodes between a state() probe and
#: the slice() that follows. Do not archive "0" on the first read — retry the
#: range a few times (and restore the viewport once) before giving up.
SLICE_RETRIES = 4

#: What the archive should do with what we are about to read.
MODE_EMPTY = "empty"            # the pane holds nothing
MODE_UNCHANGED = "unchanged"    # nothing moved — ZERO node reads
MODE_DELTA = "delta"            # the head is intact, the tail grew
MODE_FULL = "full"              # re-read the visible range and align it
