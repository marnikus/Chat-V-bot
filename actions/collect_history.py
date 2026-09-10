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
        """Archive the open conversation, and say what happened.

        Four steps, in the order the run console reads them: make sure the
        archive service is usable, work out WHO the open chat is with, read it,
        then report the outcome. Each one owns its refusal messages — RULE 4
        ("nothing new" is an OK with an explanation, "wrong chat" is a failure)
        is a property of the reporting step, not something every branch has to
        remember.
        """
        await self.pre_delay()
        run = _CollectRun(self, engine)
        if not run.attach_service():
            return ActionResult.FAIL
        if not await run.find_target():
            return ActionResult.FAIL
        await run.collect()
        return await run.report_outcome()


class _CollectRun:
    """One execution of the block: the settings, the service and the result.

    The steps below all need the same five things (the block, the engine's
    `report`, the service, the nick, the sync result), which is why they are
    methods of one small object instead of four functions with six arguments.
    """

    def __init__(self, block: CollectHistory, engine):
        self.block = block
        self.engine = engine
        self.report = getattr(engine, "report", None) or (lambda *_a, **_k: None)
        self.service = None
        self.repo = None
        self.parser = None
        self.partner = ""
        self.my_nick = ""
        self.nick = ""
        self.verify = False
        self.result = None
        self.state: dict = {}

    def say(self, message: str, level: str = "info") -> None:
        self.report(message, level)

    # ── step 1: is the archive reachable? ────────────────────────
    def attach_service(self) -> bool:
        engine = self.engine
        service = getattr(engine, "history", None) if engine else None
        if service is None:
            self.say("❌ Collect Message History: the message archive service "
                     "is not available in this run", "error")
            return False
        if not getattr(service, "enabled", True):
            self.say("❌ Collect Message History: the archive is disabled in "
                     "the settings — nothing was collected", "error")
            return False
        repo = getattr(service, "repo", None)
        parser = getattr(service, "parser", None)
        if repo is None or parser is None:
            self.say("❌ Collect Message History: the archive service is "
                     "incomplete (no repository or parser)", "error")
            return False
        self.service, self.repo, self.parser = service, repo, parser
        return True

    # ── step 2: who is this conversation with? ───────────────────
    async def find_target(self) -> bool:
        """The page's partner, cross-checked against what the run remembers.

        `target="memory_nick"` is the mode that must never file messages under
        the wrong person, so it refuses on a mismatch instead of trusting
        either side (RULE 6 in the house rules for this block).
        """
        block = self.block
        state = await self._open_page()
        self.partner = " ".join(str(state.get("partner") or "").split()).strip()
        self.my_nick = (getattr(self.service, "my_nick", "")
                        or " ".join(str(state.get("me") or "").split()).strip())
        self.state = state
        if block.require_private and state.get("tab") != "private":
            self.say("❌ Collect Message History: the active tab is not a "
                     "private chat — nothing was collected", "error")
            return False
        self.nick = self.partner
        if block.target == "memory_nick" and not self._take_memory_nick():
            return False
        if not self.nick:
            self.say("❌ Collect Message History: could not tell who this "
                     "conversation is with", "error")
            return False
        return not self._mismatch()

    async def _open_page(self) -> dict:
        state = await self.parser.state()
        if not int(state.get("agent") or 0):
            await self.parser.install()
            state = await self.parser.state()
        return state

    def _take_memory_nick(self) -> bool:
        nick = (getattr(self.engine, "selected_nick", "") or "").strip()
        if not nick:
            self.say("❌ Collect Message History: no nick is saved in "
                     "memory this run — add a Pick Person / Click User "
                     "block before it", "error")
            return False
        self.nick = nick
        self.verify = True
        return True

    def _mismatch(self) -> bool:
        """True when memory and the open tab disagree (and the run must stop)."""
        if not self.verify:
            return False
        if self.nick.strip().lower() == self.partner.strip().lower():
            return False
        self.say(f"❌ Collect Message History: nick mismatch — memory says "
                 f"“{self.nick}” but the open chat is with “{self.partner}”; "
                 f"nothing was written", "error")
        return True

    # ── step 3: read it ──────────────────────────────────────────
    async def collect(self) -> None:
        block, repo, parser = self.block, self.repo, self.parser
        parser.chunk_size = block.chunk_size
        parser.chunk_pause_ms = block.chunk_pause_ms
        if block.mode == "full":
            await repo.reset_cursor(self.nick)
        self.say(f"🗃 Collecting message history with “{self.nick}” "
                 f"({self.state.get('count', 0)} visible)…", "info")
        stopping = getattr(self.engine, "is_stopping", None)
        self.result = await sync_conversation(
            parser, repo, self.nick, my_nick=self.my_nick,
            require_private=block.require_private, verify_partner=self.verify,
            max_messages=block.max_messages or None,
            chunk_pause_ms=block.chunk_pause_ms, should_stop=stopping,
            on_progress=self._progress, now=block.now(),
            backfill_older=(block.mode == "full"),
            media=repo.media if block.download_media else None)

    def _progress(self, done: int, total: int) -> None:
        """RULE 5: every chunk, as it lands."""
        self.say(f"🗃 “{self.nick}”: {done}/{total} messages read", "info")

    # ── step 4: what does the user see? ──────────────────────────
    async def report_outcome(self) -> str:
        result = self.result
        if not result.ok:
            return self._refusal()
        await self._cache_media()
        if result.stopped:
            self.say(f"⏹ Collect Message History stopped on request — "
                     f"{result.added} new message(s) kept for “{self.nick}” "
                     f"({result.total} in the archive)", "success")
            return ActionResult.OK
        if result.gap:
            self.say("⚠ Part of the conversation was not visible — a gap was "
                     "recorded in the archive", "info")
        if result.added:
            self.say(f"✅ Archived {result.added} new message(s) for "
                     f"“{self.nick}” — {result.total} stored in total",
                     "success")
            return ActionResult.OK
        if self.block.fail_if_empty:
            self.say(f"❌ No new messages for “{self.nick}” and the block is "
                     f"set to fail when nothing new arrives", "error")
            return ActionResult.FAIL
        self.say(f"ℹ No new messages for “{self.nick}” — the archive already "
                 f"has all {result.total}", "success")
        return ActionResult.OK

    def _refusal(self) -> str:
        """The sync said no: name the reason the way the run console does."""
        result, nick = self.result, self.nick
        if result.reason == "not_private":
            self.say("❌ Collect Message History: the active tab is not a "
                     "private chat — nothing was collected", "error")
        elif result.reason == "partner_mismatch":
            self.say(f"❌ Collect Message History: nick mismatch — the open "
                     f"chat is not with “{nick}”; nothing was written",
                     "error")
        else:
            self.say(f"❌ Collect Message History failed: "
                     f"{result.reason or 'unknown reason'}", "error")
        return ActionResult.FAIL

    async def _cache_media(self) -> None:
        media = getattr(self.service, "media", None)
        if media is None or not self.block.download_media:
            return
        try:
            cached = await media.process_pending()
        except Exception as e:                        # noqa: BLE001
            log.debug("media caching skipped: %s", e)
            return
        if cached:
            self.say(f"🖼 Cached {cached} image(s)/GIF(s) for "
                     f"“{self.nick}”", "info")
