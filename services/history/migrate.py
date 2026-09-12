"""HistoryMigration — the one-time unified-DB install migration (AREA C).

`migrate_install` used to live in `mutate.py`, then in `runtime.py` next to
the switchers and the exporter. It is its own responsibility — the things a
world needs *once*, when an install predates the unified DB — so it moved
here when `runtime.py` reached the RULE 18 300-line mark.

The collaborator takes the host `HistoryService` and calls back into it
(`_merge_legacy_queue`, `_import_config_labels`, `_rehome_undo_entries`);
imports point down only — no Qt, no `bridge/`.
"""

from __future__ import annotations

import logging
import os

log = logging.getLogger("chatbot")


class HistoryMigration:
    """The one-time unified-DB install migration."""

    def __init__(self, host):
        self._host = host

    async def run(self) -> dict:
        """Merge a legacy queue / labels / prune ghosts / re-home undo."""
        host = self._host
        report = {"queue_merged": False, "labels_imported": False,
                  "recent_pruned": False, "undo_rehomed": False}
        if host.config is None:
            return report
        if await self._merge_queue(report):
            report["queue_merged"] = True
        await self._import_labels(report)
        await self._prune_recent(report)
        await self._rehome_undo(report)
        if any(report.values()):
            log.info("unified-DB migration: %s",
                     ", ".join(k for k, v in report.items() if v))
        return report

    async def _merge_queue(self, report: dict) -> bool:
        host = self._host
        legacy = str(getattr(host.memory, "db_path", "") or "") \
            if host.memory is not None else ""
        if not (legacy and os.path.exists(legacy)
                and os.path.abspath(legacy) != os.path.abspath(host.db.path)):
            return False
        try:
            await host._merge_legacy_queue(legacy)
            return True
        except Exception as exc:                       # noqa: BLE001
            log.warning("queue merge from %s failed: %s", legacy, exc)
            return False

    async def _import_labels(self, report: dict) -> None:
        host = self._host
        if host._labels is None or \
                await host.get_meta_flag("labels_migrated_from_config"):
            return
        try:
            if await host._import_config_labels():
                report["labels_imported"] = True
                await host.set_meta_flag("labels_migrated_from_config")
        except Exception as exc:                       # noqa: BLE001
            log.warning("label import from config failed: %s", exc)

    async def _prune_recent(self, report: dict) -> None:
        host = self._host
        try:
            raw = host.config.get_state("db_recent", [])
            if isinstance(raw, list):
                kept = [p for p in raw
                        if isinstance(p, str) and p and os.path.exists(p)]
                if len(kept) != len(raw):
                    host.config.set_state(db_recent=kept[:12])
                    report["recent_pruned"] = True
        except Exception as exc:                       # noqa: BLE001
            log.debug("db_recent prune failed: %s", exc)

    async def _rehome_undo(self, report: dict) -> None:
        host = self._host
        if await host.get_meta_flag("undo_migrated_v6"):
            return
        try:
            if await host._rehome_undo_entries():
                report["undo_rehomed"] = True
                await host.set_meta_flag("undo_migrated_v6")
        except Exception as exc:                       # noqa: BLE001
            log.warning("undo re-home failed: %s", exc)
