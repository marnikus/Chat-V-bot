"""The JS this family injects, and the selectors it injects them against.

Part of the `media_handler` family (entry point: `backend/media_handler.py`,
Round J step J-6). Three payloads plus the four selectors they hardcode:

* `CTX_PROBE_JS` — resolves the VISIBLE composer and returns unique CSS paths
  for its image button, its hidden file input and its chat shell, so every
  later step targets the conversation the user is actually looking at rather
  than a hidden main-room composer that also lives in the DOM;
* `count_messages_js(shell_css)` — the message-container count, scoped to that
  shell when one is known and global otherwise (the send verification's
  before/after probe);
* `readback_js(input_css)` — `input.files.length`, because `DOM.setFileInputFiles`
  can silently no-op and the pipeline must never trust it without proof;
* `IMAGE_BUTTON_SELECTOR` / `IMAGE_BUTTON_LABEL` / `IMAGE_ICON_TEXT` /
  `FILE_INPUT_SELECTOR` — the global fallback selectors. They live here, next
  to the probe that embeds the same three literals by hand, so a drift
  between the scoped probe and the fallback path is visible in one file.

`ideal-size:` the module is a payload host, like `backend/dom_highlight_js.py`:
`CTX_PROBE_JS` alone is 55 lines of JavaScript. Keeping the literals out of
the pipeline is what lets `backend/media_handler.py` hold a readable six-step
flow instead of 474 mixed lines.
"""

import json

#: Global (fallback) selectors — the live page can keep several chat panels
#: mounted, so these are only used when the active-conversation probe fails.
IMAGE_BUTTON_SELECTOR = ".mat-mdc-form-field-icon-suffix button"
IMAGE_BUTTON_LABEL = "mat-icon"
IMAGE_ICON_TEXT = "image"
FILE_INPUT_SELECTOR = "input#file[type='file']"

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


def count_messages_js(shell_css: str) -> str:
    """JS returning the message-container count — scoped to the active
    conversation when a shell CSS path is known, global otherwise."""
    sel = f"{shell_css} .message-container" if shell_css else \
        ".message-container"
    return ("(function(){return String("
            "document.querySelectorAll(%s).length);})()" % json.dumps(sel))


def readback_js(input_css: str) -> str:
    """JS returning files.length of the chosen file input ("0"/"1"/"none")."""
    return ("(function(){var i=document.querySelector(%s);"
            "return String((i&&i.files)?i.files.length:0);})()"
            % json.dumps(input_css))
