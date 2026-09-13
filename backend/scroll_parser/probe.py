"""Reading the page: the people, the geometry, the highlight, the settle.

`ProbeMixin` owns every trip to the CDP client. Nothing here decides who to
keep or when to stop — it only reports what the page is showing right now,
including the settle loop that tells "still lazy-loading" apart from "end of
the list".
"""

import asyncio
import json
import logging

from backend.dom_highlight import COLOR_COLLECT, build_highlight_probe
from backend.dom_probe import MATCH_EXACT
from stores.user_memory import UserRecord

from .constants import STOPPED, _EXTRACT_JS

log = logging.getLogger("chatbot")


class ProbeMixin:
    # ── DOM access ───────────────────────────────────────────────
    async def _snapshot(self) -> dict | None:
        """Read the rendered people and the scroll geometry in one probe."""
        raw = await self._cdp.evaluate(
            _EXTRACT_JS % {"vp": json.dumps(self.options.viewport_sel)})
        if not raw:
            return None
        try:
            return json.loads(raw) if isinstance(raw, str) else raw
        except (json.JSONDecodeError, TypeError):
            return None

    @staticmethod
    def _to_record(item: dict) -> UserRecord:
        return UserRecord(
            nick=item["nick"],
            gender=("female" if item.get("female")
                    else "male" if item.get("male") else "unknown"),
            registered=bool(item.get("registered")),
            anonymous=bool(item.get("anonymous")),
            guest=bool(item.get("guest")),
        )

    @staticmethod
    def _to_dict(item: dict) -> dict:
        return {"nick": item.get("nick", ""),
                "female": bool(item.get("female")),
                "male": bool(item.get("male")),
                "guest": bool(item.get("guest")),
                "registered": bool(item.get("registered")),
                "anonymous": bool(item.get("anonymous"))}

    async def _confirm_person(self, nick: str) -> bool:
        """Draw a GREEN overlay on the person that just matched the filter.

        Pure visual confirmation: it never clicks and never scrolls the
        viewport (that would corrupt the parser's scroll tracking).
        """
        options = self.options
        if not options.highlight_enabled:
            return False
        try:
            raw = await self._cdp.evaluate(build_highlight_probe(
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

    async def _do_scroll(self) -> bool:
        """Dispatch a mouseWheel event on the viewport center."""
        vp = await self._cdp.get_element_rect(self.options.viewport_sel)
        if not vp:
            self._say(f"❌ Failed to find element: scroll viewport "
                      f"(selector '{self.options.viewport_sel}')", "error")
            return False
        cx = vp["x"] + vp["width"] / 2
        cy = vp["y"] + vp["height"] / 2
        await self._cdp.mouse_wheel(0, self.options.scroll_dy, cx, cy)
        return True

    def _new_people(self, snap: dict, seen_before: set, waited: int) -> bool:
        """True (with the info line) when lazy-loading delivered fresh nicks."""
        nicks = {u.get("nick") for u in snap.get("users", [])
                 if u.get("nick")}
        if not (nicks - seen_before):
            return False
        if waited > self.options.poll_ms:
            self._say(f"⏳ New people appeared after {waited} ms of "
                      "lazy loading", "info")
        return True

    async def _settle(self, seen_before: set, prev_top: float) -> dict | None:
        """Wait for lazy-loaded people after a scroll.

        Returns the first snapshot that either contains new nicks or shows the
        scroll position has stopped moving. This is what separates "still
        loading" from "end of the list".
        """
        options = self.options
        waited, snap, stable = 0, None, 0
        while waited < options.load_timeout_ms:
            if self._stop_requested():
                # Distinguish "user stopped" from "page context lost": return
                # the last good snapshot, or the STOPPED sentinel if we never
                # got one, so the caller does not report a bogus page error.
                return snap if snap is not None else STOPPED
            await asyncio.sleep(options.poll_ms / 1000.0)
            waited += options.poll_ms
            snap = await self._snapshot()
            if snap is None:
                return None
            if self._new_people(snap, seen_before, waited):
                return snap
            # nothing new yet — has the viewport stopped moving?
            top = float(snap.get("scrollTop", 0))
            stable = 0 if abs(top - prev_top) >= 1 else stable + 1
            prev_top = top
            if stable >= 2:
                return snap
        self._say(f"⏳ Still nothing new after {options.load_timeout_ms} ms — "
                  "treating as loaded", "info")
        return snap

    async def _hold_confirmation(self, shown: bool) -> None:
        if shown and self.options.confirm_pause_ms:
            await asyncio.sleep(self.options.seconds("confirm_pause_ms"))
