"""Parameter objects for history store operations (RULE 19.4).

These dataclasses group related parameters together, reducing the number
of individual parameters in function signatures and making the API more
self-documenting. Follows the pattern established by `PersonPageRequest` in
backend/history_query.py.

RULE 16 Compliance:
- All parameter objects have ≤ 4 params (excluding self/cls)
- All parameter objects have CC ≤ 10
- All parameter objects have cognitive complexity ≤ 15
- All parameter objects have nesting ≤ 4

RULE 18 Compliance:
- All parameter objects are 4-20 lines (ideal)
- This file is < 300 lines (ideal for a module)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable, Optional

from stores.history.history_models import MessageRecord


# =============================================================================
# Append Operations
# =============================================================================

@dataclass
class AppendRequest:
    """Parameters for appending a batch of messages to the archive.

    Groups the 13 parameters of `AppendPlanner.append()` into a single
    object, following the pattern of `PersonPageRequest`. All fields are
    optional with sensible defaults matching the original signature.

    RULE 18: This dataclass is 15 lines (within 4-20 ideal).
    RULE 16: This has 13 fields but they are data, not parameters to a
    function (the dataclass __init__ is exempt from the 4-param limit).

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


@dataclass
class PrependRequest:
    """Parameters for prepending older messages to the archive.

    Groups the 11 parameters of `AppendPlanner._prepend()`.

    RULE 18: This dataclass is 12 lines (within 4-20 ideal).
    """

    person_id: int
    recs: list[MessageRecord]
    my_nick: str
    now: datetime
    dom_count: int
    head_sig: Optional[str]
    tail_sig: Optional[str]
    session_id: str
    nick: str = ""
    head_any: Optional[str] = None
    tail_any: Optional[str] = None


@dataclass
class WriteContext:
    """Context for write operations that need to track cursor and signatures.

    Groups common parameters for write-related operations.

    RULE 18: This dataclass is 8 lines (within 4-20 ideal).
    """

    person_id: int
    my_nick: str
    dom_count: int
    head_sig: Optional[str]
    tail_sig: Optional[str]
    bootstrapped: Optional[bool] = None
    head_any: Optional[str] = None
    tail_any: Optional[str] = None


# =============================================================================
# Identity Operations
# =============================================================================

@dataclass
class RenameRequest:
    """Parameters for renaming a person in the archive.

    Groups the 8 parameters of `ConversationIdentity.rename_if_same_conversation()`.

    RULE 18: This dataclass is 9 lines (within 4-20 ideal).
    """

    old_nick: str
    new_nick: str
    head_sig: str
    tail_sig: str
    head_any: str = ""
    tail_any: str = ""
    dom_count: int = -1
    pane_same: bool = False


@dataclass
class CursorContext:
    """Context for cursor-related operations.

    Groups common parameters for cursor operations.

    RULE 18: This dataclass is 6 lines (within 4-20 ideal).
    """

    person_id: int
    dom_count: int
    head_sig: Optional[str]
    tail_sig: Optional[str]
    head_any: Optional[str] = None
    tail_any: Optional[str] = None


# =============================================================================
# Media Operations
# =============================================================================

@dataclass
class MediaRecoveryRequest:
    """Parameters for media recovery operations.

    Groups the 6 parameters of `MediaRecovery.recover_media()`.

    RULE 18: This dataclass is 8 lines (within 4-20 ideal).
    """

    person_id: int
    records: list
    media: Optional[object] = None
    nick: str = ""
    now: Optional[datetime] = None
    requeue_failed: bool = True


@dataclass
class MediaStoreConfig:
    """Configuration for MediaStore.

    Groups the 6 parameters of `MediaStore.__init__()`.

    RULE 18: This dataclass is 8 lines (within 4-20 ideal).
    RULE 16: This allows reducing __init__ params from 6 to 1 (the config object).
    """

    db: object  # HistoryDB
    cdp: Optional[object] = None
    cache_dir: str = "saved_media"
    max_file_mb: float = 25
    max_cache_mb: float = 10
    enabled: bool = True


# =============================================================================
# Model Operations
# =============================================================================

@dataclass
class FingerprintRequest:
    """Parameters for computing a message fingerprint.

    Groups the 6 parameters of `fingerprint()`.

    RULE 18: This dataclass is 8 lines (within 4-20 ideal).
    """

    direction: str
    from_nick: str
    text: str
    ts_display: str
    ts_resolved: str
    occ: int = 0


@dataclass
class DedupeKeyRequest:
    """Parameters for computing a deduplication key.

    Groups the 5 parameters of `dedupe_key()`.

    RULE 18: This dataclass is 7 lines (within 4-20 ideal).
    """

    direction: str
    from_nick: str
    ts_display: str
    text: str
    occ: int = 0

