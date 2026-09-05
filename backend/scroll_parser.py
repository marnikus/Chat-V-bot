"""Virtual scroll parser: scroll → detect new persons → filter → collect.

The list is lazy-loaded through an Angular CDK virtual-scroll viewport, so a
slow response looks exactly like the end of the list. This parser therefore
distinguishes the two explicitly:

  * after each scroll it *settles* — polling until either new people appear
    (lazy load finished) or the scroll position stops changing;
  * the end of the list is only declared when the viewport is geometrically at
    the bottom AND a further settle window produced nothing new.

Every decision is reported through the log callback so the run is observable.
"""

import asyncio
import json
import logging
from dataclasses import dataclass, field

from backend.cdp_client import CDPClient
from backend.dom_highlight import COLOR_COLLECT, build_highlight_probe
from backend.dom_probe import MATCH_EXACT
from backend.person_filter import PersonFilter, sort_people
from backend.user_memory import UserRecord

log = logging.getLogger("chatbot")

#: One round trip returns both the rendered people AND the scroll geometry, so
#: "is more content loading?" and "are we at the bottom?" can be answered from
#: a single evaluate() call.
_EXTRACT_JS = """(function(){
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


@dataclass
class CollectResult:
    """Outcome of one full scroll-parse pipeline run."""
    all_people: list = field(default_factory=list)
    collected: list = field(default_factory=list)
    scrolls: int = 0
    reached_end: bool = False
    stopped_early: bool = False
    rejected: dict = field(default_factory=dict)     # reason -> count

    @property
    def new_unmessaged(self) -> list:
        return [p for p in self.collected if not p.messaged]


class ScrollParser:
    """Scroll through the virtual user list, filtering and collecting people."""

    def __init__(self, cdp: CDPClient, criteria=None,
                 viewport_sel: str = "cdk-virtual-scroll-viewport.users-list-viewport",
                 scroll_dy: int = 300, pause_ms: int = 800,
                 stall_threshold: int = 3, max_scrolls: int = 50,
                 load_timeout_ms: int = 2500, poll_ms: int = 150,
                 person_filter: PersonFilter | None = None,
                 person_selector: str = "user-item",
                 nick_selector: str = ".primary-text",
                 highlight_enabled: bool = True,
                 highlight_ms: int = 900,
                 confirm_pause_ms: int = 500,
                 on_collect=None,
                 log_cb=None):
        self._cdp = cdp
        self._criteria = criteria
        self._vp_sel = viewport_sel
        self._scroll_dy = scroll_dy
        self._pause_ms = pause_ms
        self._stall = stall_threshold
        self.max_scrolls = max_scrolls
        self._load_timeout_ms = load_timeout_ms
        self._poll_ms = poll_ms
        self._filter = person_filter
        self._person_sel = person_selector
        self._nick_sel = nick_selector
        self._highlight_enabled = bool(highlight_enabled)
        self._highlight_ms = max(0, int(highlight_ms))
        self._confirm_pause_ms = max(0, int(confirm_pause_ms))
        #: async callback invoked right after each person is collected, so the
        #: UI list can refresh immediately instead of at the end of the run
        self._on_collect = on_collect
        self.known_nicks: set[str] = set()
        self._log_cb = log_cb

    # ── logging ──────────────────────────────────────────────────
    def set_log_cb(self, cb) -> None:
        """Optional (message, level) callback for debugger log lines."""
        self._log_cb = cb

    def _say(self, message: str, level: str = "info") -> None:
        if self._log_cb:
            try:
                self._log_cb(message, level)
            except Exception:
                pass
        log.log(getattr(logging, level.upper(), logging.INFO)
                if level else logging.INFO, "%s", message)

    # ── DOM access ───────────────────────────────────────────────
    async def _snapshot(self) -> dict | None:
        """Read the rendered people and the scroll geometry in one probe."""
        raw = await self._cdp.evaluate(
            _EXTRACT_JS % {"vp": json.dumps(self._vp_sel)})
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
        if not self._highlight_enabled:
            return False
        try:
            raw = await self._cdp.evaluate(build_highlight_probe(
                selector=self._person_sel,
                label_selector=self._nick_sel or None,
                match_text=nick,
                match_mode=MATCH_EXACT,
                color=COLOR_COLLECT,
                caption="MATCH",
                highlight_ms=self._highlight_ms,
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
        vp = await self._cdp.get_element_rect(self._vp_sel)
        if not vp:
            self._say(f"❌ Failed to find element: scroll viewport "
                      f"(selector '{self._vp_sel}')", "error")
            return False
        cx = vp["x"] + vp["width"] / 2
        cy = vp["y"] + vp["height"] / 2
        await self._cdp.mouse_wheel(0, self._scroll_dy, cx, cy)
        return True

    async def _settle(self, seen_before: set, prev_top: float) -> dict | None:
        """Wait for lazy-loaded people after a scroll.

        Returns the first snapshot that either contains new nicks or shows the
        scroll position has stopped moving. This is what separates "still
        loading" from "end of the list".
        """
        waited = 0
        snap = None
        stable = 0
        while waited < self._load_timeout_ms:
            await asyncio.sleep(self._poll_ms / 1000.0)
            waited += self._poll_ms
            snap = await self._snapshot()
            if snap is None:
                return None
            nicks = {u.get("nick") for u in snap.get("users", []) if u.get("nick")}
            if nicks - seen_before:
                if waited > self._poll_ms:
                    self._say(f"⏳ New people appeared after {waited} ms of "
                              "lazy loading", "info")
                return snap
            # nothing new yet — has the viewport stopped moving?
            if abs(float(snap.get("scrollTop", 0)) - prev_top) < 1:
                stable += 1
                if stable >= 2:
                    return snap
            else:
                stable = 0
                prev_top = float(snap.get("scrollTop", 0))
        self._say(f"⏳ Still nothing new after {self._load_timeout_ms} ms — "
                  "treating as loaded", "info")
        return snap

    async def _notify_collected(self, record, result) -> None:
        """Tell the caller a person was added, so the UI can refresh now."""
        if self._on_collect is None:
            return
        try:
            outcome = self._on_collect(record, list(result.collected))
            if asyncio.iscoroutine(outcome):
                await outcome
        except Exception as exc:      # a UI hiccup must never kill the parse
            log.warning("on_collect callback failed for %s: %s",
                        record.nick, exc)

    # ── the pipeline ─────────────────────────────────────────────
    async def collect(self, progress_cb=None, min_new_users: int = 0,
                      known_messaged: set | None = None) -> CollectResult:
        """Run scroll → detect → filter → collect.

        :param min_new_users: finish as soon as this many new *un-messaged*
            people have been collected (0 = always scroll to the end).
        :param known_messaged: nicks already messaged, used to mark records.
        """
        known_messaged = known_messaged or set()
        person_filter = self._filter or PersonFilter(
            female="any", registered="any", guest="any", anonymous="any",
            panel_criteria=self._criteria)
        result = CollectResult()
        collected_nicks: set[str] = set()

        self._say(f"🔍 Viewport selector: {self._vp_sel}", "info")
        self._say(f"🧮 Filter: {person_filter.describe()}", "info")

        snap = await self._snapshot()
        if snap is None:
            self._say("❌ Element search failed: no data returned from the page "
                      "(wrong page? not connected?)", "error")
            return result
        if not snap.get("viewport"):
            self._say(f"⚠ Scroll viewport '{self._vp_sel}' not found — parsing "
                      "whatever is currently rendered", "warn")

        no_new_count = 0
        for scroll_i in range(self.max_scrolls):
            result.scrolls = scroll_i + 1
            items = snap.get("users", []) or []
            new_this_scroll = 0

            for item in items:
                nick = (item.get("nick") or "").strip()
                if not nick or nick in self.known_nicks:
                    continue
                self.known_nicks.add(nick)
                new_this_scroll += 1
                record = self._to_record(item)
                result.all_people.append(record)

                verdict = person_filter.check(self._to_dict(item))
                if not verdict.passed:
                    result.rejected[verdict.reason] = \
                        result.rejected.get(verdict.reason, 0) + 1
                    continue
                if nick in collected_nicks:          # belt and braces
                    continue

                # Visual confirmation BEFORE adding: show the user exactly
                # which person was detected, then hold so it can be seen.
                shown = await self._confirm_person(nick)
                self._say(
                    f"  🟢 Match “{nick}” — {verdict.reason}"
                    + (" — green outline drawn" if shown else ""),
                    "success")
                if shown and self._confirm_pause_ms:
                    await asyncio.sleep(self._confirm_pause_ms / 1000.0)

                collected_nicks.add(nick)
                record.messaged = nick in known_messaged
                result.collected.append(record)
                self._say(f"  ✅ Added “{nick}” to the list "
                          f"({len(result.collected)} collected)", "success")

                # Refresh the UI immediately — do not wait for the scroll
                # cycle to finish.
                await self._notify_collected(record, result)

            if progress_cb:
                progress_cb(scroll_i + 1, len(result.all_people), new_this_scroll)
            if new_this_scroll:
                self._say(f"📜 Scroll {scroll_i + 1}/{self.max_scrolls}: "
                          f"+{new_this_scroll} new person(s), "
                          f"{len(result.all_people)} seen, "
                          f"{len(result.collected)} collected", "info")
                no_new_count = 0
            else:
                no_new_count += 1

            # STEP 3 early finish: enough new un-messaged people collected.
            unmessaged = len(result.new_unmessaged)
            if min_new_users > 0 and unmessaged >= min_new_users:
                result.stopped_early = True
                self._say(f"🎯 Collected {unmessaged} new un-messaged person(s) "
                          f"(target {min_new_users}) — finishing scroll early",
                          "success")
                break

            # End of list? Only when geometrically at the bottom and nothing new.
            if snap.get("atBottom") and new_this_scroll == 0:
                result.reached_end = True
                self._say("⏹ Bottom of the list reached and no new people "
                          "loaded — end of list", "success")
                break
            if no_new_count >= self._stall:
                result.reached_end = True
                self._say(f"⏹ No new people after {self._stall} scrolls — "
                          "list fully parsed (stall detected)", "warn")
                break

            prev_top = float(snap.get("scrollTop", 0))
            if not await self._do_scroll():
                break
            if self._pause_ms > 0:
                await asyncio.sleep(self._pause_ms / 1000.0)
            settled = await self._settle(set(self.known_nicks), prev_top)
            if settled is None:
                self._say("❌ Lost the page context while scrolling", "error")
                break
            snap = settled
        else:
            self._say(f"⏹ Reached max scrolls ({self.max_scrolls})", "warn")

        result.collected = sort_people(result.collected)
        if result.rejected:
            detail = ", ".join(f"{n}× {reason}"
                               for reason, n in sorted(result.rejected.items()))
            self._say(f"🚫 Filtered out: {detail}", "info")
        self._say(f"📊 Parse finished: {len(result.all_people)} person(s) seen, "
                  f"{len(result.collected)} matched the filter "
                  f"({len(result.new_unmessaged)} not yet messaged)", "success")
        log.info("Collected %d/%d people", len(result.collected),
                 len(result.all_people))
        return result

    # ── backwards-compatible API ─────────────────────────────────
    async def parse(self, progress_cb=None) -> tuple[list, list]:
        """Legacy entry point: returns (all_users, filtered_users)."""
        result = await self.collect(progress_cb=progress_cb)
        return result.all_people, result.collected
