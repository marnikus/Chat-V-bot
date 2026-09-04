"""Action stack executor: runs blocks sequentially over queued users."""

import asyncio
import json
import logging
from typing import Callable, Optional
from PySide6.QtCore import QObject, Signal
from backend.cdp_client import CDPClient
from backend.user_memory import UserMemory, UserRecord
from backend.scroll_parser import ScrollParser
from backend.criteria_engine import CriteriaEngine
from actions.base_action import BaseAction, ActionResult, get_action_class

log = logging.getLogger("chatbot")


class ActionEngine(QObject):
    """Execute a stack of action blocks over a user queue."""

    step_complete = Signal(str, str)   # block_name, user_nick
    user_complete = Signal(str, bool)  # user_nick, success
    stack_complete = Signal()
    log_msg = Signal(str)

    def __init__(self, cdp: CDPClient, memory: UserMemory,
                 criteria: CriteriaEngine, parent: QObject | None = None):
        super().__init__(parent)
        self._cdp = cdp
        self._memory = memory
        self._criteria = criteria
        self._stack: list[BaseAction] = []
        self._running = False
        self._paused = False
        self._stop_requested = False

    # ── stack management ─────────────────────────────────────────
    def load_stack(self, blocks: list[dict]) -> None:
        """Build action list from block config dicts."""
        self._stack.clear()
        for b in blocks:
            cls = get_action_class(b.get("block_id", ""))
            if cls:
                self._stack.append(cls(**{k: v for k, v in b.items() if k != "block_id"}))
        log.info("Stack loaded: %d blocks", len(self._stack))

    def get_stack(self) -> list[dict]:
        return [a.to_dict() for a in self._stack]

    # ── execution control ────────────────────────────────────────
    @property
    def is_running(self) -> bool:
        return self._running

    def stop(self) -> None:
        self._stop_requested = True

    def pause(self) -> None:
        self._paused = True

    def resume(self) -> None:
        self._paused = False

    # ── main execution loop ──────────────────────────────────────
    async def execute(self, scroll_parser: ScrollParser | None = None) -> None:
        """Run the full stack over the user queue."""
        self._running = True
        self._stop_requested = False
        try:
            self.log_msg.emit(f"━━━ Stack start: {len(self._stack)} blocks ━━━")
            for i, b in enumerate(self._stack):
                cfg = {k:v for k,v in b.to_dict().items() if k not in ('block_id','pre_delay_ms')}
                cfg_str = ', '.join(f'{k}={str(v)[:25]}' for k,v in cfg.items())
                self.log_msg.emit(f"  [{i+1}] {b.icon} {b.name}" + (f" ({cfg_str})" if cfg_str else ""))
            # Phase 1: parse users if SCROLL_PARSE block exists
            has_scroll = any(b.block_id == "SCROLL_PARSE" for b in self._stack)
            if has_scroll and scroll_parser:
                self.log_msg.emit("📜 Starting user parse...")
                all_u, filtered = await scroll_parser.parse()
                for u in all_u:
                    await self._memory.upsert_user(u)
                self.log_msg.emit(f"📜 Found {len(all_u)} users, {len(filtered)} passed criteria")
            # Phase 2: get queue
            queue = await self._memory.get_queue()
            has_skip = any(b.block_id == "CONDITIONAL_SKIP" for b in self._stack)
            self.log_msg.emit(f"▶ Running stack on {len(queue)} users")
            # Phase 3: execute loop
            for user in queue:
                if self._stop_requested:
                    self.log_msg.emit("⏹ Stack stopped by user")
                    break
                while self._paused:
                    await asyncio.sleep(0.2)
                    if self._stop_requested:
                        break
                if self._stop_requested:
                    break
                success = await self._execute_for_user(user, has_skip)
                if success:
                    await self._memory.mark_messaged(user.nick)
                self.user_complete.emit(user.nick, success)
        except Exception as exc:
            log.error("Stack execution error: %s", exc, exc_info=True)
            self.log_msg.emit(f"❌ Error: {exc}")
        finally:
            self._running = False
            self.stack_complete.emit()
            self.log_msg.emit("✅ Stack execution complete")

    async def _execute_for_user(self, user: UserRecord, has_skip: bool) -> bool:
        """Execute all blocks for one user."""
        if user.messaged and has_skip:
            self.log_msg.emit(f"⏭ Skipping (already messaged): {user.nick}")
            return False
        self.log_msg.emit(f"👤 Processing: {user.nick}")
        for idx, block in enumerate(self._stack):
            if self._stop_requested:
                self.log_msg.emit(f"  ⏹ Stopped at block {idx+1}")
                return False
            while self._paused:
                await asyncio.sleep(0.2)
            if block.block_id == "CONDITIONAL_SKIP":
                if user.messaged:
                    self.log_msg.emit(f"  ⏭ Conditional skip: {user.nick}")
                    return False
                continue
            if block.block_id == "SCROLL_PARSE":
                continue
            try:
                self.log_msg.emit(f"  ▶ [{idx+1}] {block.icon} {block.name}...")
                result = await block.execute(user.nick, self._cdp)
                self.step_complete.emit(block.name, user.nick)
                if result == ActionResult.OK:
                    self.log_msg.emit(f"  ✅ [{idx+1}] {block.name} → OK")
                elif result == ActionResult.SKIP:
                    self.log_msg.emit(f"  ⏭ [{idx+1}] {block.name} → SKIP")
                else:
                    self.log_msg.emit(f"  ❌ [{idx+1}] {block.name} → FAIL")
                    return False
            except Exception as exc:
                self.log_msg.emit(f"  ❌ [{idx+1}] {block.name} CRASHED: {exc}")
                log.error("Block %s error: %s", block.name, exc, exc_info=True)
                return False
        self.log_msg.emit(f"  ✅ Message sent to {user.nick}")
        return True
