"""BotBridge — the AI Bot Chat and Prompt Editor windows' wire.

Reads and Grok calls are asynchronous, so a @Slot cannot answer inline: JS
passes a `req_id` and Python answers on `bot_reply_ready` carrying the same
id (the pattern HistoryBridge established — two windows can ask at once
without answers crossing). Failures answer on `bot_error`, so a window can
say *why* it has no suggestion (RULE 4) instead of waiting forever.

The two windows share one bridge because they share one service: the Prompt
Editor edits the templates this bridge renders. The answering plumbing sits
in module functions rather than methods, so the class stays inside RULE 16's
method budget with room for the slots the wire actually needs.
"""

from __future__ import annotations

import asyncio
import json
import logging

from PySide6.QtCore import QObject, Signal, Slot

from core.events import LogMessage
from services.bot_chat import BotChatService, deliver

log = logging.getLogger("chatbot")


def _emit_answer(bridge, req_id: str, result) -> None:
    """One Result → one signal. An `Err` never reaches the UI as silence."""
    if getattr(result, "is_err", False):
        bridge.bot_error.emit(req_id, result.detail or result.code)
        bridge.ctx.bus.emit(LogMessage(message=f"🤖 {result.detail}",
                                       level="warn"))
        return
    value = getattr(result, "value", result)
    bridge.bot_reply_ready.emit(req_id, json.dumps(value, ensure_ascii=False))


async def _guarded(bridge, req_id: str, coro) -> None:
    """Await one use case; a raising service becomes an error on the wire."""
    try:
        _emit_answer(bridge, req_id, await coro)
    except Exception as exc:                            # noqa: BLE001
        log.warning("bot request failed: %s", exc)
        bridge.bot_error.emit(req_id, str(exc)[:200])


def _schedule(bridge, req_id: str, coro) -> None:
    try:
        asyncio.ensure_future(_guarded(bridge, req_id, coro))
    except RuntimeError:
        coro.close()


class BotBridge(QObject):
    bot_reply_ready = Signal(str, str)       # req_id, JSON payload
    bot_error = Signal(str, str)             # req_id, message
    bot_prompts_changed = Signal(str)        # JSON: every template

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self._service: BotChatService | None = None

    @property
    def service(self) -> BotChatService:
        """Built lazily: the archive is attached after the bridges exist."""
        if self._service is None:
            self._service = BotChatService(archive=self.ctx.archive,
                                           config=self.ctx.config)
        self._service.archive = self.ctx.archive
        return self._service

    # ── the AI Bot Chat window ───────────────────────────────────
    @Slot(str, str)
    def bot_load_today(self, req_id, nick):
        """The current day's messages of this person."""
        _schedule(self, req_id, self.service.today(nick))

    @Slot(str, str)
    def bot_suggest_reply(self, req_id, nick):
        """Ask Grok for a reply; it arrives PENDING, nothing is sent."""
        _schedule(self, req_id, self.service.suggest_reply(nick))

    @Slot(str, str)
    def bot_analyze_reaction(self, req_id, nick):
        """Ask Grok to classify the last answer. No label is written."""
        _schedule(self, req_id, self.service.analyze_reaction(nick))

    @Slot(str, str, str)
    def bot_preview_prompt(self, req_id, nick, template_id):
        """Exactly what would be sent to Grok, for the Prompt Editor."""
        _schedule(self, req_id, self.service.preview(nick, template_id))

    @Slot(str, str)
    def bot_send_message(self, req_id, text):
        """Deliver text — an approved AI reply or a direct custom message.

        Separate from approval on purpose: approving a suggestion only
        enables the button whose click lands here.
        """
        _schedule(self, req_id, deliver(self.ctx.cdp, text))

    # ── reaction labels ──────────────────────────────────────────
    @Slot(str, result=str)
    def bot_reaction_state(self, nick):
        return json.dumps(self.service.reaction_state(nick),
                          ensure_ascii=False)

    @Slot(str, str, result=str)
    def bot_apply_reaction(self, nick, reaction):
        """Confirmed analysis OR manual click — the latest one wins."""
        result = self.service.apply_reaction(nick, reaction)
        if result.is_err:
            self.ctx.bus.emit(LogMessage(message=f"🤖 {result.detail}",
                                         level="warn"))
            return json.dumps({"error": result.code}, ensure_ascii=False)
        if result.value.get("changed"):
            self.ctx.bus.emit(LogMessage(
                message=f"🏷 {nick}: “{reaction} first reaction” applied",
                level="success"))
        return json.dumps(result.value, ensure_ascii=False)

    # ── the Prompt Editor window ─────────────────────────────────
    @Slot(result=str)
    def bot_get_prompts(self):
        return json.dumps(self.service.prompts.all(), ensure_ascii=False)

    @Slot(str, str, result=bool)
    def bot_save_prompt(self, template_id, text):
        saved = self.service.prompts.save(template_id, text)
        if saved:
            self.bot_prompts_changed.emit(self.bot_get_prompts())
        return saved

    @Slot(str, result=bool)
    def bot_reset_prompt(self, template_id):
        reset = self.service.prompts.reset(template_id)
        if reset:
            self.bot_prompts_changed.emit(self.bot_get_prompts())
        return reset
