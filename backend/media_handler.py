"""Image/GIF attachment via CDP file input injection (with debugger detail).

Accepts an optional `report(message, level)` callback for step-by-step
visibility into every stage: folder check → file pattern match → file-input
element search → file injection result.
"""

import os
import glob
import random
import logging
import json
from typing import Callable, Optional
from backend.cdp_client import CDPClient
from backend.dom_probe import build_probe, interpret_wait

log = logging.getLogger("chatbot")

FILE_INPUT_SELECTOR = "input#file[type='file']"


def _rep(report: Optional[Callable], message: str, level: str = "info") -> None:
    if report:
        try:
            report(message, level)
        except Exception:
            pass
    log.log(getattr(logging, level.upper(), logging.INFO), "%s", message)


async def attach_image(cdp: CDPClient, folder_path: str,
                       file_pattern: str = "*.jpg",
                       mode: str = "sequential",
                       report: Optional[Callable] = None) -> bool:
    """Inject an image file via DOM.setFileInputFiles."""
    if not os.path.isdir(folder_path):
        _rep(report, f"❌ Image folder not found: {folder_path}", "error")
        return False
    _rep(report, f"🔍 Scanning image folder: {folder_path} (pattern {file_pattern})",
         "info")
    files = sorted(glob.glob(os.path.join(folder_path, file_pattern)))
    if not files:
        _rep(report, f"❌ No files matching '{file_pattern}' in {folder_path}",
             "error")
        return False
    _rep(report, f"✅ Folder found — {len(files)} file(s) match '{file_pattern}'",
         "success")
    if mode == "random":
        path = random.choice(files)
    else:  # sequential — pick first
        path = files[0]
    _rep(report, f"📎 Selected file: {os.path.basename(path)}", "info")
    # Locate the hidden file input first (for a clear failure message)
    try:
        raw = await cdp.evaluate(build_probe(selector=FILE_INPUT_SELECTOR))
        res = json.loads(raw) if raw else None
    except Exception as exc:
        _rep(report, f"❌ Probe error while searching file input: {exc}", "error")
        return False
    if not (res and res.get("found")):
        total = int((res or {}).get("total", 0) or 0)
        _rep(report, f"❌ Failed to find element: hidden file input "
                     f"'{FILE_INPUT_SELECTOR}' (matched {total} node(s))", "error")
        return False
    msg, level = interpret_wait(res, f"file input '{FILE_INPUT_SELECTOR}'")
    _rep(report, msg, level)
    try:
        await cdp.set_file_input_files(FILE_INPUT_SELECTOR, [os.path.abspath(path)])
    except Exception as exc:
        _rep(report, f"❌ File injection failed: {exc}", "error")
        return False
    _rep(report, f"🖼️ Image attached: {os.path.basename(path)}", "success")
    log.info("Image attached: %s", os.path.basename(path))
    return True
