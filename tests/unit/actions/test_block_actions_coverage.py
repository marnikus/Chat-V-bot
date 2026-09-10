"""Block-level contracts for the simple actions (PAUSE, WAIT_PAGE_LOAD,
MARK_MESSAGED, TAKE_PERSON, REPEAT_LOOP, CONDITIONAL_SKIP, SEARCH_USERS,
TYPE_MESSAGE, ATTACH_IMAGE).

These are the blocks AREA D re-homes on the shared skeleton in
`actions/base.py`, so every one of them is pinned here BEFORE the move:
the log wording the UI shows, the ActionResult each path returns, the
`pre_delay_ms` suppression the marker blocks rely on, and the exact
`to_dict()` round-trip that keeps old presets loading.

Design ref: docs/REFACTOR_2026-09-09_AREA_D_DESIGN.md §6/§7 (ids AA#1–14).
Rules proven: AGENT_RULES RULE 2 (report every step), RULE 4 (empty ≠
broken), RULE 7 (stop), RULE 12/RULE 10 (marker blocks own no delay).

Run with:  python3 tests/unit/actions/test_block_actions_coverage.py
"""

import asyncio
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))))

from actions.attach_image import AttachImage  # noqa: E402
from actions.base_action import ActionResult  # noqa: E402
from actions.conditional_skip import ConditionalSkip  # noqa: E402
from actions.mark_messaged import MarkMessaged  # noqa: E402
from actions.pause import Pause  # noqa: E402
from actions.repeat_loop import RepeatLoop  # noqa: E402
from actions.search_users import SearchUsers  # noqa: E402
from actions.take_person import PICK_MODE_PHRASES, TakePerson  # noqa: E402
from actions.type_message import TypeMessage  # noqa: E402
from actions.wait_page import WaitPageLoad  # noqa: E402


class Recorder:
    """Duck-typed run context: collects report() lines and the flags blocks read."""

    def __init__(self, **attrs):
        self.lines = []
        self.__dict__.update(attrs)

    def report(self, message, level="info"):
        self.lines.append((str(message), str(level)))

    def levels(self, level):
        return [m for m, lv in self.lines if lv == level]

    def has(self, needle, level=None):
        return any(needle in m and (level is None or lv == level)
                   for m, lv in self.lines)


def run(coro):
    return asyncio.run(coro)


# ══════════════════════════════════════════════════════════════════
# AA#1 — PAUSE: own delay, no pre-delay, loud start AND end
# ══════════════════════════════════════════════════════════════════
class TestPause(unittest.TestCase):

    def test_pause_waits_reports_and_returns_ok(self):
        block = Pause(duration_ms=25)
        engine = Recorder()
        out = run(block.execute("Nick", None, engine))
        self.assertEqual(out, ActionResult.OK)
        self.assertTrue(engine.has("Pausing for 25 ms"), engine.lines)
        self.assertTrue(engine.has("Pause finished"), engine.lines)

    def test_pause_never_inherits_a_pre_delay(self):
        """RULE 10: the marker block owns its own delay, exactly one."""
        block = Pause(duration_ms=10, pre_delay_ms=5000)
        self.assertEqual(block.pre_delay_ms, 0)
        self.assertEqual(block.to_dict()["pre_delay_ms"], 0)

    def test_pause_without_engine_does_not_crash(self):
        self.assertEqual(run(Pause(duration_ms=1).execute("N", None, None)),
                         ActionResult.OK)
        self.assertEqual(run(Pause(duration_ms=1).execute("N", None)),
                         ActionResult.OK)


# ══════════════════════════════════════════════════════════════════
# AA#2 — CONDITIONAL_SKIP / REPEAT_LOOP: markers report and SKIP
# ══════════════════════════════════════════════════════════════════
class TestMarkerBlocks(unittest.TestCase):

    def test_conditional_skip_reports_and_skips(self):
        engine = Recorder()
        block = ConditionalSkip()
        self.assertEqual(run(block.execute("Anna", None, engine)),
                         ActionResult.SKIP)
        self.assertTrue(engine.has("Conditional skip marker for Anna"),
                        engine.lines)

    def test_conditional_skip_to_dict_is_minimal(self):
        self.assertEqual(ConditionalSkip().to_dict(),
                         {"block_id": "CONDITIONAL_SKIP",
                          "pre_delay_ms": 0, "enabled": True})

    def test_repeat_loop_floor_is_one_cycle(self):
        self.assertEqual(RepeatLoop(repeat_count=0).repeat_count, 1)
        self.assertEqual(RepeatLoop(repeat_count=-7).repeat_count, 1)
        self.assertEqual(RepeatLoop(repeat_count=3).repeat_count, 3)

    def test_repeat_loop_marker_returns_skip(self):
        engine = Recorder()
        self.assertEqual(run(RepeatLoop(repeat_count=2).execute("N", None, engine)),
                         ActionResult.SKIP)
        self.assertTrue(engine.has("cycle count handled by the engine"),
                        engine.lines)

    def test_repeat_loop_pre_delay_is_forced_to_zero(self):
        self.assertEqual(RepeatLoop(repeat_count=2, pre_delay_ms=900).pre_delay_ms, 0)

    def test_marker_schemas_advertise_their_only_setting(self):
        """Characterisation: the two marker schemas differ on purpose —
        PAUSE and REPEAT_LOOP replace the schema (no pre-delay knob exists,
        because both force pre_delay_ms to 0), while CONDITIONAL_SKIP has no
        settings at all and inherits the base pre-delay field. The shared
        MarkerBlock must keep all three shapes byte-for-byte."""
        self.assertEqual(set(RepeatLoop().config_schema()), {"repeat_count"})
        self.assertEqual(RepeatLoop().config_schema()["repeat_count"]["default"], 2)
        self.assertEqual(set(Pause().config_schema()), {"duration_ms"})
        self.assertEqual(set(ConditionalSkip().config_schema()), {"pre_delay_ms"})
        self.assertEqual(ConditionalSkip().config_schema()["pre_delay_ms"]["type"],
                         "number")


# ══════════════════════════════════════════════════════════════════
# AA#3/AA#4 — WAIT_PAGE_LOAD: found, timeout, probe errors, throttling
# ══════════════════════════════════════════════════════════════════
class ProbeCDP:
    """Answers the dom_probe with scripted payloads / errors."""

    def __init__(self, answers):
        self.answers = list(answers)
        self.calls = []

    async def evaluate(self, expression):
        self.calls.append(expression)
        answer = self.answers.pop(0) if self.answers else self.answers_default()
        if isinstance(answer, Exception):
            raise answer
        return answer

    @staticmethod
    def answers_default():
        return '{"found": false, "total": 0}'


class TestWaitPage(unittest.TestCase):

    def test_found_element_returns_ok_with_the_probe_message(self):
        cdp = ProbeCDP(['{"found": true, "total": 1, "index": 0, '
                        '"text": "hi", "visible": true, "disabled": false}'])
        engine = Recorder()
        out = run(WaitPageLoad(target_selector="textarea", timeout_ms=50)
                  .execute("N", cdp, engine))
        self.assertEqual(out, ActionResult.OK)
        self.assertTrue(engine.has("found — visible & enabled"), engine.lines)

    def test_timeout_reports_matched_nodes_and_fails(self):
        cdp = ProbeCDP(['{"found": false, "total": 3}'])
        engine = Recorder()
        out = run(WaitPageLoad(target_selector="textarea", timeout_ms=0)
                  .execute("N", cdp, engine))
        self.assertEqual(out, ActionResult.FAIL)
        self.assertTrue(engine.has("Failed to find element"), engine.lines)
        self.assertTrue(engine.has("matched 3 node(s)", "error"), engine.lines)

    def test_probe_errors_are_reported_only_on_the_first_of_five(self):
        """A page that throws on every evaluate must not spam the console."""
        cdp = ProbeCDP([RuntimeError("detached"), RuntimeError("detached"),
                        RuntimeError("detached"), RuntimeError("detached"),
                        '{"found": true, "total": 1, "visible": true, '
                        '"disabled": false}'])
        engine = Recorder()
        block = WaitPageLoad(target_selector="textarea", timeout_ms=5000)
        out = run(block.execute("N", cdp, engine))
        self.assertEqual(out, ActionResult.OK)
        errors = engine.levels("error")
        self.assertEqual(len([m for m in errors if "Probe error" in m]), 1,
                         errors)

    def test_selector_defaults_to_the_message_textarea(self):
        block = WaitPageLoad()
        self.assertIn("textarea", block.target_selector)
        self.assertEqual(WaitPageLoad(target_selector="").target_selector,
                         block.target_selector)
        self.assertEqual(WaitPageLoad(target_selector="x").target_selector, "x")

    def test_timeout_is_in_the_schema_and_round_trips(self):
        block = WaitPageLoad(target_selector="a", timeout_ms=1234)
        data = block.to_dict()
        self.assertEqual(data["timeout_ms"], 1234)
        self.assertEqual(data["target_selector"], "a")
        schema = WaitPageLoad().config_schema()
        self.assertEqual(schema["timeout_ms"]["type"], "number")


# ══════════════════════════════════════════════════════════════════
# AA#5 — MARK_MESSAGED: every status of the engine hook, loudly
# ══════════════════════════════════════════════════════════════════
class MarkEngine(Recorder):
    def __init__(self, status, *, selected_nick="Anna", support=True):
        super().__init__(selected_nick=selected_nick)
        self.status = status
        if support:
            self.mark_person_messaged = self._mark

    async def _mark(self, nick):
        if isinstance(self.status, Exception):
            raise self.status
        return self.status


class TestMarkMessaged(unittest.TestCase):

    def test_no_engine_fails(self):
        self.assertEqual(run(MarkMessaged().execute("N", None, None)),
                         ActionResult.FAIL)

    def test_no_saved_nick_fails_with_the_pick_person_hint(self):
        engine = Recorder(selected_nick="")
        out = run(MarkMessaged().execute("N", None, engine))
        self.assertEqual(out, ActionResult.FAIL)
        self.assertTrue(engine.has("Pick Person", "error"), engine.lines)

    def test_engine_without_marking_support_fails(self):
        engine = Recorder(selected_nick="Anna")
        out = run(MarkMessaged().execute("N", None, engine))
        self.assertEqual(out, ActionResult.FAIL)
        self.assertTrue(engine.has("does not support marking", "error"),
                        engine.lines)

    def test_status_matrix(self):
        cases = {"ok": ActionResult.OK, "already": ActionResult.OK,
                 "missing": ActionResult.FAIL, "error": ActionResult.FAIL}
        for status, expected in cases.items():
            with self.subTest(status=status):
                engine = MarkEngine(status)
                out = run(MarkMessaged().execute("N", None, engine))
                self.assertEqual(out, expected)

    def test_marked_nick_is_the_memory_one_not_the_queue_one(self):
        engine = MarkEngine("ok", selected_nick="Zoe")
        run(MarkMessaged().execute("QueueNick", None, engine))
        self.assertTrue(engine.has("“Zoe”", "success"), engine.lines)
        self.assertFalse(any("QueueNick" in m for m, _ in engine.lines))

    def test_raising_hook_is_reported_and_fails(self):
        engine = MarkEngine(RuntimeError("db locked"))
        out = run(MarkMessaged().execute("N", None, engine))
        self.assertEqual(out, ActionResult.FAIL)
        self.assertTrue(engine.has("db locked", "error"), engine.lines)


# ══════════════════════════════════════════════════════════════════
# AA#6/AA#7 — TAKE_PERSON: the three rules, engine order, no candidates
# ══════════════════════════════════════════════════════════════════
class Row:
    def __init__(self, nick, messaged=False):
        self.nick = nick
        self.messaged = messaged


class OrderEngine(Recorder):
    def __init__(self, order):
        super().__init__()
        self._order = order

    def queue_order(self, rows):
        return list(self._order)


class TestTakePerson(unittest.TestCase):

    def test_random_new_picks_only_unmessaged(self):
        rows = [Row("Anna", True), Row("Bella", True)]
        self.assertIsNone(TakePerson(pick_mode="random_new").choose(rows))
        rows.append(Row("Cara"))
        for _ in range(20):
            self.assertEqual(TakePerson().choose(rows), "Cara")

    def test_random_done_picks_only_messaged(self):
        rows = [Row("Anna", True), Row("Bella")]
        self.assertEqual(TakePerson("random_done").choose(rows), "Anna")
        self.assertIsNone(TakePerson("random_done").choose([Row("Bella")]))

    def test_order_first_uses_the_engine_queue(self):
        rows = [Row("Anna"), Row("Bella")]
        engine = OrderEngine(["Bella", "Anna"])
        self.assertEqual(TakePerson("order_first").choose(rows, engine), "Bella")

    def test_order_first_without_engine_takes_the_first_new(self):
        rows = [Row("Anna"), Row("Bella")]
        self.assertEqual(TakePerson("order_first").choose(rows, None), "Anna")
        self.assertIsNone(TakePerson("order_first").choose([Row("Zed", True)]))

    def test_unknown_mode_falls_back_to_random_new(self):
        block = TakePerson(pick_mode="chaos")
        self.assertEqual(block.pick_mode, "random_new")
        self.assertEqual(block.mode_phrase, PICK_MODE_PHRASES["random_new"])

    def test_marker_execute_skips_and_says_so(self):
        engine = Recorder()
        self.assertEqual(run(TakePerson().execute("N", None, engine)),
                         ActionResult.SKIP)
        self.assertTrue(engine.has("handled by the engine"), engine.lines)

    def test_schema_lists_every_rule(self):
        options = TakePerson().config_schema()["pick_mode"]["options"]
        self.assertEqual(options, list(PICK_MODE_PHRASES.keys()))


# ══════════════════════════════════════════════════════════════════
# AA#8 — TYPE_MESSAGE: composer source, empty composer, {{nick}}
# ══════════════════════════════════════════════════════════════════
class TypeCDP:
    """Accepts every strategy on the first try so the happy path runs."""

    def __init__(self, *, accept=True):
        self.accept = accept
        self.evaluations = []

    async def evaluate(self, expression):
        self.evaluations.append(expression)
        if "/*PROBE*/" in expression or "querySelector" in expression:
            if "textarea" in expression and "value" not in expression:
                return '{"found": true, "total": 1, "visible": true, "disabled": false}'
        return "ok"

    async def send(self, method, params=None):
        return {}

    async def get_element_rect(self, selector):
        return {"x": 0, "y": 0, "width": 10, "height": 10}

    async def click_at(self, x, y):
        return None


class TestTypeMessage(unittest.TestCase):

    def setUp(self):
        self.calls = []

        def spy(cdp, text, speed, report=None):
            self.calls.append((text, speed))
            return asyncio.sleep(0, result=True)

        import actions.type_message as mod
        self._orig = mod.type_message
        mod.type_message = spy
        self.addCleanup(lambda: setattr(mod, "type_message", self._orig))

    def test_stored_text_is_typed(self):
        out = run(TypeMessage(message="hello", typing_speed_ms=11,
                              pre_delay_ms=0).execute("Nick", None, None))
        self.assertEqual(out, ActionResult.OK)
        self.assertEqual(self.calls, [("hello", 11)])

    def test_composer_text_wins_when_enabled(self):
        engine = Recorder(composer_text=" from the window ")
        out = run(TypeMessage(use_composer=True, pre_delay_ms=0)
                  .execute("Nick", None, engine))
        self.assertEqual(out, ActionResult.OK)
        self.assertEqual(self.calls[-1][0], " from the window ")

    def test_empty_composer_is_a_loud_fail(self):
        """RULE 4: nothing typed is not the same as something typed."""
        engine = Recorder(composer_text="   ")
        out = run(TypeMessage(use_composer=True, pre_delay_ms=0)
                  .execute("Nick", None, engine))
        self.assertEqual(out, ActionResult.FAIL)
        self.assertEqual(self.calls, [])
        self.assertTrue(engine.has("composer is empty", "warn"), engine.lines)

    def test_nick_placeholder_uses_memory_then_the_queue(self):
        engine = Recorder(selected_nick="Zoe", composer_text="")
        run(TypeMessage(message="hi {{nick}}", pre_delay_ms=0)
            .execute("QueueNick", None, engine))
        self.assertEqual(self.calls[-1][0], "hi Zoe")

        run(TypeMessage(message="hi {{nick}}", pre_delay_ms=0)
            .execute("QueueNick", None, None))
        self.assertEqual(self.calls[-1][0], "hi QueueNick")

    def test_failure_of_the_injector_is_reported_as_fail(self):
        import actions.type_message as mod

        async def failing(cdp, text, speed, report=None):
            return False

        mod.type_message = failing
        out = run(TypeMessage(message="x", pre_delay_ms=0)
                  .execute("N", None, None))
        self.assertEqual(out, ActionResult.FAIL)


# ══════════════════════════════════════════════════════════════════
# AA#9 — SEARCH_USERS: one call, report wired, empty text is the injector's
# ══════════════════════════════════════════════════════════════════
class TestSearchUsers(unittest.TestCase):

    def setUp(self):
        self.calls = []
        import actions.search_users as mod
        self._orig = mod.type_search
        mod.type_search = self._spy
        self.addCleanup(lambda: setattr(mod, "type_search", self._orig))

    async def _spy(self, cdp, text, report=None):
        self.calls.append((cdp, text, report))
        return True

    def test_text_is_passed_through_with_the_report_hook(self):
        engine = Recorder()
        block = SearchUsers(text="  Anna  ", pre_delay_ms=0)
        self.assertEqual(run(block.execute("N", "CDP", engine)), ActionResult.OK)
        cdp, text, report = self.calls[-1]
        self.assertEqual(cdp, "CDP")
        self.assertEqual(text, "  Anna  ")
        self.assertTrue(callable(report))

    def test_failures_map_to_fail(self):
        import actions.search_users as mod

        async def nope(cdp, text, report=None):
            return False

        mod.type_search = nope
        self.assertEqual(run(SearchUsers(text="x", pre_delay_ms=0)
                             .execute("N", None, None)), ActionResult.FAIL)

    def test_schema_documents_the_placeholder(self):
        schema = SearchUsers().config_schema()
        self.assertIn("{{nick}}", schema["text"]["label"])


# ══════════════════════════════════════════════════════════════════
# AA#10–AA#12 — ATTACH_IMAGE: every block setting reaches the pipeline
# ══════════════════════════════════════════════════════════════════
class TestAttachImageBlock(unittest.TestCase):

    def setUp(self):
        self.args = None
        self.result = True
        import actions.attach_image as mod
        self._orig = mod.attach_image
        mod.attach_image = self._spy
        self.addCleanup(lambda: setattr(mod, "attach_image", self._orig))

    async def _spy(self, cdp, folder_path, file_pattern, mode, simulate_dialog,
                   verify_timeout_ms, highlight_enabled, confirm_pause_ms,
                   report):
        self.args = dict(cdp=cdp, folder_path=folder_path,
                         file_pattern=file_pattern, mode=mode,
                         simulate_dialog=simulate_dialog,
                         verify_timeout_ms=verify_timeout_ms,
                         highlight_enabled=highlight_enabled,
                         confirm_pause_ms=confirm_pause_ms, report=report)
        return self.result

    def test_all_settings_reach_the_pipeline_positionally(self):
        from backend.media_handler import DEFAULT_FILE_PATTERN
        engine = Recorder()
        block = AttachImage(folder_path="/tmp/x", file_pattern="",
                            rotation_mode="random", simulate_dialog=False,
                            verify_timeout_ms=1200, highlight_enabled=False,
                            confirm_pause_ms=40, pre_delay_ms=0)
        self.assertEqual(run(block.execute("N", "CDP", engine)),
                         ActionResult.OK)
        self.assertEqual(self.args["file_pattern"], DEFAULT_FILE_PATTERN)
        self.assertEqual(self.args["mode"], "random")
        self.assertIs(self.args["cdp"], "CDP")
        self.assertIs(self.args["folder_path"], "/tmp/x")
        self.assertFalse(self.args["simulate_dialog"])
        self.assertEqual(self.args["verify_timeout_ms"], 1200)
        self.assertFalse(self.args["highlight_enabled"])
        self.assertEqual(self.args["confirm_pause_ms"], 40)
        self.assertTrue(callable(self.args["report"]))

    def test_negative_and_missing_values_are_clamped(self):
        block = AttachImage(verify_timeout_ms=-5, confirm_pause_ms=None)
        self.assertEqual(block.verify_timeout_ms, 0)
        self.assertEqual(block.confirm_pause_ms, 0)
        from backend.media_handler import DEFAULT_FILE_PATTERN
        self.assertEqual(AttachImage(file_pattern="").file_pattern,
                         DEFAULT_FILE_PATTERN)

    def test_pipeline_false_is_a_failed_block(self):
        self.result = False
        self.assertEqual(run(AttachImage(folder_path="/tmp", pre_delay_ms=0)
                             .execute("N", None, None)), ActionResult.FAIL)

    def test_settings_round_trip_for_presets(self):
        block = AttachImage(folder_path="/tmp/a", file_pattern="*.gif",
                            rotation_mode="random", simulate_dialog=False,
                            verify_timeout_ms=10, confirm_pause_ms=5,
                            highlight_enabled=False)
        data = block.to_dict()
        again = AttachImage(**data)
        self.assertEqual(again.to_dict(), data)


if __name__ == "__main__":
    unittest.main(verbosity=2)
