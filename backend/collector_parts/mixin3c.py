"""Collector mixin 3c _tick_rest (<150)."""
import asyncio, json, logging
from datetime import datetime
from typing import Optional
from backend import chat_agent_js
from backend.chat_parser import _signature, verify_private
from backend.collector_parts.base import CollectorState
log = logging.getLogger("chatbot")
class CollectorMixin3c:
    async def _tick_rest(self) -> str:
        ctx = getattr(self, "_tick_ctx", {})
        nick = ctx.get("nick", ""); state = ctx.get("state", {}); my_nick = ctx.get("my_nick", "")
        head_sig = ctx.get("head_sig", ""); tail_sig = ctx.get("tail_sig", "")
        head_any = ctx.get("head_any", ""); tail_any = ctx.get("tail_any", "")
        person_id = await self.repo.ensure_person(nick)
        remembered = await self._remember_partner(nick, state)
        self._log(f"Partner “{nick}”: {remembered}", "info", nick)
        check = verify_private(state, nick, self.my_nick)
        if not check.ok:
            self._nick = nick
            self._log(f"Private-chat gate refused “{nick}” ({check.reason})", "warn", nick)
            return self._refuse(*self._gate_status(check, nick))
        self._verified = True
        if check.me and not self._detected_my_nick:
            self._detected_my_nick = check.me
        self._warning = ("" if self.my_nick else "My Nick is not known yet — the archive will use the single outbound author as 'me'")
        if nick != self._nick:
            self._nick = nick; self._added = 0
        cursor = await self.repo.get_cursor(person_id)
        count = int(state.get("count") or 0)
        unchanged = (cursor["bootstrapped"] and count == cursor["dom_count"] and tail_sig and tail_sig == cursor["tail_sig"] and head_sig == cursor["head_sig"])
        person = await self.repo.get_person_by_id(person_id) or {}
        self._total = int(person.get("message_count") or 0)
        if unchanged:
            self._added = 0; self._last_sync_reason = "unchanged_cursor"; self._last_sync_added = 0; self._last_sync_count = count
            if self.media is not None and self._settings["download_media"]:
                try: await self.media.process_pending(); await self.media.evict_if_needed()
                except Exception as e: log.debug("media caching skipped: %s", e)
            return self._set(CollectorState.NO_NEW, self._no_new_text())
        bootstrap = not cursor["bootstrapped"]; full_scan_complete = bool(cursor.get("full_scan_complete"))
        want_backfill = ((bool(self._settings.get("auto_backfill", True)) and not full_scan_complete and not self._backfill_pending) or self._force_backfill)
        self._force_backfill = False
        self._set(CollectorState.BOOTSTRAPPING if bootstrap else CollectorState.COLLECTING, f"Collecting from {nick}…")
        result = await self._sync(nick, my_nick, bootstrap, backfill_older=want_backfill)
        self._backfill_pending = bool(result.backfill_pending); self._last_sync_reason = str(result.reason or ""); self._last_sync_added = int(result.added or 0); self._last_sync_count = int(result.count or 0); self._added = result.added; self._total = result.total
        if result.media_repaired or result.media_requeued:
            self._last_media_repaired = int(result.media_repaired or 0); self._last_media_requeued = int(result.media_requeued or 0)
            self._log(f"Media recovery: repaired {result.media_repaired} message(s), re-queued {result.media_requeued} download(s)", "success", nick)
        if self.media is not None and self._settings["download_media"]:
            try: await self.media.process_pending(); await self.media.evict_if_needed()
            except Exception as e: log.debug("media caching skipped: %s", e)
        suffix = " (throttled — a run is active)" if self._throttled else ""
        if result.added:
            await self._notify_appended(nick, list(result.records[:200]), result.added, result.total)
            self._log(f"Archived {result.added} new message(s) (total {result.total})", "success", nick)
            return self._set(CollectorState.COLLECTED, f"Collected {result.added} new message{'s' if result.added != 1 else ''} from {nick}{suffix}")
        if not result.ok:
            self._log(f"Sync failed for “{nick}” ({result.reason})", "error", nick)
            return self._set(CollectorState.NOT_PRIVATE, "Not in private tab now")
        self._log(f"No new messages ({result.reason}, page count {result.count}, added {result.added})", "info", nick)
        return self._set(CollectorState.NO_NEW, self._no_new_text())
