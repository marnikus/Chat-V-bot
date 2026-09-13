"""`ScrollParser` — the public face of the package, and the run's shared state.

Owns the class every caller names: its construction (the 19-parameter legacy
signature the AREA D snapshot pins, plus the `from_options` seam new code
should use), the knobs and callbacks, the log line, and the three-step public
pipeline `collect()` → open, first snapshot, loop, finish.

The work itself lives in three collaborators built here and reached through
`self`:

    self.viewport  →  viewport.Viewport   the page: probe, scroll, settle
    self.judge     →  judge.Judge         per-person verdicts
    self.loop      →  loop.ScrollLoop     pass sequencing and end-of-list

They read this object back as `host` (`host.options`, `host._say()`,
`host.known_nicks`, …), which is the same host-protocol shape
`services/collector_*` uses. State stays here so that reassigning
`self.options` — which the callback setters do — is seen by every collaborator
at once.
"""

import asyncio
import dataclasses
import logging

from backend.cdp_client import CDPClient
from backend.person_filter import PersonFilter, sort_people
from backend.scroll_parser.judge import Judge
from backend.scroll_parser.loop import ScrollLoop
from backend.scroll_parser.options import ScrollOptions
from backend.scroll_parser.results import CollectResult, _Pass
from backend.scroll_parser.viewport import Viewport

log = logging.getLogger("chatbot")


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
        self.viewport = Viewport(self)
        self.judge = Judge(self)
        self.loop = ScrollLoop(self)

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

    def _stop_requested(self) -> bool:
        predicate = self._should_stop
        if predicate is None:
            return False
        try:
            return bool(predicate())
        except Exception:
            return False

    # ── the callbacks into the caller ────────────────────────────
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
        await self.loop.run(run)
        return self._finish(run)

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
        snap = await self.viewport.snapshot()
        if snap is None:
            self._say("❌ Element search failed: no data returned from the page "
                      "(wrong page? not connected?)", "error")
            return False
        if not snap.get("viewport"):
            self._say(f"⚠ Scroll viewport '{self.options.viewport_sel}' not "
                      "found — parsing whatever is currently rendered", "warn")
        run.snap = snap
        return True

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
