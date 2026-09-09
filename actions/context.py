"""ActionContext — the runtime state one run exposes to its action blocks.

Built once per run by the run service (services/run_service.py) and passed
to ``execute()`` in the historical `engine` parameter position — it is
duck-compatible with the ActionEngine surface the shipped blocks already
use (report / selected_nick / composer_text / history / is_stopping /
note_selected / mark_person_messaged / queue_order / unmessaged_nicks),
so existing blocks run against it unchanged, and new blocks get a typed,
documented seam instead of "whatever the engine object is".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional


@dataclass
class ActionContext:
    """Runtime state for one stack run. No business logic lives here."""

    #: the CDP connection the run drives
    cdp: Any = None
    #: the people queue repository (UserMemory)
    memory: Any = None
    #: the Filter panel criteria engine
    criteria: Any = None
    #: the message archive service, or None when the archive is off
    history: Any = None
    #: debug/log streamer: report(message, level)
    report_fn: Callable[..., None] = field(default=lambda *_a, **_k: None)
    #: the message composer window's live text (TYPE_MESSAGE
    #: use_composer=True reads it at run time)
    composer_text: str = ""
    #: nick remembered by the most recent Click User / Pick Person block
    #: ({{nick}} in any block field resolves to it)
    selected_nick: str = ""

    # ── engine-compatible surface ────────────────────────────────
    def report(self, message: str, level: str = "info") -> None:
        """Stream one debugger detail line for the current step."""
        self.report_fn(message, level)

    def note_selected(self, nick: str) -> None:
        """Remember the person a Click User block just selected."""
        if nick:
            self.selected_nick = nick

    def is_stopping(self) -> bool:
        stopper = getattr(self, "_stop_checker", None)
        return bool(stopper()) if callable(stopper) else False

    # ── optional hooks the run service installs ──────────────────
    #: predicate consulted by long-running phases so Stop is honoured
    _stop_checker: Optional[Callable[[], bool]] = None
    #: async "mark one person messaged" (MARK_MESSAGED block)
    _mark_messaged: Optional[Callable[[str], Any]] = None
    #: async "which nicks are still un-messaged" (SCROLL_PARSE seek mode)
    _unmessaged_nicks: Optional[Callable[[], Any]] = None
    #: queue order projection for the Order (#) column
    _queue_order: Optional[Callable[[list], list]] = None

    async def mark_person_messaged(self, nick: str) -> str:
        """Delegate to the run service: ok | already | missing | error."""
        if callable(self._mark_messaged):
            return await self._mark_messaged(nick)
        return "missing"

    async def unmessaged_nicks(self) -> set[str]:
        if callable(self._unmessaged_nicks):
            nicks = await self._unmessaged_nicks()
            return {n.nick for n in nicks} if nicks else set()
        return set()

    def queue_order(self, users: list) -> list[str]:
        if callable(self._queue_order):
            return self._queue_order(users)
        return [getattr(u, "nick", u) for u in users or []]
