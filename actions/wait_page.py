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


def _element_label(selector: str) -> str:
    """How every report from this block names the thing it is waiting for."""
    return f"element '{selector}'"


def _stopped_report(engine, label: str) -> None:
    """Say once, in the operator's log, that the wait was abandoned."""
    if engine:
        engine.report(
            f"⏹ Wait stopped on request — no longer waiting for {label}", "warn")


def _report_probe_error(error, attempt: int, engine) -> None:
    """A failing probe is noise on every attempt; report one in five."""
    if error is not None and engine and attempt % 5 == 1:
        engine.report(f"❌ Probe error while waiting: {error}", "error")


def _report_absent(res, attempt: int, engine, label: str) -> None:
    """Still missing. Throttled to ~once per 2 s so the console is readable."""
    if attempt % 7 != 1:
        return
    total = int((res or {}).get("total", 0) or 0)
    if engine:
        engine.report(f"⏳ {label} not present yet — matched {total} "
                      f"node(s) (attempt {attempt})", "warn")




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

    # ── stop boundaries ──────────────────────────────────────────
    @staticmethod
    def _check_stop(engine, label: str) -> None:
        """One stop boundary: report the abandonment, then let it propagate."""
        try:
            check_stopped(engine)
        except RunStopped:
            _stopped_report(engine, label)
            raise

    @staticmethod
    async def _sleep_with_stop(engine, label: str, delay_s: float, **kw) -> None:
        """One cooperative delay with the same single report on stop."""
        try:
            await sleep_with_stop(delay_s, engine, **kw)
        except RunStopped:
            _stopped_report(engine, label)
            raise

    # ── the probe ────────────────────────────────────────────────
    async def _probe_once(self, cdp, engine, deadline):
        """One bounded DOM probe, as `(payload, timed_out, error)`.

        A probe that raises answers nothing: the caller reports it and keeps the
        previous DOM state, because "last seen" must not be overwritten by a
        failure.
        """
        try:
            # At least one quick probe even when the deadline already passed
            # (preserves timeout_ms=0 single-probe semantics, so the timeout
            # report still says how many nodes were seen); otherwise the
            # hanging probe stays bounded by the deadline.
            probe_deadline = max(deadline, time.monotonic() + 0.05)
            raw = await await_with_stop(
                lambda: cdp.evaluate(build_probe(selector=self.target_selector)),
                engine,
                slice_s=0.05,
                deadline_monotonic=probe_deadline,
            )
            # A payload that is not there at all is "nothing seen"; a payload
            # that cannot be parsed is a probe failure, reported like one.
            return (json.loads(raw) if raw else None), False, None
        except RunStopped:
            _stopped_report(engine, _element_label(self.target_selector))
            raise
        except TimeoutError:
            return None, True, None
        except Exception as exc:                       # noqa: BLE001 - reported
            return None, False, exc

    def _report_found(self, res: dict, engine, label: str) -> str:
        """The found line: the panel gets the interpretation, the log the fact."""
        msg, level = interpret_wait(res, label)
        if engine:
            engine.report(msg, level)
        log.info("Element found: %s", self.target_selector[:50])
        return ActionResult.OK

    def _report_timeout(self, last_res, engine, label: str) -> None:
        """The terminal failure, quoting the last DOM state that was seen."""
        total = int((last_res or {}).get("total", 0) or 0)
        if engine:
            engine.report(f"❌ Failed to find element: {label} — timeout after "
                          f"{self.timeout_ms} ms, selector matched {total} node(s)",
                          "error")
        log.warning("Timeout waiting for: %s", self.target_selector[:50])

    def _report_wait_start(self, engine, label: str) -> None:
        """Name what is being waited for, once, before the first probe."""
        if engine:
            engine.report(f"🔍 Waiting for {label} (timeout {self.timeout_ms} ms)...",
                          "info")

    async def execute(self, user_nick: str, cdp: CDPClient,
                      engine: Optional[object] = None) -> str:
        """Poll until found / deadline / stop. The loop is the whole policy;
        the boundary, the probe and the reports are the helpers below.
        """
        label = _element_label(self.target_selector)
        self._check_stop(engine, label)     # entry: already stopped means no delay, no probe (C1a)
        await self._sleep_with_stop(engine, label, self.pre_delay_ms / 1000.0)
        deadline = time.monotonic() + self.timeout_ms / 1000
        self._report_wait_start(engine, label)
        attempt, last_res = 0, None
        while True:
            attempt += 1
            self._check_stop(engine, label)
            res, timed_out, error = await self._probe_once(cdp, engine, deadline)
            _report_probe_error(error, attempt, engine)
            if timed_out:
                break
            if error is None:
                last_res = res
            self._check_stop(engine, label)
            if res and res.get("found"):
                return self._report_found(res, engine, label)
            if time.monotonic() >= deadline:
                break
            _report_absent(res, attempt, engine, label)
            await self._sleep_with_stop(engine, label, 0.3, slice_s=0.05)
        self._report_timeout(last_res, engine, label)
        return ActionResult.FAIL

    def config_schema(self) -> dict:
        s = super().config_schema()
        s["target_selector"] = {"type": "text", "default": TEXTAREA_SEL,
                                "label": "Target selector"}
        s["timeout_ms"] = {"type": "number", "default": 5000, "label": "Timeout (ms)"}
        return s
