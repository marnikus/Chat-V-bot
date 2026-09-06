"""Collect Message History — archive the conversation that is open now.

One implementation, two triggers: this block runs exactly the same parser and
repository the passive collector uses, so a manual run and background
collection can never disagree about what is already stored.

House rules it follows:
  * RULE 4 — "nothing new" is an OK result with an explanation; "this is not
    a private chat" is a loud failure. They never look the same.
  * RULE 5 — progress is reported per chunk while it runs.
  * RULE 7 — a stop is reported as stopped (with the partial archive kept),
    never as a failure.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from actions.base_action import ActionResult, BaseAction
from backend.cdp_client import CDPClient
from backend.chat_parser import sync_conversation

log = logging.getLogger("chatbot")


class CollectHistory(BaseAction):
    block_id = "COLLECT_HISTORY"
    name = "Collect Message History"
    icon = "🗃"

    #: overridable in tests so day resolution is deterministic
    now = staticmethod(datetime.now)

    def __init__(self, target: str = "active", mode: str = "incremental",
                 require_private: bool = True, max_messages: int = 0,
                 chunk_size: int = 80, chunk_pause_ms: int = 40,
                 download_media: bool = True, fail_if_empty: bool = False,
                 **kwargs):
        super().__init__(**kwargs)
        self.target = str(target or "active")
        self.mode = str(mode or "incremental")
        self.require_private = bool(require_private)
        self.max_messages = int(max_messages or 0)
        self.chunk_size = max(1, int(chunk_size or 80))
        self.chunk_pause_ms = max(0, int(chunk_pause_ms or 0))
        self.download_media = bool(download_media)
        self.fail_if_empty = bool(fail_if_empty)

    # ── configuration ────────────────────────────────────────────
    def config_schema(self) -> dict:
        schema = super().config_schema()
        schema.update({
            "target": {"type": "select", "default": "active",
                       "options": ["active", "memory_nick"],
                       "label": "Archive for",
                       "help": "active = whoever the open tab is with; "
                               "memory_nick = the {{nick}} of this run "
                               "(refuses to file under the wrong person)"},
            "mode": {"type": "select", "default": "incremental",
                     "options": ["incremental", "full"],
                     "label": "Mode",
                     "help": "incremental = append new lines only; "
                             "full = re-read the whole visible conversation"},
            "require_private": {"type": "bool", "default": True,
                                "label": "Only private chats"},
            "max_messages": {"type": "number", "default": 0,
                             "label": "Max messages (0 = all)"},
            "chunk_size": {"type": "number", "default": 80,
                           "label": "Chunk size"},
            "chunk_pause_ms": {"type": "number", "default": 40,
                               "label": "Pause between chunks (ms)"},
            "download_media": {"type": "bool", "default": True,
                               "label": "Cache images / GIFs"},
            "fail_if_empty": {"type": "bool", "default": False,
                              "label": "Fail when nothing new"},
        })
        return schema

    def to_dict(self) -> dict:
        data = super().to_dict()
        data.pop("now", None)
        return data

    # ── execution ────────────────────────────────────────────────
    async def execute(self, user_nick: str, cdp: CDPClient,
                      engine: Optional[object] = None) -> str:
        await self.pre_delay()
        report = getattr(engine, "report", None) or (lambda *_a, **_k: None)

        service = getattr(engine, "history", None) if engine else None
        if service is None:
            report("❌ Collect Message History: the message archive service "
                   "is not available in this run", "error")
            return ActionResult.FAIL
        if not getattr(service, "enabled", True):
            report("❌ Collect Message History: the archive is disabled in "
                   "the settings — nothing was collected", "error")
            return ActionResult.FAIL

        repo = getattr(service, "repo", None)
        parser = getattr(service, "parser", None)
        if repo is None or parser is None:
            report("❌ Collect Message History: the archive service is "
                   "incomplete (no repository or parser)", "error")
            return ActionResult.FAIL

        state = await parser.state()
        if not int(state.get("agent") or 0):
            await parser.install()
            state = await parser.state()
        partner = " ".join(str(state.get("partner") or "").split()).strip()
        my_nick = (getattr(service, "my_nick", "") or
                   " ".join(str(state.get("me") or "").split()).strip())

        if self.require_private and state.get("tab") != "private":
            report("❌ Collect Message History: the active tab is not a "
                   "private chat — nothing was collected", "error")
            return ActionResult.FAIL

        nick = partner
        verify = False
        if self.target == "memory_nick":
            nick = (getattr(engine, "selected_nick", "") or "").strip()
            if not nick:
                report("❌ Collect Message History: no nick is saved in "
                       "memory this run — add a Pick Person / Click User "
                       "block before it", "error")
                return ActionResult.FAIL
            verify = True
        if not nick:
            report("❌ Collect Message History: could not tell who this "
                   "conversation is with", "error")
            return ActionResult.FAIL
        if verify and nick.strip().lower() != partner.strip().lower():
            report(f"❌ Collect Message History: nick mismatch — memory says "
                   f"“{nick}” but the open chat is with “{partner}”; nothing "
                   f"was written", "error")
            return ActionResult.FAIL

        parser.chunk_size = self.chunk_size
        parser.chunk_pause_ms = self.chunk_pause_ms
        if self.mode == "full":
            await repo.reset_cursor(nick)

        report(f"🗃 Collecting message history with “{nick}” "
               f"({state.get('count', 0)} visible)…", "info")

        def progress(done: int, total: int) -> None:
            report(f"🗃 “{nick}”: {done}/{total} messages read", "info")

        stopping = getattr(engine, "is_stopping", None)
        result = await sync_conversation(
            parser, repo, nick, my_nick=my_nick,
            require_private=self.require_private, verify_partner=verify,
            max_messages=self.max_messages or None,
            chunk_pause_ms=self.chunk_pause_ms,
            should_stop=stopping, on_progress=progress, now=self.now())

        if not result.ok:
            if result.reason == "not_private":
                report("❌ Collect Message History: the active tab is not a "
                       "private chat — nothing was collected", "error")
            elif result.reason == "partner_mismatch":
                report(f"❌ Collect Message History: nick mismatch — the open "
                       f"chat is not with “{nick}”; nothing was written",
                       "error")
            else:
                report(f"❌ Collect Message History failed: "
                       f"{result.reason or 'unknown reason'}", "error")
            return ActionResult.FAIL

        media = getattr(service, "media", None)
        if media is not None and self.download_media:
            try:
                cached = await media.process_pending()
                if cached:
                    report(f"🖼 Cached {cached} image(s)/GIF(s) for “{nick}”",
                           "info")
            except Exception as e:                    # noqa: BLE001
                log.debug("media caching skipped: %s", e)

        if result.stopped:
            report(f"⏹ Collect Message History stopped on request — "
                   f"{result.added} new message(s) kept for “{nick}” "
                   f"({result.total} in the archive)", "success")
            return ActionResult.OK
        if result.gap:
            report("⚠ Part of the conversation was not visible — a gap was "
                   "recorded in the archive", "info")
        if result.added:
            report(f"✅ Archived {result.added} new message(s) for “{nick}” "
                   f"— {result.total} stored in total", "success")
            return ActionResult.OK
        if self.fail_if_empty:
            report(f"❌ No new messages for “{nick}” and the block is set to "
                   f"fail when nothing new arrives", "error")
            return ActionResult.FAIL
        report(f"ℹ No new messages for “{nick}” — the archive already has "
               f"all {result.total}", "success")
        return ActionResult.OK
