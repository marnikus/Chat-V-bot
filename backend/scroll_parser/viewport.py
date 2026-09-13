"""Everything that talks to the page: probe, scroll, and wait for lazy load.

Owns the `Viewport` collaborator — the only place in the package that calls
`cdp.evaluate`, `cdp.get_element_rect` or `cdp.mouse_wheel`. The judging and
the loop above it never touch the browser directly, which is what lets the
pipeline be tested against a fake CDP client (RULE 8).

The hard problem this module exists for, restated from the package docstring:
**a slow lazy-load looks exactly like the end of the list.** `settle()` is the
answer — it polls until either new nicks appear (loading finished) or the
scroll position stops moving twice in a row (the pane arrived).

Host protocol: the collaborator reads `host.options`, `host._cdp`,
`host._say()` and `host._stop_requested()`. It holds no state of its own, so
reassigning `host.options` (the callback setters do) is picked up immediately.
"""

import asyncio
import json
import logging

from backend.dom_highlight import COLOR_COLLECT, build_highlight_probe
from backend.dom_probe import MATCH_EXACT
from backend.scroll_parser.probe import EXTRACT_JS, STOPPED, parse_snapshot

log = logging.getLogger("chatbot")


class Viewport:
    """The page-facing half of a scroll-parse run."""

    def __init__(self, host):
        self.p = host

    async def snapshot(self) -> dict | None:
        """Read the rendered people and the scroll geometry in one probe."""
        raw = await self.p._cdp.evaluate(
            EXTRACT_JS % {"vp": json.dumps(self.p.options.viewport_sel)})
        return parse_snapshot(raw)

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
                selector=options.person_selector,
                label_selector=options.nick_selector or None,
                match_text=nick,
                match_mode=MATCH_EXACT,
                color=COLOR_COLLECT,
                caption="MATCH",
                highlight_ms=options.highlight_ms,
            ))
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
        options = self.p.options
        vp = await self.p._cdp.get_element_rect(options.viewport_sel)
        if not vp:
            self.p._say(f"❌ Failed to find element: scroll viewport "
                        f"(selector '{options.viewport_sel}')", "error")
            return False
        cx = vp["x"] + vp["width"] / 2
        cy = vp["y"] + vp["height"] / 2
        await self.p._cdp.mouse_wheel(0, options.scroll_dy, cx, cy)
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
            if self._new_people(snap, seen_before, waited):
                return snap
            # nothing new yet — has the viewport stopped moving?
            stable, prev_top, arrived = self._settle_poll(snap, prev_top,
                                                          stable)
            if arrived:
                return snap
        self.p._say(f"⏳ Still nothing new after {options.load_timeout_ms} ms "
                    "— treating as loaded", "info")
        return snap

    def _new_people(self, snap: dict, seen_before: set, waited: int) -> bool:
        """True (with the info line) when lazy-loading delivered fresh nicks."""
        nicks = {u.get("nick") for u in snap.get("users", []) if u.get("nick")}
        if not (nicks - seen_before):
            return False
        if waited > self.p.options.poll_ms:
            self.p._say(f"⏳ New people appeared after {waited} ms of "
                        "lazy loading", "info")
        return True

    def _settle_poll(self, snap: dict, prev_top: float,
                     stable: int) -> tuple[int, float, bool]:
        """One "nothing new yet" poll → (stable count, reference top, arrived).

        Two consecutive polls at (almost) the same scrollTop are what mean the
        pane arrived, so the reference position only moves while it is still
        scrolling — a stopped viewport keeps comparing against the same mark.
        """
        stopped, top = self._scroll_stopped(snap, prev_top)
        if not stopped:
            return 0, top, False
        stable += 1
        return stable, prev_top, stable >= 2

    @staticmethod
    def _scroll_stopped(snap: dict, prev_top: float) -> tuple[bool, float]:
        """Whether the viewport stopped moving, and where it is now.

        The caller only adopts the new position while the pane is still
        moving, so a stopped viewport keeps comparing against the same
        reference — two consecutive still polls are what mean "arrived".
        """
        top = float(snap.get("scrollTop", 0))
        return abs(top - prev_top) < 1, top
