"""The conversation-sync algorithm, in phases.

`backend.chat_parser` owns the *probes* (one state probe, one range probe, one
drain) and the private-chat gate. This module owns the *decision*: what to
read given what the archive already holds, and what to write back.

    run_sync(parser, repo, nick, options)
      ├─ SyncSession.prepare()      probe → install → gate → viewport → cursor
      ├─ SyncPlanner.plan()         (state, cursor, options) → ReadPlan      [pure]
      ├─ ChunkReader.read()         paced, retrying, stop-aware range reads
      ├─ DeltaAligner.apply()       what appeared ABOVE what we stored
      ├─ SyncPersister.*            every repo.write, in one place
      └─ SyncSession.finish()       final cursor, totals, reason

The split is internal: `backend.chat_parser.sync_conversation()` keeps its
exact 14-parameter signature and delegates here, so `services/collector_service`
and the `COLLECT_HISTORY` block are untouched (plan §7.3.1).

Why the phases are objects and not functions: they share one mutable
`SyncSession` (the page state can change *during* a read — a virtualised pane
that loses its nodes mid-read updates the count and the signatures, and the
final cursor write must reflect what was actually read, not what we hoped for).
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any, Callable, Optional

from backend.chat_text import signature as _signature
from stores.history_models import MAX_LIVE_ITEMS, SyncResult
from stores.history_repo import align_batch

log = logging.getLogger("chatbot")

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


@dataclass(frozen=True, slots=True)
class SyncOptions:
    """The eleven optional knobs of one sync, in one immutable place.

    `backend.chat_parser.sync_conversation()` still takes them as keyword
    arguments (that signature is the public contract of the archive reader);
    this is where they land before the phases read them.
    """

    my_nick: str = ""
    require_private: bool = False
    verify_partner: bool = False
    max_messages: Optional[int] = None
    #: None = "whatever the parser is configured with"
    chunk_pause_ms: Optional[int] = None
    should_stop: Optional[Callable[[], bool]] = None
    on_progress: Optional[Callable[[int, int], None]] = None
    now: Optional[datetime] = None
    backfill_older: bool = False
    backfill_wait_s: float = 2.0
    media: Any = None

    # ── construction from the legacy keyword call ────────────────
    @classmethod
    def from_kwargs(cls, **kwargs) -> "SyncOptions":
        """Build from `sync_conversation`'s keyword arguments.

        Unknown keys are dropped rather than raising: the run engine and the
        collector both forward option dicts that may carry retired keys.
        """
        known = {f.name for f in dataclasses.fields(cls)}
        return cls(**{k: v for k, v in kwargs.items() if k in known})

    def for_parser(self, parser=None, now: Optional[datetime] = None
                   ) -> "SyncOptions":
        """Resolve the two values that depend on the parser/clock."""
        patch: dict = {}
        if self.chunk_pause_ms is None:
            patch["chunk_pause_ms"] = getattr(parser, "chunk_pause_ms", 0) or 0
        patch["chunk_pause_ms"] = max(0, int(patch.get("chunk_pause_ms",
                                                        self.chunk_pause_ms) or 0))
        if self.now is None:
            patch["now"] = now or datetime.now()
        return replace(self, **patch)

    # ── behaviour the phases ask for ─────────────────────────────
    def pause_seconds(self, parser=None) -> float:
        ms = self.chunk_pause_ms
        if ms is None:
            ms = getattr(parser, "chunk_pause_ms", 0) or 0
        return max(0, int(ms or 0)) / 1000.0

    def stopping(self) -> bool:
        """Is the user asking us to stop? A broken predicate says no."""
        predicate = self.should_stop
        if not callable(predicate):
            return False
        try:
            return bool(predicate())
        except Exception:                            # noqa: BLE001
            return False

    def progress(self, done: int, total: int) -> None:
        """RULE 5: report each chunk as it lands — and never let a UI
        hiccup kill the read (RULE 8 of the pipeline: callbacks are wrapped)."""
        if self.on_progress is None:
            return
        try:
            self.on_progress(done, total)
        except Exception:                            # noqa: BLE001
            pass

    def cursor_time(self) -> Optional[datetime]:
        return self.now


@dataclass(frozen=True, slots=True)
class ReadPlan:
    """What `SyncPlanner` decided: the mode, the window, and the signatures."""

    mode: str = MODE_FULL
    count: int = 0
    start: int = 0
    #: True → append per chunk; False → read everything, then align once
    streaming: bool = True
    gap: bool = False
    head_sig: str = ""
    tail_sig: str = ""
    head_any: str = ""
    tail_any: str = ""

    @property
    def delta(self) -> bool:
        return self.mode == MODE_DELTA

    @property
    def is_empty(self) -> bool:
        return self.mode == MODE_EMPTY

    @property
    def signatures(self) -> dict:
        return {"head_sig": self.head_sig, "tail_sig": self.tail_sig,
                "head_any": self.head_any, "tail_any": self.tail_any}

    def cursor_kwargs(self, dom_count: int, *, complete: bool = True) -> dict:
        """The bookkeeping `repo.append([], …)` needs.

        An incomplete read must not advertise a tail: the whole "nothing
        moved" fast path trusts `tail_sig`, and promising it after a partial
        read is how messages get skipped forever.
        """
        return {"dom_count": dom_count, "head_sig": self.head_sig,
                "tail_sig": self.tail_sig if complete else "",
                "head_any": self.head_any,
                "tail_any": self.tail_any if complete else ""}


class SyncPlanner:
    """The decision, as a pure function.

    `plan()` is what makes the delta logic testable without a page: it reads a
    state dict and a cursor dict and returns a :class:`ReadPlan`.
    """

    @staticmethod
    def signature(value) -> str:
        return _signature(value)

    @staticmethod
    def signatures(state: dict) -> dict:
        state = state if isinstance(state, dict) else {}
        return {"head_sig": _signature(state.get("head")),
                "tail_sig": _signature(state.get("tail")),
                "head_any": _signature(state.get("head_any")),
                "tail_any": _signature(state.get("tail_any"))}

    @staticmethod
    def nothing_moved(count: int, head_sig: str, tail_sig: str,
                      cursor: dict) -> bool:
        """The fast path: one cheap probe and no node reads at all.

        Needs all four: we have a stored position, the same number of nodes,
        the same first line and the same last line. A same-count-but-different
        tail means the pane re-rendered something in the middle, which we must
        not mistake for "already stored".
        """
        return bool(cursor.get("bootstrapped")
                    and count == cursor.get("dom_count")
                    and tail_sig and tail_sig == cursor.get("tail_sig")
                    and head_sig == cursor.get("head_sig"))

    @staticmethod
    def is_delta(count: int, head_sig: str, cursor: dict) -> bool:
        """The list only grew at the bottom, so everything before the stored
        `dom_count` is already in the archive."""
        return bool(cursor.get("bootstrapped")
                    and cursor.get("dom_count")
                    and head_sig == cursor.get("head_sig")
                    and count >= int(cursor.get("dom_count") or 0))

    @staticmethod
    def plan(state: dict, cursor: dict, options: Optional[SyncOptions] = None,
             *, count: Optional[int] = None) -> ReadPlan:
        state = state if isinstance(state, dict) else {}
        cursor = cursor if isinstance(cursor, dict) else {}
        options = options or SyncOptions()
        count = int(state.get("count") or 0) if count is None else int(count)
        sigs = SyncPlanner.signatures(state)
        head_sig = sigs["head_sig"]

        if count == 0:
            return ReadPlan(mode=MODE_EMPTY, count=0, start=0, **sigs)
        if SyncPlanner.nothing_moved(count, head_sig, sigs["tail_sig"], cursor):
            return ReadPlan(mode=MODE_UNCHANGED, count=count, start=count,
                            streaming=True, **sigs)

        delta = SyncPlanner.is_delta(count, head_sig, cursor)
        start = int(cursor.get("dom_count") or 0) if delta else 0
        gap = False
        cap = int(options.max_messages or 0)
        if cap and (count - start) > cap:
            start = count - cap
            gap = True
        return ReadPlan(mode=MODE_DELTA if delta else MODE_FULL,
                        count=count, start=start, gap=gap,
                        streaming=delta or not cursor.get("tail_fps"),
                        **sigs)


def merge_live(result: SyncResult, appended, baseline: int = 0) -> None:
    """Keep only the newest records actually inserted for a live UI update.

    `baseline` is the previous archive `last_ord`: rows a backfill prepends
    (they are *older* than everything the user already had) must not be
    pushed through the live-append channel; only rows appended after the
    previous tail belong there.
    """
    for record in (getattr(appended, "records", None) or []):
        if len(result.records) >= MAX_LIVE_ITEMS:
            break
        try:
            ord_value = int(record.get("ord") or 0)
        except (TypeError, ValueError):
            ord_value = 0
        if ord_value <= baseline:
            continue
        result.records.append(record)


class SyncPersister:
    """Every write to the archive, in one place.

    `HistoryRepo` is the only thing that may touch the database, so the sync
    never calls it from two different layers: recovery, gap notes, cursor
    bookkeeping and the "this conversation is fully backfilled" flag all live
    here. Each one is best-effort — a bookkeeping failure must never turn a
    successful read into an exception (RULE 4: an empty/partial result is
    reported as such, not as a crash).
    """

    def __init__(self, session: "SyncSession"):
        self.s = session

    # ── cursor bookkeeping ───────────────────────────────────────
    @staticmethod
    def cursor_kwargs(signatures, dom_count: int, *, complete: bool = True
                      ) -> dict:
        return {"dom_count": dom_count,
                "head_sig": getattr(signatures, "head_sig", ""),
                "tail_sig": (getattr(signatures, "tail_sig", "")
                             if complete else ""),
                "head_any": getattr(signatures, "head_any", ""),
                "tail_any": (getattr(signatures, "tail_any", "")
                             if complete else "")}

    def _cursor_kwargs(self, dom_count: int, *, complete: bool) -> dict:
        return self.cursor_kwargs(self.s, dom_count, complete=complete)

    async def touch(self, dom_count: int, *, complete: bool = True) -> None:
        """Write the read position without appending any record."""
        s = self.s
        await s.repo.append(s.nick, [], my_nick=s.options.my_nick,
                            **self._cursor_kwargs(dom_count, complete=complete),
                            now=s.options.now)

    async def mark_backfilled(self, *, why: str) -> None:
        try:
            await self.s.repo.mark_backfilled(self.s.person_id)
        except Exception as exc:                     # noqa: BLE001
            log.debug("could not mark %s fully backfilled (%s): %s",
                      self.s.nick, why, exc)

    async def empty(self) -> None:
        """An empty pane: store the shape, and only trust "complete" when the
        pane really has nothing to scroll."""
        s, result = self.s, self.s.result
        await self.touch(0)
        scroll = (s.state or {}).get("scroll") or {}
        truly_empty = int(scroll.get("height") or 0) <= 0
        if result.backfilled and truly_empty and not result.stopped:
            await self.mark_backfilled(why="empty pane")

    async def record_cap_gap(self) -> None:
        """`max_messages` trimmed the window: note the hole we left behind."""
        s = self.s
        after = await s.repo._last_ord(s.person_id)
        await s.repo.record_gap(
            s.person_id, after, "capped",
            f"only the newest {int(s.options.max_messages or 0)} messages "
            "were collected")

    # ── records ──────────────────────────────────────────────────
    async def stream_chunk(self, records, position: int, *, first: bool) -> None:
        """Append one chunk as it lands (the delta / first-ever-read path)."""
        s = self.s
        appended = await s.repo.append(
            s.nick, records, my_nick=s.options.my_nick,
            align=first and not s.delta and not s.result.gap,
            expect_idx=position if (s.delta or not first or s.result.gap)
            else None,
            now=s.options.now)
        s.absorb(appended)

    async def write_batch(self, records) -> None:
        """Append a whole re-read, letting the archive align it."""
        s = self.s
        appended = await s.repo.append(s.nick, records,
                                       my_nick=s.options.my_nick, align=True,
                                       now=s.options.now)
        s.absorb(appended)

    async def write_backfill(self, records) -> None:
        """Prepend the lines that appeared ABOVE what we already stored."""
        s = self.s
        appended = await s.repo.append(s.nick, records,
                                       my_nick=s.options.my_nick, prepend=True,
                                       now=s.options.now)
        s.absorb(appended)

    # ── media ────────────────────────────────────────────────────
    async def recover(self, records, *, requeue_failed: bool) -> None:
        s = self.s
        if s.options.media is None or not records:
            return
        try:
            stats = await s.repo.recover_media(
                s.person_id, records, media=s.options.media, nick=s.nick,
                now=s.options.now, requeue_failed=requeue_failed)
        except Exception as exc:                     # noqa: BLE001
            log.debug("media recovery for %s failed: %s", s.nick, exc)
            return
        s.result.media_repaired += int(stats.get("repaired") or 0)
        s.result.media_requeued += int(stats.get("requeued") or 0)

    async def repair_tail(self) -> None:
        """The newest window, after the viewport went back.

        A scroll-to-top pass drops the newest nodes from the DOM, so a broken
        media line at the BOTTOM of the chat never met its DOM record during
        the reads above. One more pass over the tail repairs it — and it also
        runs on ordinary ticks, which is how a media line that rendered after
        its first parse is repaired within one heartbeat instead of never.
        """
        s = self.s
        if s.options.media is None or s.options.stopping():
            return
        try:
            if not await s.repo.has_repairable_media(
                    s.person_id, include_failed=bool(s.options.backfill_older)):
                return
            tail_state = await s.parser.state()
            tail_count = int((tail_state or {}).get("count") or 0)
            if tail_count <= 0:
                return
            window = max(int(s.parser.chunk_size), 80)
            records = await s.parser.slice(max(0, tail_count - window),
                                           tail_count)
            if records:
                await self.recover(records,
                                   requeue_failed=bool(s.options.backfill_older))
        except Exception as exc:                     # noqa: BLE001
            log.debug("tail media recovery for %s failed: %s", s.nick, exc)


class ChunkReader:
    """Read `[start, count)` in paced, retrying chunks.

    Owns the two nested loops (chunk loop × slice retries) so the sync body
    does not. Each chunk goes straight to the :class:`SyncPersister` when the
    read is streaming, or into `session.collected` when the archive has a tail
    we must align against first.
    """

    def __init__(self, session: "SyncSession"):
        self.s = session
        self.persister = session.persister

    async def read(self) -> None:
        s = self.s
        options = s.options
        start, first = s.plan.start, True            # `position` was primed
        while s.position < s.count:
            if options.stopping():
                s.result.stopped = True
                break
            records, end = await self._window(s.position, start)
            if not records:
                break
            s.scanned += len(records)
            await self._sink(records, s.position, first=first)
            s.result.chunks.append({"from": s.position, "to": end,
                                    "added": s.result.added})
            if options.backfill_older:
                await self.persister.recover(records, requeue_failed=True)
            s.position = end
            first = False
            options.progress(s.scanned, max(0, s.count - start))
            await self._pace()

    async def _window(self, position: int, start: int):
        """One slice, retried; may move the window when the page moved."""
        s, end = self.s, min(self.s.count,
                             position + int(self.s.parser.chunk_size))
        for attempt in range(SLICE_RETRIES):
            records = await s.parser.slice(position, end)
            if records:
                return records, end
            if self._may_restore_viewport(position, start, attempt):
                end = await s.restore_viewport(position)
            else:
                await asyncio.sleep(0.2)
        return [], end

    def _may_restore_viewport(self, position: int, start: int,
                              attempt: int) -> bool:
        """Only once, only at the first window of a backfill that never
        settled: the DOM lost the nodes between the settle probe and this
        read, so put the viewport back and look again."""
        s = self.s
        return bool(position == start and s.options.backfill_older
                    and not s.result.backfilled and s.before_count > 0
                    and attempt == 0)

    async def _sink(self, records, position: int, *, first: bool) -> None:
        if self.s.plan.streaming:
            await self.persister.stream_chunk(records, position, first=first)
        else:
            self.s.collected.extend(records)

    async def _pace(self) -> None:
        s = self.s
        if s.position >= s.count:
            return
        pause = s.options.pause_seconds()
        if pause:
            await asyncio.sleep(pause)


class DeltaAligner:
    """Where a freshly read conversation continues the stored one."""

    @staticmethod
    def split(collected, cursor: dict) -> list:
        """The records that belong BEFORE what we already stored.

        Empty unless the alignment found a real overlap: with no shared tail
        there is nothing proving where the batch starts, so everything is
        written as one append and `HistoryRepo` records the gap itself.
        """
        if not collected:
            return []
        tail = (cursor or {}).get("tail_keys") or (cursor or {}).get("tail_fps") \
            or []
        alignment = align_batch([r.dup_key for r in collected], tail)
        if not alignment.start or alignment.gap:
            return []
        return list(collected[:alignment.start])

    async def apply(self, session: "SyncSession") -> None:
        """Write the buffered re-read, then prepend its older prefix."""
        s = session
        if s.plan.streaming or not s.collected:
            return
        await s.persister.write_batch(s.collected)
        older = self.split(s.collected, s.cursor)
        if older:
            await s.persister.write_backfill(older)
        if s.options.backfill_older:
            await s.persister.recover(s.collected, requeue_failed=True)


@dataclass
class SyncSession:
    """The state one sync shares between its phases.

    Not thread-local magic — just the handful of values that the phases agree
    on and that may move while a read is in flight (`count`, the signatures).
    """

    parser: Any
    repo: Any
    nick: str
    options: SyncOptions = field(default_factory=SyncOptions)
    result: SyncResult = field(default=None)          # built in __post_init__

    state: dict = field(default_factory=dict)
    plan: Optional[ReadPlan] = None
    cursor: dict = field(default_factory=dict)
    person_id: int = 0
    live_baseline: int = 0
    before_count: int = 0
    old_top: int = 0
    restored_top: Optional[int] = None
    count: int = 0
    head_sig: str = ""
    tail_sig: str = ""
    head_any: str = ""
    tail_any: str = ""
    scanned: int = 0
    position: int = 0
    collected: list = field(default_factory=list)
    complete: bool = False

    def __post_init__(self):
        self.options = self.options.for_parser(self.parser)
        if self.result is None:
            self.result = SyncResult(ok=True, nick=self.nick,
                                     my_nick=self.options.my_nick)
        self._persister: SyncPersister = SyncPersister(self)

    # ── collaborators ────────────────────────────────────────────
    @property
    def persister(self) -> SyncPersister:
        return self._persister

    @property
    def delta(self) -> bool:
        return bool(self.plan and self.plan.delta)

    def absorb(self, appended) -> None:
        """Fold one `AppendResult` into the outcome the caller sees."""
        self.result.added += getattr(appended, "added", 0) or 0
        self.result.gap = self.result.gap or bool(getattr(appended, "gap", False))
        merge_live(self.result, appended, self.live_baseline)

    # ── the opening phases ───────────────────────────────────────
    async def prepare(self) -> bool:
        """Probe the page, pass the gate, settle the viewport, load the cursor.

        False means the caller must return `result` as it stands (refused or
        broken page) — nothing has been written.
        """
        if not await self._open_page():
            return False
        if not await self._pass_gate():
            return False
        await self._prepare_viewport()
        self._sync_sigs()
        await self._load_archive()
        self.plan = SyncPlanner.plan(self.state, self.cursor, self.options,
                                    count=self.count)
        # the read starts where the plan says: `start` is 0 for a full re-read
        # and the stored `dom_count` (or the trimmed cap) otherwise
        self.position = self.plan.start
        return True

    async def _open_page(self) -> bool:
        state = await self.parser.state() or {}
        if not int(state.get("agent") or 0):
            await self.parser.install()
            state = await self.parser.state()
        self.state = state if isinstance(state, dict) else {}
        if self.state.get("ok", True):
            return True
        self.result.ok = False
        self.result.reason = self.state.get("reason") or "no_agent"
        return False

    async def _pass_gate(self) -> bool:
        """RULE 15: the two-step private-chat gate, before any write.

        `verify_private` is imported here rather than at module top: the gate
        is defined in `backend.chat_parser`, which imports this module for the
        façade — a cycle at load time otherwise.
        """
        from backend.chat_parser import verify_private     # cycle, see above
        from backend.chat_text import norm

        options, state = self.options, self.state
        if options.require_private and state.get("tab") != "private":
            return self._refuse("not_private")
        if options.verify_partner:
            if norm(state.get("partner")) != norm(self.nick):
                return self._refuse("partner_mismatch")
            check = verify_private(state, self.nick, options.my_nick,
                                   require_private=options.require_private)
            if not check.ok:
                return self._refuse(check.reason)
        return True

    def _refuse(self, reason: str) -> bool:
        self.result.ok = False
        self.result.reason = reason
        return False

    async def _prepare_viewport(self) -> None:
        """`backfill_older`: visit the first message, then come back."""
        options = self.options
        self.before_count = int(self.state.get("count") or 0)
        if not options.backfill_older or options.stopping():
            return
        scroll = self.state.get("scroll") or {}
        self.old_top = int(scroll.get("top") or 0)
        moved = await self.parser.scroll_to_top()
        if not (moved or {}).get("ok") or options.stopping():
            return                                   # a page that cannot scroll
        await self._settle_at_top()

    async def _settle_at_top(self) -> None:
        wait = max(float(self.options.backfill_wait_s or 2.0), 4.0)
        try:
            state = await self.parser.settle_after_top(
                self.state, wait_ms=300, stable_polls=3, max_wait_s=wait,
                minimum_count=self.before_count)
        except Exception:                            # noqa: BLE001
            state = await self.parser.state()
        self.state = state if isinstance(state, dict) else self.state
        self._sync_sigs()
        after = self.state.get("scroll") or {}
        post_count = int(self.state.get("count") or 0)
        settled = (bool(after.get("atTop")) and bool(self.state.get("_settled"))
                   and post_count >= self.before_count)
        if settled:
            self.result.backfilled = True
            self.restored_top = self.old_top or None
            return
        if self.before_count > 0 and post_count < self.before_count:
            # The pane emptied while it re-rendered older lines. Put the
            # viewport back and read what is visible now; do NOT mark the
            # full scan complete, so a later tick retries from the top.
            self.result.backfill_pending = True
            await self.restore_viewport()
            fallback = await self.parser.state()
            if int((fallback or {}).get("count") or 0) > 0:
                self.state = fallback
                self._sync_sigs()
        else:
            self.result.backfill_pending = True

    async def restore_viewport(self, position: Optional[int] = None) -> int:
        """Put the conversation back where the user had it.

        Returns the end of the window to retry, so the caller can re-clamp it
        against a count that changed while we were restoring.
        """
        try:
            await self.parser.restore_scroll(self.old_top)
        except Exception:                            # noqa: BLE001
            pass
        state = await self.parser.state()
        count = int((state or {}).get("count") or 0)
        if count <= 0:
            return self._window_end(position)
        self.state = state
        self.count = count
        self.result.count = count
        self._sync_sigs()
        self.result.backfill_pending = True
        return self._window_end(position)

    def _window_end(self, position: Optional[int]) -> int:
        if position is None:
            return self.position
        return min(self.count, position + int(self.parser.chunk_size))

    def _sync_sigs(self) -> None:
        """Re-read the four cursor signatures from the current state."""
        sigs = SyncPlanner.signatures(self.state)
        self.head_sig = sigs["head_sig"]
        self.tail_sig = sigs["tail_sig"]
        self.head_any = sigs["head_any"]
        self.tail_any = sigs["tail_any"]
        self.count = int(self.state.get("count") or 0)
        self.result.count = self.count

    async def _load_archive(self) -> None:
        self.person_id = await self.repo.ensure_person(self.nick)
        self.cursor = await self.repo.get_cursor(self.person_id) or {}
        self.live_baseline = int(self.cursor.get("last_ord") or 0)
        self.result.total = await self.person_total()

    async def person_total(self) -> int:
        person = await self.repo.get_person_by_id(self.person_id) or {}
        return int(person.get("message_count") or 0)

    # ── the closing phases ───────────────────────────────────────
    async def finish_empty(self) -> None:
        await self.persister.empty()
        self.result.reason = "empty"

    async def record_cap_gap(self) -> None:
        if not self.plan.gap:
            return
        self.result.gap = True
        await self.persister.record_cap_gap()

    async def restore_if_needed(self) -> None:
        if self.restored_top is None:
            return
        try:
            await self.parser.restore_scroll(self.restored_top)
        except Exception:                            # noqa: BLE001
            log.debug("could not restore scroll position for %s", self.nick)

    async def finish(self) -> None:
        self.complete = (not self.result.stopped) and self.position >= self.count
        if self.result.backfilled and not self.result.stopped \
                and not self.result.backfill_pending:
            await self.persister.mark_backfilled(why="backfill")
        await self.persister.touch(self.count if self.complete else self.position,
                                   complete=self.complete)
        self.result.total = await self.person_total()
        self.result.scanned = self.scanned
        if not self.result.reason:
            self.result.reason = self._default_reason()

    def _default_reason(self) -> str:
        if self.result.stopped:
            return "stopped"
        return "added" if self.result.added else "no_new"


async def run_sync(parser, repo, nick: str,
                   options: Optional[SyncOptions] = None, **legacy) -> SyncResult:
    """Bring the archive up to date with what the page currently shows.

    `backend.chat_parser.sync_conversation()` is the public entry point and
    forwards its keyword arguments; `options` is the typed seam new callers
    should use.
    """
    session = SyncSession(parser, repo, nick,
                          options or SyncOptions.from_kwargs(**legacy))
    if not await session.prepare():
        return session.result
    if session.plan.is_empty:
        await session.finish_empty()
        return session.result
    if session.plan.mode == MODE_UNCHANGED:
        session.result.reason = "unchanged"
        return session.result
    await session.record_cap_gap()
    await ChunkReader(session).read()
    await DeltaAligner().apply(session)
    await session.restore_if_needed()
    await session.persister.repair_tail()
    await session.finish()
    return session.result
