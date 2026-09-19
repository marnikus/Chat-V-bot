"""Reading a conversation without re-reading it.

`ChatParser` is the Python side of the in-page agent: a state probe, a range
probe and a drain probe, plus the door to the typed private-chat gate
(`backend.private_gate`; decoded via `backend.probe_results`). `sync_conversation()`
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
from typing import Iterable, Optional

from backend import chat_agent_js, chat_text
from backend.private_gate import PrivateCheck, judge_private, title_matches  # noqa: F401
from backend.probe_results import TabState, decode_tab_state  # noqa: F401
from backend.chat_sync import (  # noqa: F401  (re-exported: the seam, §3.1)
    SLICE_RETRIES, SyncOptions, merge_live as _merge_live, run_sync)
from backend.parser_requests import (  # noqa: F401  (re-exported with the gate)
    PrivateQuery, SettleSpec)
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
_distinct = chat_text.distinct
_authors_from_items = chat_text.authors_from_items


# ── the two-step private-chat gate (bug report of 2026-09-07) ─────
#
# STEP 1  the conversation must contain exactly two nicks: mine and the
#         partner's. A third author means this is not a private chat.
# STEP 2  the ACTIVE tab title must name that same partner.
#
# Both must pass before a single line may be written to that person's
# history. Everything that saves goes through `verify_private()`.

def verify_private(state: dict, nick: str, my_nick: str = "",
                   query: PrivateQuery = PrivateQuery()) -> PrivateCheck:
    """The legacy gate door; decode once and judge typed author evidence.

    Non-dicts still count as an empty state. Malformed author lists now
    explicitly refuse instead of raising or accidentally authorizing a write.
    """
    state = state if isinstance(state, dict) else {}
    return judge_private(decode_tab_state(state), nick, my_nick, query)


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
                               spec: Optional[SettleSpec] = None) -> dict:
        """Poll until the pane is at the top and older lines stopped arriving.

        The chat loads older history asynchronously when it is scrolled up, so
        the collector must wait for the DOM to settle before it reads. A slow
        or virtualised page must not be mistaken for an empty chat: if the
        conversation had messages before the scroll and the DOM loses them
        while it re-renders older lines, `spec.minimum_count` keeps us polling
        until the visible count returns (and stays) above that floor. A page
        that times out reports `_settled=False` so the caller knows the full
        scan is incomplete and must be retried. The knobs travel as one
        `SettleSpec`; None means the defaults.
        """
        spec = spec or SettleSpec()
        floor = max(0, int(spec.minimum_count or 0))
        last_count = int(first_state.get("count") or 0)
        stable = 0
        deadline = asyncio.get_event_loop().time() + spec.max_wait_s
        state = first_state
        while stable < spec.stable_polls:
            state, count, settled = await self._poll_snapshot(floor)
            stable = stable + 1 if settled and count == last_count else 0
            last_count = count
            state["_settled"] = stable >= spec.stable_polls
            done = self._settle_exit(state, stable, spec.stable_polls, deadline)
            if done is not None:
                return done
            await asyncio.sleep(spec.wait_ms / 1000.0)
        state["_settled"] = True
        return state

    async def _poll_snapshot(self, floor: int) -> tuple:
        """One settle poll → (state, visible count, at-top-and-above-floor).

        The count floor is what keeps a slow or virtualised page from being
        mistaken for an empty chat while it re-renders older lines.
        """
        state = await self.state()
        state = state if isinstance(state, dict) else {}
        count = int(state.get("count") or 0)
        scroll = state.get("scroll") or {}
        return state, count, bool(scroll.get("atTop")) and count >= floor

    @staticmethod
    def _settle_exit(state: dict, stable: int, stable_polls: int,
                     deadline: float) -> Optional[dict]:
        """The loop's exit — the state to return — or None to poll again.

        A timeout reports `_settled=False` so the caller knows the full scan
        is incomplete and must be retried.
        """
        if stable >= stable_polls:
            return state
        if asyncio.get_event_loop().time() >= deadline:
            state["_settled"] = False
            return state
        return None

    async def pause(self) -> None:
        if self.chunk_pause_ms:
            await asyncio.sleep(self.chunk_pause_ms / 1000.0)


async def sync_conversation(parser: ChatParser, repo: HistoryRepo, nick: str,
                            options: Optional[SyncOptions] = None) -> SyncResult:
    """Bring the archive up to date with what the page currently shows.

    With `options.backfill_older=True` the pane is first scrolled to its first
    message (and put back after the read). This is the “full history from the
    beginning” path: the in-page virtualiser only keeps recent nodes, so the
    earliest lines visit the DOM only after scrolling up.

    The algorithm itself is in `backend.chat_sync` (see its module docstring
    for the phase map); this signature is the public contract of the archive
    reader and stays put — it is what `services/collector_service` and the
    COLLECT_HISTORY block call. The knobs travel as one typed `SyncOptions`
    (Round G step 4: the gathering this body used to do now happens at the
    call sites, which already knew every value by name); `options=None`
    means all defaults.
    """
    return await run_sync(parser, repo, nick, options)
