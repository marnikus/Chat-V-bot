"""Reading a conversation without re-reading it.

`ChatParser` is the Python side of the in-page agent: a state probe, a range
probe and a drain probe. `sync_conversation()` is the algorithm that turns
those three into "append only what is new":

    state()                     one cheap probe
      │  nothing changed        → done, ZERO node reads
      │  head unchanged, longer → read [dom_count, count)      (delta)
      └─ anything else          → read the visible range and let the
                                  archive align it, backfilling anything
                                  that appeared ABOVE what we stored

Chunked reads are paced and interruptible, so a 3000-message bootstrap never
blocks the UI and stops promptly when the user says stop (RULE 7).
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Iterable, Optional

from backend import chat_agent_js
from backend.history_models import (MAX_LIVE_ITEMS, Alignment,  # noqa: F401
                                    MessageRecord,  # noqa: F401
                                    SyncResult)
from backend.history_repo import HistoryRepo, align_batch

log = logging.getLogger("chatbot")

#: A virtualised pane can drop its message nodes between a state() probe and
#: the slice() that follows. Do not archive "0" on the first read — retry the
#: range a few times (and restore the viewport once) before giving up.
SLICE_RETRIES = 4


def align(dom_fps, tail_fps) -> Alignment:
    """Where a freshly read conversation continues the stored one."""
    return align_batch(dom_fps, tail_fps)


def parse_records(raw: Iterable) -> list[MessageRecord]:
    """Normalise what the agent produced; drop anything unusable."""
    out: list[MessageRecord] = []
    for item in raw or []:
        if not isinstance(item, dict):
            continue
        if not (item.get("fp") or item.get("text") or item.get("media")):
            continue
        try:
            out.append(MessageRecord.from_dict(item))
        except Exception as e:                        # noqa: BLE001
            log.debug("skipping unparseable record: %s", e)
    return out


def _signature(value) -> str:
    if isinstance(value, (list, tuple)):
        return "|".join(str(v) for v in value)
    return str(value or "")


def _norm(nick: str) -> str:
    return " ".join(str(nick or "").split()).strip().lower()


def _merge_live(result: SyncResult, appended: AppendResult,
                baseline: int = 0) -> None:
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


# ── the two-step private-chat gate (bug report of 2026-09-07) ─────
#
# STEP 1  the conversation must contain exactly two nicks: mine and the
#         partner's. A third author means this is not a private chat.
# STEP 2  the ACTIVE tab title must name that same partner.
#
# Both must pass before a single line may be written to that person's
# history. Everything that saves goes through `verify_private()`.

@dataclass
class PrivateCheck:
    ok: bool = True
    reason: str = "ok"          # ok|not_private|no_partner|title_mismatch|
    #                             self_chat|strangers|no_author_data
    detail: str = ""            # human text for the status window
    me: str = ""                # my nick, detected when it was not configured
    partner: str = ""           # the nick the page says we are talking to
    strangers: list = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.ok)


def _distinct(names) -> list:
    out = []
    for name in names or []:
        clean = " ".join(str(name or "").split()).strip()
        if clean and clean not in out:
            out.append(clean)
    return out


def _authors_from_items(items) -> tuple:
    """Split a batch of records into (inbound nicks, outbound nicks)."""
    ins, outs = [], []
    for item in items or []:
        if isinstance(item, MessageRecord):
            direction = item.direction
            nick = item.from_nick
        elif isinstance(item, dict):
            direction = item.get("dir") or item.get("direction") or "in"
            nick = item.get("from") or item.get("from_nick") or ""
        else:
            continue
        (outs if direction == "out" else ins).append(nick)
    return _distinct(ins), _distinct(outs)


def title_matches(title: str, nick: str) -> bool:
    """Step 2: does the active tab title name this person?"""
    want, have = _norm(nick), _norm(title)
    if not want or not have:
        return False
    return have == want or want in have


def verify_private(state: dict, nick: str, my_nick: str = "",
                   items=None, require_private: bool = True) -> PrivateCheck:
    """The gate. `ok` is False unless BOTH steps pass."""
    state = state if isinstance(state, dict) else {}
    target = " ".join(str(nick or "").split()).strip()
    partner = " ".join(str(state.get("partner") or "").split()).strip()
    title = str(state.get("title") or state.get("partner") or "")
    me_cfg = " ".join(str(my_nick or "").split()).strip()

    if require_private and str(state.get("tab") or "") != "private":
        return PrivateCheck(False, "not_private",
                            "the active tab is not a private chat",
                            me_cfg, partner)
    if not target or not partner:
        return PrivateCheck(False, "no_partner",
                            "the active tab does not name a person",
                            me_cfg, partner)
    # ── step 2: the tab title ─────────────────────────────────────
    if not title_matches(title, target):
        return PrivateCheck(
            False, "title_mismatch",
            f"the active tab is “{' '.join(str(title).split())}”, "
            f"not “{target}”", me_cfg, partner)
    if me_cfg and _norm(me_cfg) == _norm(target):
        return PrivateCheck(False, "self_chat",
                            "the partner is my own nick", me_cfg, partner)

    # ── step 1: exactly two nicks ─────────────────────────────────
    if items is not None:
        ins, outs = _authors_from_items(items)
    elif ("in_authors" in state or "out_authors" in state
            or "authors" in state):
        ins = _distinct(state.get("in_authors"))
        outs = _distinct(state.get("out_authors"))
        if not ins and not outs:
            everyone = _distinct(state.get("authors"))
            ins = [a for a in everyone if _norm(a) != _norm(me_cfg or target)]
            outs = [a for a in everyone if _norm(a) == _norm(me_cfg)]
    else:
        return PrivateCheck(False, "no_author_data",
                            "this page cannot tell me who wrote what",
                            me_cfg, partner)

    me = me_cfg or (outs[0] if len(outs) == 1 else "")
    strangers = [a for a in ins if _norm(a) != _norm(target)]
    if me:
        strangers += [a for a in outs
                      if _norm(a) != _norm(me) and _norm(a) != _norm(target)]
    elif len(outs) > 1:
        strangers += list(outs)
    strangers = _distinct(strangers)
    if strangers:
        shown = ", ".join(strangers[:3]) + ("…" if len(strangers) > 3 else "")
        return PrivateCheck(False, "strangers",
                            f"other people write here: {shown}",
                            me, partner, strangers)
    return PrivateCheck(True, "ok", "", me, partner, [])


def _payload(result) -> list:
    """Agent probes may answer with a bare list or `{ok, items}`."""
    if result is None:
        return []
    if isinstance(result, str):
        try:
            result = json.loads(result)
        except (TypeError, ValueError):
            return []
    if isinstance(result, dict):
        return list(result.get("items") or [])
    if isinstance(result, list):
        return result
    return []


class ChatParser:
    """Talks to the in-page agent through CDP evaluates."""

    def __init__(self, cdp, chunk_size: int = 80, chunk_pause_ms: int = 40):
        self.cdp = cdp
        self.chunk_size = max(1, int(chunk_size))
        self.chunk_pause_ms = max(0, int(chunk_pause_ms))

    async def _eval(self, expression: str):
        return await self.cdp.evaluate(expression)

    async def state(self) -> dict:
        """One small probe: shape of the conversation, not its content."""
        raw = await self._eval(chat_agent_js.state_expression())
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except (TypeError, ValueError):
                raw = None
        if not isinstance(raw, dict):
            return {"ok": False, "agent": 0, "reason": "no answer",
                    "tab": "none", "partner": "", "me": "", "participants": 0,
                    "count": 0, "head": [], "tail": [], "pending": 0}
        return raw

    async def install(self) -> int:
        raw = await self._eval(chat_agent_js.install_expression())
        try:
            return int(raw or 0)
        except (TypeError, ValueError):
            return 0

    async def ensure_agent(self) -> int:
        """Install the agent if the page lost it (SPA re-render, navigation)."""
        state = await self.state()
        version = int(state.get("agent") or 0)
        if version:
            return version
        return await self.install()

    async def slice(self, start: int, end: int) -> list[MessageRecord]:
        raw = await self._eval(chat_agent_js.slice_expression(start, end))
        return parse_records(_payload(raw))

    async def drain(self) -> list[MessageRecord]:
        raw = await self._eval(chat_agent_js.drain_expression())
        return parse_records(_payload(raw))

    async def scroll_to_top(self) -> dict:
        """Scroll the active conversation pane to its first message."""
        raw = await self._eval(chat_agent_js.scroll_top_expression())
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except (TypeError, ValueError):
                raw = {}
        return raw if isinstance(raw, dict) else {}

    async def restore_scroll(self, top: int) -> dict:
        """Put the conversation back where the user had it."""
        try:
            raw = await self._eval(chat_agent_js.restore_scroll_expression(top))
        except Exception:                            # noqa: BLE001
            return {"ok": False}
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except (TypeError, ValueError):
                raw = {}
        return raw if isinstance(raw, dict) else {}

    async def settle_after_top(self, first_state: dict,
                               wait_ms: int = 300,
                               stable_polls: int = 3,
                               max_wait_s: float = 6.0,
                               minimum_count: int = 0) -> dict:
        """Poll until the pane is at the top and older lines stopped arriving.

        The chat loads older history asynchronously when it is scrolled up, so
        the collector must wait for the DOM to settle before it reads. A slow
        or virtualised page must not be mistaken for an empty chat: if the
        conversation had messages before the scroll and the DOM loses them
        while it re-renders older lines, `minimum_count` keeps us polling until
        the visible count returns (and stays) above that floor. A page that
        times out reports `_settled=False` so the caller knows the full scan
        is incomplete and must be retried.
        """
        floor = max(0, int(minimum_count or 0))
        last_count = int(first_state.get("count") or 0)
        stable = 0
        deadline = asyncio.get_event_loop().time() + max_wait_s
        state = first_state
        while stable < stable_polls:
            state = await self.state()
            state = state if isinstance(state, dict) else {}
            scroll = state.get("scroll") or {}
            count = int(state.get("count") or 0)
            settled = bool(scroll.get("atTop")) and count >= floor
            if settled and count == last_count:
                stable += 1
            else:
                stable = 0
            last_count = count
            state["_settled"] = stable >= stable_polls
            if stable >= stable_polls:
                return state
            if asyncio.get_event_loop().time() >= deadline:
                state["_settled"] = False
                return state
            await asyncio.sleep(wait_ms / 1000.0)
        state["_settled"] = True
        return state

    async def pause(self) -> None:
        if self.chunk_pause_ms:
            await asyncio.sleep(self.chunk_pause_ms / 1000.0)


async def sync_conversation(parser: ChatParser, repo: HistoryRepo, nick: str,
                            my_nick: str = "",
                            require_private: bool = False,
                            verify_partner: bool = False,
                            max_messages: Optional[int] = None,
                            chunk_pause_ms: Optional[int] = None,
                            should_stop: Optional[Callable[[], bool]] = None,
                            on_progress: Optional[Callable[[int, int], None]] = None,
                            now: Optional[datetime] = None,
                            backfill_older: bool = False,
                            backfill_wait_s: float = 2.0,
                            media=None) -> SyncResult:
    """Bring the archive up to date with what the page currently shows.

    With `backfill_older=True` the pane is first scrolled to its first message
    (and put back after the read). This is the “full history from the
    beginning” path: the in-page virtualiser only keeps recent nodes, so the
    earliest lines visit the DOM only after scrolling up.
    """
    now = now or datetime.now()
    pause_ms = parser.chunk_pause_ms if chunk_pause_ms is None \
        else max(0, int(chunk_pause_ms))
    result = SyncResult(ok=True, nick=nick, my_nick=my_nick)

    state = await parser.state()
    if not int(state.get("agent") or 0):
        await parser.install()
        state = await parser.state()
    if not state.get("ok", True):
        result.ok = False
        result.reason = state.get("reason") or "no_agent"
        return result
    if require_private and state.get("tab") != "private":
        result.ok, result.reason = False, "not_private"
        return result
    if verify_partner and _norm(state.get("partner")) != _norm(nick):
        result.ok, result.reason = False, "partner_mismatch"
        return result
    if verify_partner:
        # The two-step gate: nothing is written unless the pane holds only
        # the two of us AND the active tab names this person.
        check = verify_private(state, nick, my_nick,
                               require_private=require_private)
        if not check.ok:
            result.ok, result.reason = False, check.reason
            return result

    restored_top = None
    backfill_pending = False
    before_count = int(state.get("count") or 0)
    if backfill_older and not (should_stop and should_stop()):
        scroll = state.get("scroll") or {}
        old_top = int(scroll.get("top") or 0)
        got = await parser.scroll_to_top()
        if got.get("ok") and not (should_stop and should_stop()):
            try:
                state = await parser.settle_after_top(
                    state, wait_ms=300, stable_polls=3,
                    max_wait_s=max(float(backfill_wait_s or 2.0), 4.0),
                    minimum_count=before_count)
            except Exception:                        # noqa: BLE001
                state = await parser.state()
            after = state.get("scroll") or {}
            post_count = int(state.get("count") or 0)
            settled = bool(after.get("atTop")) and \
                bool(state.get("_settled")) and post_count >= before_count
            if settled:
                result.backfilled = True
                restored_top = old_top if old_top else None
            elif before_count > 0 and post_count < before_count:
                # Scroll-to-top emptied (or virtualised away) the active
                # pane before older history re-rendered. Put the viewport
                # back and read the window we can see now; do NOT mark the
                # full scan complete so a later tick retries from the top.
                backfill_pending = True
                try:
                    await parser.restore_scroll(old_top)
                except Exception:                    # noqa: BLE001
                    pass
                fallback = await parser.state()
                if int(fallback.get("count") or 0) > 0:
                    state = fallback
            else:
                backfill_pending = True
                result.backfill_pending = True
        # a page that cannot scroll falls through to the normal visible range
    result.backfill_pending = bool(result.backfill_pending or backfill_pending)

    count = int(state.get("count") or 0)
    result.count = count
    head_sig = _signature(state.get("head"))
    tail_sig = _signature(state.get("tail"))

    person_id = await repo.ensure_person(nick)
    cursor = await repo.get_cursor(person_id)
    live_baseline = int(cursor.get("last_ord") or 0)
    person = await repo.get_person_by_id(person_id) or {}
    result.total = int(person.get("message_count") or 0)

    if count == 0:
        await repo.append(nick, [], my_nick=my_nick, dom_count=0,
                          head_sig=head_sig, tail_sig=tail_sig, now=now)
        scroll = state.get("scroll") or {}
        # A truly empty conversation has no scrollable body. If the pane still
        # reports height there were (or could be) messages that the current
        # probe did not see — do NOT mark the full scan complete, so a later
        # tick tries again instead of silently keeping the archive at zero.
        truly_empty = int(scroll.get("height") or 0) <= 0
        if result.backfilled and truly_empty and not result.stopped:
            try:
                await repo.mark_backfilled(person_id)
            except Exception as e:                   # noqa: BLE001
                log.debug("could not mark %s fully backfilled: %s", nick, e)
        result.reason = "empty"
        return result

    # ── nothing moved: the whole point of the design ──────────────
    if (cursor["bootstrapped"] and count == cursor["dom_count"]
            and tail_sig and tail_sig == cursor["tail_sig"]
            and head_sig == cursor["head_sig"]):
        result.reason = "unchanged"
        return result

    delta = (cursor["bootstrapped"] and cursor["dom_count"]
             and head_sig == cursor["head_sig"]
             and count >= cursor["dom_count"])
    start = int(cursor["dom_count"]) if delta else 0

    if max_messages and (count - start) > int(max_messages):
        start = count - int(max_messages)
        result.gap = True
        await repo.record_gap(person_id, await repo._last_ord(person_id),
                              "capped",
                              f"only the newest {int(max_messages)} messages "
                              "were collected")

    streaming = delta or not cursor["tail_fps"]
    collected: list[MessageRecord] = []
    scanned = 0
    position = start
    first = True

    while position < count:
        if should_stop and should_stop():
            result.stopped = True
            break
        end = min(count, position + parser.chunk_size)
        records = []
        for _attempt in range(SLICE_RETRIES):
            records = await parser.slice(position, end)
            if records:
                break
            # The settle probe reported count=count, then the DOM lost the
            # nodes between probes (a virtualised pane re-rendering). Do not
            # give up and save nothing: restore the viewport, take the state
            # again, and retry the same range a few times.
            if (position == start and backfill_older and
                    not result.backfilled and before_count > 0 and
                    _attempt == 0):
                try:
                    await parser.restore_scroll(old_top)
                except Exception:                    # noqa: BLE001
                    pass
                fallback = await parser.state()
                if int(fallback.get("count") or 0) > 0:
                    state = fallback
                    count = int(state.get("count") or 0)
                    result.count = count
                    end = min(count, position + parser.chunk_size)
                    head_sig = _signature(state.get("head"))
                    tail_sig = _signature(state.get("tail"))
                    result.backfill_pending = True
            else:
                await asyncio.sleep(0.2)
        if not records:
            break
        scanned += len(records)
        if streaming:
            appended = await repo.append(
                nick, records, my_nick=my_nick,
                align=first and not delta and not result.gap,
                expect_idx=position if (delta or not first or result.gap)
                else None,
                now=now)
            result.added += appended.added
            result.gap = result.gap or appended.gap
            _merge_live(result, appended, live_baseline)
        else:
            collected.extend(records)
        result.chunks.append({"from": position, "to": end,
                              "added": result.added})
        if backfill_older and media is not None and records:
            try:
                stats = await repo.recover_media(
                    person_id, records, media=media, nick=nick, now=now,
                    requeue_failed=True)
                result.media_repaired += int(stats.get("repaired") or 0)
                result.media_requeued += int(stats.get("requeued") or 0)
            except Exception as e:                    # noqa: BLE001
                log.debug("media recovery for %s failed: %s", nick, e)
        position = end
        first = False
        if on_progress:
            try:
                on_progress(scanned, max(0, count - start))
            except Exception:                          # noqa: BLE001
                pass
        if position < count and pause_ms:
            await asyncio.sleep(pause_ms / 1000.0)

    if not streaming and collected:
        appended = await repo.append(nick, collected, my_nick=my_nick,
                                     align=True, now=now)
        result.added += appended.added
        result.gap = result.gap or appended.gap
        _merge_live(result, appended, live_baseline)
        # anything that appeared ABOVE the part we already knew
        tail = cursor.get("tail_keys") or cursor.get("tail_fps") or []
        alignment = align([r.dup_key for r in collected], tail)
        if alignment.start and not alignment.gap:
            backfill = await repo.append(nick, collected[:alignment.start],
                                         my_nick=my_nick, prepend=True,
                                         now=now)
            result.added += backfill.added
            _merge_live(result, backfill, live_baseline)
        if backfill_older and media is not None and collected:
            try:
                stats = await repo.recover_media(
                    person_id, collected, media=media, nick=nick, now=now,
                    requeue_failed=True)
                result.media_repaired += int(stats.get("repaired") or 0)
                result.media_requeued += int(stats.get("requeued") or 0)
            except Exception as e:                    # noqa: BLE001
                log.debug("media recovery for %s failed: %s", nick, e)

    if restored_top is not None:
        try:
            await parser.restore_scroll(restored_top)
        except Exception:                            # noqa: BLE001
            log.debug("could not restore scroll position for %s", nick)

    # ── the newest messages' media (Bug #2, 2026-09-07) ───────────
    # A scroll-to-top pass (and any virtualised pane) drops the newest nodes
    # from the DOM, so a broken media line at the BOTTOM of the chat never
    # met its DOM record during the reads above. If anything is still
    # repairable, read the newest window — after the viewport was put back —
    # and run one more recovery pass over it. This also runs on ordinary
    # ticks, which is how a media line that rendered after its first parse
    # is repaired within one heartbeat instead of never.
    if media is not None and not (should_stop and should_stop()):
        try:
            if await repo.has_repairable_media(
                    person_id, include_failed=bool(backfill_older)):
                tail_state = await parser.state()
                tail_count = int(tail_state.get("count") or 0)
                if tail_count > 0:
                    window = max(parser.chunk_size, 80)
                    tail_records = await parser.slice(
                        max(0, tail_count - window), tail_count)
                    if tail_records:
                        stats = await repo.recover_media(
                            person_id, tail_records, media=media, nick=nick,
                            now=now, requeue_failed=bool(backfill_older))
                        result.media_repaired += int(stats.get("repaired")
                                                     or 0)
                        result.media_requeued += int(stats.get("requeued")
                                                     or 0)
        except Exception as e:                        # noqa: BLE001
            log.debug("tail media recovery for %s failed: %s", nick, e)

    if result.backfilled and not result.stopped and not result.backfill_pending:
        try:
            await repo.mark_backfilled(person_id)
        except Exception as e:                       # noqa: BLE001
            log.debug("could not mark %s fully backfilled: %s", nick, e)

    complete = (not result.stopped) and position >= count
    await repo.append(nick, [], my_nick=my_nick,
                      dom_count=position if not complete else count,
                      head_sig=head_sig,
                      tail_sig=tail_sig if complete else "",
                      now=now)

    person = await repo.get_person_by_id(person_id) or {}
    result.total = int(person.get("message_count") or 0)
    result.scanned = scanned
    if not result.reason:
        result.reason = "stopped" if result.stopped else (
            "added" if result.added else "no_new")
    return result
