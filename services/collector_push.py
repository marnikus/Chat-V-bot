"""The live push channel and the private-chat gate.

Owns the `__cvbPush` path: the gate that decides whether the active tab is
a private chat this app may write to, and the append/announce pair that
archives a pushed batch. Built from the aggregate only; `_verified` and
the counters stay on `Collector`.
"""

from __future__ import annotations

import logging

from backend.chat_parser import verify_private
from services.collector_states import CollectorState

log = logging.getLogger("chatbot")


class PushPath:
    """One responsibility of `Collector`, built from it."""

    def __init__(self, owner):
        self._o = owner

    # ── the gate helpers ─────────────────────────────────────────
    def _refuse(self, state: str, text: str) -> str:
        """Refuse to save: the push channel is disarmed with the tick."""
        self._o._verified = False
        return self._o._set(state, text)

    @staticmethod
    def _gate_status(check, nick: str) -> tuple:
        """Turn a failed PrivateCheck into (state, status text)."""
        if check.reason == "strangers":
            shown = ", ".join(check.strangers[:3])
            if len(check.strangers) > 3:
                shown += "…"
            return (CollectorState.GROUP_TAB,
                    f"Not a private chat — {shown} write here too "
                    f"(nothing saved for {nick})")
        if check.reason == "title_mismatch":
            return (CollectorState.NOT_PRIVATE,
                    f"Tab does not match “{nick}” — nothing saved")
        if check.reason == "self_chat":
            return (CollectorState.NOT_PRIVATE,
                    "Partner is ambiguous (same as My Nick)")
        if check.reason == "no_author_data":
            return (CollectorState.NOT_PRIVATE,
                    "Cannot verify this chat yet — nothing saved")
        return (CollectorState.NOT_PRIVATE, "Not in private tab now")

    # ── the live push channel ────────────────────────────────────
    def _push_ready(self) -> bool:
        """Whether a push may be stored at all right now.

        Both halves are pure reads of the collector's own state, so answering
        them before the payload is parsed cannot reorder anything observable.
        """
        if not self._o._nick or not self._o.enabled or self._o._paused:
            return False
        if not self._o._verified:
            # No tick has verified this conversation (or the last one
            # refused it): the observer may be describing another pane.
            return False
        return True

    def _gate_check(self, data: dict, items: list):
        """Re-verify the conversation this push claims to describe."""
        return verify_private(
            {"tab": data.get("tab") or "private",
             "partner": data.get("partner") or self._o._nick,
             "title": data.get("title") or data.get("partner") or "",
             "me": data.get("me") or ""},
            self._o._nick, self._o.my_nick, items=items)

    async def _append_push(self, items: list):
        """Store the pushed records; None when the write raised."""
        try:
            return await self._o.repo.append(self._o._nick, items,
                                          my_nick=self._o.my_nick,
                                          align=False, now=self._o.now())
        except Exception as e:                        # noqa: BLE001
            log.warning("push append failed: %s", e)
            return None

    async def _announce_push(self, result) -> None:
        """Publish what the push added and move the collector to COLLECTED."""
        self._o._added = result.added
        self._o._total = result.total
        await self._o._notify_appended(
            self._o._nick, list(result.records[:200]),
            result.added, result.total)
        self._o._set(CollectorState.COLLECTED,
                  f"Collected {result.added} new "
                  f"message{'s' if result.added != 1 else ''} "
                  f"from {self._o._nick}")

    async def handle_push(self, payload) -> int:
        """Store what the in-page observer pushed. Never raises."""
        if not self._o._push_ready():
            return 0
        data = self._o._payload(payload)
        items = self._o._records(data)
        if not items:
            return 0
        check = self._o._gate_check(data, items)
        if not check.ok:
            self._o._refuse(*self._o._gate_status(check, self._o._nick))
            return 0
        result = await self._o._append_push(items)
        if result is None:
            return 0
        if result.added:
            await self._o._announce_push(result)
        return result.added
