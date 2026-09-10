"""Wait for a target element to appear in the DOM (with debugger detail).

Polls the DOM and reports: each probe attempt (throttled), the moment the
element is found (with visibility/interactivity state), or the timeout with
the last known DOM state so the failure can be traced.

Cooperative cancellation (Area C1): honours engine stop via
actions.cancellation — pre-delay, probes and polling sleeps are stop-aware
and raise RunStopped (translated to stop/stopped only at run boundaries).
"""

import asyncio
import json
import logging
import time
from typing import Optional
from actions.base_action import BaseAction, ActionResult
from actions.cancellation import await_or_stop, raise_if_stopped, sleep_or_stop
from backend.cdp_client import CDPClient
from backend.dom_probe import build_probe, interpret_wait

log = logging.getLogger("chatbot")

TEXTAREA_SEL = "textarea[placeholder='Сообщение']"
TEXTAREA_FALLBACK = "textarea#mat-input-1"


class WaitPageLoad(BaseAction):
    block_id = "WAIT_PAGE_LOAD"
    name = "Wait for Page"
    icon = "⏳"

    def __init__(self, target_selector: str = "", timeout_ms: int = 5000,
                 pre_delay_ms: int = 200, **kw):
        super().__init__(pre_delay_ms=pre_delay_ms, **kw)
        self.target_selector = target_selector or TEXTAREA_SEL
        self.timeout_ms = timeout_ms

    async def execute(self, user_nick: str, cdp: CDPClient,
                      engine: Optional[object] = None) -> str:
        # Already-stopped: no delay, no probe.
        raise_if_stopped(engine)
        await sleep_or_stop(self.pre_delay_ms / 1000.0, engine, slice_s=0.05)
        label = f"element '{self.target_selector}'"
        try:
            timeout_s = max(0.0, float(self.timeout_ms) / 1000.0)
        except (TypeError, ValueError):
            timeout_s = 5.0
        deadline = time.monotonic() + timeout_s
        attempt = 0
        last_res = None
        if engine:
            engine.report(f"🔍 Waiting for {label} (timeout {self.timeout_ms} ms)...",
                          "info")
        while True:
            attempt += 1
            raise_if_stopped(engine)
            try:
                remaining = deadline - time.monotonic()
                # At least one quick attempt even when the deadline already
                # passed (preserves timeout_ms=0 single-probe semantics);
                # otherwise bound the hanging probe by the deadline.
                probe_timeout = max(remaining, 0.05)
                raw = await asyncio.wait_for(
                    await_or_stop(
                        cdp.evaluate(build_probe(selector=self.target_selector)),
                        engine, slice_s=0.05),
                    timeout=probe_timeout)
                res = json.loads(raw) if raw else None
                last_res = res
            except asyncio.TimeoutError:
                # Deadline exceeded while a probe was pending: timeout, not error.
                res = None
                break
            except (asyncio.CancelledError,):
                raise
            except Exception as exc:
                # RunStopped must propagate (never a probe error); everything
                # else is the existing throttled probe-error path.
                from actions.cancellation import RunStopped as _RS
                if isinstance(exc, _RS):
                    raise
                if engine and attempt % 5 == 1:
                    engine.report(f"❌ Probe error while waiting: {exc}", "error")
                res = None
            if res and res.get("found"):
                msg, level = interpret_wait(res, label)
                if engine:
                    engine.report(msg, level)
                log.info("Element found: %s", self.target_selector[:50])
                return ActionResult.OK
            raise_if_stopped(engine)
            if time.monotonic() >= deadline:
                break
            # Report failed probes at most ~once per 2s so the console is readable
            if attempt % 7 == 1:
                total = int((res or {}).get("total", 0) or 0)
                if engine:
                    engine.report(f"⏳ {label} not present yet — matched {total} "
                                  f"node(s) (attempt {attempt})", "warn")
            await sleep_or_stop(0.3, engine, slice_s=0.05)
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
