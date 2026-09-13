"""The archive's own settings, with and without a running archive.

`SettingsMixin` reads and writes the archive configuration: through the
service when the world is open, through the config file when it is not,
so the window still shows and keeps its settings before the first
database exists.
"""

from __future__ import annotations

import json

from PySide6.QtCore import Slot

from core.events import LogMessage


class SettingsMixin:
    # ── archive settings ─────────────────────────────────────────
    @Slot(result=str)
    def get_history_settings(self):
        if self.ctx.archive is None:
            return json.dumps(self.ctx.config.get_copy("history",
                                                       default={}))
        return json.dumps(self.ctx.archive.settings(), ensure_ascii=False)

    @Slot(str)
    def save_history_settings(self, settings_json):
        patch = self._json_arg(settings_json)
        if self.ctx.archive is None:
            stored = self.ctx.config.get_copy("history", default={})
            stored.update(patch)
            self.ctx.config.set("history", stored)
            self.ctx.config.save()
            return
        self.ctx.archive.apply_settings(patch)
        self.ctx.bus.emit(LogMessage(message="💾 Archive settings saved",
                                     level="info"))
