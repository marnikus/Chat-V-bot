"""BotPromptBridge — the Grok Prompt Editor window's wire.

Its own bridge because it is its own window: the Prompt Editor is opened by
the `[edit]` buttons beside the Bot Chat actions and is never embedded in
them, so the two wires are separated for the same reason the two windows are.
It also keeps each class inside RULE 16's method budget, which one combined
bridge no longer was.

What it owns: the two editable templates, their saved PRESETS, the variable
library the editor lists, the live preview of exactly what would be sent, and
which connection is selected.

It owns no API key and no endpoint. Those moved to the AI Connections window
(`BotSettingsBridge`) so the editor holds prompt controls only — the two
slots that used to read and write the key here were deleted, not hidden.

The API key travels ONE way. `bot_connection` reports whether a key is set
and which model is used, never the key itself, so a saved secret is never
echoed back into the DOM or a log line.
"""

from __future__ import annotations

import json
import logging

from PySide6.QtCore import Signal, Slot

from bridge.bot_bridge import BotSideBridge, schedule
from services import bot_variables
from services.bot_presets import PresetLibrary

log = logging.getLogger("chatbot")


class BotPromptBridge(BotSideBridge):
    #: Only ONE new signal: the preview answers on the Bot Chat bridge's
    #: `bot_reply_ready` / `bot_error`, because the router exposes one signal
    #: of each name and JS listens to it once. `req_id` already keeps the two
    #: windows' answers apart, which is the whole point of that pattern.
    bot_prompts_changed = Signal(str)        # JSON: every template

    @property
    def _prompts(self):
        """The template library, borrowed from the Bot Chat service.

        One library, so a template saved here is the one the other window
        renders on its very next call — no second copy to keep in step.
        """
        return self._chat_bridge().service.prompts

    @property
    def _presets(self) -> PresetLibrary:
        """The saved wordings of the templates."""
        return PresetLibrary(self.ctx.config)

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

    @Slot(str, str, str, str)
    def bot_preview_prompt(self, req_id, nick, template_id, scope):
        """Exactly what would be sent for this person, right now."""
        owner = self._chat_bridge()
        schedule(owner, req_id,
                 owner.service.preview(nick, template_id, scope))

    # ── the variable library ─────────────────────────────────────
    @Slot(result=str)
    def bot_get_variables(self):
        """Every placeholder a template may use, with a description.

        Served from `bot_variables`, which is also what resolves them, so the
        editor cannot list a variable that would not work.
        """
        return json.dumps(bot_variables.catalog(), ensure_ascii=False)

    @Slot(str, result=str)
    def bot_check_prompt(self, text):
        """Which placeholders are recognised, unknown or malformed.

        A warning only — the editor still saves the template. Refusing the
        save is what used to throw the user's work away.
        """
        return json.dumps(bot_variables.validate(text), ensure_ascii=False)

    # ── presets ──────────────────────────────────────────────────
    @Slot(str, result=str)
    def bot_get_presets(self, template_id):
        """Every saved preset for one template."""
        return json.dumps(self._presets.for_template(template_id),
                          ensure_ascii=False)

    @Slot(str, str, str, str, result=str)
    def bot_save_preset(self, template_id, title, text, ident):
        """Create a preset, or update `ident`. Returns the id ("" = refused)."""
        return str(self._presets.save(template_id, title, text, ident))

    @Slot(str, result=bool)
    def bot_delete_preset(self, ident):
        """Delete one preset. Touches no connection and no API key (I-30)."""
        return bool(self._presets.delete(ident))
