"""BotPromptBridge — the Grok Prompt Editor window's wire.

Its own bridge because it is its own window: the Prompt Editor is opened by
the `[edit]` buttons beside the Bot Chat actions and is never embedded in
them, so the two wires are separated for the same reason the two windows are.
It also keeps each class inside RULE 16's method budget, which one combined
bridge no longer was.

What it owns: the two editable templates, the live preview of exactly what
would be sent to Grok, and the connection settings (API key, model) — without
which the feature cannot make a single call.

The API key travels ONE way. `bot_connection` reports whether a key is set
and which model is used, never the key itself, so a saved secret is never
echoed back into the DOM or a log line.
"""

from __future__ import annotations

import json
import logging

from PySide6.QtCore import QObject, Signal, Slot

from bridge.bot_bridge import schedule
from services.bot_grok import GrokSettings

log = logging.getLogger("chatbot")


class BotPromptBridge(QObject):
    #: Only ONE new signal: the preview answers on the Bot Chat bridge's
    #: `bot_reply_ready` / `bot_error`, because the router exposes one signal
    #: of each name and JS listens to it once. `req_id` already keeps the two
    #: windows' answers apart, which is the whole point of that pattern.
    bot_prompts_changed = Signal(str)        # JSON: every template

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self._fallback = None

    def _chat_bridge(self):
        """The Bot Chat bridge — owner of the service and of the two signals
        a preview answers on.

        Must be the SAME object every time: a preview answers on its signals,
        so handing out a fresh bridge per call would emit the answer into an
        object nobody is connected to. The router already caches its bridges;
        without one, this caches its own.
        """
        from bridge.bot_bridge import BotBridge
        getter = getattr(self.parent(), "_bridge", None)
        if getter is not None:
            return getter(BotBridge)
        if self._fallback is None:
            self._fallback = BotBridge(self.ctx, parent=self)
        return self._fallback

    @property
    def _prompts(self):
        """The template library, borrowed from the Bot Chat service.

        One library, so a template saved here is the one the other window
        renders on its very next call — no second copy to keep in step.
        """
        return self._chat_bridge().service.prompts

    @property
    def _settings(self) -> GrokSettings:
        """Read from the CONFIG: the connection outlives any one transport."""
        return GrokSettings(self.ctx.config)

    # ── templates ────────────────────────────────────────────────
    @Slot(result=str)
    def bot_get_prompts(self):
        return json.dumps(self._prompts.all(), ensure_ascii=False)

    @Slot(str, str, result=bool)
    def bot_save_prompt(self, template_id, text):
        """Persist an edited template; a broken one is refused, not stored."""
        saved = self._prompts.save(template_id, text)
        if saved:
            self.bot_prompts_changed.emit(self.bot_get_prompts())
        return saved

    @Slot(str, result=bool)
    def bot_reset_prompt(self, template_id):
        """Forget the user's edit so the shipped template is used again."""
        reset = self._prompts.reset(template_id)
        if reset:
            self.bot_prompts_changed.emit(self.bot_get_prompts())
        return reset

    @Slot(str, str, str)
    def bot_preview_prompt(self, req_id, nick, template_id):
        """Exactly what would be sent to Grok for this person, right now."""
        owner = self._chat_bridge()
        schedule(owner, req_id, owner.service.preview(nick, template_id))

    # ── connection ───────────────────────────────────────────────
    @Slot(result=str)
    def bot_connection(self):
        """Whether a key is set, and the model — never the key itself."""
        return json.dumps(self._settings.state(), ensure_ascii=False)

    @Slot(str, str, result=bool)
    def bot_save_connection(self, api_key, model):
        """Store the Grok API key / model the editor collected."""
        return bool(self._settings.save(api_key, model))
