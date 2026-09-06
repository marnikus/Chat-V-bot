"""Image/GIF attachment via CDP file-input injection — human-like flow.

Pipeline (each stage logged through the optional `report` callback):

  1. folder + file-pattern scan — .jpg/.jpeg/.png/.gif by default,
     case-insensitive (a folder full of .GIF files is found too);
  2. pick a file (sequential / random);
  3. optional "open the upload dialog" — click the site's image (attach)
     button exactly like a human would;
  4. DOM.setFileInputFiles on the hidden input, then READ BACK
     `input.files.length` so a silent no-op injection is impossible;
  5. optional verify — poll until a new `.message-container` appears
     (the site auto-sends the image once it has been chosen).

The block stays fully compatible with the old direct-inject behaviour:
simulate_dialog=false + verify_timeout_ms=0 reproduces it exactly.
"""

import asyncio
import fnmatch
import json
import logging
import os
import random
import re
import time
from typing import Callable, Optional

from backend.cdp_client import CDPClient
from backend.dom_probe import MATCH_EXACT, build_probe, interpret_wait

log = logging.getLogger("chatbot")

#: Default selection: every common image format the chat accepts.
DEFAULT_FILE_PATTERN = "*.jpg, *.jpeg, *.png, *.gif"

#: The site's image/attach button lives in the message form's icon suffix.
IMAGE_BUTTON_SELECTOR = ".mat-mdc-form-field-icon-suffix button"
IMAGE_BUTTON_LABEL = "mat-icon"
IMAGE_ICON_TEXT = "image"

#: The hidden input the chat app reads after the dialog closes.
FILE_INPUT_SELECTOR = "input#file[type='file']"

#: Returns the number of files currently set on the input ("0"/"1"/"none").
READBACK_JS = (
    '(function(){var i=document.querySelector("input#file[type=\'file\']");'
    "return String((i&&i.files)?i.files.length:0);})()"
)

#: Total rendered chat message containers — a growing count means the
#: attached image was really sent.
COUNT_MESSAGES_JS = (
    "(function(){return String("
    "document.querySelectorAll('.message-container').length);})()"
)


def _rep(report: Optional[Callable], message: str, level: str = "info") -> None:
    if report:
        try:
            report(message, level)
        except Exception:
            pass
    log.log(getattr(logging, level.upper(), logging.INFO), "%s", message)


def parse_patterns(file_pattern: str) -> list[str]:
    """Normalize a comma/space/semicolon list into lowercase glob patterns.

    ``"gif"``, ``".png"`` and ``"*.JPG"`` all become usable patterns;
    anything containing its own wildcard is kept as-is. Empty input falls
    back to the default image formats.
    """
    tokens = [t.strip() for t in re.split(r"[,\s;]+", file_pattern or "")
              if t.strip()]
    patterns = []
    for token in tokens:
        low = token.lower()
        if low.startswith("*."):
            patterns.append(low)
        elif low.startswith("."):
            patterns.append("*" + low)
        elif "*" in low or "?" in low:
            patterns.append(low)
        else:
            patterns.append("*." + low.lstrip("."))
    return patterns or [p.strip() for p in DEFAULT_FILE_PATTERN.split(",")]


def list_image_files(folder: str, file_pattern: str) -> list[str]:
    """Absolute paths of files in `folder` matching `file_pattern`.

    Matching is case-insensitive (``fnmatch`` against lowercased names), so
    ``*.gif`` also finds ``X.GIF`` — important on Linux where glob() is
    case-sensitive.
    """
    patterns = parse_patterns(file_pattern)
    try:
        names = os.listdir(folder)
    except OSError:
        return []
    files = []
    for name in names:
        low = name.lower()
        if any(fnmatch.fnmatchcase(low, p) for p in patterns):
            files.append(os.path.join(folder, name))
    return sorted(set(files))


async def _message_count(cdp: CDPClient) -> Optional[int]:
    try:
        raw = await cdp.evaluate(COUNT_MESSAGES_JS)
        return int(str(raw).strip()) if str(raw).strip().isdigit() else None
    except Exception:
        return None


async def attach_image(cdp: CDPClient, folder_path: str,
                       file_pattern: str = DEFAULT_FILE_PATTERN,
                       mode: str = "sequential",
                       simulate_dialog: bool = True,
                       verify_timeout_ms: int = 8000,
                       report: Optional[Callable] = None,
                       verify_poll_ms: int = 200) -> bool:
    """Attach (and let the site send) one image file.

    Returns True only when the file was injected AND (unless verification
    is disabled) a new message container appeared in the chat.
    """
    # ── 1. folder + pattern ───────────────────────────────────────
    if not os.path.isdir(folder_path):
        _rep(report, f"❌ Image folder not found: {folder_path}", "error")
        return False
    _rep(report, f"🔍 Scanning image folder: {folder_path} "
                 f"(patterns: {file_pattern})", "info")
    files = list_image_files(folder_path, file_pattern)
    if not files:
        wanted = ", ".join(parse_patterns(file_pattern))
        _rep(report, f"❌ No image files matching '{wanted}' found in "
                     f"{folder_path}", "error")
        return False
    _rep(report, f"✅ Folder found — {len(files)} image file(s) match",
         "success")

    # ── 2. pick ───────────────────────────────────────────────────
    path = random.choice(files) if mode == "random" else files[0]
    _rep(report, f"📎 Selected file: {os.path.basename(path)}", "info")

    # ── 3. open the upload dialog like a human (optional) ─────────
    if simulate_dialog:
        # Imported here, not at module top: visual_click pulls in the
        # actions package, which imports this module — a cycle at load time.
        from backend.visual_click import find_and_click
        _rep(report, "🖱 Opening the image upload dialog…", "info")
        outcome = await find_and_click(
            cdp,
            selector=IMAGE_BUTTON_SELECTOR,
            label_selector=IMAGE_BUTTON_LABEL,
            match_text=IMAGE_ICON_TEXT,
            match_mode=MATCH_EXACT,
            click_enabled=True,
            highlight_enabled=False,
            confirm_pause_ms=0,
            label="image upload button",
            engine=None,
        )
        if outcome != "ok":
            _rep(report, "⚠ Could not click the image button — trying the "
                         "hidden file input directly", "warn")

    # ── 4. inject the file + read it back ─────────────────────────
    try:
        raw = await cdp.evaluate(build_probe(selector=FILE_INPUT_SELECTOR))
        res = json.loads(raw) if raw else None
    except Exception as exc:
        _rep(report, f"❌ Probe error while searching file input: {exc}",
             "error")
        return False
    if not (res and res.get("found")):
        total = int((res or {}).get("total", 0) or 0)
        _rep(report, f"❌ Failed to find element: hidden file input "
                     f"'{FILE_INPUT_SELECTOR}' (matched {total} node(s))",
             "error")
        return False
    msg, level = interpret_wait(res, f"file input '{FILE_INPUT_SELECTOR}'")
    _rep(report, msg, level)

    baseline = await _message_count(cdp)

    try:
        await cdp.set_file_input_files(FILE_INPUT_SELECTOR,
                                       [os.path.abspath(path)])
    except Exception as exc:
        _rep(report, f"❌ File injection failed: {exc}", "error")
        return False

    # Read back: DOM.setFileInputFiles can silently no-op (node id 0) —
    # never trust it without proof the file actually landed.
    try:
        raw = await cdp.evaluate(READBACK_JS)
        got = int(str(raw).strip()) if str(raw).strip().isdigit() else -1
    except Exception:
        got = -1
    if got != 1:
        _rep(report, f"❌ File injection did not stick (input.files.length "
                     f"= {got}) — nothing was sent", "error")
        return False
    _rep(report, f"🖼️ Image set on the upload input: {os.path.basename(path)}",
         "success")

    # ── 5. verify the site sent it (optional) ─────────────────────
    if verify_timeout_ms <= 0:
        _rep(report, "📤 Verification disabled — image injected (site is "
                     "expected to send it)", "info")
        return True
    if baseline is None:
        _rep(report, "⚠ Cannot read the message list — trusting the "
                     "injection", "warn")
        return True

    deadline = time.monotonic() + verify_timeout_ms / 1000.0
    while time.monotonic() < deadline:
        await asyncio.sleep(verify_poll_ms / 1000.0)
        now = await _message_count(cdp)
        if now is not None and now > baseline:
            _rep(report, "📤 Image message appeared in the chat — sent",
                 "success")
            return True
    _rep(report, f"❌ No new message appeared after {verify_timeout_ms} ms — "
                 "the image may not have been sent (the site may need a "
                 "Click Send block after Attach Image, or a longer "
                 "'wait for send' timeout)", "error")
    return False
