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
from datetime import datetime
from typing import Callable, Iterable, Optional

from backend import chat_agent_js
from backend.history_models import (Alignment, MessageRecord,  # noqa: F401
                                    SyncResult)
from backend.history_repo import HistoryRepo, align_batch

log = logging.getLogger("chatbot")


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
                            now: Optional[datetime] = None) -> SyncResult:
    """Bring the archive up to date with what the page currently shows."""
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

    count = int(state.get("count") or 0)
    head_sig = _signature(state.get("head"))
    tail_sig = _signature(state.get("tail"))

    person_id = await repo.ensure_person(nick)
    cursor = await repo.get_cursor(person_id)
    person = await repo.get_person_by_id(person_id) or {}
    result.total = int(person.get("message_count") or 0)

    if count == 0:
        await repo.append(nick, [], my_nick=my_nick, dom_count=0,
                          head_sig=head_sig, tail_sig=tail_sig, now=now)
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
        records = await parser.slice(position, end)
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
        else:
            collected.extend(records)
        result.chunks.append({"from": position, "to": end,
                              "added": result.added})
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
        # anything that appeared ABOVE the part we already knew
        alignment = align([r.fp for r in collected], cursor["tail_fps"])
        if alignment.start and not alignment.gap:
            backfill = await repo.append(nick, collected[:alignment.start],
                                         my_nick=my_nick, prepend=True,
                                         now=now)
            result.added += backfill.added

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
