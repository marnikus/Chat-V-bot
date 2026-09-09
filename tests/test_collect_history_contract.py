"""`actions.collect_history` — the archive block's decision contract (P1).

SPEC-FIRST (docs/ACTIONS_TEST_DESIGN_2026-09-09.md §10), pinned against the
house rules the module docstring quotes:

  * RULE 3 — every setting round-trips;
  * RULE 4 — "nothing new" is an OK/informational result, "this is not a
    private chat" is a loud failure. They must never look the same;
  * RULE 5 — progress is reported per chunk while it runs;
  * RULE 7 — a stop is reported as stopped, never as a failure.

`tests/test_collect_history_block.py` covers the same block END-TO-END
against a real sqlite HistoryDB + ChatParser.

This file isolates the block's own branching instead: the ONE I/O call the
block makes — `backend.chat_parser.sync_conversation` — is replaced per
test with the `SyncRecorder` below (via `BlockCase.setUp`, so no other
test in the session ever sees the recorder). Everything else is real: the
real `SyncResult` from `backend.history_models`, the real `ActionResult`,
the real block code.

Run with:  python3 tests/test_collect_history_contract.py
"""

import asyncio
import importlib
import os
import sys
import unittest
from datetime import datetime
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from actions.base_action import ActionResult  # noqa: E402
from backend.history_models import SyncResult  # noqa: E402

NOW = datetime(2026, 9, 9, 12, 0, 0)


class SyncRecorder:
    """Stands in for backend.chat_parser.sync_conversation."""

    def __init__(self):
        self.result = SyncResult(ok=True, added=1, total=5)
        self.calls = []
        #: optional callable(…)->SyncResult to drive per-test outcomes
        self.side_effect = None

    async def __call__(self, parser, repo, nick, **kwargs):
        self.calls.append({"parser": parser, "repo": repo, "nick": nick,
                           **kwargs})
        if self.side_effect is not None:
            return self.side_effect(self.calls[-1])
        return self.result

    @property
    def last(self):
        return self.calls[-1]


SYNC = SyncRecorder()

from actions.collect_history import CollectHistory  # noqa: E402
import actions.collect_history as _ch_module  # noqa: E402


def run(coro):
    return asyncio.run(coro)


class FakeParser:
    def __init__(self, state=None):
        self.state_data = {"agent": 1, "tab": "private", "partner": "Ксюша",
                           "me": "Me", "count": 12}
        self.state_data.update(state or {})
        self.installs = 0
        self.chunk_size = 80
        self.chunk_pause_ms = 40

    async def state(self):
        return dict(self.state_data)

    async def install(self):
        self.installs += 1
        self.state_data["agent"] = 1
        self.state_data["partner"] = "Ксюша"


class FakeRepo:
    def __init__(self):
        self.resets = []
        self.media = object()

    async def reset_cursor(self, nick):
        self.resets.append(nick)


class FakeMedia:
    def __init__(self, cached=0, raises=False):
        self.cached = cached
        self.raises = raises
        self.calls = 0

    async def process_pending(self):
        self.calls += 1
        if self.raises:
            raise RuntimeError("disk full")
        return self.cached


#: distinguishes "not supplied" from "supplied as None" (a service whose
#: repository is missing is exactly what CH-03 is about)
MISSING = object()


class FakeService:
    def __init__(self, parser=MISSING, repo=MISSING, enabled=True,
                 my_nick="", media=None):
        self.parser = FakeParser() if parser is MISSING else parser
        self.repo = FakeRepo() if repo is MISSING else repo
        self.enabled = enabled
        self.my_nick = my_nick
        self.media = media


class FakeEngine:
    def __init__(self, service=None, selected_nick="", stopping=False):
        self.history = service
        self.selected_nick = selected_nick
        self.lines = []
        self._stopping = stopping

    def report(self, message, level="info"):
        self.lines.append((level, message))

    def is_stopping(self):
        return self._stopping

    def levels(self):
        return [lvl for lvl, _m in self.lines]

    def text(self):
        return " | ".join(m for _lvl, m in self.lines)


class BlockCase(unittest.TestCase):
    def setUp(self):
        SYNC.result = SyncResult(ok=True, added=1, total=5)
        SYNC.side_effect = None
        SYNC.calls.clear()
        # The block bound the real sync_conversation at module import;
        # point its module-global at the recorder for this test only.
        patcher = mock.patch.object(_ch_module, "sync_conversation", SYNC)
        patcher.start()
        self.addCleanup(patcher.stop)

    def block(self, **kw):
        kw.setdefault("pre_delay_ms", 0)
        kw.setdefault("chunk_pause_ms", 0)
        blk = CollectHistory(**kw)
        blk.now = lambda: NOW
        return blk

    def execute(self, blk, engine):
        return run(blk.execute("Ann", object(), engine))


class TestImportGate(unittest.TestCase):
    """CH-00."""

    def test_the_block_import_dependency_is_healthy(self):
        """The block imports backend.chat_parser at module scope.

        Health pin (was BUG-02): the import must succeed, otherwise the
        whole block — and `tests/test_collect_history_block.py` with
        it — is dead code.
        """
        if "backend.chat_parser" in sys.modules:
            del sys.modules["backend.chat_parser"]
        importlib.import_module("backend.chat_parser")


class TestServiceGuards(BlockCase):
    """CH-01, CH-02, CH-03."""

    def test_no_archive_service_is_a_loud_failure(self):
        """CH-01."""
        engine = FakeEngine(service=None)
        self.assertEqual(self.execute(self.block(), engine),
                         ActionResult.FAIL)
        self.assertIn("not available", engine.text())

    def test_no_engine_at_all_is_a_loud_failure(self):
        self.assertEqual(run(self.block().execute("Ann", object(), None)),
                         ActionResult.FAIL)

    def test_a_disabled_archive_is_a_loud_failure(self):
        """CH-02."""
        engine = FakeEngine(service=FakeService(enabled=False))
        self.assertEqual(self.execute(self.block(), engine),
                         ActionResult.FAIL)
        self.assertIn("disabled", engine.text())

    def test_a_service_without_a_repository_is_a_loud_failure(self):
        """CH-03."""
        engine = FakeEngine(service=FakeService(repo=None))
        self.assertEqual(self.execute(self.block(), engine),
                         ActionResult.FAIL)
        self.assertIn("incomplete", engine.text())

    def test_a_service_without_a_parser_is_a_loud_failure(self):
        engine = FakeEngine(service=FakeService(parser=None))
        self.assertEqual(self.execute(self.block(), engine),
                         ActionResult.FAIL)
        self.assertIn("incomplete", engine.text())


class TestPrivateGate(BlockCase):
    """CH-04, CH-05 — RULE 4's loud half."""

    def test_a_main_room_tab_is_refused(self):
        """CH-04."""
        service = FakeService(parser=FakeParser({"tab": "main"}))
        engine = FakeEngine(service=service)
        self.assertEqual(self.execute(self.block(), engine),
                         ActionResult.FAIL)
        self.assertIn("not a private chat", engine.text())
        self.assertEqual(SYNC.calls, [], "nothing was archived")

    def test_the_gate_can_be_switched_off(self):
        """CH-05."""
        service = FakeService(parser=FakeParser({"tab": "main"}))
        engine = FakeEngine(service=service)
        self.assertEqual(self.execute(self.block(require_private=False),
                                      engine), ActionResult.OK)
        self.assertEqual(len(SYNC.calls), 1)

    def test_an_unknown_tab_state_is_refused_too(self):
        service = FakeService(parser=FakeParser({"tab": ""}))
        engine = FakeEngine(service=service)
        self.assertEqual(self.execute(self.block(), engine),
                         ActionResult.FAIL)


class TestPartnerResolution(BlockCase):
    """CH-06, CH-10, CH-21."""

    def test_an_unknown_partner_is_a_loud_failure(self):
        """CH-06."""
        service = FakeService(parser=FakeParser({"partner": "   "}))
        engine = FakeEngine(service=service)
        self.assertEqual(self.execute(self.block(), engine),
                         ActionResult.FAIL)
        self.assertIn("could not tell who", engine.text())

    def test_the_agent_is_installed_when_missing(self):
        """CH-10."""
        parser = FakeParser({"agent": 0, "partner": ""})
        service = FakeService(parser=parser)
        engine = FakeEngine(service=service)
        self.execute(self.block(), engine)
        self.assertEqual(parser.installs, 1)
        self.assertEqual(SYNC.last["nick"], "Ксюша")

    def test_the_partner_nick_is_normalised(self):
        service = FakeService(parser=FakeParser({"partner": "  Ксюша \n "}))
        engine = FakeEngine(service=service)
        self.execute(self.block(), engine)
        self.assertEqual(SYNC.last["nick"], "Ксюша")

    def test_my_nick_comes_from_the_service_when_it_knows(self):
        """CH-21."""
        engine = FakeEngine(service=FakeService(my_nick="ServiceMe"))
        self.execute(self.block(), engine)
        self.assertEqual(SYNC.last["my_nick"], "ServiceMe")

    def test_my_nick_falls_back_to_the_page_state(self):
        service = FakeService(parser=FakeParser({"me": "  PageMe  "}),
                              my_nick="")
        engine = FakeEngine(service=service)
        self.execute(self.block(), engine)
        self.assertEqual(SYNC.last["my_nick"], "PageMe")


class TestMemoryTarget(BlockCase):
    """CH-07, CH-08, CH-09 — "refuses to file under the wrong person"."""

    def test_no_nick_in_memory_is_a_loud_failure(self):
        """CH-07."""
        engine = FakeEngine(service=FakeService(), selected_nick="")
        self.assertEqual(self.execute(self.block(target="memory_nick"),
                                      engine), ActionResult.FAIL)
        self.assertIn("Pick Person", engine.text())
        self.assertEqual(SYNC.calls, [])

    def test_a_mismatched_nick_writes_nothing(self):
        """CH-08."""
        engine = FakeEngine(service=FakeService(), selected_nick="Someone")
        self.assertEqual(self.execute(self.block(target="memory_nick"),
                                      engine), ActionResult.FAIL)
        self.assertIn("nick mismatch", engine.text())
        self.assertEqual(SYNC.calls, [])

    def test_a_matching_nick_archives_and_asks_for_verification(self):
        """CH-09: case and surrounding space must not matter."""
        engine = FakeEngine(service=FakeService(), selected_nick="  КСЮША ")
        self.assertEqual(self.execute(self.block(target="memory_nick"),
                                      engine), ActionResult.OK)
        self.assertEqual(SYNC.last["nick"], "КСЮША")
        self.assertIs(SYNC.last["verify_partner"], True)

    def test_the_active_target_does_not_verify_the_partner(self):
        engine = FakeEngine(service=FakeService(), selected_nick="Someone")
        self.execute(self.block(target="active"), engine)
        self.assertIs(SYNC.last["verify_partner"], False)
        self.assertEqual(SYNC.last["nick"], "Ксюша")


class TestMode(BlockCase):
    """CH-11, CH-17, CH-18."""

    def test_full_mode_resets_the_cursor_first(self):
        """CH-11."""
        repo = FakeRepo()
        engine = FakeEngine(service=FakeService(repo=repo))
        self.execute(self.block(mode="full"), engine)
        self.assertEqual(repo.resets, ["Ксюша"])
        self.assertIs(SYNC.last["backfill_older"], True)

    def test_incremental_mode_keeps_the_cursor(self):
        repo = FakeRepo()
        engine = FakeEngine(service=FakeService(repo=repo))
        self.execute(self.block(mode="incremental"), engine)
        self.assertEqual(repo.resets, [])
        self.assertIs(SYNC.last["backfill_older"], False)

    def test_chunk_settings_are_pushed_onto_the_parser(self):
        """CH-17."""
        parser = FakeParser()
        engine = FakeEngine(service=FakeService(parser=parser))
        self.execute(self.block(chunk_size=17, chunk_pause_ms=5), engine)
        self.assertEqual(parser.chunk_size, 17)
        self.assertEqual(parser.chunk_pause_ms, 5)

    def test_max_messages_zero_means_unlimited(self):
        engine = FakeEngine(service=FakeService())
        self.execute(self.block(max_messages=0), engine)
        self.assertIsNone(SYNC.last["max_messages"])

    def test_max_messages_is_forwarded(self):
        engine = FakeEngine(service=FakeService())
        self.execute(self.block(max_messages=25), engine)
        self.assertEqual(SYNC.last["max_messages"], 25)

    def test_the_stop_predicate_and_timestamp_are_forwarded(self):
        engine = FakeEngine(service=FakeService(), stopping=True)
        self.execute(self.block(), engine)
        self.assertEqual(SYNC.last["should_stop"](), True)
        self.assertEqual(SYNC.last["now"], NOW)

    def test_media_is_passed_only_when_downloading_is_on(self):
        """CH-18."""
        repo = FakeRepo()
        engine = FakeEngine(service=FakeService(repo=repo))
        self.execute(self.block(download_media=True), engine)
        self.assertIs(SYNC.last["media"], repo.media)
        self.execute(self.block(download_media=False), engine)
        self.assertIsNone(SYNC.last["media"])


class TestOutcomeMapping(BlockCase):
    """CH-12 .. CH-16, CH-19, CH-20 — RULES 4, 5 and 7."""

    def test_new_messages_are_reported_as_a_success(self):
        """CH-12."""
        SYNC.result = SyncResult(ok=True, added=4, total=40)
        engine = FakeEngine(service=FakeService())
        self.assertEqual(self.execute(self.block(), engine),
                         ActionResult.OK)
        self.assertIn("Archived 4", engine.text())

    def test_nothing_new_is_a_quiet_success(self):
        """CH-13 — RULE 4's quiet half: OK, with an explanation."""
        SYNC.result = SyncResult(ok=True, added=0, total=40)
        engine = FakeEngine(service=FakeService())
        self.assertEqual(self.execute(self.block(), engine),
                         ActionResult.OK)
        self.assertIn("No new messages", engine.text())
        self.assertNotIn("error", engine.levels())

    def test_nothing_new_can_be_configured_to_fail(self):
        """CH-14."""
        SYNC.result = SyncResult(ok=True, added=0, total=40)
        engine = FakeEngine(service=FakeService())
        self.assertEqual(self.execute(self.block(fail_if_empty=True), engine),
                         ActionResult.FAIL)

    def test_a_stop_is_not_a_failure(self):
        """CH-15 — RULE 7."""
        SYNC.result = SyncResult(ok=True, added=2, total=9, stopped=True)
        engine = FakeEngine(service=FakeService())
        self.assertEqual(self.execute(self.block(), engine),
                         ActionResult.OK)
        self.assertIn("stopped on request", engine.text())
        self.assertNotIn("error", engine.levels())

    def test_a_recorded_gap_is_reported_but_still_a_success(self):
        SYNC.result = SyncResult(ok=True, added=1, total=9, gap=True)
        engine = FakeEngine(service=FakeService())
        self.assertEqual(self.execute(self.block(), engine),
                         ActionResult.OK)
        self.assertIn("gap", engine.text())

    def test_the_three_failure_reasons_never_look_the_same(self):
        """CH-16 — RULE 4: three distinct explanations."""
        messages = {}
        for reason in ("not_private", "partner_mismatch", "agent_lost"):
            SYNC.result = SyncResult(ok=False, reason=reason)
            engine = FakeEngine(service=FakeService())
            self.assertEqual(self.execute(self.block(), engine),
                             ActionResult.FAIL)
            self.assertIn("error", engine.levels())
            messages[reason] = engine.text()
        self.assertEqual(len(set(messages.values())), 3,
                         f"failure messages are not distinct: {messages}")

    def test_a_reasonless_failure_is_still_explained(self):
        SYNC.result = SyncResult(ok=False, reason="")
        engine = FakeEngine(service=FakeService())
        self.assertEqual(self.execute(self.block(), engine),
                         ActionResult.FAIL)
        self.assertIn("unknown reason", engine.text())

    def test_progress_is_reported_while_it_runs(self):
        """CH-20 — RULE 5."""
        engine = FakeEngine(service=FakeService())

        def drive(call):
            call["on_progress"](10, 40)
            call["on_progress"](40, 40)
            return SyncResult(ok=True, added=3, total=40)

        SYNC.side_effect = drive
        self.execute(self.block(), engine)
        text = engine.text()
        self.assertIn("10/40", text)
        self.assertIn("40/40", text)

    def test_media_caching_runs_and_is_reported(self):
        media = FakeMedia(cached=2)
        engine = FakeEngine(service=FakeService(media=media))
        self.assertEqual(self.execute(self.block(), engine),
                         ActionResult.OK)
        self.assertEqual(media.calls, 1)
        self.assertIn("Cached 2", engine.text())

    def test_media_caching_is_skipped_when_downloading_is_off(self):
        media = FakeMedia(cached=2)
        engine = FakeEngine(service=FakeService(media=media))
        self.execute(self.block(download_media=False), engine)
        self.assertEqual(media.calls, 0)

    def test_a_broken_media_cache_does_not_fail_the_archive(self):
        """CH-19: the messages are already stored; the images are a bonus."""
        media = FakeMedia(raises=True)
        engine = FakeEngine(service=FakeService(media=media))
        self.assertEqual(self.execute(self.block(), engine),
                         ActionResult.OK)


class TestSettings(unittest.TestCase):
    """RULE 3."""

    def test_defaults(self):
        block = CollectHistory()
        self.assertEqual(block.target, "active")
        self.assertEqual(block.mode, "incremental")
        self.assertTrue(block.require_private)
        self.assertEqual(block.max_messages, 0)
        self.assertEqual(block.chunk_size, 80)
        self.assertEqual(block.chunk_pause_ms, 40)
        self.assertTrue(block.download_media)
        self.assertFalse(block.fail_if_empty)

    def test_an_unset_chunk_size_falls_back_to_the_default(self):
        self.assertEqual(CollectHistory(chunk_size=0).chunk_size, 80)
        self.assertEqual(CollectHistory(chunk_size=None).chunk_size, 80)

    def test_a_negative_chunk_size_can_never_reach_the_parser(self):
        self.assertEqual(CollectHistory(chunk_size=-5).chunk_size, 1)

    def test_schema_exposes_every_control(self):
        schema = CollectHistory().config_schema()
        for key in ("target", "mode", "require_private", "max_messages",
                    "chunk_size", "chunk_pause_ms", "download_media",
                    "fail_if_empty", "pre_delay_ms"):
            self.assertIn(key, schema, f"{key} missing from the schema")

    def test_settings_round_trip_without_the_clock(self):
        block = CollectHistory(target="memory_nick", mode="full",
                               require_private=False, max_messages=7,
                               chunk_size=11, chunk_pause_ms=0,
                               download_media=False, fail_if_empty=True)
        data = block.to_dict()
        self.assertEqual(data["block_id"], "COLLECT_HISTORY")
        self.assertNotIn("now", data, "the injected clock must not be saved")
        clone = CollectHistory(**{k: v for k, v in data.items()
                                  if k != "block_id"})
        self.assertEqual(clone.to_dict(), data)

    def test_an_unknown_legacy_key_still_loads(self):
        block = CollectHistory(retired_option=1)
        self.assertTrue(block.enabled)
        self.assertEqual(block.to_dict()["retired_option"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
