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

The family (Round J step J-7): this module is the public contract — the gate's
entry point (`verify_private`, whose guard ORDER is the contract), `PrivateCheck`
and `title_matches`, the reader/value builders (`align`, `parse_records`), the
`ChatParser` DOM surface and `sync_conversation()`. The gate's decision
machinery is in `backend/chat_parser_gate.py`, the settle policy in
`backend/chat_parser_settle.py`. Both are imported here; neither imports this
module back except through `chat_parser_gate._check()`'s documented local
import of `PrivateCheck`. The API snapshot pins `PrivateCheck`, `title_matches`
and `verify_private` to *this* module, which is why the public half did not
move with the machinery.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Iterable, Optional

from backend import chat_agent_js, chat_text
from backend.chat_parser_gate import (  # noqa: F401  (re-exported: family internals)
    _GateNames, _authors_of, _check, _is_self_chat, _split_authors,
    _strangers_verdict, _tab_gate, _partner_gate, _title_gate,
    _foreign_authors,
)
from backend.chat_parser_settle import SettleMixin
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


def title_matches(title: str, nick: str) -> bool:
    """Step 2: does the active tab title name this person?"""
    want, have = _norm(nick), _norm(title)
    if not want or not have:
        return False
    return have == want or want in have


def verify_private(state: dict, nick: str, my_nick: str = "",
                   query: PrivateQuery = PrivateQuery()) -> PrivateCheck:
    """The gate. `ok` is False unless BOTH steps pass.

    RULE 15: this is the only place the private-chat decision is made, and it
    runs before a single record is written. Each guard keeps its own reason
    code because the run panel shows them to the user verbatim.
    """
    state = state if isinstance(state, dict) else {}
    names = _GateNames.read(state, nick, my_nick)
    # The guard ORDER is part of the contract: the run panel shows whichever
    # reason fired first, so not_private → no_partner → title → self_chat →
    # authors must stay in that sequence.
    refusal = _tab_gate(state, names, query.require_private)
    if refusal is not None:
        return refusal
    refusal = _partner_gate(names)
    if refusal is not None:
        return refusal
    refusal = _title_gate(names)
    if refusal is not None:
        return refusal

    # ── step 1: exactly two nicks ─────────────────────────────────
    authors = _authors_of(state, query.items, names)
    if authors is None:
        return names.refuse("no_author_data",
                            "this page cannot tell me who wrote what")
    return _strangers_verdict(authors, names)


_payload = chat_text.payload


class ChatParser(SettleMixin):
    """Talks to the in-page agent through CDP evaluates.

    The three waiting methods (`settle_after_top`, `_poll_snapshot`,
    `_settle_exit`) come from `SettleMixin`; everything else is below.
    """

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
