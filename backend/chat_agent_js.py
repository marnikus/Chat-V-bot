"""The JavaScript half of the collector, and the probes that drive it.

The agent itself lives in `backend/js/chat_agent.js` (a real file, so Node can
unit-test it). This module only loads it and builds the little expressions we
hand to `Runtime.evaluate`. Each probe is tagged with a marker comment
(`/*CVB_STATE*/` …) so the tests — and anyone reading a CDP log — can tell at
a glance which probe is running, and arguments travel inside a single
`/*ARGS:{…}*/` block comment rather than being pasted into the source.
"""

from __future__ import annotations

import json
import os

#: The version the shipped agent declares. Python refuses to trust an older
#: agent (it predates the pane-scoped parser and the author report) and
#: re-installs instead — see backend/collector.py.
AGENT_VERSION = 13

AGENT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "js",
                          "chat_agent.js")

_CACHE: dict[str, str] = {}


def agent_source() -> str:
    """The shipped in-page agent, read once."""
    if "src" not in _CACHE:
        with open(AGENT_PATH, encoding="utf-8") as handle:
            _CACHE["src"] = handle.read()
    return _CACHE["src"]


def _args(payload: dict) -> str:
    # A single block comment. The old `/*ARGS*/{…}/*END*/` CLOSED the comment
    # at `/*ARGS*/`, so the JSON object literal became real source and the
    # probe caused a SyntaxError — which is why state() worked (8 messages)
    # but every slice() returned [] and the archive stayed at 0.
    return "/*ARGS:" + json.dumps(payload, ensure_ascii=False) + "*/"


def install_expression(*, force: bool = False) -> str:
    """(Re-)install the agent and return its version number."""
    reset = ("var old=window.__cvbAgent;if(old&&old.uninstall)old.uninstall();"
             "delete window.__cvbAgent;") if force else ""
    return ("/*CVB_INSTALL*/(function(){try{" + reset + agent_source() +
            "}catch(e){return 0;}"
            "return window.__cvbAgent?window.__cvbAgent.version:0;})()")


def state_expression() -> str:
    """A cheap summary of the conversation — never its contents."""
    return ("/*CVB_STATE*/(function(){var a=window.__cvbAgent;"
            "if(!a)return JSON.stringify({ok:false,agent:0,"
            "reason:'agent missing'});"
            "try{return JSON.stringify(a.state());}"
            "catch(e){return JSON.stringify({ok:false,agent:a.version,"
            "reason:String(e)});}})()")


def reset_expression(nick=None) -> str:
    payload = {"nick": nick}
    return ("/*CVB_RESET_AGENT*/(function(){var a=window.__cvbAgent;"
            "if(!a||!a.reset)return JSON.stringify({ok:false,reason:'reset unavailable'});"
            "try{return JSON.stringify(a.reset(" + json.dumps(nick, ensure_ascii=False) + "));}"
            "catch(e){return JSON.stringify({ok:false,reason:String(e)});}})()" + _args(payload))


def slice_expression(start: int, end: int, *, refresh: bool = False) -> str:
    """Exactly the half-open range [start, end) of message records."""
    payload = {"from": int(start), "to": int(end)}
    if refresh:
        payload["refresh"] = True
    return ("/*CVB_SLICE*/(function(){var a=window.__cvbAgent;"
            "if(!a)return JSON.stringify({ok:false,items:[]});"
            "var p=" + json.dumps(payload) + ";"
            "try{return JSON.stringify(a.slice(p.from,p.to,!!p.refresh));}"
            "catch(e){return JSON.stringify({ok:false,items:[],"
            "error:String(e)});}})()" +
            _args(payload))


def drain_expression() -> str:
    """Take whatever the observer buffered since the last drain."""
    return ("/*CVB_DRAIN*/(function(){var a=window.__cvbAgent;"
            "if(!a)return JSON.stringify({ok:false,items:[]});"
            "try{return JSON.stringify(a.drain());}"
            "catch(e){return JSON.stringify({ok:false,items:[]});}})()")


def scroll_top_expression() -> str:
    """Ask the agent to scroll the conversation to its first message."""
    return ("/*CVB_SCROLL_TOP*/(function(){var a=window.__cvbAgent;"
            "if(!a)return JSON.stringify({ok:false,error:'agent missing'});"
            "try{return JSON.stringify(a.scrollToTop());}"
            "catch(e){return JSON.stringify({ok:false,error:String(e)});}})()")


def restore_scroll_expression(top: int) -> str:
    """Put the conversation back where the collector found it."""
    payload = {"top": int(top or 0)}
    return ("/*CVB_RESTORE_SCROLL*/(function(){var a=window.__cvbAgent;"
            "if(!a)return JSON.stringify({ok:false,error:'agent missing'});"
            "var p=" + json.dumps(payload) + ";"
            "try{return JSON.stringify(a.restoreScroll(p.top));}"
            "catch(e){return JSON.stringify({ok:false,error:String(e)});}})()" +
            _args(payload))


def fetch_media_expression(url: str) -> str:
    """Fetch one media file *from inside the page*, so its cookies apply."""
    payload = {"url": str(url)}
    return ("/*CVB_FETCH_MEDIA*/(async function(){var p=" +
            json.dumps(payload, ensure_ascii=False) + ";try{"
            "var r=await fetch(p.url,{credentials:'include'});"
            "if(!r.ok)return JSON.stringify({ok:false,"
            "error:'HTTP '+r.status});"
            "var b=await r.blob();"
            "if(b.size>25*1024*1024)return JSON.stringify({ok:false,"
            "error:'too large to transfer'});"
            "var buf=await b.arrayBuffer();var bytes=new Uint8Array(buf);"
            "var bin='';for(var i=0;i<bytes.length;i++)"
            "bin+=String.fromCharCode(bytes[i]);"
            "return JSON.stringify({ok:true,b64:btoa(bin),mime:b.type,"
            "bytes:bytes.length});}"
            "catch(e){return JSON.stringify({ok:false,error:String(e)});}"
            "})()" + _args(payload))
