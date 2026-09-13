"""The page probe: one round trip, and how its JSON becomes records.

Owns the embedded `_EXTRACT_JS` payload, the `STOPPED` sentinel, and the two
pure mappers that turn a probe item into a `UserRecord` or a filter dict.

One probe returns both the rendered people AND the scroll geometry, so "is
more content loading?" and "are we at the bottom?" are answered from a single
`evaluate()` call rather than two races.

RULE 16 §16.1.5: the length of this module is a JS string literal, not control
flow. The Python around it stays CC <= 10.
"""

import json
import logging

from stores.user_memory import UserRecord

log = logging.getLogger("chatbot")

#: "is more content loading?" and "are we at the bottom?" can be answered from
#: a single evaluate() call.
EXTRACT_JS = """(function(){
    var vp = document.querySelector(%(vp)s);
    var items = document.querySelectorAll('user-item');
    var users = [];
    items.forEach(function(item){
        var wrapper = item.querySelector('.avatar-wrapper');
        var badge = item.querySelector('.badge');
        var nickEl = item.querySelector('.primary-text');
        if(!wrapper||!nickEl) return;
        var cl = wrapper.classList;
        users.push({
            nick: nickEl.textContent.trim(),
            female: cl.contains('female-avatar'),
            male: cl.contains('male-avatar'),
            guest: cl.contains('guest-avatar'),
            registered: badge ? badge.classList.contains('registered-badge') : false,
            anonymous: badge ? badge.classList.contains('anonymous-badge') : false
        });
    });
    var top = 0, height = 0, client = 0;
    if (vp) {
        top = vp.scrollTop || 0;
        height = vp.scrollHeight || 0;
        client = vp.clientHeight || 0;
    }
    return JSON.stringify({
        users: users, count: users.length, viewport: !!vp,
        scrollTop: top, scrollHeight: height, clientHeight: client,
        atBottom: !!vp && (top + client >= height - 4)
    });
})()""" 


#: Returned by :meth:`ScrollParser._settle` when the user stopped the run
#: before any snapshot could be taken — distinct from ``None``, which means
#: the page context was genuinely lost.
STOPPED = object()


def to_record(item: dict) -> UserRecord:
    """One probe item -> the record the rest of the app stores."""
    return UserRecord(
        nick=item["nick"],
        gender=("female" if item.get("female")
                else "male" if item.get("male") else "unknown"),
        registered=bool(item.get("registered")),
        anonymous=bool(item.get("anonymous")),
        guest=bool(item.get("guest")),
    )


def to_dict(item: dict) -> dict:
    """One probe item -> the plain dict `PersonFilter.check` expects."""
    return {"nick": item.get("nick", ""),
            "female": bool(item.get("female")),
            "male": bool(item.get("male")),
            "guest": bool(item.get("guest")),
            "registered": bool(item.get("registered")),
            "anonymous": bool(item.get("anonymous"))}


def parse_snapshot(raw) -> dict | None:
    """Decode one probe response; None when the page said nothing usable."""
    if not raw:
        return None
    try:
        return json.loads(raw) if isinstance(raw, str) else raw
    except (json.JSONDecodeError, TypeError):
        return None
