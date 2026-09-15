"""Image/GIF attachment via CDP file-input injection — human-like flow.

Pipeline (each stage logged through the optional `report` callback):

  1. folder + file-pattern scan — .jpg/.jpeg/.png/.gif by default,
     case-insensitive (a folder full of .GIF files is found too);
  2. pick a file (sequential / random);
  3. resolve the ACTIVE conversation (the visible composer) so every later
     step targets the chat the user is actually looking at — the private
     chat, not a hidden main-room composer that also lives in the DOM;
  4. optional "open the upload dialog" — click the active conversation's
     image (attach) button WITH the shared visual-confirmation overlays
     (red find outline -> pause -> orange click outline), then the click;
  5. DOM.setFileInputFiles on the active conversation's OWN hidden input,
     then READ BACK `input.files.length` so a silent no-op is impossible;
  6. optional verify — poll until a new `.message-container` appears
     INSIDE the same conversation (the site auto-sends once chosen).

If the active-conversation probe cannot resolve (single-composer layout,
selector drift) the pipeline falls back to today's global selectors with a
logged warning — never a silent skip.

The family (Round J step J-6): this module is the pipeline's decision half —
scan, pick, scope, verify. The page half (the upload-dialog click, the hidden
file input, the readback, the report/refusal plumbing) is
`backend/media_dialog.py`, and the injected JS with the selectors it embeds is
`backend/media_handler_js.py`. The direction is one-way: this module imports
the other two.
"""

import dataclasses
import fnmatch
import json
import logging
import os
import random
import re
from dataclasses import dataclass, field
from typing import Callable, Optional

from backend.cdp_client import CDPClient
from backend.media_dialog import (                             # noqa: F401
    _AttachRefused, _inject_file, _open_dialog, _rep, _refuse, _verify_sent,
)
from backend.media_handler_js import (
    CTX_PROBE_JS, FILE_INPUT_SELECTOR, IMAGE_BUTTON_SELECTOR,
)

log = logging.getLogger("chatbot")

#: Default selection: every common image format the chat accepts.
DEFAULT_FILE_PATTERN = "*.jpg, *.jpeg, *.png, *.gif"


def parse_patterns(file_pattern: str) -> list[str]:
    """Normalize a comma/space/semicolon list into lowercase glob patterns.

    ``"gif"``, ``".png"`` and ``"*.JPG"`` all become usable patterns;
    anything containing its own wildcard is kept as-is. Empty input falls
    back to the default image formats.
    """
    tokens = [t.strip() for t in re.split(r"[,\s;]+", file_pattern or "")
              if t.strip()]
    patterns = [_glob_for(token) for token in tokens]
    return patterns or [p.strip() for p in DEFAULT_FILE_PATTERN.split(",")]


def _glob_for(token: str) -> str:
    """One pattern token as a usable lowercase glob.

    The four shapes a user types: already a glob (``*.jpg``), a bare
    extension (``.png``), a token carrying its own wildcard (``img?``), or a
    plain format name (``gif``). Only the last needs the ``*.`` prefix, and
    it also sheds a stray leading dot so ``".gif"`` and ``"gif"`` agree.
    """
    low = token.lower()
    if low.startswith("*."):
        return low
    if low.startswith("."):
        return "*" + low
    if "*" in low or "?" in low:
        return low
    return "*." + low.lstrip(".")


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
            path = os.path.join(folder, name)
            # a directory named `vacation.jpg` matches the glob but is
            # not attachable — only real files reach the file input
            if os.path.isfile(path):
                files.append(path)
    return sorted(set(files))


async def _active_chat_context(cdp: CDPClient,
                               report: Optional[Callable]) -> dict:
    """Resolve the visible conversation's image button / file input / shell.

    Returns a dict with ``input_css``, ``button_css``, ``shell_css``,
    ``chat_count`` and ``ok``. On any failure the dict is empty — the caller
    falls back to the global selectors (single-composer layouts included).
    """
    empty = {"ok": False, "chat_count": 0,
             "input_css": "", "button_css": "", "shell_css": ""}
    try:
        raw = await cdp.evaluate(CTX_PROBE_JS)
        ctx = json.loads(raw) if raw else {}
    except Exception as exc:
        _rep(report, f"⚠ Could not resolve the active conversation "
                     f"({exc}) — using global selectors", "warn")
        return empty
    if not isinstance(ctx, dict) or not ctx.get("ok") or \
            not ctx.get("input_css") or not ctx.get("button_css"):
        _rep(report, "⚠ Active-conversation probe found no composer — "
                     "falling back to global selectors", "warn")
        return empty
    _rep(report, f"🎯 Active conversation resolved "
                 f"({ctx.get('chat_count', 1)} chat panel(s) on page)",
         "info")
    return ctx


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


async def attach_image(cdp: CDPClient, folder_path: str = "",
                       options: Optional[AttachOptions] = None,
                       **legacy) -> bool:
    """Attach (and let the site send) one image file to the ACTIVE chat.

    Returns True only when the file was injected AND (unless verification
    is disabled) a new message container appeared in that conversation.

    The steps, each in its own function below: scan the folder → scope the
    selectors to the active conversation → click the upload button → write the
    hidden file input and read it back → wait for the new message.

    The knobs travel as one :class:`AttachOptions` (Round G step 4); the
    legacy keyword form the tests and old callers use is absorbed into the
    same object, with `folder_path` kept positional for them.
    """
    return await attach_with_options(
        cdp, options or AttachOptions(folder_path=folder_path, **legacy))
