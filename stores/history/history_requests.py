"""Parameter objects for history store operations (RULE 19.4).

These dataclasses group related parameters together, reducing the number
of individual parameters in function signatures and making the API more
self-documenting. Follows the pattern established by `PersonPageRequest` in
backend/history_query.py.
"""

from __future__ import annotations

from datetime import datetime
from typing import Iterable, Optional

from stores.history.history_models import MessageRecord


class AppendRequest:
    """Parameters for appending a batch of messages to the archive.

    Groups the 13 parameters of `AppendPlanner.append()` into a single
    object, following the pattern of `PersonPageRequest`. All fields are
    optional with sensible defaults matching the original signature.

    Fields:
        nick: The person's nickname
        records: Iterable of MessageRecord to append
        my_nick: Current user's nickname
        align: Whether to align with existing messages
        expect_idx: Expected index for alignment
        dom_count: DOM node count from the page
        head_sig: Head signature for deduplication
        tail_sig: Tail signature for deduplication
        now: Current timestamp (defaults to now)
        session_id: Session identifier
        head_any: Additional head metadata
        tail_any: Additional tail metadata
        prepend: Whether to prepend (insert at beginning)
    """

    nick: str
    records: Iterable[MessageRecord]
    my_nick: str = ""
    align: bool = True
    expect_idx: Optional[int] = None
    dom_count: int = 0
    head_sig: Optional[str] = None
    tail_sig: Optional[str] = None
    now: Optional[datetime] = None
    session_id: str = ""
    head_any: Optional[str] = None
    tail_any: Optional[str] = None
    prepend: bool = False
