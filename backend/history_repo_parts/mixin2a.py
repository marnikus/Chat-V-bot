"""History repo 2a rename (<150)."""
import asyncio, json, logging, re
from datetime import datetime
from typing import Optional

class HistoryRepoMixin2a:
    async def rename_if_same_conversation(self, old_nick: str,
                                          new_nick: str, head_sig: str,
                                          tail_sig: str,
                                          head_any: str = "",
                                          tail_any: str = "",
                                          dom_count: int = -1,
                                          pane_same: bool = False) -> bool:
        """Continue the previous person's archive under a changed nick.

        The partner can rename at any moment; the conversation on screen is
        still the same one. When the pane we are about to collect shows the
        same head AND tail the previous partner's cursor ended with — the
        same messages, therefore the same chat under a new title — the
        person row is renamed in place and the history, cursors and counters
        continue. Returns True when the rename happened.

        Two signatures are accepted, because the site may re-render history
        under the new nick (every fingerprint changes): the exact head/tail,
        or the author-agnostic head_any/tail_any (fingerprint without the
        nick). `dom_count` must be unchanged — a rename does not add or
        remove messages. `pane_same` must be True: the in-page agent reports
        whether this is literally the SAME pane element as the previous
        probe — a rename happens inside the open pane, while switching to
        another conversation always swaps the pane. That is what keeps two
        different people with similar content from being merged.
        Deliberately conservative: the new nick must be free (an existing
        person means the user may have two conversations — merging stays a
        manual action).
        """
        if not pane_same:
            return False
        old = await self.get_person(old_nick)
        if not old:
            return False
        clean = self.normalise_nick(new_nick)
        if not clean or clean == old["nick"]:
            return False
        if await self.get_person(clean):
            return False                      # nick already known — not a rename
        cursor = await self.get_cursor(int(old["id"]))
        if not cursor.get("bootstrapped"):
            return False
        if dom_count >= 0 and int(cursor.get("dom_count") or -1) != dom_count:
            return False
        same_exact = bool(
            head_sig and tail_sig
            and head_sig == str(cursor.get("head_sig") or "")
            and tail_sig == str(cursor.get("tail_sig") or ""))
        same_any = bool(
            head_any and tail_any
            and str(cursor.get("head_any") or "")
            and head_any == str(cursor.get("head_any") or "")
            and tail_any == str(cursor.get("tail_any") or ""))
        if not (same_exact or same_any):
            return False
        stamp = datetime.now().isoformat(timespec="seconds")
        pid = int(old["id"])
        await self.db.execute(
            "UPDATE persons SET nick=?, nick_lc=?, last_seen=? WHERE id=?",
            (clean, clean.lower(), stamp, pid))
        await self.db.commit()
        # The site re-renders the past under the new nick, so the stored
        # lines must follow — otherwise the next full read would archive
        # every line a second time (identity includes the author). Their
        # identity is recomputed with the new nick; there can be no
        # collision because a person with the new nick would have refused
        # the rename above.
        rows = await self.db.fetchdicts(
            "SELECT m.id, m.occ, m.kind, m.text, m.ts_display, "
            "md.url AS media_url FROM messages m "
            "LEFT JOIN media md ON md.id = m.media_id "
            "WHERE m.person_id=? AND m.from_nick=?",
            (pid, old["nick"]))
        for row in rows:
            payload = row.get("media_url") or row.get("text") or ""
            occ = int(row.get("occ") or 0)
            await self.db.execute(
                "UPDATE messages SET from_nick=?, dup_key=?, fp=? WHERE id=?",
                (clean,
                 dedupe_key("in", clean, row.get("ts_display") or "",
                            row.get("kind") or "text", payload),
                 fingerprint("in", clean, row.get("ts_display") or "",
                             row.get("kind") or "text", payload, occ),
                 int(row["id"])))
        if rows:
            await self.db.commit()
        log.info("partner “%s” is now “%s” — the same conversation "
                 "continues under the new nick (%d stored line(s) "
                 "re-attributed)", old["nick"], clean, len(rows))
        return True

    # ── cursor ───────────────────────────────────────────────────
