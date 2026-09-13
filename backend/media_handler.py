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
from backend.logger import report_and_log
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


#: the shared report-and-log helper; `_rep` stays as this module's spelling
#: because it is called dozens of times here and at every call site the short
#: name reads better than the import path.
_rep = report_and_log


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


