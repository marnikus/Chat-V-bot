"""Write path of the message archive.

Everything that adds to `history.db` goes through here. The two rules that
shape the code:

  * **append-only and idempotent.** Collection re-reads the same DOM over and
    over; replaying a batch, re-running a bootstrap or overlapping a delta
    must never duplicate a line. Identity is the fingerprint plus the
    resolved day, so the same sentence on two days is two rows.
  * **honest about holes.** When the site trimmed its buffer and the new
    batch has nothing in common with what we stored, we append and write a
    `gaps` row rather than pretending the conversation is contiguous.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from typing import Iterable, Optional

from stores.history_db import HistoryDB
from stores.history_models import (MAX_LIVE_ITEMS, Alignment,  # noqa: F401
                                    AppendResult,  # noqa: F401
                                    MessageRecord, dedupe_key,  # noqa: F401
                                    fingerprint)  # noqa: F401
from stores.history_repo_append import AppendPlanner
from stores.history_repo_identity import (                        # noqa: F401
    TAIL_FP_LIMIT,
    align_batch,
    resolve_days,
)
from stores.history_repo_identity import ConversationIdentity
from stores.history_repo_lifecycle import PersonLifecycle
from stores.history_repo_media import MediaRecovery

log = logging.getLogger("chatbot")

#: the surface `stores/history_repo.py` promised before B2 split it. The
#: alignment helpers moved to `history_repo_identity.py` and are re-exported
#: here because `services/history/*` and three test modules import them from
#: this name (gate 3 of design §5).
__all__ = ["HistoryRepo", "align_batch", "resolve_days", "TAIL_FP_LIMIT",
           "MAX_LIVE_ITEMS", "Alignment", "AppendResult", "MessageRecord",
           "dedupe_key", "fingerprint"]


class HistoryRepo:
    """Append-only writer for one archive database."""

    def __init__(self, db: HistoryDB, media=None, session_id: str = ""):
        self.db = db
        self.media = media
        self.session_id = session_id or ""
        self._scan_seq = 0       # unique scan marker per recovery pass
        # the B2 split (design §2.3): four parts, no state of their own. Each
        # one reads `db` / `media` / `session_id` / `_scan_seq` back off this
        # object at call time, so a collector that swaps `repo.media` or a
        # recovery pass that bumps `_scan_seq` keeps working unchanged.
        self.identity = ConversationIdentity(self)
        self.planner = AppendPlanner(self)
        self.media_recovery = MediaRecovery(self)
        self.lifecycle = PersonLifecycle(self)

    # ── persons ──────────────────────────────────────────────────
    @staticmethod
    def normalise_nick(nick: str) -> str:
        return " ".join(str(nick or "").split()).strip()

    async def ensure_person(self, nick: str) -> int:
        """See `ConversationIdentity.ensure_person` — the name stays on the facade, which is what `services/`, the bridges and the archive tests call (design §2.3)."""
        return await self.identity.ensure_person(nick)

    async def get_person(self, nick: str) -> Optional[dict]:
        """See `ConversationIdentity.get_person` — the name stays on the facade, which is what `services/`, the bridges and the archive tests call (design §2.3)."""
        return await self.identity.get_person(nick)

    async def get_person_by_id(self, person_id: int) -> Optional[dict]:
        """See `ConversationIdentity.get_person_by_id` — the name stays on the facade, which is what `services/`, the bridges and the archive tests call (design §2.3)."""
        return await self.identity.get_person_by_id(person_id)

    @staticmethod
    def _person_dict(row) -> dict:
        data = dict(row)
        try:
            data["my_nicks"] = json.loads(data.get("my_nicks") or "[]")
        except Exception:                            # noqa: BLE001
            data["my_nicks"] = []
        data["deleted"] = bool(data.get("deleted_at"))
        return data

    async def possible_duplicates(self) -> list[dict]:
        """See `ConversationIdentity.possible_duplicates` — the name stays on the facade, which is what `services/`, the bridges and the archive tests call (design §2.3)."""
        return await self.identity.possible_duplicates()

    async def rename_if_same_conversation(self, old_nick: str, new_nick: str, head_sig: str, tail_sig: str, head_any: str='', tail_any: str='', dom_count: int=-1, pane_same: bool=False) -> bool:
        """See `PersonLifecycle.rename_if_same_conversation` — the name stays on the facade, which is what `services/`, the bridges and the archive tests call (design §2.3)."""
        return await self.identity.rename_if_same_conversation(old_nick, new_nick, head_sig, tail_sig, head_any, tail_any, dom_count, pane_same)

    # ── cursor ───────────────────────────────────────────────────
    async def get_cursor(self, person_id: int) -> dict:
        """See `PersonLifecycle.get_cursor` — the name stays on the facade, which is what `services/`, the bridges and the archive tests call (design §2.3)."""
        return await self.lifecycle.get_cursor(person_id)

    async def reset_cursor(self, nick: str) -> None:
        """See `PersonLifecycle.reset_cursor` — the name stays on the facade, which is what `services/`, the bridges and the archive tests call (design §2.3)."""
        await self.lifecycle.reset_cursor(nick)

    async def _last_ord(self, person_id: int) -> int:
        """See `PersonLifecycle._last_ord` — the name stays on the facade, which is what `services/`, the bridges and the archive tests call (design §2.3)."""
        return await self.lifecycle._last_ord(person_id)

    async def mark_backfilled(self, nick_or_id) -> None:
        """See `PersonLifecycle.mark_backfilled` — the name stays on the facade, which is what `services/`, the bridges and the archive tests call (design §2.3)."""
        await self.lifecycle.mark_backfilled(nick_or_id)

    # ── append ───────────────────────────────────────────────────
    async def append(self, nick: str, records: Iterable, my_nick: str='', align: bool=True, expect_idx: Optional[int]=None, dom_count: int=0, head_sig: Optional[str]=None, tail_sig: Optional[str]=None, now: Optional[datetime]=None, session_id: str='', head_any: Optional[str]=None, tail_any: Optional[str]=None, prepend: bool=False) -> AppendResult:
        """See `AppendPlanner.append` — the name stays on the facade, which is what `services/`, the bridges and the archive tests call (design §2.3)."""
        return await self.planner.append(nick, records, my_nick, align, expect_idx, dom_count, head_sig, tail_sig, now, session_id, head_any, tail_any, prepend)

    async def _prepend(self, person_id: int, recs, my_nick: str, now: datetime, dom_count: int, head_sig: Optional[str], tail_sig: Optional[str], session_id: str, nick: str='', head_any: Optional[str]=None, tail_any: Optional[str]=None) -> AppendResult:
        """See `AppendPlanner._prepend` — the name stays on the facade, which is what `services/`, the bridges and the archive tests call (design §2.3)."""
        return await self.planner._prepend(person_id, recs, my_nick, now, dom_count, head_sig, tail_sig, session_id, nick, head_any, tail_any)

    async def record_gap(self, nick_or_id, after_ord: int, reason: str, detail: str='') -> None:
        """See `AppendPlanner.record_gap` — the name stays on the facade, which is what `services/`, the bridges and the archive tests call (design §2.3)."""
        await self.planner.record_gap(nick_or_id, after_ord, reason, detail)

    async def _existing_dup_keys(self, person_id: int, keys) -> set:
        """See `AppendPlanner._existing_dup_keys` — the name stays on the facade, which is what `services/`, the bridges and the archive tests call (design §2.3)."""
        return await self.planner._existing_dup_keys(person_id, keys)

    async def _query_dup_keys(self, person_id: int, keys: list) -> set:
        """See `AppendPlanner._query_dup_keys` — the name stays on the facade, which is what `services/`, the bridges and the archive tests call (design §2.3)."""
        return await self.planner._query_dup_keys(person_id, keys)

    # ── empty slots left by a media line parsed too early ────────
    #
    # The in-page observer can fire before Angular renders `app-chat-image`,
    # so the row is stored with neither text nor media (`kind='text'`,
    # `text=''`, `media_id NULL`). When the real payload arrives — on the
    # next push, the next full read or a backfill — the empty slot must be
    # FILLED, not duplicated (Bug #2, 2026-09-07).

    @staticmethod
    def _slot_key(rec: MessageRecord) -> tuple:
        return (str(rec.direction or "").strip().lower(),
                " ".join(str(rec.from_nick or "").split()).strip().lower(),
                " ".join(str(rec.ts_display or "").split()).strip())

    async def _empty_slot_rows(self, person_id: int) -> list:
        """See `AppendPlanner._empty_slot_rows` — the name stays on the facade, which is what `services/`, the bridges and the archive tests call (design §2.3)."""
        return await self.planner._empty_slot_rows(person_id)

    @staticmethod
    def _slot_row_key(row) -> tuple:
        return (str(row.get("direction") or "").strip().lower(),
                " ".join(str(row.get("from_nick") or "").split())
                .strip().lower(),
                " ".join(str(row.get("ts_display") or "").split()).strip(),
                str(row.get("day") or "")[:10])

    async def _take_empty_slot(self, person_id: int, rec: MessageRecord, used: dict, day: str='', rows: Optional[list]=None) -> Optional[int]:
        """See `AppendPlanner._take_empty_slot` — the name stays on the facade, which is what `services/`, the bridges and the archive tests call (design §2.3)."""
        return await self.planner._take_empty_slot(person_id, rec, used, day, rows)

    async def _fill_slot(self, slot_id: int, rec: MessageRecord, media_id: Optional[int]) -> None:
        """See `AppendPlanner._fill_slot` — the name stays on the facade, which is what `services/`, the bridges and the archive tests call (design §2.3)."""
        await self.planner._fill_slot(slot_id, rec, media_id)

    async def _ord_of(self, row_id: int) -> int:
        """See `AppendPlanner._ord_of` — the name stays on the facade, which is what `services/`, the bridges and the archive tests call (design §2.3)."""
        return await self.planner._ord_of(row_id)


    async def _media_id(self, rec: MessageRecord, nick: str='', day: str='') -> Optional[int]:
        """See `ConversationIdentity._media_id` — the name stays on the facade, which is what `services/`, the bridges and the archive tests call (design §2.3)."""
        return await self.identity._media_id(rec, nick, day)

    async def _ui_record(self, rec: MessageRecord, ord_value: int, day: str, my_nick: str, media_id) -> dict:
        """See `ConversationIdentity._ui_record` — the name stays on the facade, which is what `services/`, the bridges and the archive tests call (design §2.3)."""
        return await self.identity._ui_record(rec, ord_value, day, my_nick, media_id)

    async def _record_gap(self, person_id: int, after_ord: int, reason: str, detail: str='') -> None:
        """See `AppendPlanner._record_gap` — the name stays on the facade, which is what `services/`, the bridges and the archive tests call (design §2.3)."""
        await self.planner._record_gap(person_id, after_ord, reason, detail)

    # ── media recovery during a backfill ────────────────────────
    @staticmethod
    def _media_key(direction: str, from_nick: str, ts_display: str) -> str:
        return " ".join([
            " ".join(str(direction or "").split()).strip().lower(),
            " ".join(str(from_nick or "").split()).strip().lower(),
            " ".join(str(ts_display or "").split()).strip().lower(),
        ])

    async def recover_media(self, person_id: int, records, media=None, nick: str='', now=None, requeue_failed: bool=True) -> dict:
        """See `MediaRecovery.recover_media` — the name stays on the facade, which is what `services/`, the bridges and the archive tests call (design §2.3)."""
        return await self.media_recovery.recover_media(person_id, records, media, nick, now, requeue_failed)

    async def _all_person_keys(self, person_id: int) -> set:
        """See `MediaRecovery._all_person_keys` — the name stays on the facade, which is what `services/`, the bridges and the archive tests call (design §2.3)."""
        return await self.media_recovery._all_person_keys(person_id)

    async def has_repairable_media(self, person_id: int, include_failed: bool=False, rescan_after_s: int=600) -> bool:
        """See `MediaRecovery.has_repairable_media` — the name stays on the facade, which is what `services/`, the bridges and the archive tests call (design §2.3)."""
        return await self.media_recovery.has_repairable_media(person_id, include_failed, rescan_after_s)


    async def _touch_cursor(self, person_id: int, dom_count: int, head_sig: Optional[str], tail_sig: Optional[str], head_any: Optional[str]=None, tail_any: Optional[str]=None) -> None:
        """See `AppendPlanner._touch_cursor` — the name stays on the facade, which is what `services/`, the bridges and the archive tests call (design §2.3)."""
        await self.lifecycle._touch_cursor(person_id, dom_count, head_sig, tail_sig, head_any, tail_any)

    async def _after_write(self, person_id: int, my_nick: str, dom_count: int, head_sig: Optional[str], tail_sig: Optional[str], bootstrapped: Optional[bool], head_any: Optional[str]=None, tail_any: Optional[str]=None) -> None:
        """See `AppendPlanner._after_write` — the name stays on the facade, which is what `services/`, the bridges and the archive tests call (design §2.3)."""
        await self.lifecycle._after_write(person_id, my_nick, dom_count, head_sig, tail_sig, bootstrapped, head_any, tail_any)

    async def _recount(self, person_id: int, my_nick: str='') -> None:
        """See `AppendPlanner._recount` — the name stays on the facade, which is what `services/`, the bridges and the archive tests call (design §2.3)."""
        await self.lifecycle._recount(person_id, my_nick)

    # ── lifecycle ────────────────────────────────────────────────
    @staticmethod
    def new_op_token() -> str:
        """One stamp shared by every row of a single delete operation.

        Undo is then a single `WHERE deleted_at=?` update, so the history
        entry stays tiny no matter how many messages were hidden.
        """
        return (datetime.now().isoformat(timespec="seconds") + "#" +
                uuid.uuid4().hex[:8])

    async def soft_delete_message(self, nick: str, message_id: int, token: str='') -> str:
        """See `PersonLifecycle.soft_delete_message` — the name stays on the facade, which is what `services/`, the bridges and the archive tests call (design §2.3)."""
        return await self.lifecycle.soft_delete_message(nick, message_id, token)

    async def soft_delete_history(self, nick: str, token: str='') -> str:
        """See `PersonLifecycle.soft_delete_history` — the name stays on the facade, which is what `services/`, the bridges and the archive tests call (design §2.3)."""
        return await self.lifecycle.soft_delete_history(nick, token)

    async def restore_deleted(self, nick: str, token: str) -> int:
        """See `PersonLifecycle.restore_deleted` — the name stays on the facade, which is what `services/`, the bridges and the archive tests call (design §2.3)."""
        return await self.lifecycle.restore_deleted(nick, token)

    async def _restore_rows(self, person_id: int, token: str) -> int:
        """See `PersonLifecycle._restore_rows` — the name stays on the facade, which is what `services/`, the bridges and the archive tests call (design §2.3)."""
        return await self.lifecycle._restore_rows(person_id, token)

    async def deleted_count(self, nick: str='') -> int:
        """See `PersonLifecycle.deleted_count` — the name stays on the facade, which is what `services/`, the bridges and the archive tests call (design §2.3)."""
        return await self.lifecycle.deleted_count(nick)

    async def purge_deleted(self, nick: str='') -> int:
        """See `PersonLifecycle.purge_deleted` — the name stays on the facade, which is what `services/`, the bridges and the archive tests call (design §2.3)."""
        return await self.lifecycle.purge_deleted(nick)

    async def delete_person(self, nick: str, hard: bool=False, token: str='') -> bool:
        """See `PersonLifecycle.delete_person` — the name stays on the facade, which is what `services/`, the bridges and the archive tests call (design §2.3)."""
        return await self.lifecycle.delete_person(nick, hard, token)

    async def restore_person(self, nick: str, token: str='') -> bool:
        """See `PersonLifecycle.restore_person` — the name stays on the facade, which is what `services/`, the bridges and the archive tests call (design §2.3)."""
        return await self.lifecycle.restore_person(nick, token)

    async def merge_persons(self, from_nick: str, into_nick: str) -> int:
        """See `PersonLifecycle.merge_persons` — the name stays on the facade, which is what `services/`, the bridges and the archive tests call (design §2.3)."""
        return await self.lifecycle.merge_persons(from_nick, into_nick)

    async def _resequence(self, person_id: int) -> None:
        """See `PersonLifecycle._resequence` — the name stays on the facade, which is what `services/`, the bridges and the archive tests call (design §2.3)."""
        await self.lifecycle._resequence(person_id)
