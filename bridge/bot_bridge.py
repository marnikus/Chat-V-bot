"""BotBridge — the AI Bot Chat and Prompt Editor windows' wire.

Reads and Grok calls are asynchronous, so a @Slot cannot answer inline: JS
passes a `req_id` and Python answers on `bot_reply_ready` carrying the same
id (the pattern HistoryBridge established — two windows can ask at once
without answers crossing). Failures answer on `bot_error`, so a window can
say *why* it has no suggestion (RULE 4) instead of waiting forever.

This bridge is the AI Bot Chat window ALONE. The Grok Prompt Editor is a
separate window and has its own bridge (`bridge/bot_prompt_bridge.py`) — the
same separation the feature requires of the UI, and what keeps each class
inside RULE 16's method budget. The shared plumbing (`_emit_answer`,
`_guarded`, `schedule`) lives in module functions both bridges import, so
neither spends a method on it.
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


def schedule(bridge, req_id: str, coro) -> None:
    """Fire one use case off on the loop and answer on the bridge's signals.

    Public because the Prompt Editor's bridge answers the same way; a second
    copy of the req_id/guard plumbing is exactly what RULE 5 forbids.
    """
    try:
        asyncio.ensure_future(_guarded(bridge, req_id, coro))
    except RuntimeError:
        coro.close()


def label_edit_of(bridge):
    """`LabelBridge._labels_edit` — the ONE label-writing transaction.

    A label set from this window must be the same edit as one set by hand:
    one undo entry, one `LabelsChanged`, one `PeopleChanged` (RULE 12). Rather
    than copy those steps, the bot bridge borrows the method from the bridge
    that owns them.

    The router is normally the Qt parent, and going through it keeps the
    LabelBridge a singleton whose `labels_changed` is already connected to the
    router's signal. Without a router (a hand-assembled bridge) it builds one
    on the same context instead of returning None: degrading to a raw,
    unundoable write is exactly the bug this function exists to prevent.
    """
    from bridge.label_bridge import LabelBridge
    getter = getattr(bridge.parent(), "_bridge", None)
    owner = getter(LabelBridge) if getter else LabelBridge(bridge.ctx)
    return owner._labels_edit


class BotBridge(QObject):
    bot_reply_ready = Signal(str, str)       # req_id, JSON payload
    bot_error = Signal(str, str)             # req_id, message

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
        # Re-read every time: both are rebuilt on a world switch.
        self._service.label_store = self.ctx.label_store()
        self._service.edit = label_edit_of(self)
        return self._service

    # ── the AI Bot Chat window ───────────────────────────────────
    @Slot(str, str)
    def bot_load_today(self, req_id, nick):
        """The current day's messages of this person."""
        schedule(self, req_id, self.service.today(nick))

    @Slot(str, str)
    def bot_suggest_reply(self, req_id, nick):
        """Ask Grok for a reply; it arrives PENDING, nothing is sent."""
        schedule(self, req_id, self.service.suggest_reply(nick))

    @Slot(str, str)
    def bot_analyze_reaction(self, req_id, nick):
        """Ask Grok to classify the last answer. No label is written."""
        schedule(self, req_id, self.service.analyze_reaction(nick))

    @Slot(str, str, str)
    def bot_send_message(self, req_id, nick, text):
        """Deliver text — an approved AI reply or a direct custom message.

        Separate from approval on purpose: approving a suggestion only
        enables the button whose click lands here. `nick` is not decoration:
        the delivery refuses unless the chat open in the browser is really
        that person's.
        """
        schedule(self, req_id, deliver(self.ctx.cdp, nick, text,
                                        parser=self._parser))

    @property
    def _parser(self):
        """The live ChatParser the archive already owns, for the send gate."""
        return getattr(self.ctx.archive, "parser", None)

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

class BotSideBridge(QObject):
    """Base for the AI feature's SIDE windows: the Prompt Editor and the AI
    Settings dialog.

    Both are their own window with their own bridge, and both answer on
    `BotBridge`'s signals — the router exposes ONE signal of each name, so
    replies ride the chat bridge keyed by `req_id`. That shared wiring lives
    here rather than being copied into each (the clone scanner caught the
    copy, which is what it is for).
    """

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self._fallback = None

    def _chat_bridge(self):
        """The Bot Chat bridge — owner of the signals answers arrive on.

        Must be the SAME object every time or a reply is emitted into
        something nobody is connected to. The router caches its bridges;
        without one, this caches its own.
        """
        getter = getattr(self.parent(), "_bridge", None)
        if getter is not None:
            return getter(BotBridge)
        if self._fallback is None:
            self._fallback = BotBridge(self.ctx, parent=self)
        return self._fallback
