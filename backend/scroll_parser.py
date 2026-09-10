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
import dataclasses
import json
import logging
from dataclasses import dataclass, field

from backend.cdp_client import CDPClient
from backend.dom_highlight import COLOR_COLLECT, build_highlight_probe
from backend.dom_probe import MATCH_EXACT
from backend.person_filter import PersonFilter, sort_people
from stores.user_memory import UserRecord

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


#: Returned by :meth:`ScrollParser._settle` when the user stopped the run
#: before any snapshot could be taken — distinct from ``None``, which means
#: the page context was genuinely lost.
STOPPED = object()


@dataclass
class CollectResult:
    """Outcome of one full scroll-parse pipeline run."""
    all_people: list = field(default_factory=list)
    collected: list = field(default_factory=list)
    scrolls: int = 0
    reached_end: bool = False
    stopped_early: bool = False
    stopped: bool = False                            # halted by the user
    seeking: bool = False                            # scroll-only seek run
    found: object = None                             # person located by a seek
    rejected: dict = field(default_factory=dict)     # reason -> count
    rejected_people: list = field(default_factory=list)   # (record, reason)
    purged: list = field(default_factory=list)       # nicks destroyed

    @property
    def new_unmessaged(self) -> list:
        return [p for p in self.collected if not p.messaged]


#: The pipeline's pacing and appearance knobs, in one immutable place.
#:
#: `ScrollParser.__init__` used to take these as 17 keyword arguments, which
#: meant every phase of the run threaded them along by hand and
#: `actions/scroll_parse.py` had to unpack its whole block configuration into
#: them one by one. They are data now: `ScrollOptions`, and the block can hand
#: the same thing over as one value (`ScrollParser.from_options`).
@dataclass(frozen=True, slots=True)
class ScrollOptions:
    """Configuration of one scroll-parse run."""

    viewport_sel: str = "cdk-virtual-scroll-viewport.users-list-viewport"
    scroll_dy: int = 300
    #: pause after each wheel event, so the page can catch up
    pause_ms: int = 800
    #: how many quiet scrolls in a row mean "this list is done"
    stall_threshold: int = 3
    max_scrolls: int = 50
    #: how long to wait for lazy-loaded people after a scroll
    load_timeout_ms: int = 2500
    poll_ms: int = 150
    person_filter: PersonFilter | None = None
    person_selector: str = "user-item"
    nick_selector: str = ".primary-text"
    highlight_enabled: bool = True
    highlight_ms: int = 900
    #: how long a drawn confirmation stays on screen
    confirm_pause_ms: int = 500
    #: async callback invoked right after each person is collected, so the
    #: UI list can refresh immediately instead of at the end of the run
    on_collect: object = None
    #: async callback for people that FAIL the filter, so the caller can
    #: destroy any stored record for them
    on_reject: object = None
    #: predicate returning True when the user asked the run to stop
    should_stop: object = None
    #: (message, level) callback for the debugger pane
    log_cb: object = None

    def __post_init__(self):
        # the three knobs the old constructor normalised — same clamping,
        # same place (a negative highlight would make the JS timer fire
        # immediately and the user would never see the outline)
        _set = object.__setattr__
        _set(self, "highlight_enabled", bool(self.highlight_enabled))
        _set(self, "highlight_ms", max(0, int(self.highlight_ms)))
        _set(self, "confirm_pause_ms", max(0, int(self.confirm_pause_ms)))

    def seconds(self, ms_attr: str) -> float:
        return getattr(self, ms_attr) / 1000.0


@dataclass
class _Pass:
    """What one scroll pass mutates, so the phases do not need 12 arguments.

    `seeking` is a snapshot of "the caller handed us names", taken BEFORE the
    loop starts shrinking `seek_nicks` — the mode must not silently flip off
    halfway through a run (RULE 9).
    """

    result: CollectResult
    person_filter: PersonFilter
    options: ScrollOptions
    seeking: bool = False
    seek_nicks: set = field(default_factory=set)
    known_messaged: set = field(default_factory=set)
    min_new_users: int = 0
    progress_cb: object = None
    #: nicks already added in THIS run (belt and braces against a page that
    #: renders the same person twice in one viewport)
    collected_nicks: set = field(default_factory=set)
    snap: dict = field(default_factory=dict)
    new_this_scroll: int = 0
    no_new_count: int = 0


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
                 on_reject=None,
                 should_stop=None,
                 log_cb=None):
        self.options = ScrollOptions(
            viewport_sel=viewport_sel, scroll_dy=scroll_dy, pause_ms=pause_ms,
            stall_threshold=stall_threshold, max_scrolls=max_scrolls,
            load_timeout_ms=load_timeout_ms, poll_ms=poll_ms,
            person_filter=person_filter, person_selector=person_selector,
            nick_selector=nick_selector, highlight_enabled=highlight_enabled,
            highlight_ms=highlight_ms, confirm_pause_ms=confirm_pause_ms,
            on_collect=on_collect, on_reject=on_reject,
            should_stop=should_stop, log_cb=log_cb)
        self._cdp = cdp
        self._criteria = criteria
        self._filter = person_filter
        self._log_cb = log_cb                  # reassignable: set_log_cb()
        self.known_nicks: set[str] = set()

    @classmethod
    def from_options(cls, cdp: CDPClient, options: ScrollOptions,
                     criteria=None) -> "ScrollParser":
        """The constructor new code should use: one config value, not 19."""
        return cls(cdp, criteria, **{
            f.name: getattr(options, f.name)
            for f in dataclasses.fields(options)})

    # ── the knobs the run reads (see `ScrollOptions`) ────────────
    @property
    def max_scrolls(self) -> int:
        return self.options.max_scrolls

    # The three callbacks stay readable and assignable on the parser: the
    # block wiring hands them over at construction (`ScrollParse.build_parser`)
    # and `tests/test_filter_purge.py` inspects them to prove a disabled purge
    # really detached the hook. Assigning writes them back into the frozen
    # options, so there is still exactly one place that holds them.
    @property
    def _on_collect(self):
        return self.options.on_collect

    @_on_collect.setter
    def _on_collect(self, callback) -> None:
        self.options = dataclasses.replace(self.options, on_collect=callback)

    @property
    def _on_reject(self):
        return self.options.on_reject

    @_on_reject.setter
    def _on_reject(self, callback) -> None:
        self.options = dataclasses.replace(self.options, on_reject=callback)

    @property
    def _should_stop(self):
        return self.options.should_stop

    @_should_stop.setter
    def _should_stop(self, predicate) -> None:
        self.options = dataclasses.replace(self.options,
                                           should_stop=predicate)

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

    async def _settle(self, seen_before: set, prev_top: float) -> dict | None:
        """Wait for lazy-loaded people after a scroll.

        Returns the first snapshot that either contains new nicks or shows the
        scroll position has stopped moving. This is what separates "still
        loading" from "end of the list".
        """
        options = self.options
        waited = 0
        snap = None
        stable = 0
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
            nicks = {u.get("nick") for u in snap.get("users", []) if u.get("nick")}
            if nicks - seen_before:
                if waited > options.poll_ms:
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
        self._say(f"⏳ Still nothing new after {options.load_timeout_ms} ms — "
                  "treating as loaded", "info")
        return snap

    async def _notify_collected(self, record, result) -> None:
        """Tell the caller a person was added, so the UI can refresh now."""
        callback = self._on_collect
        if callback is None:
            return
        try:
            outcome = callback(record, list(result.collected))
            if asyncio.iscoroutine(outcome):
                await outcome
        except Exception as exc:      # a UI hiccup must never kill the parse
            log.warning("on_collect callback failed for %s: %s",
                        record.nick, exc)

    async def _notify_rejected(self, record, reason: str, result) -> None:
        """Tell the caller a person FAILED the filter.

        The caller destroys any stored record for them, so a person who does
        not pass the filter can never linger in the list from an earlier run.
        """
        result.rejected_people.append((record, reason))
        callback = self._on_reject
        if callback is None:
            return
        try:
            outcome = callback(record, reason)
            if asyncio.iscoroutine(outcome):
                outcome = await outcome
            if outcome:
                result.purged.append(record.nick)
        except Exception as exc:      # a purge hiccup must never kill the parse
            log.warning("on_reject callback failed for %s: %s",
                        record.nick, exc)

    def _stop_requested(self) -> bool:
        predicate = self._should_stop
        if predicate is None:
            return False
        try:
            return bool(predicate())
        except Exception:
            return False

    # ── the pipeline ─────────────────────────────────────────────
    async def collect(self, progress_cb=None, min_new_users: int = 0,
                      known_messaged: set | None = None,
                      seek_nicks: set | None = None) -> CollectResult:
        """Run scroll → detect → filter → collect.

        :param min_new_users: finish as soon as this many new *un-messaged*
            people have been collected (0 = always scroll to the end).
        :param known_messaged: nicks already messaged, used to mark records.
        :param seek_nicks: scroll-only mode. Instead of adding new people,
            scroll hunting for one of these already-known nicks and stop on
            the first that passes the filter. Nothing is written or purged.
        """
        run = self._open(known_messaged=known_messaged, seek_nicks=seek_nicks,
                         min_new_users=min_new_users, progress_cb=progress_cb)
        if not await self._first_snapshot(run):
            return run.result
        await self._scroll_loop(run)
        return self._finish(run)

    # ── phase 1: the filter, the first snapshot, the warnings ────
    def _open(self, *, known_messaged, seek_nicks, min_new_users,
              progress_cb) -> _Pass:
        seeking = bool(seek_nicks)
        run = _Pass(
            result=CollectResult(seeking=seeking),
            person_filter=self._filter or PersonFilter(
                female="any", registered="any", guest="any", anonymous="any",
                panel_criteria=self._criteria),
            options=self.options, seeking=seeking,
            seek_nicks=set(seek_nicks or ()),
            known_messaged=known_messaged or set(),
            min_new_users=min_new_users, progress_cb=progress_cb)
        self._say(f"🔍 Viewport selector: {self.options.viewport_sel}", "info")
        self._say(f"🧮 Filter: {run.person_filter.describe()}", "info")
        if seeking:
            self._say(f"🔎 Seeking {len(run.seek_nicks)} un-messaged person(s) "
                      "— no new people will be added", "warn")
        return run

    async def _first_snapshot(self, run: _Pass) -> bool:
        """The opening probe: False means the page has nothing to say."""
        snap = await self._snapshot()
        if snap is None:
            self._say("❌ Element search failed: no data returned from the page "
                      "(wrong page? not connected?)", "error")
            return False
        if not snap.get("viewport"):
            self._say(f"⚠ Scroll viewport '{self.options.viewport_sel}' not "
                      "found — parsing whatever is currently rendered", "warn")
        run.snap = snap
        return True

    # ── phase 2: judge everybody the viewport is showing ─────────
    async def _consume_batch(self, run: _Pass) -> None:
        """One viewport's worth of people.

        The three modes are separate methods now (design doc §4): a seek only
        looks, a stranger is rejected-and-purged, a match is confirmed and
        announced. What every mode shares is the counting of NEWLY RENDERED
        people — that is what the stall detector below feeds on, and a seek
        that stopped counting would stall out before reaching its target.
        """
        for item in (run.snap or {}).get("users", []) or []:
            nick = (item.get("nick") or "").strip()
            if not nick:
                continue
            is_new = nick not in self.known_nicks
            if is_new:
                self.known_nicks.add(nick)
                run.new_this_scroll += 1
            if run.seeking:
                if await self._seek_hit(nick, item, run):
                    return
                continue
            if not is_new:
                continue
            await self._judge(nick, item, run)

    async def _seek_hit(self, nick: str, item: dict, run: _Pass) -> bool:
        """Scroll-only mode: is this the person we are hunting for?

        A target is by definition ALREADY known, so the `known_nicks`
        short-circuit in the caller would skip exactly the people we are after
        — membership is tested instead. And a target that does not pass the
        filter is passed over, never purged: it is not being judged for
        membership, only for suitability right now.
        """
        if nick not in run.seek_nicks:
            return False
        verdict = run.person_filter.check(self._to_dict(item))
        if not verdict.passed:
            self._say(f"  ↷ “{nick}” is waiting but does not pass "
                      f"the filter ({verdict.reason}) — skipping", "info")
            run.seek_nicks = run.seek_nicks - {nick}
            return False
        record = self._to_record(item)
        record.messaged = False
        shown = await self._confirm_person(nick)
        self._say(f"  🎯 Found “{nick}” on the page — {verdict.reason}"
                  + (" — outline drawn" if shown else ""), "success")
        await self._hold_confirmation(shown)
        run.result.found = record
        run.result.collected.append(record)
        run.result.all_people.append(record)
        return True

    async def _judge(self, nick: str, item: dict, run: _Pass) -> None:
        """Every person the page showed us is REPORTED, whoever passes.

        `all_people` is the run's "seen" list — the log summary, the queue
        builder and the debugger table all read it, so a rejected person has
        to be in it too.
        """
        record = self._to_record(item)
        run.result.all_people.append(record)
        verdict = run.person_filter.check(self._to_dict(item))
        if not verdict.passed:
            await self._reject_one(record, verdict.reason, run)
            return
        if nick in run.collected_nicks:              # belt and braces
            return
        await self._collect_one(record, nick, verdict.reason, run)

    async def _reject_one(self, record, reason: str, run: _Pass) -> None:
        run.result.rejected[reason] = run.result.rejected.get(reason, 0) + 1
        # Confirmed NOT to pass: destroy any stored record so the
        # person cannot survive from an earlier / laxer run.
        await self._notify_rejected(record, reason, run.result)

    async def _collect_one(self, record, nick: str, reason: str,
                           run: _Pass) -> None:
        result = run.result
        # Visual confirmation BEFORE adding: show the user exactly
        # which person was detected, then hold so it can be seen.
        shown = await self._confirm_person(nick)
        self._say(f"  🟢 Match “{nick}” — {reason}"
                  + (" — green outline drawn" if shown else ""), "success")
        await self._hold_confirmation(shown)

        run.collected_nicks.add(nick)
        record.messaged = nick in run.known_messaged
        result.collected.append(record)
        self._say(f"  ✅ Added “{nick}” to the list "
                  f"({len(result.collected)} collected)", "success")
        # Refresh the UI immediately — do not wait for the scroll
        # cycle to finish.
        await self._notify_collected(record, result)

    async def _hold_confirmation(self, shown: bool) -> None:
        if shown and self.options.confirm_pause_ms:
            await asyncio.sleep(self.options.seconds("confirm_pause_ms"))

    # ── phase 3: report, decide, scroll, settle ─────────────────
    async def _scroll_loop(self, run: _Pass) -> None:
        for scroll_i in range(self.options.max_scrolls):
            if self._stop_requested():
                run.result.stopped = True
                self._say("⏹ Stopped by user — halting the scroll", "warn")
                return
            run.result.scrolls = scroll_i + 1
            run.new_this_scroll = 0
            await self._consume_batch(run)
            if run.result.found is not None:
                run.result.stopped_early = True
                return
            if not await self._advance(run, scroll_i):
                return
        self._say(f"⏹ Reached max scrolls ({self.options.max_scrolls})", "warn")

    async def _advance(self, run: _Pass, scroll_i: int) -> bool:
        """False = this was the last pass (and the reason was reported)."""
        if run.progress_cb:
            run.progress_cb(scroll_i + 1, len(run.result.all_people),
                            run.new_this_scroll)
        if run.new_this_scroll:
            self._say(f"📜 Scroll {scroll_i + 1}/{self.options.max_scrolls}: "
                      f"+{run.new_this_scroll} new person(s), "
                      f"{len(run.result.all_people)} seen, "
                      f"{len(run.result.collected)} collected", "info")
            run.no_new_count = 0
        else:
            run.no_new_count += 1
        if self._target_reached(run) or self._list_is_over(run):
            return False
        return await self._scroll_and_settle(run)

    def _target_reached(self, run: _Pass) -> bool:
        """STEP 3 early finish: enough new un-messaged people collected."""
        if run.min_new_users <= 0:
            return False
        unmessaged = len(run.result.new_unmessaged)
        if unmessaged < run.min_new_users:
            return False
        run.result.stopped_early = True
        self._say(f"🎯 Collected {unmessaged} new un-messaged person(s) "
                  f"(target {run.min_new_users}) — finishing scroll early",
                  "success")
        return True

    def _list_is_over(self, run: _Pass) -> bool:
        """End of list: only when geometrically at the bottom AND quiet.

        A slow response looks exactly like the end of a lazy-loaded list, so
        neither half is enough on its own (module docstring).
        """
        if (run.snap or {}).get("atBottom") and run.new_this_scroll == 0:
            run.result.reached_end = True
            self._say("⏹ Bottom of the list reached and no new people "
                      "loaded — end of list", "success")
            return True
        if run.no_new_count >= self.options.stall_threshold:
            run.result.reached_end = True
            self._say(f"⏹ No new people after {self.options.stall_threshold} "
                      "scrolls — list fully parsed (stall detected)", "warn")
            return True
        return False

    async def _scroll_and_settle(self, run: _Pass) -> bool:
        prev_top = float((run.snap or {}).get("scrollTop", 0))
        if not await self._do_scroll():
            return False
        if self.options.pause_ms > 0:
            await asyncio.sleep(self.options.seconds("pause_ms"))
        settled = await self._settle(set(self.known_nicks), prev_top)
        if settled is STOPPED or self._stop_requested():
            run.result.stopped = True
            self._say("⏹ Stopped by user — halting the scroll", "warn")
            return False
        if settled is None:
            self._say("❌ Lost the page context while scrolling", "error")
            return False
        run.snap = settled
        return True

    # ── phase 4: the outcome the caller and the log get ─────────
    def _finish(self, run: _Pass) -> CollectResult:
        result = run.result
        result.collected = sort_people(result.collected)
        if result.rejected:
            detail = ", ".join(f"{n}× {reason}"
                               for reason, n in sorted(result.rejected.items()))
            self._say(f"🚫 Filtered out: {detail}", "info")
        if result.purged:
            self._say(f"🗑 Removed {len(result.purged)} stored record(s) for "
                      f"people that do not pass the filter: "
                      + ", ".join(f"“{n}”" for n in result.purged[:8])
                      + ("…" if len(result.purged) > 8 else ""), "warn")
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
