"""The viewport probe and the scroll mechanics of one scroll-parse run.

Part of the `scroll_parser_*` family (facade and family map:
`backend/scroll_parser.py`). One JS payload, one settle detector, one
highlight confirmation — everything that talks to the DOM.
"""

from __future__ import annotations

import asyncio
import json
import logging

from backend.dom_highlight import build_highlight_probe
from backend.probe_requests import HighlightSpec
from backend.scroll_parser_model import STOPPED
from backend.selectors import js_literals
from stores.user_memory import UserRecord

log = logging.getLogger("chatbot")

#: One round trip returns both the rendered people AND the scroll geometry, so
#: "is more content loading?" and "are we at the bottom?" can be answered from
#: a single evaluate() call.
_EXTRACT_JS = """(function(){
    var vp = document.querySelector(%(vp)s);
    var items = document.querySelectorAll(%(user_item)s);
    var users = [];
    items.forEach(function(item){
        var wrapper = item.querySelector(%(avatar_wrapper)s);
        var badge = item.querySelector(%(user_badge)s);
        var nickEl = item.querySelector(%(user_nick)s);
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


def _to_record(item: dict) -> UserRecord:
    return UserRecord(
        nick=item["nick"],
        gender=("female" if item.get("female")
                else "male" if item.get("male") else "unknown"),
        registered=bool(item.get("registered")),
        anonymous=bool(item.get("anonymous")),
        guest=bool(item.get("guest")),
    )


def _to_dict(item: dict) -> dict:
    return {"nick": item.get("nick", ""),
            "female": bool(item.get("female")),
            "male": bool(item.get("male")),
            "guest": bool(item.get("guest")),
            "registered": bool(item.get("registered")),
            "anonymous": bool(item.get("anonymous"))}


class ScrollDom:
    """The DOM half of one parser: probe, confirm, scroll, settle.

    Holds the facade and reads its `_cdp` / `options` / `_log_cb` **live** —
    the callback setters replace the frozen options object, so nothing here
    may cache it.
    """

    def __init__(self, parser):
        self.p = parser

    async def snapshot(self) -> dict | None:
        """Read the rendered people and the scroll geometry in one probe."""
        raw = await self.p._cdp.evaluate(
            _EXTRACT_JS % {"vp": json.dumps(self.p.options.viewport_sel),
                           **js_literals()})
        if not raw:
            return None
        try:
            return json.loads(raw) if isinstance(raw, str) else raw
        except (json.JSONDecodeError, TypeError):
            return None

    async def confirm_person(self, nick: str) -> bool:
        """Draw a GREEN overlay on the person that just matched the filter.

        Pure visual confirmation: it never clicks and never scrolls the
        viewport (that would corrupt the parser's scroll tracking).
        """
        options = self.p.options
        if not options.highlight_enabled:
            return False
        try:
            raw = await self.p._cdp.evaluate(build_highlight_probe(
                options.person_selector,
                HighlightSpec(label_selector=options.nick_selector or None,
                              match_text=nick,
                              highlight_ms=options.highlight_ms)))
        except Exception as exc:
            log.warning("Highlight probe failed for %s: %s", nick, exc)
            return False
        try:
            res = json.loads(raw) if raw else None
        except (json.JSONDecodeError, TypeError):
            res = None
        return bool(res and res.get("highlighted"))

    async def do_scroll(self) -> bool:
        """Dispatch a mouseWheel event on the viewport center."""
        vp = await self.p._cdp.get_element_rect(self.p.options.viewport_sel)
        if not vp:
            self.p._say(f"❌ Failed to find element: scroll viewport "
                        f"(selector '{self.p.options.viewport_sel}')", "error")
            return False
        cx = vp["x"] + vp["width"] / 2
        cy = vp["y"] + vp["height"] / 2
        await self.p._cdp.mouse_wheel(0, self.p.options.scroll_dy, cx, cy)
        return True

    async def settle(self, seen_before: set, prev_top: float) -> dict | None:
        """Wait for lazy-loaded people after a scroll.

        Returns the first snapshot that either contains new nicks or shows the
        scroll position has stopped moving. This is what separates "still
        loading" from "end of the list".
        """
        options = self.p.options
        waited = 0
        snap = None
        stable = 0
        while waited < options.load_timeout_ms:
            if self.p._stop_requested():
                # Distinguish "user stopped" from "page context lost": return
                # the last good snapshot, or the STOPPED sentinel if we never
                # got one, so the caller does not report a bogus page error.
                return snap if snap is not None else STOPPED
            await asyncio.sleep(options.poll_ms / 1000.0)
            waited += options.poll_ms
            snap = await self.snapshot()
            if snap is None:
                return None
            if self.new_people(snap, seen_before, waited):
                return snap
            # nothing new yet — has the viewport stopped moving?
            stable, prev_top, arrived = self.settle_poll(snap, prev_top, stable)
            if arrived:
                return snap
        self.p._say(f"⏳ Still nothing new after {options.load_timeout_ms} ms — "
                    "treating as loaded", "info")
        return snap

    def new_people(self, snap: dict, seen_before: set, waited: int) -> bool:
        """True (with the info line) when lazy-loading delivered fresh nicks."""
        nicks = {u.get("nick") for u in snap.get("users", []) if u.get("nick")}
        if not (nicks - seen_before):
            return False
        if waited > self.p.options.poll_ms:
            self.p._say(f"⏳ New people appeared after {waited} ms of "
                        "lazy loading", "info")
        return True

    def settle_poll(self, snap: dict, prev_top: float,
                    stable: int) -> tuple[int, float, bool]:
        """One "nothing new yet" poll → (stable count, reference top, arrived).

        Two consecutive polls at (almost) the same scrollTop are what mean the
        pane arrived, so the reference position only moves while it is still
        scrolling — a stopped viewport keeps comparing against the same mark.
        """
        stopped, top = self.scroll_stopped(snap, prev_top)
        if not stopped:
            return 0, top, False
        stable += 1
        return stable, prev_top, stable >= 2

    @staticmethod
    def scroll_stopped(snap: dict, prev_top: float) -> tuple[bool, float]:
        """Whether the viewport stopped moving, and where it is now.

        The caller only adopts the new position while the pane is still
        moving, so a stopped viewport keeps comparing against the same
        reference — two consecutive still polls are what mean "arrived".
        """
        top = float(snap.get("scrollTop", 0))
        return abs(top - prev_top) < 1, top
