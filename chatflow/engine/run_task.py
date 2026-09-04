"""One RUN: connect, build context, execute the sequence, tear down.

Kept separate from worker.py so the QThread plumbing stays small.
"""
from __future__ import annotations

import random

from ..blocks.context import BlockContext
from ..core.models import Block, EngineState, FilterRule
from ..engine.errors import OpError, StopRequested
from ..engine.executor import SequenceExecutor
from ..engine.humanize import Humanizer


async def do_run(worker, payload: dict) -> None:
    from ..browser import connect as cdp
    from ..browser.page_ops import GuardedOps
    from ..browser.watchdog import TabWatchdog

    worker.stop_run = False
    worker.sm.go(EngineState.CONNECTING)
    worker.log("info",
               f"Connecting to Chrome {worker.s.cdp_host}:{worker.s.cdp_port}…")
    try:
        pw, _browser, page = await cdp.connect_and_find(worker.s)
    except OpError as e:
        worker.sm.go(EngineState.ERROR)
        worker.log("error", str(e))
        worker.emit_event("error", {"code": "connect", "msg": str(e)})
        return
    worker.log("info", f"Connected — page: {page.url}")
    ops = GuardedOps(page, worker.s)
    worker.pause_evt = asyncio_event_set()
    ctx = BlockContext(ops, page, worker.s, Humanizer(worker.s),
                       payload.get("queued", []), worker.emit_event,
                       random.Random())
    ctx.gate = worker.gate
    ctx.rules = [FilterRule.from_dict(r) for r in payload.get("rules", [])]
    worker.ctx = ctx
    worker.sm.go(EngineState.RUNNING)
    watchdog = TabWatchdog(ops, on_lost=lambda: on_lost(worker))
    watchdog.start()
    executor = SequenceExecutor(worker.emit_event, worker.log, worker.s)
    blocks = [Block.from_dict(b) for b in payload.get("blocks", [])]
    try:
        await executor.run_sequence(blocks, ctx)
        worker.log("info", "Sequence finished")
    except StopRequested:
        worker.log("info", "Stopped by user")
    except Exception as e:  # noqa: BLE001 — never kill the worker thread
        worker.sm.go(EngineState.ERROR)
        worker.log("error", f"Run crashed: {e}")
    finally:
        watchdog.stop()
        worker.pause_evt = None
        worker.ctx = None
        worker.sm.force(EngineState.IDLE)
        await cdp.close_quiet(pw)


def on_lost(worker) -> None:
    worker.stop_run = True
    if worker.ctx:
        worker.ctx.mark_stopped()
    if worker.sm.state == EngineState.RUNNING:
        worker.sm.go(EngineState.DEGRADED)
    worker.log("error", "Chat tab lost — reconnect and resume when ready")
    worker.emit_event("connection_lost", {})


def asyncio_event_set():
    import asyncio
    evt = asyncio.Event()
    evt.set()
    return evt
