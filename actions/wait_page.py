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

    # ── the pinned notices ───────────────────────────────────────
    @property
    def _label(self) -> str:
        """The wait target's display name, used in every pinned notice."""
        return f"element '{self.target_selector}'"

    def _report_stop(self, engine) -> None:
        """The pinned "stopped on request" notice, identical at every
        boundary — a private property, so `to_dict()` never sees it."""
        if engine:
            engine.report("⏹ Wait stopped on request — no longer waiting "
                          f"for {self._label}", "warn")

    def _report_progress(self, res, attempt, engine) -> None:
        """Not-found cadence: at most ~once per 2 s so the console is readable."""
        if attempt % 7 != 1:
            return
        total = int((res or {}).get("total", 0) or 0)
        if engine:
            engine.report(f"⏳ {self._label} not present yet — matched {total} "
                          f"node(s) (attempt {attempt})", "warn")

    def _report_timeout(self, last_res, engine) -> None:
        """Terminal failure line, carrying the last known DOM state."""
        total = int((last_res or {}).get("total", 0) or 0)
        if engine:
            engine.report(f"❌ Failed to find element: {self._label} — timeout "
                          f"after {self.timeout_ms} ms, selector matched "
                          f"{total} node(s)", "error")
        log.warning("Timeout waiting for: %s", self.target_selector[:50])

    # ── the cooperative boundaries ───────────────────────────────
    async def _stop_boundary(self, engine) -> None:
        """A stop check that announces itself, then re-raises RunStopped."""
        try:
            check_stopped(engine)
        except RunStopped:
            self._report_stop(engine)
            raise

    async def _sleep_or_stop(self, delay_s: float, engine,
                             slice_s: float = 0.02) -> None:
        """Cooperative sleep reporting a stop with the pinned notice.

        `slice_s` keeps `sleep_with_stop`'s own default so the pre-delay
        boundary answers a stop exactly as fast as it did before.
        """
        try:
            await sleep_with_stop(delay_s, engine, slice_s=slice_s)
        except RunStopped:
            self._report_stop(engine)
            raise

    async def _probe_attempt(self, cdp: CDPClient, deadline: float, engine,
                             attempt: int) -> tuple:
        """One bounded probe → (parsed result | None, outcome).

        Outcome is "ok" (the probe returned; the result may still be None),
        "timeout" (the deadline landed mid-probe) or "failed" (the probe
        raised, reported at the pinned cadence). A stop is announced here
        and re-raised, so the caller's boundary never reports it twice.
        """
        try:
            # At least one quick probe even when the deadline already
            # passed (preserves timeout_ms=0 single-probe semantics, so
            # the timeout error still reports how many nodes were seen);
            # otherwise the hanging probe stays bounded by the deadline.
            probe_deadline = max(deadline, time.monotonic() + 0.05)
            raw = await await_with_stop(
                lambda: cdp.evaluate(build_probe(
                    selector=self.target_selector)),
                engine, slice_s=0.05, deadline_monotonic=probe_deadline)
            return (json.loads(raw) if raw else None), "ok"
        except RunStopped:
            self._report_stop(engine)
            raise
        except TimeoutError:
            return None, "timeout"
        except Exception as exc:
            if engine and attempt % 5 == 1:
                engine.report(f"❌ Probe error while waiting: {exc}", "error")
            return None, "failed"

    async def _wait_loop(self, cdp: CDPClient, deadline: float,
                         engine) -> tuple[bool, Optional[dict]]:
        """Poll until found / timeout / stop → (found, last parsed result)."""
        attempt, last_res = 0, None
        while True:
            attempt += 1
            await self._stop_boundary(engine)
            res, outcome = await self._probe_attempt(cdp, deadline, engine,
                                                     attempt)
            if outcome == "timeout":
                return False, last_res
            if outcome == "ok":
                # A successful probe owns `last_res` even when it parsed to
                # None; a *failed* one must leave the previous reading in
                # place, because the timeout line reports that node count.
                last_res = res
            await self._stop_boundary(engine)
            if res and res.get("found"):
                msg, level = interpret_wait(res, self._label)
                if engine:
                    engine.report(msg, level)
                log.info("Element found: %s", self.target_selector[:50])
                return True, last_res
            if time.monotonic() >= deadline:
                return False, last_res
            self._report_progress(res, attempt, engine)
            await self._sleep_or_stop(0.3, engine, slice_s=0.05)

    async def execute(self, user_nick: str, cdp: CDPClient,
                      engine: Optional[object] = None) -> str:
        # Already-stopped entry: no delay, no probe (C1a).
        await self._stop_boundary(engine)
        await self._sleep_or_stop(self.pre_delay_ms / 1000.0, engine)
        deadline = time.monotonic() + self.timeout_ms / 1000
        if engine:
            engine.report(f"🔍 Waiting for {self._label} "
                          f"(timeout {self.timeout_ms} ms)...", "info")
        found, last_res = await self._wait_loop(cdp, deadline, engine)
        if found:
            return ActionResult.OK
        self._report_timeout(last_res, engine)
        return ActionResult.FAIL

    def config_schema(self) -> dict:
        s = super().config_schema()
        s["target_selector"] = {"type": "text", "default": TEXTAREA_SEL,
                                "label": "Target selector"}
        s["timeout_ms"] = {"type": "number", "default": 5000, "label": "Timeout (ms)"}
        return s
