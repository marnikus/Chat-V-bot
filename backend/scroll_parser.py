"""Virtual scroll parser: extract users from CDK virtual-scroll viewport."""

import asyncio
import json
import logging
from backend.cdp_client import CDPClient
from backend.user_memory import UserRecord
from backend.criteria_engine import CriteriaEngine

log = logging.getLogger("chatbot")

_EXTRACT_JS = """(function(){
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
    return JSON.stringify(users);
})()"""


class ScrollParser:
    """Scroll through the virtual user list and extract all users."""

    def __init__(self, cdp: CDPClient, criteria: CriteriaEngine,
                 viewport_sel: str = "cdk-virtual-scroll-viewport.users-list-viewport",
                 scroll_dy: int = 300, pause_ms: int = 800,
                 stall_threshold: int = 3, max_scrolls: int = 50,
                 log_cb=None):
        self._cdp = cdp
        self._criteria = criteria
        self._vp_sel = viewport_sel
        self._scroll_dy = scroll_dy
        self._pause_ms = pause_ms
        self._stall = stall_threshold
        self.max_scrolls = max_scrolls
        self.known_nicks: set[str] = set()
        self._log_cb = log_cb

    def set_log_cb(self, cb) -> None:
        """Optional (message, level) callback for debugger log lines."""
        self._log_cb = cb

    def _say(self, message: str, level: str = "info") -> None:
        if self._log_cb:
            try:
                self._log_cb(message, level)
            except Exception:
                pass
        log.log(getattr(logging, level.upper(), logging.INFO) if level else logging.INFO,
                "%s", message)

    async def parse(self, progress_cb=None) -> tuple[list[UserRecord], list[UserRecord]]:
        """Run the full scroll-parse loop.
        Returns (all_users, filtered_users)."""
        all_users: list[UserRecord] = []
        no_new_count = 0
        self._say(f"🔍 Viewport selector: {self._vp_sel}", "info")
        for scroll_i in range(self.max_scrolls):
            raw = await self._cdp.evaluate(_EXTRACT_JS)
            if not raw:
                self._say("❌ Element search failed: no user-item nodes found on page "
                          "(wrong page? not connected?)", "error")
                break
            items = json.loads(raw) if isinstance(raw, str) else raw
            new_this_scroll = 0
            for item in items:
                if item["nick"] in self.known_nicks or not item["nick"]:
                    continue
                self.known_nicks.add(item["nick"])
                user = UserRecord(
                    nick=item["nick"],
                    gender="female" if item["female"] else "male" if item["male"] else "unknown",
                    registered=item["registered"],
                    anonymous=item["anonymous"],
                    guest=item["guest"],
                )
                all_users.append(user)
                new_this_scroll += 1
            if progress_cb:
                progress_cb(scroll_i + 1, len(all_users), new_this_scroll)
            if new_this_scroll > 0:
                self._say(f"📜 Scroll {scroll_i + 1}/{self.max_scrolls}: "
                          f"+{new_this_scroll} new user(s), {len(all_users)} total", "info")
            if new_this_scroll == 0:
                no_new_count += 1
                if no_new_count >= self._stall:
                    self._say(f"⏹ No new users after {self._stall} scrolls — "
                              "list fully parsed (stall detected)", "warn")
                    break
            else:
                no_new_count = 0
            if not await self._do_scroll():
                break
            await asyncio.sleep(self._pause_ms / 1000.0)
        else:
            self._say(f"⏹ Reached max scrolls ({self.max_scrolls})", "warn")
        filtered = [u for u in all_users if self._criteria.evaluate_user({
            "female": u.gender == "female", "male": u.gender == "male",
            "registered": u.registered, "anonymous": u.anonymous, "guest": u.guest,
        })]
        self._say(f"📊 Parse finished: {len(all_users)} users total, "
                  f"{len(filtered)} passed criteria", "success")
        log.info("Parsed %d users total, %d passed criteria", len(all_users), len(filtered))
        return all_users, filtered

    async def _do_scroll(self) -> bool:
        """Dispatch a mouseWheel event on the viewport center."""
        vp = await self._cdp.get_element_rect(self._vp_sel)
        if not vp:
            self._say(f"❌ Failed to find element: scroll viewport "
                      f"(selector '{self._vp_sel}')", "error")
            return False
        cx = vp["x"] + vp["width"] / 2
        cy = vp["y"] + vp["height"] / 2
        await self._cdp.mouse_wheel(0, self._scroll_dy, cx, cy)
        return True
