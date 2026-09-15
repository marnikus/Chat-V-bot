"""The settle policy: when has the pane finished loading older messages?

Part of the `chat_parser` family (public entry point: `backend/chat_parser.py`,
Round J step J-7). Scrolling a conversation to its first message makes the page
load older history asynchronously, so the collector has to wait for the DOM to
settle before it reads — and a slow or virtualised page must not be mistaken
for an empty chat.

Three methods, one job: `settle_after_top` is the loop the caller awaits,
`_poll_snapshot` reads one snapshot and answers (state, visible count,
at-top-and-above-the-floor), and `_settle_exit` is the loop's exit — including
the timeout that reports `_settled=False`, which is how the caller learns the
full scan is incomplete and must be retried. The count floor is what keeps a
virtualised re-render from looking like an empty chat.

They are a mixin rather than module functions because `settle_after_top` is a
public method of `ChatParser` in the API snapshot: moving it into a base keeps
the same signature and the same callable, which is the drift the snapshot
explicitly models (`inherited`). `ChatParser` adds these three to the nine
methods that stay in its own file.
"""

from __future__ import annotations

import asyncio
from typing import Optional

from backend.parser_requests import SettleSpec


class SettleMixin:
    """`ChatParser`'s waiting half — see the module docstring."""

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
