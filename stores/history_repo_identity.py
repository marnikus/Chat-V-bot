"""Who a line belongs to, and how it becomes a row.

H-C5: split into person/media/rename parts, facade ≤80 LOC.
"""

from __future__ import annotations

from stores.history_repo_identity_helpers import _as_record, align_batch, resolve_days
from stores.history_repo_identity_media import ConversationIdentityMedia
from stores.history_repo_identity_person import ConversationIdentityPerson
from stores.history_repo_identity_rename import ConversationIdentityRename

TAIL_FP_LIMIT = 200


class ConversationIdentity(
    ConversationIdentityPerson, ConversationIdentityMedia, ConversationIdentityRename
):
    def __init__(self, owner):
        self._owner = owner


__all__ = ["ConversationIdentity", "TAIL_FP_LIMIT", "align_batch", "resolve_days", "_as_record"]
