"""Parameter objects for the history store (RULE 19 §19.4).

`PersonPageRequest` in `backend/history_query.py` is the model: related
arguments become fields of one typed request instead of a positional list every
caller has to keep in order.

Only objects a real signature consumes live here. Step F5's first attempt
(2026-09-13, branch `arena/01a09a61-chat-v-bot`) added nine and wired none:
eight had exactly one reference in the whole tree — their own definition — and
`AppendPlanner.append_v2()` was never called, so the metric the step targets did
not move (70 functions over 4 params, worst 20, before *and* after). Unused code
that changes no metric is the `foo_part1` / `foo_part2` shape §16.1.1 forbids,
so the eight were dropped and this one kept, because it is wired: `WriteContext`
is what `_after_write` now takes.

The rest of the plan — including why `AppendRequest` cannot be wired yet, its
only production callers being in `backend/chat_sync.py` under the AREA D
snapshot — is in
`docs/archive/2026-09-13-round-f/F5_PARAMETER_OBJECTS.md`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class WriteContext:
    """What `_after_write` needs to refresh the counters and the resume cursor.

    Replaces the 8-parameter signature of `HistoryRepo._after_write` and its
    `PersonLifecycle` implementation — all five call sites are inside
    `stores/`, so nothing outside the family had to change.

    `head_sig` / `tail_sig` (and their author-agnostic twins `head_any` /
    `tail_any`) of None mean "leave as is"; an empty string deliberately CLEARS
    the signature. `bootstrapped` of None means "keep what the cursor says".
    """

    person_id: int
    my_nick: str
    dom_count: int
    head_sig: Optional[str]
    tail_sig: Optional[str]
    bootstrapped: Optional[bool] = None
    head_any: Optional[str] = None
    tail_any: Optional[str] = None
