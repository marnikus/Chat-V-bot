"""The page side of attaching an image: report plumbing + dialog drive.

Part of the `media_handler` family (entry point: `backend/media_handler.py`,
Round J step J-6). The handler owns the user-facing pipeline (folder scan,
target resolution, send verification); everything that talks to the page for
the upload itself lives here:

* the shared voice every step reports through — `_rep` (the report callback
  with the logging fallback), `_refuse` + `_AttachRefused` (report, then stop
  the run) and `_ReportBridge` (the action-side `report` seam for the visual
  click). They live on this side because both halves need them and this half
  must not import the handler back;
* step 4 — `_open_dialog`, the human-like click on the active conversation's
  image button, with the shared visual-confirmation overlays;
* step 5 — `_probe_file_input`, `_inject_file` and `_readback_count`: wait for
  the hidden input, write the file, read `input.files.length` back so a silent
  no-op is impossible;
* step 6 — `_verify_sent` and `_message_count`: poll until a new message
  container appears in the same conversation, or refuse with the reason.

`_AttachState` (the handler's record of what the steps discovered) is imported
for typing only — under `TYPE_CHECKING`, resolved to a string by the future
import — which is what keeps the dependency one-way: the handler imports this
module, never the other way round.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import TYPE_CHECKING, Callable, Optional

from backend.cdp_client import CDPClient
from backend.dom_probe import MATCH_EXACT, build_probe, interpret_wait
from backend.media_handler_js import (IMAGE_BUTTON_LABEL, IMAGE_BUTTON_SELECTOR,
                                      IMAGE_ICON_TEXT, count_messages_js,
                                      readback_js)

if TYPE_CHECKING:                    # typing only — no runtime import back
    from backend.media_handler import _AttachState

log = logging.getLogger("chatbot")

class _ReportBridge:
    """Minimal engine stand-in so the shared visual runner can log through
    the block's `report` callback without an API change."""

    def __init__(self, report: Optional[Callable]):
        self.report = report or (lambda *a, **kw: None)


def _rep(report: Optional[Callable], message: str, level: str = "info") -> None:
    if report:
        try:
            report(message, level)
        except Exception:
            pass
    log.log(getattr(logging, level.upper(), logging.INFO), "%s", message)




class _AttachRefused(Exception):
    """A step said no — it has already reported why, in its own words.

    `attach_image` is a linear pipeline in which every step can only run if
    the one before it worked; written as `if …: report; return False` twelve
    times in one body, that is what pushed it to CC 26.
    """


def _refuse(report, message: str, level: str = "error") -> None:
    """Report the reason, then stop the run."""
    _rep(report, message, level)
    raise _AttachRefused(message)



async def _message_count(cdp: CDPClient, shell_css: str = "") -> Optional[int]:
    try:
        raw = await cdp.evaluate(count_messages_js(shell_css))
        return int(str(raw).strip()) if str(raw).strip().isdigit() else None
    except Exception:
        return None


async def _open_dialog(cdp: CDPClient, state: _AttachState) -> None:
    """Step 4: click the upload button, the way a human would.

    Best-effort on purpose: when the button cannot be clicked the hidden file
    input is written directly afterwards, so this never refuses the run — it
    only reports what it managed.
    """
    options, report = state.options, state.options.report
    # Imported here, not at module top: visual_click pulls in the actions
    # package, which imports this module — a cycle at load time.
    from backend.visual_click import find_and_click

    _rep(report, "🖱 Opening the image upload dialog…", "info")
    outcome = await find_and_click(
        cdp, selector=state.button_sel, click_enabled=True,
        highlight_enabled=options.highlight_enabled,
        confirm_pause_ms=options.confirm_pause_ms,
        label="image upload button (active chat)",
        engine=_ReportBridge(report))
    if outcome != "ok" and state.scoped:
        # Scoped path missed (DOM shifted) — retry with the classic
        # text-based search, still with full visual confirmation.
        _rep(report, "↩ Scoped image button not found — retrying with "
                     "the text-based search", "warn")
        outcome = await find_and_click(
            cdp, selector=IMAGE_BUTTON_SELECTOR,
            label_selector=IMAGE_BUTTON_LABEL, match_text=IMAGE_ICON_TEXT,
            match_mode=MATCH_EXACT, click_enabled=True,
            highlight_enabled=options.highlight_enabled,
            confirm_pause_ms=options.confirm_pause_ms,
            label="image upload button (text search)",
            engine=_ReportBridge(report))
    if outcome != "ok":
        _rep(report, "⚠ Could not click the image button — trying the "
                     "hidden file input directly", "warn")


async def _probe_file_input(cdp: CDPClient, state: _AttachState) -> dict:
    """Step 5a: find the hidden file input (refuses when it is not there)."""
    report = state.options.report
    try:
        raw = await cdp.evaluate(build_probe(selector=state.input_sel))
        res = json.loads(raw) if raw else None
    except Exception as exc:                       # noqa: BLE001
        _refuse(report, f"❌ Probe error while searching file input: {exc}")
    if not (res and res.get("found")):
        total = int((res or {}).get("total", 0) or 0)
        _refuse(report, f"❌ Failed to find element: hidden file input "
                        f"'{state.input_sel}' (matched {total} node(s))")
    msg, level = interpret_wait(res, f"file input '{state.input_sel}'")
    _rep(report, msg, level)
    return res


async def _readback_count(cdp: CDPClient, state: _AttachState) -> int:
    """How many files the input actually holds (-1 when that is unreadable)."""
    try:
        raw = await cdp.evaluate(readback_js(state.input_sel))
    except Exception:                              # noqa: BLE001
        return -1
    return int(str(raw).strip()) if str(raw).strip().isdigit() else -1


async def _inject_file(cdp: CDPClient, state: _AttachState) -> None:
    """Step 5: wait for the hidden input, write the file, read it back."""
    report = state.options.report
    await _probe_file_input(cdp, state)
    state.baseline = await _message_count(cdp, state.shell_css)
    try:
        await cdp.set_file_input_files(state.input_sel,
                                       [os.path.abspath(state.path)])
    except Exception as exc:                       # noqa: BLE001
        _refuse(report, f"❌ File injection failed: {exc}")

    # Read back: DOM.setFileInputFiles can silently no-op (node id 0) —
    # never trust it without proof the file actually landed.
    got = await _readback_count(cdp, state)
    if got != 1:
        _refuse(report, f"❌ File injection did not stick (input.files.length "
                        f"= {got}) — nothing was sent")
    _rep(report, f"🖼️ Image set on the upload input: "
                 f"{os.path.basename(state.path)}", "success")


async def _verify_sent(cdp: CDPClient, state: _AttachState) -> None:
    """Step 6: did the site actually post it?

    The one step that can turn a successful injection into a False — which is
    exactly what the caller's "the image was sent" promise needs.
    """
    options, report = state.options, state.options.report
    if not options.verifies:
        _rep(report, "📤 Verification disabled — image injected (site is "
                     "expected to send it)", "info")
        return
    if state.baseline is None:
        _rep(report, "⚠ Cannot read the message list — trusting the "
                     "injection", "warn")
        return
    deadline = time.monotonic() + options.verify_timeout_ms / 1000.0
    while time.monotonic() < deadline:
        await asyncio.sleep(options.verify_poll_ms / 1000.0)
        now = await _message_count(cdp, state.shell_css)
        if now is not None and now > state.baseline:
            _rep(report, "📤 Image message appeared in the chat — sent",
                 "success")
            return
    _refuse(report, f"❌ No new message appeared after "
                    f"{options.verify_timeout_ms} ms — the image may not have "
                    "been sent (the site may need a Click Send block after "
                    "Attach Image, or a longer 'wait for send' timeout)",
            "error")
