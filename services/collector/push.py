"""The live push channel from the in-page observer.

`PushMixin` owns the whole `__cvbPush` path: normalise whatever the page
pushed, gate it (RULE 15), append it, and announce the COLLECTED status plus
the UI-shaped rows. Nothing here probes the page — that is the heartbeat's
job.
"""

import json
import logging

from backend.chat_parser import verify_private
from backend.history_query import HistoryQuery

from .constants import CollectorState

log = logging.getLogger("chatbot")


class PushMixin:
    async def handle_push(self, payload) -> int:
        """Store what the in-page observer pushed. Never raises."""
        if not self._nick or not self.enabled or self._paused:
            return 0
        data = self._payload(payload)
        items = self._records(data)
        if not items:
            return 0
        if not self._verified:
            # No tick has verified this conversation (or the last one
            # refused it): the observer may be describing another pane.
            return 0
        if not self._push_gate(data, items):
            return 0
        result = await self._append_pushed(items)
        if result is None:
            return 0
        if result.added:
            await self._announce_push(result)
        return result.added

    def _push_gate(self, data: dict, items: list) -> bool:
        """RULE 15 gate: refuse the push unless the pane proves private."""
        check = verify_private(
            {"tab": data.get("tab") or "private",
             "partner": data.get("partner") or self._nick,
             "title": data.get("title") or data.get("partner") or "",
             "me": data.get("me") or ""},
            self._nick, self.my_nick, items=items)
        if check.ok:
            return True
        self._refuse(*self._gate_status(check, self._nick))
        return False

    async def _append_pushed(self, items: list):
        """Archive the pushed records; None when the write failed (logged)."""
        try:
            return await self.repo.append(self._nick, items,
                                          my_nick=self.my_nick,
                                          align=False, now=self.now())
        except Exception as e:                        # noqa: BLE001
            log.warning("push append failed: %s", e)
            return None

    async def _announce_push(self, result) -> None:
        """Counters + notify + the COLLECTED status line (strings pinned)."""
        self._added = result.added
        self._total = result.total
        await self._notify_appended(self._nick, list(result.records[:200]),
                                    result.added, result.total)
        self._set(CollectorState.COLLECTED,
                  f"Collected {result.added} new "
                  f"message{'s' if result.added != 1 else ''} "
                  f"from {self._nick}")

    @staticmethod
    def _payload(payload) -> dict:
        """Normalise whatever the page pushed into a dict."""
        data = payload
        if isinstance(data, (bytes, bytearray)):
            data = data.decode("utf-8", "replace")
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except (TypeError, ValueError):
                return {}
        if isinstance(data, list):
            return {"items": data}
        return data if isinstance(data, dict) else {}

    @classmethod
    def _records(cls, payload) -> list:
        data = payload if isinstance(payload, dict) else cls._payload(payload)
        items = data.get("items")
        if not isinstance(items, list):
            return []
        return [item for item in items if isinstance(item, dict)]

    async def _notify_appended(self, nick: str, items: list, added: int,
                               total: int) -> None:
        """Emit UI-shaped rows, never the raw parser records.

        The UI rows need `ord`, `day`, `time` and the joined media fields;
        `AppendResult.records` now carries that shape from the write.  If it
        is somehow empty, re-read the newest page from SQLite as a fallback.
        """
        live = list(items or [])[:200]
        if not live:
            try:
                page = await HistoryQuery(self.repo.db).page(
                    nick, limit=min(200, max(50, added or 50)))
                live = page.get("items") or []
                if page.get("total") is not None:
                    total = int(page.get("total") or 0)
            except Exception as e:                    # noqa: BLE001
                log.debug("live history page for %s failed: %s", nick, e)
        try:
            self.history_appended.emit(json.dumps(
                {"nick": nick, "my_nick": self.my_nick, "items": live,
                 "added": added, "total": total}, ensure_ascii=False))
        except Exception as e:                        # noqa: BLE001
            log.debug("history_appended emit failed: %s", e)
