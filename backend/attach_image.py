"""Attaching one image to the open conversation, refusing loudly if it cannot.

Split out of backend/media_handler.py in Round H (step H5), which was 480
lines covering two jobs joined only by the word "media": deciding WHICH file
to send (globbing a folder against a pattern — pure, synchronous, filesystem
only) and the CDP conversation that actually attaches it (open the picker,
inject into the file input, read back, verify the message count grew).

The attach half is a fail-closed pipeline: `_AttachRefused` carries a reason
to the caller instead of a bare False. It is raised OUTSIDE the broad
`except Exception` handlers on purpose — a control-flow exception caught by a
generic handler is silently disarmed.

`DEFAULT_FILE_PATTERN` stays in media_handler: actions/attach_image.py imports
it from there, and a split must not move a name another area depends on.
"""

import asyncio
import dataclasses
import json
import logging
import os
import random
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from backend.cdp_client import CDPClient
from backend.dom_probe import MATCH_EXACT, build_probe, interpret_wait
from backend.logger import report_and_log
from backend.media_handler import (CTX_PROBE_JS, DEFAULT_FILE_PATTERN,
                                   _ReportBridge, list_image_files,
                                   parse_patterns,
                                   FILE_INPUT_SELECTOR, IMAGE_BUTTON_LABEL,
                                   IMAGE_BUTTON_SELECTOR, IMAGE_ICON_TEXT,
                                   _active_chat_context, _count_messages_js,
                                   _message_count, _readback_js)

log = logging.getLogger("chatbot")
_rep = report_and_log


@dataclass(frozen=True, slots=True)
class AttachOptions:
    """Everything `attach_image` needs to know, as one value.

    The block (`ATTACH_IMAGE`) keeps calling the long function — that signature
    is its contract with the run engine — but the phases below take this
    instead of nine arguments, and a caller that holds the settings as data (a
    preset, a test) can build the options once and call
    :func:`attach_with_options`.
    """

    folder_path: str = ""
    file_pattern: str = DEFAULT_FILE_PATTERN
    mode: str = "sequential"
    #: click the upload button like a human before injecting
    simulate_dialog: bool = True
    #: 0 or less = "do not wait for the new message"
    verify_timeout_ms: int = 8000
    verify_poll_ms: int = 200
    highlight_enabled: bool = True
    confirm_pause_ms: int = 700
    report: Optional[Callable] = None

    @classmethod
    def from_kwargs(cls, **kwargs) -> "AttachOptions":
        """From a block's settings — unknown keys are dropped, not fatal."""
        known = {f.name for f in dataclasses.fields(cls)}
        return cls(**{k: v for k, v in kwargs.items() if k in known})

    @property
    def verifies(self) -> bool:
        return int(self.verify_timeout_ms or 0) > 0


@dataclass
class _AttachState:
    """What the steps discover, in the order they run."""

    options: AttachOptions
    files: list = field(default_factory=list)
    path: str = ""
    input_sel: str = ""
    button_sel: str = ""
    shell_css: str = ""
    scoped: bool = False
    baseline: Optional[int] = None


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


def _scan_folder(state: _AttachState) -> None:
    """Step 1+2: find something to send, and pick it."""
    options = state.options
    report, folder_path = options.report, options.folder_path
    if not os.path.isdir(folder_path):
        _refuse(report, f"❌ Image folder not found: {folder_path}")
    _rep(report, f"🔍 Scanning image folder: {folder_path} "
                 f"(patterns: {options.file_pattern})", "info")
    files = list_image_files(folder_path, options.file_pattern)
    if not files:
        wanted = ", ".join(parse_patterns(options.file_pattern))
        _refuse(report, f"❌ No image files matching '{wanted}' found in "
                        f"{folder_path}")
    _rep(report, f"✅ Folder found — {len(files)} image file(s) match",
         "success")
    state.files = files
    state.path = (random.choice(files) if options.mode == "random"
                  else files[0])
    _rep(report, f"📎 Selected file: {os.path.basename(state.path)}", "info")


async def _resolve_target(cdp: CDPClient, state: _AttachState) -> None:
    """Step 3: which conversation is on screen — the selectors are scoped to it."""
    ctx = await _active_chat_context(cdp, state.options.report)
    state.input_sel = ctx.get("input_css") or FILE_INPUT_SELECTOR
    state.button_sel = ctx.get("button_css") or IMAGE_BUTTON_SELECTOR
    state.shell_css = ctx.get("shell_css") or ""
    state.scoped = bool(ctx.get("ok"))


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
        raw = await cdp.evaluate(_readback_js(state.input_sel))
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


async def attach_with_options(cdp: CDPClient,
                              options: AttachOptions) -> bool:
    """The whole pipeline, driven from an :class:`AttachOptions`."""
    state = _AttachState(options=options)
    try:
        _scan_folder(state)
        await _resolve_target(cdp, state)
        if options.simulate_dialog:
            await _open_dialog(cdp, state)
        await _inject_file(cdp, state)
        await _verify_sent(cdp, state)
    except _AttachRefused:
        return False
    return True


async def attach_image(cdp: CDPClient, folder_path: str,
                       file_pattern: str = DEFAULT_FILE_PATTERN,
                       mode: str = "sequential",
                       simulate_dialog: bool = True,
                       verify_timeout_ms: int = 8000,
                       highlight_enabled: bool = True,
                       confirm_pause_ms: int = 700,
                       report: Optional[Callable] = None,
                       verify_poll_ms: int = 200) -> bool:
    """Attach (and let the site send) one image file to the ACTIVE chat.

    Returns True only when the file was injected AND (unless verification
    is disabled) a new message container appeared in that conversation.

    The steps, each in its own function below: scan the folder → scope the
    selectors to the active conversation → click the upload button → write the
    hidden file input and read it back → wait for the new message.
    """
    return await attach_with_options(
        cdp, AttachOptions(folder_path=folder_path,
                           file_pattern=file_pattern, mode=mode,
                           simulate_dialog=simulate_dialog,
                           verify_timeout_ms=verify_timeout_ms,
                           highlight_enabled=highlight_enabled,
                           confirm_pause_ms=confirm_pause_ms, report=report,
                           verify_poll_ms=verify_poll_ms))
