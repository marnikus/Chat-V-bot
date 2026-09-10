"""Reading a conversation without re-reading it.

`ChatParser` is the Python side of the in-page agent: a state probe, a range
probe and a drain probe, plus the two-step private-chat gate. `sync_conversation()`
is the algorithm that turns those three into "append only what is new" — it is a
façade over `backend.chat_sync`, which owns the phases (plan → read → align →
persist). This module stays the import site for all of it, so no caller changed
(design doc §3.1).

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

from backend import chat_agent_js, chat_text
from backend.chat_sync import (  # noqa: F401  (re-exported: the seam, §3.1)
    SLICE_RETRIES, SyncOptions, merge_live as _merge_live, run_sync)
from stores.history_models import (MAX_LIVE_ITEMS, Alignment,  # noqa: F401
                                    AppendResult,  # noqa: F401
                                    MessageRecord,  # noqa: F401
                                    SyncResult)
from stores.history_repo import HistoryRepo, align_batch

log = logging.getLogger("chatbot")

def align(dom_fps, tail_fps) -> Alignment:
    """Where a freshly read conversation continues the stored one."""
    return align_batch(dom_fps, tail_fps)


def parse_records(raw: Iterable) -> list[MessageRecord]:
    """Normalise what the agent produced; drop anything unusable.

    Accepts the agent's two answer shapes — a bare list of records or
    the `{ok, items}` envelope (via `_payload`). Passing the envelope
    used to iterate the dict's KEYS and silently drop every record.
    """
    if isinstance(raw, dict):
        raw = _payload(raw)
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


# ── shared text helpers (design doc §3.1) ─────────────────────────
# `_signature` / `_norm` / `_payload` / … stay importable from here: the
# collector's live-status fast path uses `_signature`, and the module was the
# only documented home for these names. Their behaviour is unchanged — only the
# file they live in moved, so that `backend.chat_sync` can use them without
# importing this module back (it is the one module that imports chat_sync).
_signature = chat_text.signature
_norm = chat_text.norm


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


_distinct = chat_text.distinct
_authors_from_items = chat_text.authors_from_items


def title_matches(title: str, nick: str) -> bool:
    """Step 2: does the active tab title name this person?"""
    want, have = _norm(nick), _norm(title)
    if not want or not have:
        return False
    return have == want or want in have


@dataclass(frozen=True)
class _GateNames:
    """The five nicks the gate compares, each normalised exactly once.

    The page hands these over in whatever shape its DOM had them — padded,
    doubled spaces, non-strings — and every comparison below (and every
    message shown to the user) must use the same collapse, or a nick that
    reads fine to a human refuses its own chat.
    """

    target: str = ""          # the person we think we are collecting
    partner: str = ""         # the nick the page says we are talking to
    title: str = ""           # the raw ACTIVE TAB title
    me_cfg: str = ""          # My Nick from the settings
    me_state: str = ""        # the pane's own user list

    @classmethod
    def read(cls, state: dict, nick: str, my_nick: str) -> "_GateNames":
        clean = chat_text.clean
        return cls(target=clean(nick),
                   partner=clean(state.get("partner")),
                   title=str(state.get("title") or state.get("partner") or ""),
                   me_cfg=clean(my_nick),
                   me_state=clean(state.get("me")))

    @property
    def effective_me(self) -> str:
        # the pane's own user list is the authoritative "me": a configured My
        # Nick can go stale when the user renames themselves on the site, and
        # the stale value must not make this gate refuse the chat (2026-09-08)
        return self.me_cfg or self.me_state

    def refuse(self, reason: str, detail: str) -> "PrivateCheck":
        return PrivateCheck(False, reason, detail, self.me_cfg, self.partner)


def _is_self_chat(names: _GateNames) -> bool:
    """Writing to your own chat can look like a perfect conversation."""
    effective = names.effective_me
    return bool(effective and _norm(effective) == _norm(names.target)
                and (not names.me_state
                     or _norm(names.me_state) == _norm(names.target)))


def _split_authors(state: dict, names: _GateNames) -> tuple:
    """Some pages report only one flat `authors` list — guess the sides."""
    everyone = _distinct(state.get("authors"))
    ins = [a for a in everyone
           if _norm(a) != _norm(names.effective_me or names.target)]
    outs = [a for a in everyone if _norm(a) == _norm(names.effective_me)]
    return ins, outs


def _authors_of(state: dict, items, names: _GateNames) -> Optional[tuple]:
    """Step 1's raw material: (inbound, outbound) authors, or None when the
    page cannot tell who wrote what."""
    if items is not None:
        return _authors_from_items(items)
    if not ("in_authors" in state or "out_authors" in state
            or "authors" in state):
        return None
    ins = _distinct(state.get("in_authors"))
    outs = _distinct(state.get("out_authors"))
    return (ins, outs) if (ins or outs) else _split_authors(state, names)


def _foreign_authors(outs, names: _GateNames) -> tuple:
    """Who wrote outbound lines that is neither me nor my partner.

    "Me" is often undetectable — the page does not always label my own
    messages — so a single outbound author is taken to be me (that is the
    `me` the caller reports back); more than one, and we cannot tell, so all
    of them count as strangers.
    """
    me = names.me_cfg or names.me_state or (outs[0] if len(outs) == 1 else "")
    if me:
        return me, [a for a in outs
                    if _norm(a) != _norm(me)
                    and _norm(a) != _norm(names.me_state)
                    and _norm(a) != _norm(names.target)]
    return me, list(outs) if len(outs) > 1 else []


def verify_private(state: dict, nick: str, my_nick: str = "",
                   items=None, require_private: bool = True) -> PrivateCheck:
    """The gate. `ok` is False unless BOTH steps pass.

    RULE 15: this is the only place the private-chat decision is made, and it
    runs before a single record is written. Each guard keeps its own reason
    code because the run panel shows them to the user verbatim.
    """
    state = state if isinstance(state, dict) else {}
    names = _GateNames.read(state, nick, my_nick)
    if require_private and str(state.get("tab") or "") != "private":
        return names.refuse("not_private",
                            "the active tab is not a private chat")
    if not names.target or not names.partner:
        return names.refuse("no_partner",
                            "the active tab does not name a person")
    # ── step 2: the tab title ─────────────────────────────────────
    if not title_matches(names.title, names.target):
        return names.refuse(
            "title_mismatch",
            f"the active tab is “{chat_text.clean(names.title)}”, "
            f"not “{names.target}”")
    if _is_self_chat(names):
        return names.refuse("self_chat", "the partner is my own nick")

    # ── step 1: exactly two nicks ─────────────────────────────────
    authors = _authors_of(state, items, names)
    if authors is None:
        return names.refuse("no_author_data",
                            "this page cannot tell me who wrote what")
    ins, outs = authors
    me, foreign = _foreign_authors(outs, names)
    strangers = _distinct([a for a in ins
                           if _norm(a) != _norm(names.target)] + foreign)
    if not strangers:
        return PrivateCheck(True, "ok", "", me, names.partner, [])
    shown = ", ".join(strangers[:3]) + ("…" if len(strangers) > 3 else "")
    return PrivateCheck(False, "strangers",
                        f"other people write here: {shown}",
                        me, names.partner, strangers)


_payload = chat_text.payload


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

    The algorithm itself is in `backend.chat_sync` (see its module docstring
    for the phase map); this signature is the public contract of the archive
    reader and stays put — it is what `services/collector_service` and the
    COLLECT_HISTORY block call. The keyword arguments are gathered into a
    `SyncOptions` and handed to `run_sync()`, which returns the same
    `SyncResult` this function always returned.
    """
    options = SyncOptions.from_kwargs(
        my_nick=my_nick, require_private=require_private,
        verify_partner=verify_partner, max_messages=max_messages,
        chunk_pause_ms=chunk_pause_ms, should_stop=should_stop,
        on_progress=on_progress, now=now, backfill_older=backfill_older,
        backfill_wait_s=backfill_wait_s, media=media)
    return await run_sync(parser, repo, nick, options)
