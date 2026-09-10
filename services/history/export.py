"""History export formats and the compatibility lifecycle mixin."""

from __future__ import annotations
import json
from .binding import HistoryBinding
from .lifecycle import HistoryLifecycle
from .migration import HistoryMigration


class HistoryExportService(HistoryBinding, HistoryLifecycle, HistoryMigration):
    async def export_chat(self, nick: str, fmt: str = "json"):
        page = await self.query.page(nick, limit=500)
        items = page.get("items") or []
        if fmt == "text":
            return "\n".join(
                f"[{i.get('time', '')}] {i.get('from', '')}: {i.get('text', '')}"
                for i in items
            )
        if fmt == "csv":
            rows = ["time,from,text"] + [
                json.dumps(
                    [i.get("time", ""), i.get("from", ""), i.get("text", "")],
                    ensure_ascii=False,
                )[1:-1]
                for i in items
            ]
            return "\n".join(rows)
        return json.dumps(page, ensure_ascii=False)
