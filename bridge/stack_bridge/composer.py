"""The message composer's draft text.

`ComposerMixin` owns the two slots that keep what the user is typing,
mirrored onto the engine so a run can send it.
"""

from __future__ import annotations

from PySide6.QtCore import Slot


class ComposerMixin:
    # ── message composer ─────────────────────────────────────────
    @Slot(str)
    def save_message(self, text):
        self._message_text = text
        try:
            self.ctx.engine.composer_text = text
        except Exception:                               # noqa: BLE001
            pass

    @Slot(result=str)
    def get_message(self):
        return self._message_text
