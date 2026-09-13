"""The read/persist half of a conversation sync, driven against scripted fakes.

AREA D splits `sync_conversation()`'s 295-line body into phases
(design doc §3: ChunkReader, DeltaAligner, SyncPersister). What must not
change is what the ARCHIVE sees, because the archive is the user's data and
the "nothing moved → zero writes" behaviour is the entire design.

So these tests assert the call sequence on a recording fake repo — the exact
kwargs of every `append`, when `record_gap`/`mark_backfilled` fire, which
media passes run — and the `SyncResult` the caller gets back.

Ids SY#11–24 from docs/archive/2026-09-09-four-area-refactor/REFACTOR_2026-09-09_AREA_D_DESIGN.md §7.
Rules enforced: AGENT_RULES RULE 4 (empty vs broken), RULE 5 (progress per
chunk), RULE 7 (stop honoured mid-loop), RULE 15 (the gate).

Run with:  python3 tests/unit/backend/test_chat_sync_phases.py
"""

import asyncio
import json
import os
import sys
import unittest
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))))

from backend.chat_parser import ChatParser, sync_conversation  # noqa: E402
from backend.chat_sync import SyncPersister, SyncSession  # noqa: E402
from stores.history_models import MessageRecord, fingerprint  # noqa: E402

NOW = datetime(2026, 9, 9, 10, 0, 0)


def record(i, *, direction="in", nick="Nick", text=None):
    text = f"m{i}" if text is None else text
    fp = fingerprint(direction, nick, "10:00", "text", text, 0)
    return {"fp": fp, "dir": direction, "from": nick, "kind": "text",
            "text": text, "time": "10:00", "occ": 0, "idx": i,
            "media": None}


class FakeParser:
    """A chat pane that answers exactly the four probes the sync performs."""

    def __init__(self, messages=(), *, count=None, chunk_size=5,
                 chunk_pause_ms=0, state_extra=None, empty_reads=0,
                 scroll_ok=True, settle_ok=True):
        self.messages = list(messages)
        self._count = len(self.messages) if count is None else count
        self.chunk_size = chunk_size
        self.chunk_pause_ms = chunk_pause_ms
        self.state_extra = dict(state_extra or {})
        self.empty_reads = empty_reads
        self.scroll_ok = scroll_ok
        self.settle_ok = settle_ok
        self.slice_calls = []
        self.restore_calls = []
        self.scroll_to_top_calls = 0
        self.installs = 0
        self.states = 0
        self.slept = 0
        self.settles = 0

    # ── the ChatParser surface the sync uses ─────────────────────
    async def state(self):
        self.states += 1
        msgs = self.messages
        body = {"ok": True, "agent": 10, "tab": "private", "partner": "Nick",
                "me": "Me", "title": "Nick", "participants": 2,
                "count": self._count,
                "head": msgs[0]["fp"] if msgs else "",
                "tail": msgs[-1]["fp"] if msgs else "",
                "in_authors": ["Nick"], "out_authors": ["Me"],
                "scroll": {"top": 250, "height": 400, "client": 100,
                           "atTop": False, "atBottom": False}}
        body.update(self.state_extra)
        return json.loads(json.dumps(body))

    async def install(self):
        self.installs += 1
        return 10

    async def slice(self, start, end):
        self.slice_calls.append((start, end))
        if self.empty_reads > 0:
            self.empty_reads -= 1
            return []
        return [MessageRecord.from_dict(m)
                for m in self.messages[start:end]]

    async def drain(self):
        return []

    async def scroll_to_top(self):
        self.scroll_to_top_calls += 1
        return {"ok": self.scroll_ok, "top": 0, "atTop": True}

    async def restore_scroll(self, top):
        self.restore_calls.append(top)
        return {"ok": True, "top": top}

    async def settle_after_top(self, first_state, *, wait_ms=300,
                               stable_polls=3, max_wait_s=6.0,
                               minimum_count=0):
        self.settles += 1
        state = dict(first_state)
        # a real re-probe keeps the pane's own geometry — only the scroll
        # position moves, so `height` still tells the caller whether there is
        # anything to scroll at all (the empty-pane check relies on that)
        scroll = dict(first_state.get("scroll") or {})
        scroll.update({"top": 0, "atTop": self.settle_ok})
        state["scroll"] = scroll
        state["_settled"] = self.settle_ok
        if self.settle_ok:
            state["count"] = self._count
        return state

    async def pause(self):
        self.slept += 1


class FakeRepo:
    """Records every archive mutation, with the defaults the sync relies on."""

    def __init__(self, *, cursor=None, person=None, repairable=False,
                 media_stats=None, last_ord=0):
        self.calls = []
        self._cursor = {"last_ord": 0, "dom_count": 0, "head_sig": "",
                        "tail_sig": "", "head_any": "", "tail_any": "",
                        "tail_fps": [], "tail_keys": [],
                        "bootstrapped": False, "full_scan_complete": False}
        if cursor:
            self._cursor.update(cursor)
        self._person = {"message_count": 0} if person is None else person
        self._repairable = repairable
        self._media_stats = media_stats or {"repaired": 0, "requeued": 0}
        self._last_ord_value = last_ord

    # ── recording ────────────────────────────────────────────────
    def _note(self, name, **kw):
        self.calls.append((name, kw))
        return self

    def calls_of(self, name):
        return [kw for n, kw in self.calls if n == name]

    @property
    def names(self):
        return [n for n, _ in self.calls]

    # ── the HistoryRepo surface the sync uses ────────────────────
    async def ensure_person(self, nick):
        self._note("ensure_person", nick=nick)
        return 7

    async def get_cursor(self, person_id):
        self._note("get_cursor", person_id=person_id)
        return dict(self._cursor)

    async def get_person_by_id(self, person_id):
        return dict(self._person)

    async def _last_ord(self, person_id):
        return self._last_ord_value

    async def append(self, nick, records, my_nick="", **kw):
        class Appended:
            pass
        out = Appended()
        out.added = len(records or [])
        out.gap = bool(kw.get("gap", False))
        out.records = [r if isinstance(r, dict) else r.to_dict()
                       for r in (records or [])]
        for i, r in enumerate(out.records):
            r.setdefault("ord", self._last_ord_value + i + 1)
        self._note("append", nick=nick, count=len(records or []),
                   my_nick=my_nick, **kw)
        return out

    async def record_gap(self, person_id, after_ord, reason, detail):
        self._note("record_gap", person_id=person_id, after_ord=after_ord,
                   reason=reason, detail=detail)

    async def mark_backfilled(self, person_id):
        self._note("mark_backfilled", person_id=person_id)

    async def has_repairable_media(self, person_id, include_failed=False,
                                   rescan_after_s=600):
        self._note("has_repairable_media", person_id=person_id,
                   include_failed=include_failed)
        return self._repairable

    async def recover_media(self, person_id, records, media=None,
                            nick="", now=None, requeue_failed=True):
        self._note("recover_media", person_id=person_id,
                   count=len(records or []), requeue_failed=requeue_failed)
        return dict(self._media_stats)

    async def reset_cursor(self, nick):
        self._note("reset_cursor", nick=nick)


def sync(parser, repo, **kw):
    kw.setdefault("now", NOW)
    return asyncio.run(sync_conversation(parser, repo, "Nick", **kw))


# ══════════════════════════════════════════════════════════════════
# SY#11 / SY#16 / SY#17 — chunking, progress, pacing
# ══════════════════════════════════════════════════════════════════
class TestChunkReader(unittest.TestCase):

    def test_reads_in_chunks_and_appends_every_one(self):
        parser = FakeParser([record(i) for i in range(7)], chunk_size=3)
        repo = FakeRepo()
        result = sync(parser, repo)
        self.assertEqual(parser.slice_calls, [(0, 3), (3, 6), (6, 7)])
        appended = [c for c in repo.calls_of("append") if c["count"]]
        self.assertEqual([c["count"] for c in appended], [3, 3, 1])
        self.assertEqual(result.added, 7)
        self.assertEqual(result.scanned, 7)
        self.assertEqual([(c["from"], c["to"]) for c in result.chunks],
                         [(0, 3), (3, 6), (6, 7)])

    def test_progress_is_reported_per_chunk_not_at_the_end(self):
        """RULE 5."""
        seen = []
        parser = FakeParser([record(i) for i in range(7)], chunk_size=3)
        sync(parser, FakeRepo(), on_progress=lambda d, t: seen.append((d, t)))
        self.assertEqual(seen, [(3, 7), (6, 7), (7, 7)])

    def test_pacing_happens_between_chunks_only(self):
        parser = FakeParser([record(i) for i in range(9)], chunk_size=3,
                            chunk_pause_ms=1)
        sync(parser, FakeRepo())
        self.assertEqual(parser.slept, 0, "the sync paces itself, not the parser")

    def test_zero_pause_does_not_sleep(self):
        slept = []
        parser = FakeParser([record(i) for i in range(9)], chunk_size=3,
                            chunk_pause_ms=0)
        real_sleep = asyncio.sleep

        async def spy(delay, *a, **k):
            slept.append(delay)
            return await real_sleep(0, *a, **k)

        asyncio.sleep = spy
        try:
            sync(parser, FakeRepo())
            sync(parser, FakeRepo(), chunk_pause_ms=5)
        finally:
            asyncio.sleep = real_sleep
        self.assertEqual([d for d in slept if d], [0.005, 0.005],
                         "one pacing sleep between chunks, never after the last")

    def test_empty_reads_are_retried_before_giving_up(self):
        """A virtualised pane can lose its nodes between probes: retry, do
        not archive nothing."""
        parser = FakeParser([record(i) for i in range(4)], chunk_size=10,
                            empty_reads=2)
        result = sync(parser, FakeRepo())
        self.assertEqual(parser.slice_calls, [(0, 4)] * 3)
        self.assertEqual(result.added, 4)

    def test_a_still_empty_range_stops_the_read(self):
        parser = FakeParser([], count=9, chunk_size=4, empty_reads=99)
        result = sync(parser, FakeRepo())
        self.assertEqual(parser.slice_calls, [(0, 4)] * 4,
                         "SLICE_RETRIES attempts, then give up")
        self.assertEqual(result.added, 0)
        self.assertEqual(result.reason, "no_new")

    def test_stop_between_chunks_is_stopped_not_failed(self):
        """RULE 7 + RULE 4."""
        parser = FakeParser([record(i) for i in range(9)], chunk_size=3)

        def stopping():
            return len(parser.slice_calls) >= 1    # one chunk through, then stop

        repo = FakeRepo()
        result = sync(parser, repo, should_stop=stopping)
        self.assertTrue(result.stopped)
        self.assertEqual(result.reason, "stopped")
        self.assertEqual(parser.slice_calls, [(0, 3)])
        self.assertEqual([c["count"] for c in repo.calls_of("append")
                          if c["count"]], [3])

    def test_a_stopped_read_records_where_it_stopped(self):
        parser = FakeParser([record(i) for i in range(9)], chunk_size=3)
        repo = FakeRepo()
        sync(parser, repo, should_stop=lambda: True)
        cursors = [c for c in repo.calls_of("append") if not c["count"]]
        self.assertTrue(cursors, "the cursor must still be written")
        self.assertEqual(cursors[-1]["dom_count"], 0,
                         "a sync that never read must not claim a window")
        self.assertEqual(cursors[-1]["tail_sig"], "",
                         "an incomplete read may not advertise its tail")


# ══════════════════════════════════════════════════════════════════
# SY#14 — viewport fallback in the middle of a read
# ══════════════════════════════════════════════════════════════════
class TestViewportFallback(unittest.TestCase):

    def test_a_cleared_pane_is_restored_and_reread(self):
        """An unsettled scroll-to-top loses the nodes: put the viewport back,
        re-read the state, retry the SAME range, and do not claim the full
        scan finished."""
        parser = FakeParser([record(i) for i in range(6)], chunk_size=10,
                            empty_reads=1, settle_ok=False)
        repo = FakeRepo()
        result = sync(parser, repo, backfill_older=True, backfill_wait_s=0.01)
        self.assertEqual(parser.restore_calls, [250],
                         "the user's viewport is restored, not left at the top")
        self.assertTrue(result.backfill_pending)
        self.assertFalse(result.backfilled)
        self.assertEqual(parser.slice_calls, [(0, 6), (0, 6)])
        self.assertEqual(result.added, 6)


# ══════════════════════════════════════════════════════════════════
# SY#15 / SY#18 — full re-read with a stored tail: align, then write
# ══════════════════════════════════════════════════════════════════
class TestAlignThenWrite(unittest.TestCase):

    def test_a_full_reread_writes_once_after_alignment(self):
        parser = FakeParser([record(i) for i in range(5)], chunk_size=2)
        repo = FakeRepo(cursor={"bootstrapped": True, "dom_count": 5,
                                "head_sig": "different", "tail_sig": "old",
                                "tail_fps": ["x", "y"]})
        result = sync(parser, repo)
        self.assertEqual([c["count"] for c in repo.calls_of("append")
                          if c["count"]], [5],
                         "not one append per chunk: the batch is aligned first")
        appended = [c for c in repo.calls_of("append") if c["count"]][0]
        self.assertTrue(appended["align"])
        self.assertEqual(result.added, 5)

    def test_prepended_history_is_written_as_a_backfill_not_as_new(self):
        """Everything ABOVE the alignment point is older than the stored tail:
        it must be prepended and must not reach the live-append channel."""
        msgs = [record(i) for i in range(6)]
        stored = [msgs[0]["fp"], msgs[1]["fp"]]        # the archive's newest 2
        # the page now shows 0..5 again, so 2..5 are new and 0..1 are older
        # than the stored tail (they dropped out of the pane and came back)
        parser = FakeParser(msgs, chunk_size=10)
        repo = FakeRepo(cursor={"bootstrapped": True, "dom_count": 2,
                                "head_sig": "moved", "tail_sig": "old",
                                "tail_fps": stored})
        result = sync(parser, repo)
        writes = [c for c in repo.calls_of("append") if c["count"]]
        self.assertEqual([c["count"] for c in writes], [6, 2],
                         "one aligned batch, then the older prefix")
        self.assertTrue(writes[0]["align"] and not writes[0].get("prepend"))
        self.assertTrue(writes[1]["prepend"],
                        "records older than the stored tail are prepended")
        self.assertFalse(writes[1].get("align"),
                         "a prepend is positional, not aligned")
        self.assertEqual(result.added, 8)


# ══════════════════════════════════════════════════════════════════
# SY#19 / SY#20 / SY#21 — persistence bookkeeping
# ══════════════════════════════════════════════════════════════════
class TestPersister(unittest.TestCase):

    def test_gap_is_recorded_when_the_window_was_capped(self):
        parser = FakeParser([record(i) for i in range(20)], chunk_size=50)
        repo = FakeRepo()
        result = sync(parser, repo, max_messages=5)
        gaps = repo.calls_of("record_gap")
        self.assertEqual(len(gaps), 1)
        self.assertEqual(gaps[0]["reason"], "capped")
        self.assertEqual(gaps[0]["after_ord"], 0)
        self.assertIn("newest 5", gaps[0]["detail"])
        self.assertTrue(result.gap)
        self.assertEqual(result.added, 5, "only the newest window is collected")
        first_write = next(i for i, (n, c) in enumerate(repo.calls)
                           if n == "append" and c["count"])
        self.assertLess(repo.names.index("record_gap"), first_write,
                        "the gap is recorded BEFORE anything is written")

    def test_full_scan_is_marked_complete_only_after_a_settled_backfill(self):
        msgs = [record(i) for i in range(4)]
        parser = FakeParser(msgs, chunk_size=10)
        repo = FakeRepo()
        result = sync(parser, repo, backfill_older=True, backfill_wait_s=0.01)
        self.assertTrue(result.backfilled)
        self.assertEqual([c["person_id"] for c in repo.calls_of("mark_backfilled")],
                         [7])

    def test_a_pending_backfill_is_not_marked_complete(self):
        parser = FakeParser([record(i) for i in range(4)], chunk_size=10,
                            settle_ok=False)
        repo = FakeRepo()
        result = sync(parser, repo, backfill_older=True, backfill_wait_s=0.01)
        self.assertFalse(result.backfilled)
        self.assertEqual(repo.calls_of("mark_backfilled"), [],
                         "an incomplete scan must be retried by a later tick")

    def test_an_empty_pane_with_nothing_to_scroll_is_complete(self):
        parser = FakeParser([], chunk_size=10,
                            state_extra={"scroll": {"top": 0, "height": 0,
                                                   "client": 0,
                                                   "atTop": True,
                                                   "atBottom": True}})
        repo = FakeRepo()
        result = sync(parser, repo, backfill_older=True, backfill_wait_s=0.01)
        self.assertEqual(result.reason, "empty")
        self.assertEqual(repo.calls_of("append")[0]["count"], 0)
        self.assertEqual(len(repo.calls_of("mark_backfilled")), 1)

    def test_an_empty_pane_that_is_scrollable_stays_suspicious(self):
        parser = FakeParser([], chunk_size=10)
        repo = FakeRepo()
        result = sync(parser, repo, backfill_older=True, backfill_wait_s=0.01)
        self.assertEqual(result.reason, "empty")
        self.assertEqual(repo.calls_of("mark_backfilled"), [],
                         "a scrollable pane that shows nothing was not read "
                         "to the end")

    def test_cursor_is_written_with_the_final_window(self):
        parser = FakeParser([record(i) for i in range(5)], chunk_size=10)
        repo = FakeRepo()
        sync(parser, repo)
        cursor_writes = [c for c in repo.calls_of("append") if not c["count"]]
        self.assertEqual(cursor_writes[-1]["dom_count"], 5)
        self.assertEqual(cursor_writes[-1]["now"], NOW)
        self.assertEqual(cursor_writes[-1]["head_sig"],
                         record(0)["fp"])
        self.assertEqual(cursor_writes[-1]["tail_sig"], record(4)["fp"])

    def test_persister_blanks_the_tail_for_an_incomplete_window(self):
        plan = type("P", (), {"head_sig": "h", "tail_sig": "t",
                             "head_any": "ha", "tail_any": "ta"})()
        kwargs = SyncPersister.cursor_kwargs(plan, 3, complete=False)
        self.assertEqual(kwargs, {"dom_count": 3, "head_sig": "h",
                                  "tail_sig": "", "head_any": "ha",
                                  "tail_any": ""})
        self.assertEqual(SyncPersister.cursor_kwargs(plan, 9,
                                                     complete=True)["tail_sig"],
                         "t")

    def test_a_failing_mark_backfilled_never_breaks_the_sync(self):
        class Broken(FakeRepo):
            async def mark_backfilled(self, person_id):
                raise RuntimeError("locked")

        parser = FakeParser([record(i) for i in range(3)], chunk_size=10)
        result = sync(parser, Broken(), backfill_older=True,
                      backfill_wait_s=0.01)
        self.assertTrue(result.ok)


# ══════════════════════════════════════════════════════════════════
# SY#22 — media recovery passes
# ══════════════════════════════════════════════════════════════════
class TestMediaPasses(unittest.TestCase):
    MEDIA = object()

    def test_no_media_pass_without_a_media_object(self):
        repo = FakeRepo(repairable=True)
        sync(FakeParser([record(0)], chunk_size=10), repo)
        self.assertEqual(repo.calls_of("recover_media"), [])
        self.assertEqual(repo.calls_of("has_repairable_media"), [])

    def test_tail_recovery_runs_after_the_viewport_is_restored(self):
        parser = FakeParser([record(i) for i in range(3)], chunk_size=10)
        repo = FakeRepo(repairable=True,
                        media_stats={"repaired": 2, "requeued": 1})
        result = sync(parser, repo, media=self.MEDIA)
        self.assertEqual(len(repo.calls_of("recover_media")), 1)
        self.assertEqual(result.media_repaired, 2)
        self.assertEqual(result.media_requeued, 1)
        self.assertEqual(repo.calls_of("has_repairable_media")[0],
                         {"person_id": 7, "include_failed": False})

    def test_a_backfill_requeues_known_bad_downloads_too(self):
        parser = FakeParser([record(i) for i in range(3)], chunk_size=10)
        repo = FakeRepo(repairable=True)
        sync(parser, repo, media=self.MEDIA, backfill_older=True,
             backfill_wait_s=0.01)
        self.assertTrue(repo.calls_of("has_repairable_media")[0]["include_failed"])
        recoveries = repo.calls_of("recover_media")
        self.assertTrue(recoveries, "a backfill runs a media pass per chunk")
        self.assertTrue(all(c["requeue_failed"] for c in recoveries),
                        "a manual backfill gives known-bad downloads a "
                        "second chance")

    def test_a_raising_recovery_is_logged_not_fatal(self):
        class Broken(FakeRepo):
            async def recover_media(self, *a, **k):
                raise RuntimeError("network down")

        parser = FakeParser([record(i) for i in range(3)], chunk_size=10)
        result = sync(parser, Broken(), media=self.MEDIA, backfill_older=True,
                      backfill_wait_s=0.01)
        self.assertTrue(result.ok)

    def test_no_media_work_after_a_stop(self):
        parser = FakeParser([record(i) for i in range(3)], chunk_size=10)
        repo = FakeRepo(repairable=True)
        sync(parser, repo, media=self.MEDIA, should_stop=lambda: True)
        self.assertEqual(repo.calls_of("recover_media"), [])


# ══════════════════════════════════════════════════════════════════
# SY#23/24 + the gate — the façade contract
# ══════════════════════════════════════════════════════════════════
class TestFacadeContract(unittest.TestCase):

    def test_agent_is_installed_once_then_state_reread(self):
        parser = FakeParser([record(0)], chunk_size=10,
                            state_extra={"agent": 0})
        repo = FakeRepo()
        sync(parser, repo)
        self.assertEqual(parser.installs, 1)
        self.assertGreaterEqual(parser.states, 2)

    def test_a_broken_agent_page_reports_the_page_reason(self):
        parser = FakeParser([], state_extra={"ok": False, "reason": "no node"})
        repo = FakeRepo()
        result = sync(parser, repo)
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, "no node")
        self.assertEqual(repo.calls_of("append"), [])

    def test_require_private_refuses_a_main_room(self):
        parser = FakeParser([], state_extra={"tab": "main"})
        result = sync(parser, FakeRepo(), require_private=True)
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, "not_private")

    def test_verify_partner_refuses_the_wrong_person(self):
        parser = FakeParser([], state_extra={"partner": "Someone Else"})
        result = sync(parser, FakeRepo(), verify_partner=True,
                      require_private=True, my_nick="Me")
        self.assertFalse(result.ok)

    def test_unchanged_page_writes_nothing_at_all(self):
        msgs = [record(i) for i in range(6)]
        cursor = {"bootstrapped": True, "dom_count": 6,
                  "head_sig": msgs[0]["fp"], "tail_sig": msgs[-1]["fp"],
                  "tail_fps": [m["fp"] for m in msgs]}
        parser = FakeParser(msgs, chunk_size=10)
        repo = FakeRepo(cursor=cursor)
        result = sync(parser, repo)
        self.assertEqual(result.reason, "unchanged")
        self.assertEqual(result.added, 0)
        self.assertEqual(repo.calls_of("append"), [],
                         "the whole point: a settled page costs zero writes")
        self.assertEqual(parser.slice_calls, [],
                         "and zero node reads")

    def test_result_counts_and_totals_come_from_the_archive(self):
        parser = FakeParser([record(i) for i in range(4)], chunk_size=10)
        repo = FakeRepo(person={"message_count": 42})
        result = sync(parser, repo)
        self.assertEqual(result.count, 4)
        self.assertEqual(result.total, 42)
        self.assertEqual(result.nick, "Nick")
        self.assertEqual(result.my_nick, "")

    def test_session_exposes_the_state_the_phases_share(self):
        parser = FakeParser([record(0)], chunk_size=10)
        session = SyncSession(parser, FakeRepo(), "Nick")
        self.assertEqual(session.nick, "Nick")
        self.assertTrue(session.result.ok)
        self.assertEqual(session.result.nick, "Nick")
        asyncio.run(session.prepare())
        self.assertEqual(session.person_id, 7)
        self.assertEqual(session.state["count"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
