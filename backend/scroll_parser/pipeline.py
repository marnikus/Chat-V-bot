"""The orchestration: open a run, drive the loop, finish and report.

`PipelineMixin` owns `collect` (the public entry) and the three thin phases
around the loop — the opening filter/snapshot, the closing summary, and the
legacy `parse` shim. The heavy work lives in `probe`, `judge` and `loop`.
"""

import logging

from backend.person_filter import PersonFilter, sort_people

from .result import CollectResult
from .runstate import _Pass

log = logging.getLogger("chatbot")


class PipelineMixin:
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
