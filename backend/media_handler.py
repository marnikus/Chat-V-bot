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
"""

import asyncio
import dataclasses
import fnmatch
import json
import logging
import os
import random
import re
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from backend.cdp_client import CDPClient
from backend.dom_probe import MATCH_EXACT, build_probe, interpret_wait

log = logging.getLogger("chatbot")

#: Default selection: every common image format the chat accepts.
DEFAULT_FILE_PATTERN = "*.jpg, *.jpeg, *.png, *.gif"

#: Global (fallback) selectors — the live page can keep several chat panels
#: mounted, so these are only used when the active-conversation probe fails.
IMAGE_BUTTON_SELECTOR = ".mat-mdc-form-field-icon-suffix button"
IMAGE_BUTTON_LABEL = "mat-icon"
IMAGE_ICON_TEXT = "image"
FILE_INPUT_SELECTOR = "input#file[type='file']"

#: Resolves the VISIBLE composer and returns unique CSS paths for its
#: image button, its hidden file input and its chat shell (used to scope
#: the send verification). Mirrors what a human sees: the conversation the
#: on-screen message box belongs to.
CTX_PROBE_JS = r"""(function(){
  /*ACTIVE_CHAT_CTX*/
  var out={ok:false,chat_count:0,input_css:"",button_css:"",shell_css:""};
  function cssPath(el){
    if(!el||el.nodeType!==1) return "";
    var parts=[];
    while(el&&el.nodeType===1&&el.tagName.toLowerCase()!=="html"){
      var parent=el.parentElement;
      if(!parent) break;
      var tag=el.tagName.toLowerCase();
      var sibs=Array.prototype.filter.call(parent.children,
        function(c){return c.tagName===el.tagName;});
      var idx=sibs.indexOf(el)+1;
      parts.unshift(tag+(sibs.length>1?":nth-of-type("+idx+")":""));
      el=parent;
    }
    return parts.join(" > ");
  }
  var chats=Array.prototype.slice.call(
    document.querySelectorAll('app-chat'));
  out.chat_count=chats.length;
  var forms=Array.prototype.slice.call(
    document.querySelectorAll('app-message-form'));
  var active=null;
  for(var i=0;i<forms.length;i++){
    var ta=forms[i].querySelector("textarea[placeholder='Сообщение']");
    if(ta&&ta.offsetParent!==null){active=forms[i];break;}
  }
  if(!active&&forms.length) active=forms[0];
  var shell=null;
  if(active){
    var n=active;
    while(n&&n.tagName!=='APP-CHAT') n=n.parentElement;
    shell=n;
  }
  var root=shell||active||document;
  var input=null;
  if(root&&root.querySelector){
    input=root.querySelector("input#file[type='file']");
  }
  var btn=null;
  var cands=(root&&root.querySelectorAll)?
    root.querySelectorAll(".mat-mdc-form-field-icon-suffix button"):[];
  for(var j=0;j<cands.length;j++){
    var ic=cands[j].querySelector("mat-icon");
    if(ic&&String(ic.textContent||"").trim()==='image'){btn=cands[j];break;}
  }
  out.ok=!!(input&&btn);
  if(input) out.input_css=cssPath(input);
  if(btn) out.button_css=cssPath(btn);
  if(shell) out.shell_css=cssPath(shell);
  return JSON.stringify(out);
})()"""


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


def _glob_of(low: str) -> str:
    """One lowercase token as a glob: a bare name/ext becomes ``*.name``;
    a token carrying its own wildcard is kept as-is."""
    if low.startswith("*."):
        return low
    if low.startswith("."):
        return "*" + low
    if "*" in low or "?" in low:
        return low
    return "*." + low.lstrip(".")


def parse_patterns(file_pattern: str) -> list[str]:
    """Normalize a comma/space/semicolon list into lowercase glob patterns.

    ``"gif"``, ``".png"`` and ``"*.JPG"`` all become usable patterns;
    anything containing its own wildcard is kept as-is. Empty input falls
    back to the default image formats.
    """
    tokens = [t.strip() for t in re.split(r"[,\s;]+", file_pattern or "")
              if t.strip()]
    patterns = [_glob_of(token.lower()) for token in tokens]
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
            path = os.path.join(folder, name)
            # a directory named `vacation.jpg` matches the glob but is
            # not attachable — only real files reach the file input
            if os.path.isfile(path):
                files.append(path)
    return sorted(set(files))


def _count_messages_js(shell_css: str) -> str:
    """JS returning the message-container count — scoped to the active
    conversation when a shell CSS path is known, global otherwise."""
    sel = f"{shell_css} .message-container" if shell_css else \
        ".message-container"
    return ("(function(){return String("
            "document.querySelectorAll(%s).length);})()" % json.dumps(sel))


def _readback_js(input_css: str) -> str:
    """JS returning files.length of the chosen file input ("0"/"1"/"none")."""
    return ("(function(){var i=document.querySelector(%s);"
            "return String((i&&i.files)?i.files.length:0);})()"
            % json.dumps(input_css))


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


async def _message_count(cdp: CDPClient, shell_css: str = "") -> Optional[int]:
    try:
        raw = await cdp.evaluate(_count_messages_js(shell_css))
        return int(str(raw).strip()) if str(raw).strip().isdigit() else None
    except Exception:
        return None


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


async def _guard_file_input(cdp: CDPClient, state: "_AttachState") -> None:
    """Find + report the hidden upload input (refuses when unusable)."""
    report = state.options.report
    try:
        raw = await cdp.evaluate(build_probe(selector=state.input_sel))
        res = json.loads(raw) if raw else None
    except Exception as exc:
        _refuse(report, f"❌ Probe error while searching file input: {exc}")
    if not (res and res.get("found")):
        total = int((res or {}).get("total", 0) or 0)
        _refuse(report, f"❌ Failed to find element: hidden file input "
                        f"'{state.input_sel}' (matched {total} node(s))")
    msg, level = interpret_wait(res, f"file input '{state.input_sel}'")
    _rep(report, msg, level)


async def _set_upload_file(cdp: CDPClient, state: "_AttachState") -> None:
    try:
        await cdp.set_file_input_files(state.input_sel,
                                       [os.path.abspath(state.path)])
    except Exception as exc:
        _refuse(state.options.report, f"❌ File injection failed: {exc}")


async def _readback_count(cdp: CDPClient, input_sel: str) -> int:
    """input.files.length after the write; -1 when unreadable."""
    try:
        raw = await cdp.evaluate(_readback_js(input_sel))
        return int(str(raw).strip()) if str(raw).strip().isdigit() else -1
    except Exception:
        return -1


async def _inject_file(cdp: CDPClient, state: _AttachState) -> None:
    """Step 5: wait for the hidden input, write the file, read it back."""
    report = state.options.report
    await _guard_file_input(cdp, state)
    state.baseline = await _message_count(cdp, state.shell_css)
    await _set_upload_file(cdp, state)
    # Read back: DOM.setFileInputFiles can silently no-op (node id 0) —
    # never trust it without proof the file actually landed.
    got = await _readback_count(cdp, state.input_sel)
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
