"""Shared constants for the conversation-sync algorithm.

Pure data, no imports: the modes every phase and the public façade agree on.
It sits at the top of the dependency order so `plan` / `session` / `sync` can
all import it without forming a cycle — `backend/chat_sync` imports from
`stores.*` and `backend.chat_text`, never the other way around.
"""

#: A virtualised pane can drop its message nodes between a state() probe and
#: the slice() that follows. Do not archive "0" on the first read — retry the
#: range a few times (and restore the viewport once) before giving up.
SLICE_RETRIES = 4

#: What the archive should do with what we are about to read.
MODE_EMPTY = "empty"            # the pane holds nothing
MODE_UNCHANGED = "unchanged"    # nothing moved — ZERO node reads
MODE_DELTA = "delta"            # the head is intact, the tail grew
MODE_FULL = "full"              # re-read the visible range and align it

#: how many tail records a capped read keeps when `max_messages` bites
_MAX_QUIET_RETRIES = 4
