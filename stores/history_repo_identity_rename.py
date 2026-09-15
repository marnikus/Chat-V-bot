"""Rename if same conversation — extracted from history_repo_identity (H-C5 split)

≤150 LOC.
"""

from __future__ import annotations

import logging
from datetime import datetime

from stores.history_models import LineIdentity, dedupe_key, fingerprint
from stores.history_requests import PaneSignature

log = logging.getLogger("chatbot")


class ConversationIdentityRename:
    def __init__(self, owner):
        self._owner = owner

    async def rename_if_same_conversation(
        self, old_nick: str, new_nick: str, pane: PaneSignature, pane_same: bool = False
    ) -> bool:
        if not pane_same:
            return False
        old = await self._owner.get_person(old_nick)
        if not old:
            return False
        clean = self._owner.normalise_nick(new_nick)
        if not clean or clean == old["nick"]:
            return False
        if await self._owner.get_person(clean):
            return False
        pid = int(old["id"])
        cursor = await self._owner.get_cursor(pid)
        if not self._same_conversation(cursor, pane):
            return False
        return await self._apply_rename(pid, str(old["nick"]), clean)

    def _same_conversation(self, cursor: dict, pane: PaneSignature) -> bool:
        if not cursor.get("bootstrapped"):
            return False
        if pane.dom_count >= 0 and int(cursor.get("dom_count") or -1) != pane.dom_count:
            return False
        return self._exact_match(cursor, pane.head_sig, pane.tail_sig) or self._any_match(
            cursor, pane.head_any, pane.tail_any
        )

    @staticmethod
    def _exact_match(cursor: dict, head_sig: str, tail_sig: str) -> bool:
        return bool(
            head_sig
            and tail_sig
            and head_sig == str(cursor.get("head_sig") or "")
            and tail_sig == str(cursor.get("tail_sig") or "")
        )

    @staticmethod
    def _any_match(cursor: dict, head_any: str, tail_any: str) -> bool:
        return bool(
            head_any
            and tail_any
            and str(cursor.get("head_any") or "")
            and head_any == str(cursor.get("head_any") or "")
            and tail_any == str(cursor.get("tail_any") or "")
        )

    async def _apply_rename(self, pid: int, old_nick: str, clean: str) -> bool:
        stamp = datetime.now().isoformat(timespec="seconds")
        await self._owner.db.execute(
            "UPDATE persons SET nick=?, nick_lc=?, last_seen=? WHERE id=?", (clean, clean.lower(), stamp, pid)
        )
        await self._owner.db.commit()
        moved = await self._reattribute(pid, old_nick, clean)
        log.info("partner “%s” is now “%s” — continues (%d re-attributed)", old_nick, clean, moved)
        return True

    async def _reattribute(self, pid: int, old_nick: str, clean: str) -> int:
        rows = await self._owner.db.fetchdicts(
            "SELECT m.id, m.occ, m.kind, m.text, m.ts_display, md.url AS media_url FROM messages m "
            "LEFT JOIN media md ON md.id = m.media_id WHERE m.person_id=? AND m.from_nick=?",
            (pid, old_nick),
        )
        for row in rows:
            payload = row.get("media_url") or row.get("text") or ""
            occ = int(row.get("occ") or 0)
            await self._owner.db.execute(
                "UPDATE messages SET from_nick=?, dup_key=?, fp=? WHERE id=?",
                (
                    clean,
                    dedupe_key(LineIdentity("in", clean, row.get("ts_display") or "", row.get("kind") or "text", payload)),
                    fingerprint(LineIdentity("in", clean, row.get("ts_display") or "", row.get("kind") or "text", payload), occ),
                    int(row["id"]),
                ),
            )
        if rows:
            await self._owner.db.commit()
        return len(rows)
