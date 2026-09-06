"""The JavaScript half of the collector, and the probes that drive it.

The agent itself lives in `backend/js/chat_agent.js` (a real file, so Node can
unit-test it). This module only loads it and builds the little expressions we
hand to `Runtime.evaluate`. Each probe is tagged with a marker comment
(`/*CVB_STATE*/` …) so the tests — and anyone reading a CDP log — can tell at
a glance which probe is running, and arguments travel inside
`/*ARGS*/{…}/*END*/` rather than being pasted into the source.
"""

from __future__ import annotations

import json
import os

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
    return "/*ARGS*/" + json.dumps(payload, ensure_ascii=False) + "/*END*/"


def install_expression() -> str:
    """(Re-)install the agent and return its version number."""
    return ("/*CVB_INSTALL*/(function(){try{" + agent_source() +
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


def slice_expression(start: int, end: int) -> str:
    """Exactly the half-open range [start, end) of message records."""
    return ("/*CVB_SLICE*/(function(){var a=window.__cvbAgent;"
            "if(!a)return JSON.stringify({ok:false,items:[]});"
            "var p=" + json.dumps({"from": int(start), "to": int(end)}) + ";"
            "try{return JSON.stringify(a.slice(p.from,p.to));}"
            "catch(e){return JSON.stringify({ok:false,items:[],"
            "error:String(e)});}})()" +
            _args({"from": int(start), "to": int(end)}))


def drain_expression() -> str:
    """Take whatever the observer buffered since the last drain."""
    return ("/*CVB_DRAIN*/(function(){var a=window.__cvbAgent;"
            "if(!a)return JSON.stringify({ok:false,items:[]});"
            "try{return JSON.stringify(a.drain());}"
            "catch(e){return JSON.stringify({ok:false,items:[]});}})()")


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
