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
from dataclasses import dataclass, field, replace
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


class CaptureReadError(RuntimeError):
    """An unsuccessful browser probe, not an empty message body."""

    def __init__(self, reason: str, detail: str):
        self.reason = reason
        self.detail = str(detail or reason).splitlines()[0][:400]
        super().__init__(self.detail)


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


def state_signatures(state: dict) -> tuple[str, str]:
    """Include middle-of-chat payload changes without shipping every body."""
    head, tail = _signature(state.get("head")), _signature(state.get("tail"))
    if "content_revision" in state:
        head += "#rev:" + str(state["content_revision"])
    if state.get("content_sig"):
        tail += "#content:" + str(state["content_sig"])
    return head, tail


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
    self_nicks: list = field(default_factory=list)
    identity_source: str = "configured"
    warning: str = ""

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


def self_nick_history(value) -> list[str]:
    """Only explicit nick strings; never learn names from an author payload."""
    if not isinstance(value, (list, tuple, set)):
        return []
    return _distinct([n for n in value if isinstance(n, str)])[:32]


def verify_private(state: dict, nick: str, my_nick: str = "",
                   items=None, require_private: bool = True,
                   known_self_nicks=(), require_two_participants: bool = True) -> PrivateCheck:
    """Two participant identities, including already declared former self names.

    A scoped, two-member browser roster can identify the current self. An
    untrusted/global `me` field or an arbitrary outbound author cannot override
    a configured nickname. Alias declarations come from the caller's config /
    archive metadata, never the incoming push payload.
    """
    state = state if isinstance(state, dict) else {}
    target = " ".join(str(nick or "").split()).strip()
    partner = " ".join(str(state.get("partner") or "").split()).strip()
    title = str(state.get("title") or state.get("partner") or "")
    configured = " ".join(str(my_nick or "").split()).strip()
    if require_private and str(state.get("tab") or "") != "private":
        return PrivateCheck(False, "not_private", "the active tab is not a private chat", configured, partner)
    if not target or not partner:
        return PrivateCheck(False, "no_partner", "the active tab does not name a person", configured, partner)
    if require_private and require_two_participants and "participants" in state:
        try:
            two_people = int(state["participants"]) == 2
        except (TypeError, ValueError):
            two_people = False
        if not two_people:
            return PrivateCheck(False, "participants_mismatch", "the pane does not contain exactly two participants", configured, partner)
    if _norm(partner) != _norm(target) or not title_matches(title, target):
        return PrivateCheck(False, "title_mismatch", f"the active tab is “{title}”, not “{target}”", configured, partner)

    detected = " ".join(str(state.get("me") or "").split()).strip()
    roster = {_norm(n) for n in self_nick_history(state.get("participant_nicks"))}
    scoped_self = (state.get("me_source") == "pane_roster" and
                   str(state.get("participants")) == "2" and detected and
                   _norm(detected) != _norm(target) and
                   roster == {_norm(detected), _norm(target)})
    me = detected if scoped_self else configured
    source = "pane_roster" if scoped_self else "configured"
    if me and _norm(me) == _norm(target):
        return PrivateCheck(False, "self_chat", "the partner is my own nick", me, partner)
    aliases = _distinct([me, configured] + self_nick_history(known_self_nicks))
    aliases = [name for name in aliases if _norm(name) != _norm(target)]
    accepted = {_norm(n) for n in aliases}
    if roster and (len(roster) != 2 or _norm(target) not in roster or
                   not (roster - {_norm(target)}) <= accepted):
        return PrivateCheck(False, "roster_mismatch", "the pane's participant list does not match this private conversation", me, partner)

    if items is not None:
        ins, outs = _authors_from_items(items)
    elif any(k in state for k in ("in_authors", "out_authors", "authors")):
        ins, outs = _distinct(state.get("in_authors")), _distinct(state.get("out_authors"))
        if not ins and not outs:
            everyone = _distinct(state.get("authors"))
            ins = [name for name in everyone if _norm(name) not in accepted]
            outs = [name for name in everyone if _norm(name) in accepted]
    else:
        return PrivateCheck(False, "no_author_data", "this page cannot tell me who wrote what", me, partner)
    if not me and len(outs) == 1 and _norm(outs[0]) != _norm(target):
        # Existing no-configuration fallback: only a single own-side name.
        me, source = outs[0], "single_outbound"
        aliases = _distinct([me] + aliases)
        accepted.add(_norm(me))
    everyone = _distinct(ins + outs)
    strangers = [name for name in everyone if _norm(name) != _norm(target) and _norm(name) not in accepted]
    if strangers:
        detail = ", ".join(strangers[:3]) + ("…" if len(strangers) > 3 else "")
        return PrivateCheck(False, "strangers", f"unrecognized author(s): {detail}", me, partner, strangers,
                            self_nicks=aliases, identity_source=source)
    if not everyone and int(state.get("count") or 0) > 0 and items is None:
        return PrivateCheck(False, "no_author_data", "message authors are not available", me, partner)
    warning = ""
    if scoped_self and configured and _norm(configured) != _norm(me):
        warning = f"Browser self is “{me}”; configured My Nick is “{configured}” (configuration kept)"
    return PrivateCheck(True, "ok", "", me, partner, [], self_nicks=aliases,
                        identity_source=source, warning=warning)


def identify_records(records, identity: PrivateCheck) -> list[MessageRecord]:
    """Preserve sender text; correct historical CSS direction using known identity.

    Some sites style old self messages as inbound after a nickname change.
    Only an already verified self/partner name can be normalized this way.
    """
    own = {_norm(name) for name in identity.self_nicks}
    out = []
    for record in records:
        direction = "out" if _norm(record.from_nick) in own else "in"
        if direction != record.direction:
            record = replace(record, direction=direction, fp="")
            record.ensure_fp()
        out.append(record)
    return out


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
        self.probe_seconds = 0.0
        self.last_capture_diagnostic = {}

    def reset_probe_metrics(self) -> None:
        self.probe_seconds = 0.0

    async def _eval(self, expression: str):
        started = asyncio.get_running_loop().time()
        try:
            return await self.cdp.evaluate(expression)
        finally:
            # Only browser/transport time: retry sleeps, scroll-settle waits,
            # database work and downloads must not inflate browser backoff.
            self.probe_seconds = max(self.probe_seconds,
                                     asyncio.get_running_loop().time() - started)

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

    async def install(self, *, force: bool = False) -> int:
        raw = await self._eval(chat_agent_js.install_expression(force=force))
        try:
            return int(raw or 0)
        except (TypeError, ValueError):
            return 0

    async def ensure_agent(self) -> int:
        """Install the agent if the page lost it (SPA re-render, navigation)."""
        state = await self.state()
        version = int(state.get("agent") or 0)
        if version >= chat_agent_js.AGENT_VERSION:
            return version
        return await self.install()

    async def slice(self, start: int, end: int, *, refresh: bool = False) -> list[MessageRecord]:
        diagnostic = {"from": start, "to": end, "returned": 0, "ready": 0}
        self.last_capture_diagnostic = diagnostic
        try:
            try:
                raw = await self._eval(chat_agent_js.slice_expression(start, end, refresh=refresh))
            except Exception as exc:
                raise CaptureReadError("probe_exception", str(exc)) from exc
            if isinstance(raw, str):
                try:
                    raw = json.loads(raw)
                except (TypeError, ValueError) as exc:
                    raise CaptureReadError("malformed_json", "Message range returned invalid JSON") from exc
            if isinstance(raw, dict):
                if raw.get("ok") is False:
                    raise CaptureReadError("agent_error", raw.get("error") or raw.get("reason") or "Message range probe failed")
                diagnostic["node_count"] = raw.get("count")
                items = raw.get("items")
            else:
                items = raw
            if not isinstance(items, list):
                raise CaptureReadError("invalid_response", "Message range did not return a record list")
            diagnostic["returned"] = len(items)
            try:
                records = parse_records(items)
            except (TypeError, ValueError, AttributeError) as exc:
                raise CaptureReadError("invalid_record", "Message range contains malformed records") from exc
            if len(records) != len(items):
                raise CaptureReadError("invalid_record", "Message range contains unusable records")
            reasons, sources = {}, {}
            for record in records:
                if record.incomplete:
                    reason = record.capture_reason or "payload_empty"
                    reasons[reason] = reasons.get(reason, 0) + 1
                source = record.text_source or "unspecified"
                sources[source] = sources.get(source, 0) + 1
            diagnostic.update(ready=sum(not r.incomplete for r in records),
                              reasons=reasons, sources=sources,
                              reason="range_empty" if not records else "payload_pending" if reasons else "ok")
            return records
        except CaptureReadError as exc:
            diagnostic.update(reason=exc.reason, error=exc.detail)
            raise

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
                               minimum_count: int = 0,
                               should_stop=None) -> dict:
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
            if should_stop and should_stop():
                state["_settled"] = False
                state["_stopped"] = True
                return state
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
                            my_nick: str = "", **kwargs) -> SyncResult:
    """Hold one archive generation across every chunk and media recovery."""
    async with repo.db.operation_lock:
        try:
            if not kwargs.get("backfill_older"):
                return await _sync_conversation(parser, repo, nick, my_nick, **kwargs)

            # The visible chat is the only payload we know is available now.
            # Save it BEFORE scroll-to-top can virtualize/unload it. A failed
            # visible pass must retry in place, not repeat a destructive scroll.
            visible_args = {**kwargs, "backfill_older": False}
            visible = await _sync_conversation(parser, repo, nick, my_nick, **visible_args)
            if not visible.ok or visible.stopped or visible.capture_missing:
                visible.backfill_pending = True
                return visible
            cap = int(kwargs.get("max_messages") or 0)
            if cap and visible.scanned >= cap:
                visible.backfill_pending = True
                return visible
            older_args = dict(kwargs)
            if cap:
                older_args["max_messages"] = cap - visible.scanned
            older = await _sync_conversation(parser, repo, nick, my_nick, **older_args)
            older.added += visible.added
            older.scanned += visible.scanned
            older.text_repaired += visible.text_repaired
            older.media_repaired += visible.media_repaired
            older.media_requeued += visible.media_requeued
            older.count = max(older.count, visible.count)
            older.gap = older.gap or visible.gap
            older.chunks = visible.chunks + older.chunks
            older.capture_diagnostics = (visible.capture_diagnostics + older.capture_diagnostics)[-8:]
            combined = {}
            for row in visible.records + older.records:
                key = row.get("id") or (row.get("ord"), row.get("fp"))
                combined[key] = row
            older.records = list(combined.values())[-MAX_LIVE_ITEMS:]
            if older.ok and not older.stopped and not older.capture_missing and older.added:
                older.reason = "added"
            return older
        except BaseException:
            if repo.db.is_open:
                await repo.db.conn.rollback()
            raise


async def _sync_conversation(parser: ChatParser, repo: HistoryRepo, nick: str,
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
                            media=None, known_self_nicks=(),
                            require_two_participants: bool = True) -> SyncResult:
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
    known_person = await repo.get_person(nick) or {}
    known_self_nicks = _distinct(self_nick_history(known_self_nicks) +
                                 self_nick_history(known_person.get("my_nicks")))

    state = await parser.state()
    if int(state.get("agent") or 0) < chat_agent_js.AGENT_VERSION:
        await parser.install()
        state = await parser.state()
    if int(state.get("agent") or 0) < chat_agent_js.AGENT_VERSION:
        result.ok, result.reason = False, "agent_unavailable"
        return result
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
    if verify_partner or require_private:
        # The two-step gate: nothing is written unless the pane holds only
        # the two of us AND the active tab names this person.
        check = verify_private(state, nick, my_nick,
                               require_private=require_private, known_self_nicks=known_self_nicks,
                               require_two_participants=require_two_participants)
        if not check.ok:
            result.ok, result.reason = False, check.reason
            return result
        my_nick = check.me or my_nick
        result.my_nick = my_nick

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
                    minimum_count=before_count, should_stop=should_stop)
            except Exception:                        # noqa: BLE001
                state = await parser.state()
            if state.get("_stopped"):
                result.stopped = True
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
    head_sig, tail_sig = state_signatures(state)

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
        if restored_top is not None:
            await parser.restore_scroll(restored_top)
        result.reason = "stopped" if result.stopped else "empty"
        return result

    repair_text = await repo.has_missing_text(person_id, force=bool(backfill_older))
    repair_media = media is not None and await repo.has_repairable_media(
        person_id, include_failed=bool(backfill_older))

    # A stable cursor is not proof that all bodies were captured. Manual
    # backfill and pending legacy repairs must get past the idle shortcut.
    if (not backfill_older and not repair_text and not repair_media
            and not state.get("incomplete") and cursor["bootstrapped"]
            and count == cursor["dom_count"]
            and tail_sig and tail_sig == cursor["tail_sig"]
            and head_sig == cursor["head_sig"]):
        result.reason = "unchanged"
        return result

    delta = (not backfill_older and not repair_text and not state.get("incomplete")
             and cursor["bootstrapped"] and cursor["dom_count"]
             and head_sig == cursor["head_sig"]
             and count > cursor["dom_count"])
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
        best = []
        read_error = None
        refreshed = False
        attempts = 0
        for _attempt in range(SLICE_RETRIES):
            if should_stop and should_stop():
                result.stopped = True
                break
            attempts += 1
            try:
                records = await parser.slice(position, end, refresh=_attempt > 0)
                read_error = None
            except CaptureReadError as exc:
                read_error = exc
                records = []
                log.warning("Message read %s DOM %d:%d failed (%s): %s", nick, position, end, exc.reason, exc.detail)
            if verify_partner or require_private:
                live_state = await parser.state()
                gate = verify_private(live_state, nick, my_nick,
                                      require_private=require_private, known_self_nicks=known_self_nicks,
                                      require_two_participants=require_two_participants)
                if gate.ok:
                    gate = verify_private(live_state, nick, my_nick, items=records,
                                          require_private=require_private, known_self_nicks=gate.self_nicks,
                                          require_two_participants=require_two_participants)
                if not gate.ok:
                    result.ok, result.reason = False, gate.reason
                    # Do not scroll the different chat the user switched to.
                    return result
                records = identify_records(records, gate)
            if should_stop and should_stop():
                result.stopped = True
            captured = [r for r in records if not r.incomplete]
            if len(captured) > len(best):
                best = captured
            missing = max(0, end - position - len(captured))
            if records and not missing:
                best = captured
                break
            if _attempt == 0 and read_error is None:
                log.warning("Payload pending for %s at DOM %d:%d (%s); retrying", nick, position, end,
                            parser.last_capture_diagnostic.get("reasons") or "range changed")
            if _attempt == SLICE_RETRIES - 1 or result.stopped:
                break
            if read_error is not None and not refreshed:
                # A stale/broken agent may have a healthy state() but a broken
                # slice(). A same-version no-op install cannot repair that.
                refreshed = True
                try:
                    await parser.install(force=True)
                except Exception as exc:
                    log.warning("Could not refresh capture agent: %s", exc)
            elif (not records and position == start and backfill_older and
                  not result.backfilled and before_count > 0 and _attempt == 0):
                await parser.restore_scroll(old_top)
                fallback = await parser.state()
                if int(fallback.get("count") or 0) > 0:
                    state = fallback
                    count = int(state.get("count") or 0)
                    result.count = count
                    end = min(count, position + parser.chunk_size)
                    head_sig, tail_sig = state_signatures(state)
                    result.backfill_pending = True
            else:
                await asyncio.sleep(0.2)
        records = best
        missing = max(0, end - position - len(records))
        diagnostic = {**parser.last_capture_diagnostic, "attempts": attempts,
                      "agent_refreshed": refreshed, "kept": len(records)}
        result.capture_diagnostics = (result.capture_diagnostics + [diagnostic])[-8:]
        if read_error is not None:
            result.capture_errors += 1
            result.ok = False
            result.error = f"DOM {position}:{end}: {read_error.detail}"
            result.reason = "capture_error"
        if missing:
            result.capture_missing += missing
            result.backfill_pending = True
        if not records:
            result.chunks.append({"from": position, "to": end, "added": 0, "pending": missing})
            position = end
            # Do not let one old/unreadable chunk starve new text after it.
            if not result.stopped and position < count and pause_ms:
                await asyncio.sleep(pause_ms / 1000.0)
            continue
        scanned += len(records)
        if streaming:
            appended = await repo.append(
                nick, records, my_nick=my_nick,
                align=first and not delta and not result.gap,
                expect_idx=position if (delta or not first or result.gap)
                else None,
                now=now)
            result.added += appended.added
            result.text_repaired += appended.text_repaired
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
        result.text_repaired += appended.text_repaired
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
            result.text_repaired += backfill.text_repaired
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

    # Re-read the newest window AFTER restoring a virtualized viewport. It
    # can contain text/media that disappeared during the scroll-to-top pass.
    if not (should_stop and should_stop()) and not result.stopped:
        needs_text = await repo.has_missing_text(person_id, force=bool(backfill_older))
        needs_media = media is not None and await repo.has_repairable_media(
            person_id, include_failed=bool(backfill_older))
        if needs_text or needs_media or (backfill_older and restored_top is not None):
            tail_state = await parser.state()
            tail_count = int(tail_state.get("count") or 0)
            if tail_count > 0:
                try:
                    tail_records = await parser.slice(max(0, tail_count - max(parser.chunk_size, 80)), tail_count, refresh=True)
                except CaptureReadError as exc:
                    tail_records = []
                    result.capture_errors += 1
                    result.ok, result.reason, result.error = False, "capture_error", exc.detail
                    result.backfill_pending = True
                    result.capture_diagnostics = (result.capture_diagnostics + [dict(parser.last_capture_diagnostic)])[-8:]
                safe = bool(tail_records)
                if verify_partner or require_private:
                    live_state = await parser.state()
                    identity = verify_private(live_state, nick, my_nick,
                                              require_private=require_private, known_self_nicks=known_self_nicks,
                                              require_two_participants=require_two_participants)
                    safe = safe and identity.ok
                    if safe:
                        identity = verify_private(live_state, nick, identity.me or my_nick,
                                                  items=tail_records, require_private=require_private,
                                                  known_self_nicks=identity.self_nicks,
                                                  require_two_participants=require_two_participants)
                        safe = identity.ok
                    if safe:
                        tail_records = identify_records(tail_records, identity)
                if safe:
                    captured = [r for r in tail_records if not r.incomplete]
                    if backfill_older and captured:
                        appended = await repo.append(nick, captured, my_nick=my_nick,
                                                     prepend=True, now=now)
                        result.added += appended.added
                        result.text_repaired += appended.text_repaired
                        _merge_live(result, appended, live_baseline)
                    missing = sum(r.incomplete for r in tail_records)
                    if missing:
                        result.capture_missing += missing
                        result.backfill_pending = True
                        log.warning("Tail text/payload not captured for %s; retrying %d line(s)", nick, missing)
                    stats = await repo.recover_text(person_id, tail_records, now=now)
                    result.text_repaired += stats["repaired"]
                    if media is not None:
                        stats = await repo.recover_media(
                            person_id, tail_records, media=media, nick=nick,
                            now=now, requeue_failed=bool(backfill_older))
                        result.media_repaired += int(stats.get("repaired") or 0)
                        result.media_requeued += int(stats.get("requeued") or 0)

    if result.backfilled and result.ok and not result.stopped and not result.backfill_pending:
        try:
            await repo.mark_backfilled(person_id)
        except Exception as e:                       # noqa: BLE001
            log.debug("could not mark %s fully backfilled: %s", nick, e)

    complete = (result.ok and not result.stopped and not result.capture_missing and position >= count)
    await repo.append(nick, [], my_nick=my_nick,
                      dom_count=position if not complete else count,
                      head_sig=head_sig if complete else "",
                      tail_sig=tail_sig if complete else "",
                      now=now)

    person = await repo.get_person_by_id(person_id) or {}
    result.total = int(person.get("message_count") or 0)
    result.scanned = scanned
    if not result.reason:
        result.reason = "stopped" if result.stopped else (
            "capture_pending" if result.capture_missing else (
                "added" if result.added else "repaired" if result.text_repaired else "no_new"))
    return result
