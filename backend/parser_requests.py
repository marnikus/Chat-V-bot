"""The knobs of ChatParser's two configurable operations.

Second request module of the chat family — the sync knobs live in
`backend.chat_sync_options.SyncOptions`, the gate and settle knobs live
here. Keeping them out of `chat_parser.py` holds that file at reading
size while the signatures stay at RULE 16 width (identity inputs plus
one spec object; Round G step 4 design §1b wave 1).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class PrivateQuery:
    """The policy of one `verify_private()` call.

    `my_nick` and `nick` stay positional on the gate itself: like the
    state dict they are *identity* inputs, not knobs.
    """

    #: pushed records to judge the authors of; None = read them from the
    #: page state (the normal sync path).
    items: Any = None
    #: refuse panes whose tab is not a private chat (the strict default).
    require_private: bool = True


@dataclass(frozen=True, slots=True)
class SettleSpec:
    """How long `settle_after_top()` waits for the pane to go quiet."""

    #: pause between polls.
    wait_ms: int = 300
    #: consecutive unchanged polls that count as "settled".
    stable_polls: int = 3
    #: hard deadline; a timeout reports `_settled=False`.
    max_wait_s: float = 6.0
    #: visible-count floor while the virtualiser re-renders older lines.
    minimum_count: int = 0
