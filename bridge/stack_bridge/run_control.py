"""Starting, stopping and snapshotting a run.

`RunControlMixin` owns the run slots: `run_stack` (validate the JSON,
normalise it, hand it to the engine, remember it as the last stack),
the three engine controls, the engine's current stack as JSON, and the
debounced last-session snapshot. Wrong-shaped JSON must not execute
anything or touch config.
"""

from __future__ import annotations

import json

from PySide6.QtCore import Slot


class RunControlMixin:
    # ── run / pause / stop ───────────────────────────────────────
    @Slot(str)
    def run_stack(self, stack_json):
        engine = self.ctx.engine
        if engine.is_running:
            self._log("⚠ Already running", "warn")
            return
        try:
            blocks = json.loads(stack_json)
        except json.JSONDecodeError:
            self._log("❌ Bad JSON", "error")
            return
        if not isinstance(blocks, list):
            # Wrong-shaped JSON must not execute anything or touch config
            # (a dict/string/number used to reach normalize_blocks, which
            # silently ran an empty stack or raised TypeError on numbers).
            self._log("❌ Stack is not a list of blocks", "error")
            return
        blocks = self._clean_blocks(blocks)
        engine.load_stack(blocks)
        self.ctx.config.set_state(last_stack=blocks,
                                  last_stack_preset="")
        self._schedule(engine.execute())

    @Slot()
    def stop_stack(self):
        self.ctx.engine.stop()

    @Slot()
    def pause_stack(self):
        self.ctx.engine.pause()

    @Slot()
    def resume_stack(self):
        self.ctx.engine.resume()

    # ── engine current stack (compat helper) ─────────────────────
    @Slot(result=str)
    def get_stack_json(self):
        return json.dumps(self.ctx.engine.get_stack(), ensure_ascii=False)

    # ── last-session stack snapshot ──────────────────────────────
    @Slot(str)
    def snapshot_stack(self, stack_json):
        """Persist the current stack for the next session (debounced)."""
        try:
            blocks = json.loads(stack_json or "[]")
        except json.JSONDecodeError:
            return
        if not isinstance(blocks, list):
            return
        # App.recordGlobal() already recorded the edit; this is only the
        # last-session snapshot and must not create a second entry.
        self.ctx.config.set_state(last_stack=self._clean_blocks(blocks),
                                  last_stack_preset="")
