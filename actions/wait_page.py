"""Wait for a target element to appear in the DOM (with debugger detail).

Polls the DOM and reports: each probe attempt (throttled), the moment the
element is found (with visibility/interactivity state), or the timeout with
the last known DOM state so the failure can be traced.
"""

import json
import logging
import time
from typing import Optional
from actions.base_action import BaseAction, ActionResult
from actions.cancellation import (
    RunStopped,
    await_with_stop,
    check_stopped,
    sleep_with_stop,
)
from backend.cdp_client import CDPClient
from backend.dom_probe import build_probe, interpret_wait

log = logging.getLogger("chatbot")

TEXTAREA_SEL = "textarea[placeholder='Сообщение']"
TEXTAREA_FALLBACK = "textarea#mat-input-1"


class WaitPageLoad(BaseAction):
    block_id = "WAIT_PAGE_LOAD"
    name = "Wait for Page"
    icon = "⏳"

    def __init__(self, target_selector: str = "",
                 timeout_ms: int = 5000,
                 pre_delay_ms: int = 200, **kw):
        super().__init__(pre_delay_ms=pre_delay_ms, **kw)
        self.target_selector = target_selector or TEXTAREA_SEL
        self.timeout_ms = timeout_ms

    async def execute(self, user_nick: str, cdp: CDPClient,
                      engine: Optional[object] = None) -> str:
        label = f"element '{self.target_selector}'"

        def _stopped_report() -> None:
            if engine:
                engine.report(
                    f"⏹ Wait stopped on request — no longer waiting for {label}",
                    "warn",
                )

        # Already-stopped entry: no delay, no probe (C1a).
        try:
            check_stopped(engine)
        except RunStopped:
            _stopped_report()
            raise
        try:
            await sleep_with_stop(self.pre_delay_ms / 1000.0, engine)
        except RunStopped:
            _stopped_report()
            raise
        deadline = time.monotonic() + self.timeout_ms / 1000
        attempt = 0
        last_res = None
        if engine:
            engine.report(f"🔍 Waiting for {label} (timeout {self.timeout_ms} ms)...",
                          "info")
        while True:
            attempt += 1
            try:
                check_stopped(engine)
            except RunStopped:
                _stopped_report()
                raise
            try:
                raw = await await_with_stop(
                    lambda: cdp.evaluate(
                        build_probe(selector=self.target_selector)
                    ),
                    engine,
                    slice_s=0.05,
                    deadline_monotonic=deadline,
                )
                res = json.loads(raw) if raw else None
                last_res = res
            except RunStopped:
                _stopped_report()
                raise
            except TimeoutError:
                break
            except Exception as exc:
                if engine and attempt % 5 == 1:
                    engine.report(f"❌ Probe error while waiting: {exc}", "error")
                res = None
            try:
                check_stopped(engine)
            except RunStopped:
                _stopped_report()
                raise
            if res and res.get("found"):
                msg, level = interpret_wait(res, label)
                if engine:
                    engine.report(msg, level)
                log.info("Element found: %s", self.target_selector[:50])
                return ActionResult.OK
            now = time.monotonic()
            if now >= deadline:
                break
            # Report failed probes at most ~once per 2s so the console is readable
            if attempt % 7 == 1:
                total = int((res or {}).get("total", 0) or 0)
                if engine:
                    engine.report(f"⏳ {label} not present yet — matched {total} "
                                  f"node(s) (attempt {attempt})", "warn")
            try:
                await sleep_with_stop(0.3, engine, slice_s=0.05)
            except RunStopped:
                _stopped_report()
                raise
        total = int((last_res or {}).get("total", 0) or 0)
        if engine:
            engine.report(f"❌ Failed to find element: {label} — timeout after "
                          f"{self.timeout_ms} ms, selector matched {total} node(s)",
                          "error")
        log.warning("Timeout waiting for: %s", self.target_selector[:50])
        return ActionResult.FAIL

    def config_schema(self) -> dict:
        s = super().config_schema()
        s["target_selector"] = {"type": "text", "default": TEXTAREA_SEL,
                                "label": "Target selector"}
        s["timeout_ms"] = {"type": "number", "default": 5000, "label": "Timeout (ms)"}
        return s
