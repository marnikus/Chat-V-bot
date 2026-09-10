"""Independent, retryable install migrations for HistoryService."""

from __future__ import annotations

import logging
import os

log = logging.getLogger("chatbot")


class HistoryMigration:
    async def migrate_install(self) -> dict:
        report = {
            "queue_merged": False,
            "labels_imported": False,
            "recent_pruned": False,
            "undo_rehomed": False,
        }
        if self.config is None:
            return report
        report["queue_merged"] = await self._migrate_queue()
        if self._labels is not None:
            report["labels_imported"] = await self._migrate_flagged(
                "labels_migrated_from_config",
                self._import_config_labels,
                "label import from config",
            )
        report["recent_pruned"] = self._prune_recent()
        report["undo_rehomed"] = await self._migrate_flagged(
            "undo_migrated_v6", self._rehome_undo_entries, "undo re-home"
        )
        if any(report.values()):
            log.info(
                "unified-DB migration: %s",
                ", ".join(key for key, changed in report.items() if changed),
            )
        return report

    async def _migrate_queue(self) -> bool:
        legacy = str(getattr(self.memory, "db_path", "") or "")
        if not legacy or not os.path.exists(legacy):
            return False
        if os.path.abspath(legacy) == os.path.abspath(self.db.path):
            return False
        try:
            await self._merge_legacy_queue(legacy)
            return True
        except Exception as exc:
            log.warning("queue merge from %s failed: %s", legacy, exc)
            return False

    async def _migrate_flagged(self, flag, operation, label) -> bool:
        if await self.get_meta_flag(flag):
            return False
        try:
            if await operation():
                await self.set_meta_flag(flag)
                return True
        except Exception as exc:
            log.warning("%s failed: %s", label, exc)
        return False

    def _prune_recent(self) -> bool:
        try:
            raw = self.config.get_state("db_recent", [])
            if not isinstance(raw, list):
                return False
            kept = [
                path
                for path in raw
                if isinstance(path, str) and path and os.path.exists(path)
            ]
            if len(kept) != len(raw):
                self.config.set_state(db_recent=kept[:12])
                return True
        except Exception as exc:
            log.debug("db_recent prune failed: %s", exc)
        return False
