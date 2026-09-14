"""Parameter objects for the history store (RULE 19 §19.4).

`PersonPageRequest` in `backend/history_query.py` is the model: related
arguments become fields of one typed request instead of a positional list every
caller has to keep in order, and the function that used to take them changes
signature in place — no `_v2` twin, no optional migration.

Every object here is consumed by a live signature; the docstring of each names
the function it replaced and the parameter count it removed. Step F5's first
attempt (2026-09-13, branch `arena/01a09a61-chat-v-bot`) added nine and wired
none: eight had exactly one reference in the whole tree — their own definition —
and `AppendPlanner.append_v2()` was never called, so the metric the step targets
did not move (70 functions over 4 params, worst 20, before *and* after). Unused
code that changes no metric is the `foo_part1` / `foo_part2` shape §16.1.1
forbids, so those eight were dropped.

Two groups of arguments recur through the append path, which is why there are
fewer objects than there were wide functions:

* the **cursor context** (`WriteContext`) — what `_after_write`, `_touch_cursor`,
  `_report_unchanged`, `_same_conversation` and `_prepend` all need to move the
  resume cursor. `AppendPlanner.append` builds it once and passes it down, which
  removed three places that re-derived the same six values.
* the **placed record** (`PlacedRecord`) — one message and where it landed,
  threaded by `_insert_message` into `_collect` and on into `_ui_record`.

`AppendRequest` is deliberately absent: `HistoryRepo.append` and
`AppendPlanner.append` (13 params each) have production callers in
`backend/chat_sync.py`, which the AREA D snapshot freezes, so migrating them is
the §7 option (a) decision rather than a stores/-local one. See
`docs/archive/2026-09-13-round-f/F5_PARAMETER_OBJECTS.md`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Iterable

from stores.history_models import MessageRecord


@dataclass
class WriteContext:
    """What the cursor-refreshing calls need after a write.

    Replaces the 8-parameter signature of `HistoryRepo._after_write` and its
    `PersonLifecycle` implementation, the 6-parameter `_touch_cursor` on both,
    6 of the 7 parameters of `_report_unchanged`, and 5 of the 6 of
    `_same_conversation`. Every call site is inside `stores/`, so nothing
    outside the family changed.

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


@dataclass
class PlacedRecord:
    """One message and the row it landed in.

    Replaces the 5-parameter `ConversationIdentity._ui_record` and the same five
    arguments of `_collect` (6 -> 2) and `_insert_message` (8 -> 4). The bundle
    was already being threaded through all three at six call sites: a record is
    inserted, then collected, then rendered for the UI, and every step needs the
    record, its `ord`, its resolved day, my nick and its media id.
    """

    rec: MessageRecord
    ord_value: int
    day: str
    my_nick: str
    media_id: Optional[int] = None


@dataclass
class SlotSearch:
    """State of the hunt for an empty slot a new payload can fill.

    Replaces 3 of the 5 parameters of `_take_empty_slot` (5 -> 3, with the
    record and its day left explicit because they vary per call while the search
    state does not). `used` accumulates the slot ids already consumed by this
    batch; `rows` of None means "not loaded yet", and the callee loads them on
    first need exactly as the loose `rows=None` default did.
    """

    person_id: int
    used: dict
    rows: Optional[list] = None


@dataclass
class AlignSpec:
    """The inputs to "where does this batch continue the stored conversation".

    Replaces the 5-parameter `AppendPlanner._align`. `align` False means the
    caller is not asking for continuation at all; `expect_idx` of None means
    there is no DOM index to cross-check against.
    """

    batch_keys: list
    cursor: dict
    recs: list
    align: bool
    expect_idx: Optional[int] = None


@dataclass
class RowBatch:
    """The genuinely new lines of one append, oldest first.

    Replaces 7 of the 8 parameters of `AppendPlanner._write_rows` (8 -> 2; the
    `AppendResult` it fills stays a separate argument because it is an output
    accumulator, not part of the batch). `pending` and `days` are parallel lists,
    which is the shape `resolve_days` returns and the loop zips.
    """

    person_id: int
    pending: list
    days: list
    my_nick: str
    nick: str
    session_id: str
    last_ord: int


@dataclass
class PaneSignature:
    """What the visible pane looks like right now, for cursor comparisons.

    Replaces 5 of the 6 parameters of `ConversationIdentity._same_conversation`
    (6 -> 2, the stored `cursor` stays separate because it is the other side of
    the comparison) and 5 of the 8 of its
    `rename_if_same_conversation` (8 -> 4). This is deliberately NOT
    `WriteContext`: a pane comparison has no person and no nick of mine, and
    reusing that object here would mean inventing values for two required
    fields. `dom_count` of -1 means "the caller did not measure the pane".
    """

    head_sig: str
    tail_sig: str
    head_any: str = ""
    tail_any: str = ""
    dom_count: int = -1


@dataclass
class MediaRecoveryRequest:
    """One pass over a person's archive looking for broken media.

    Replaces the 6-parameter `MediaRecovery.recover_media` (6 -> 1) and 4 of
    the 8 parameters of `_RecoveryPass.__init__` (8 -> 4): the pass takes the
    request plus the `stamp` and `marker` its caller has just minted, and
    derives its own `by_key` index from `req.records`. Defaults match the
    signature they replaced exactly, so the frozen `HistoryRepo.recover_media`
    facade can build one without changing what any caller sees.
    """

    person_id: int
    records: list
    media: Optional[dict] = None
    nick: str = ""
    now: Optional[datetime] = None
    requeue_failed: bool = True


@dataclass
class AppendRequest:
    """One archive-append request.

    Replaces the 13-parameter `AppendPlanner.append` and its `HistoryRepo`
    facade twin (13 -> 1) — G7 §2, the stores wide-parameter adjudication
    the F5/G4 freeze blocked. Defaults match the signature it replaced
    exactly, so a caller that passed two positional args and a keyword or
    two keeps working unchanged inside the wrapper; `**cursor_kwargs`
    expansion keeps working because every key it yields is a field here.
    """

    nick: str
    records: Iterable
    my_nick: str = ""
    align: bool = True
    expect_idx: Optional[int] = None
    dom_count: int = 0
    head_sig: Optional[str] = None
    tail_sig: Optional[str] = None
    now: Optional[datetime] = None
    session_id: str = ""
    head_any: Optional[str] = None
    tail_any: Optional[str] = None
    prepend: bool = False


@dataclass
class PrependRequest:
    """One backfill of OLDER lines that appeared above what is stored.

    Replaces the 11-parameter `_prepend` on both `AppendPlanner` and the
    `HistoryRepo` facade. Seven of those eleven were the cursor context, so it
    carries a `WriteContext` rather than repeating its fields — the caller has
    already built one for `_after_write`.
    """

    recs: list
    now: datetime
    session_id: str
    ctx: WriteContext
    nick: str = ""
