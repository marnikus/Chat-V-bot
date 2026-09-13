"""Global wait speed multiplier (SPEED_MULTIPLIER block + actions/speed.py).

One coefficient scales every user-facing wait of the run: pre-delays,
pauses, visual-confirmation holds, page waits, scroll pacing, attach
verification and history chunk pauses. ×1.0 is byte-identical to the old
behaviour; anything else multiplies each wait.

Design: docs/archive/2026-09-13-speed-multiplier/SPEED_MULTIPLIER_DESIGN_2026-09-13.md

Run with:  python3 tests/unit/actions/test_speed_multiplier.py
"""

import asyncio
import json
import os
import sys
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))))

import actions  # noqa: E402,F401  (package scan registers the new block)
from actions.base_action import ActionResult  # noqa: E402
from actions.context import ActionContext  # noqa: E402
from actions.pause import Pause  # noqa: E402
from actions.registry import ActionRegistry  # noqa: E402
from actions.speed import (  # noqa: E402
    SPEED_BLOCK_ID,
    coerce_multiplier,
    describe,
    read_multiplier,
    resolve_stack_multiplier,
    scale_ms,
)
from actions.speed_multiplier import SpeedMultiplier  # noqa: E402
from actions.type_message import TypeMessage  # noqa: E402
from backend.scroll_parser import CollectResult, ScrollOptions  # noqa: E402
from backend.visual_click import ClickRequest, run_click  # noqa: E402


def run(coro):
    return asyncio.run(coro)


class Recorder:
    """Duck-typed run context: collects report() lines, carries flags."""

    def __init__(self, **attrs):
        self.lines = []
        self.__dict__.update(attrs)

    def report(self, message, level="info"):
        self.lines.append((str(message), str(level)))

    def has(self, needle, level=None):
        return any(needle in m and (level is None or lv == level)
                   for m, lv in self.lines)


class ScriptedCDP:
    """Answers evaluate() from a script, recording the expressions."""

    def __init__(self, *payloads):
        self.payloads = list(payloads)
        self.calls = 0

    async def evaluate(self, expression):
        self.calls += 1
        value = self.payloads[min(self.calls - 1, len(self.payloads) - 1)]
        return json.dumps(value) if not isinstance(value, str) else value


FOUND = {"found": True, "total": 3, "index": 1, "visible": True,
         "clickable": True, "text": "x", "target_desc": "div.x"}
STAGED = {"ok": True, "clickable": True, "target_desc": "div.x"}
CLICKED = {"ok": True, "clicked": True, "target_desc": "div.x"}
WAIT_FOUND = {"found": True, "total": 1, "visible": True, "disabled": False}
WAIT_ABSENT = {"found": False, "total": 0}


def speed_block(multiplier=1.0, enabled=True):
    return SpeedMultiplier(multiplier=multiplier, enabled=enabled)


# ══════════════════════════════════════════════════════════════════
# actions/speed.py — the pure core
# ══════════════════════════════════════════════════════════════════
class TestCoerceMultiplier(unittest.TestCase):
    def test_sane_values_pass_through(self):
        self.assertEqual(coerce_multiplier(1.0), 1.0)
        self.assertEqual(coerce_multiplier(0.5), 0.5)
        self.assertEqual(coerce_multiplier(2.0), 2.0)
        self.assertEqual(coerce_multiplier("0.5"), 0.5)

    def test_garbage_fails_open_to_normal_speed(self):
        for bad in (None, "", "fast", object()):
            self.assertEqual(coerce_multiplier(bad), 1.0)
        self.assertEqual(coerce_multiplier(float("nan")), 1.0)
        self.assertEqual(coerce_multiplier(float("inf")), 1.0)

    def test_out_of_range_is_clamped_not_honoured(self):
        self.assertEqual(coerce_multiplier(0), 0.1)
        self.assertEqual(coerce_multiplier(-5), 0.1)
        self.assertEqual(coerce_multiplier(99), 10.0)


class TestReadMultiplier(unittest.TestCase):
    def test_no_engine_means_normal_speed(self):
        self.assertEqual(read_multiplier(None), 1.0)
        self.assertEqual(read_multiplier(object()), 1.0)

    def test_engine_value_is_used_and_coerced(self):
        self.assertEqual(read_multiplier(Recorder(speed_multiplier=0.5)),
                         0.5)
        self.assertEqual(read_multiplier(Recorder(speed_multiplier="junk")),
                         1.0)


class TestScaleMs(unittest.TestCase):
    def test_identity_without_a_run(self):
        self.assertEqual(scale_ms(1000, None), 1000)
        self.assertEqual(scale_ms(1000, Recorder()), 1000)
        self.assertEqual(scale_ms(1000, Recorder(speed_multiplier=1.0)),
                         1000)

    def test_faster_and_slower(self):
        self.assertEqual(scale_ms(1000, Recorder(speed_multiplier=0.5)),
                         500)
        self.assertEqual(scale_ms(1000, Recorder(speed_multiplier=2.0)),
                         2000)

    def test_zero_stays_zero_and_garbage_stays_zero(self):
        self.assertEqual(scale_ms(0, Recorder(speed_multiplier=3.0)), 0)
        self.assertEqual(scale_ms(None, None), 0)
        self.assertEqual(scale_ms("500", Recorder(speed_multiplier=0.5)),
                         250)


class TestDescribe(unittest.TestCase):
    def test_the_three_shapes(self):
        self.assertEqual(describe(1.0), "×1.0 (normal speed)")
        self.assertEqual(describe(0.5), "×0.5 (2× faster)")
        self.assertEqual(describe(2.0), "×2.0 (2× slower)")
        self.assertEqual(describe(0.1), "×0.1 (10× faster)")
        self.assertEqual(describe(3.0), "×3.0 (3× slower)")


class TestResolveStackMultiplier(unittest.TestCase):
    def test_no_blocks_means_normal_speed(self):
        self.assertEqual(resolve_stack_multiplier(None), 1.0)
        self.assertEqual(resolve_stack_multiplier([]), 1.0)

    def test_no_speed_block_means_normal_speed(self):
        self.assertEqual(resolve_stack_multiplier([Pause(duration_ms=5)]),
                         1.0)

    def test_single_speed_block_wins(self):
        self.assertEqual(resolve_stack_multiplier([speed_block(0.5)]), 0.5)

    def test_last_enabled_speed_block_wins(self):
        stack = [speed_block(0.5), Pause(duration_ms=5), speed_block(2.0)]
        self.assertEqual(resolve_stack_multiplier(stack), 2.0)

    def test_disabled_speed_blocks_do_not_vote(self):
        stack = [speed_block(0.5, enabled=False)]
        self.assertEqual(resolve_stack_multiplier(stack), 1.0)
        stack = [speed_block(0.5, enabled=False), speed_block(2.0)]
        self.assertEqual(resolve_stack_multiplier(stack), 2.0)

    def test_garbage_multiplier_fails_open(self):
        fake = types.SimpleNamespace(block_id=SPEED_BLOCK_ID, enabled=True,
                                     multiplier="junk")
        self.assertEqual(resolve_stack_multiplier([fake]), 1.0)

    def test_speed_block_without_a_value_does_not_vote(self):
        none_vote = types.SimpleNamespace(block_id=SPEED_BLOCK_ID,
                                          enabled=True, multiplier=None)
        self.assertEqual(resolve_stack_multiplier([none_vote]), 1.0)
        stack = [speed_block(0.5), none_vote]
        self.assertEqual(resolve_stack_multiplier(stack), 0.5)

    def test_block_id_matches_the_shipped_block(self):
        """speed.py and the block must name the same id (no silent drift)."""
        self.assertEqual(SPEED_BLOCK_ID, SpeedMultiplier.block_id)


# ══════════════════════════════════════════════════════════════════
# the block itself
# ══════════════════════════════════════════════════════════════════
class TestSpeedBlock(unittest.TestCase):
    def test_registered_by_the_package_scan(self):
        self.assertIs(ActionRegistry.get("SPEED_MULTIPLIER"),
                      SpeedMultiplier)

    def test_defaults_normal_speed_and_no_pre_delay(self):
        block = SpeedMultiplier()
        self.assertEqual(block.multiplier, 1.0)
        self.assertEqual(block.pre_delay_ms, 0)  # a control block never waits
        self.assertTrue(block.enabled)

    def test_garbage_preset_is_coerced_at_load(self):
        self.assertEqual(SpeedMultiplier(multiplier="fast").multiplier, 1.0)
        self.assertEqual(SpeedMultiplier(multiplier=0).multiplier, 0.1)
        self.assertEqual(SpeedMultiplier(multiplier=99).multiplier, 10.0)

    def test_old_preset_pre_delay_does_not_resurrect_a_delay(self):
        block = SpeedMultiplier(multiplier=0.5, pre_delay_ms=900)
        self.assertEqual(block.pre_delay_ms, 0)
        self.assertEqual(block.to_dict()["pre_delay_ms"], 0)

    def test_settings_round_trip_through_dict(self):
        block = SpeedMultiplier(multiplier=0.5)
        data = block.to_dict()
        rebuilt = SpeedMultiplier(**{k: v for k, v in data.items()
                                     if k != "block_id"})
        self.assertEqual(rebuilt.multiplier, 0.5)
        self.assertEqual(rebuilt.pre_delay_ms, 0)

    def test_schema_exposes_the_coefficient(self):
        entry = SpeedMultiplier().config_schema()["multiplier"]
        self.assertEqual(entry["type"], "number")
        self.assertEqual(entry["default"], 1.0)

    def test_execute_sets_the_rate_reports_and_returns_ok(self):
        engine = Recorder()
        out = run(SpeedMultiplier(multiplier=0.5).execute("Nick", None,
                                                           engine))
        self.assertEqual(out, ActionResult.OK)
        self.assertEqual(engine.speed_multiplier, 0.5)
        self.assertTrue(engine.has("×0.5 (2× faster)", "info"), engine.lines)

    def test_execute_without_engine_is_a_noop_success(self):
        out = run(SpeedMultiplier(multiplier=0.5).execute("N", None, None))
        self.assertEqual(out, ActionResult.OK)

    def test_execute_sets_the_typed_context_field(self):
        seen = []
        ctx = ActionContext(report_fn=lambda m, lv="info": seen.append(m))
        out = run(SpeedMultiplier(multiplier=2.0).execute("N", None, ctx))
        self.assertEqual(out, ActionResult.OK)
        self.assertEqual(ctx.speed_multiplier, 2.0)
        self.assertTrue(any("×2.0 (2× slower)" in m for m in seen), seen)


# ══════════════════════════════════════════════════════════════════
# wiring: each wait site honours the rate
# ══════════════════════════════════════════════════════════════════
class TestPreDelayScaling(unittest.TestCase):
    def test_unscaled_without_a_run(self):
        block = TypeMessage(pre_delay_ms=500)
        with mock.patch("asyncio.sleep", new=mock.AsyncMock()) as nap:
            run(block.pre_delay())
        nap.assert_called_once_with(0.5)

    def test_scaled_with_a_run(self):
        block = TypeMessage(pre_delay_ms=500)
        engine = Recorder(speed_multiplier=0.5)
        with mock.patch("asyncio.sleep", new=mock.AsyncMock()) as nap:
            run(block.pre_delay(engine))
        nap.assert_called_once_with(0.25)

    def test_zero_delay_never_sleeps(self):
        block = TypeMessage(pre_delay_ms=0)
        with mock.patch("asyncio.sleep", new=mock.AsyncMock()) as nap:
            run(block.pre_delay(Recorder(speed_multiplier=3.0)))
        nap.assert_not_called()


class TestPauseScaling(unittest.TestCase):
    def test_pause_sleeps_and_reports_the_scaled_wait(self):
        engine = Recorder(speed_multiplier=0.5)
        with mock.patch("asyncio.sleep", new=mock.AsyncMock()) as nap:
            out = run(Pause(duration_ms=1000).execute("N", None, engine))
        self.assertEqual(out, ActionResult.OK)
        nap.assert_called_once_with(0.5)
        self.assertTrue(engine.has("Pausing for 500 ms"), engine.lines)
        self.assertTrue(engine.has("Pause finished"), engine.lines)


class TestVisualHoldScaling(unittest.TestCase):
    def test_hold_and_click_beat_scale_together(self):
        from backend.visual_click import find_and_click
        engine = Recorder(speed_multiplier=0.5)
        cdp = ScriptedCDP(FOUND, STAGED, CLICKED)
        with mock.patch("asyncio.sleep", new=mock.AsyncMock()) as nap:
            out = run(find_and_click(cdp, selector="div.x",
                                     confirm_pause_ms=700, engine=engine))
        self.assertEqual(out, ActionResult.OK)
        # 700 ms hold → 350 ms; 250 ms outline→click beat → 125 ms
        self.assertEqual([c.args[0] for c in nap.call_args_list],
                         [0.35, 0.125])
        self.assertTrue(engine.has("Holding 350 ms"), engine.lines)

    def test_unscaled_without_a_run(self):
        engine = Recorder()
        cdp = ScriptedCDP(FOUND, STAGED, CLICKED)
        request = ClickRequest(selector="div.x", confirm_pause_ms=700)
        with mock.patch("asyncio.sleep", new=mock.AsyncMock()) as nap:
            out = run(run_click(cdp, request, engine=engine))
        self.assertEqual(out, ActionResult.OK)
        self.assertEqual([c.args[0] for c in nap.call_args_list],
                         [0.7, 0.25])


class TestWaitPageScaling(unittest.TestCase):
    def test_found_immediately_reports_the_scaled_timeout(self):
        from actions.wait_page import WaitPageLoad
        engine = Recorder(speed_multiplier=0.5)
        cdp = ScriptedCDP(WAIT_FOUND)
        block = WaitPageLoad(timeout_ms=5000, pre_delay_ms=0)
        out = run(block.execute("N", cdp, engine))
        self.assertEqual(out, ActionResult.OK)
        self.assertTrue(engine.has("(timeout 2500 ms)"), engine.lines)

    def test_pre_delay_and_poll_gap_are_scaled(self):
        """One missed probe, then found: both sleeps carry the rate."""
        import time as real_time
        from actions.wait_page import WaitPageLoad
        engine = Recorder(speed_multiplier=0.5)
        cdp = ScriptedCDP(WAIT_ABSENT, WAIT_FOUND)
        block = WaitPageLoad(timeout_ms=5000, pre_delay_ms=200)
        frozen = real_time.monotonic() + 1000.0
        with mock.patch("actions.wait_page.sleep_with_stop",
                        new=mock.AsyncMock()) as gated, \
             mock.patch("actions.wait_page.time") as clock:
            clock.monotonic.return_value = frozen
            out = run(block.execute("N", cdp, engine))
        self.assertEqual(out, ActionResult.OK)
        # 200 ms pre-delay → 0.1 s; 300 ms poll gap → 0.15 s
        self.assertEqual([c.args[0] for c in gated.call_args_list],
                         [0.1, 0.15])

    def test_timeout_line_reports_the_scaled_wait(self):
        from actions.wait_page import WaitPageLoad
        engine = Recorder(speed_multiplier=0.5)
        block = WaitPageLoad(timeout_ms=5000)
        block._report_timeout({"total": 3}, engine)
        self.assertTrue(engine.has("timeout after 2500 ms"), engine.lines)
        self.assertTrue(engine.has("3 node(s)"), engine.lines)


class TestClickUserTabWaitScaling(unittest.TestCase):
    def test_tab_pause_is_scaled(self):
        from actions.click_user import ClickUser
        engine = Recorder(speed_multiplier=0.5)
        block = ClickUser(tab_pause_ms=800)
        with mock.patch("asyncio.sleep", new=mock.AsyncMock()) as nap:
            run(block._wait_for_new_tab(engine))
        nap.assert_called_once_with(0.4)
        self.assertTrue(engine.has("Waiting 400 ms"), engine.lines)


class TestScrollOptionsScaling(unittest.TestCase):
    def test_collect_stamps_the_rate_onto_fresh_options(self):
        """Real to_scroll_options → from_options; only the page is faked."""
        import actions.scroll_parse as block_mod
        from actions.scroll_parse import ScrollParse
        from backend.scroll_parser import ScrollParser
        seen = {}

        async def fake_collect(self, **kwargs):
            seen["options"] = self.options
            return CollectResult()

        block = ScrollParse()
        engine = Recorder(speed_multiplier=0.5)
        with mock.patch.object(ScrollParser, "collect", new=fake_collect):
            run(block._collect(None, engine, None, set(), None, None, None,
                               None))
        options = seen["options"]
        self.assertIsInstance(options, ScrollOptions)
        self.assertEqual(options.pause_ms, 400)          # 800 × 0.5
        self.assertEqual(options.load_timeout_ms, 1250)  # 2500 × 0.5
        self.assertEqual(options.confirm_pause_ms, 250)  # 500 × 0.5
        self.assertEqual(block.scroll_pause_ms, 800)  # own setting kept

    def test_without_a_run_the_values_pass_through(self):
        import actions.scroll_parse as block_mod
        from backend.scroll_parser import ScrollParser
        seen = {}

        async def fake_collect(self, **kwargs):
            seen["options"] = self.options
            return CollectResult()

        block = block_mod.ScrollParse()
        with mock.patch.object(ScrollParser, "collect", new=fake_collect):
            run(block._collect(None, None, None, set(), None, None, None,
                               None))
        self.assertEqual(seen["options"].pause_ms, 800)
        self.assertEqual(seen["options"].load_timeout_ms, 2500)


class TestAttachImageScaling(unittest.TestCase):
    def test_verify_and_confirm_timeouts_scale(self):
        import actions.attach_image as block_mod
        seen = []

        async def fake_attach(*args, **kwargs):
            seen.extend(args)
            return True

        engine = Recorder(speed_multiplier=0.5)
        block = block_mod.AttachImage(pre_delay_ms=0, verify_timeout_ms=8000,
                                      confirm_pause_ms=700)
        with mock.patch.object(block_mod, "attach_image", new=fake_attach):
            out = run(block.execute("N", None, engine))
        self.assertEqual(out, ActionResult.OK)
        self.assertEqual(seen[5], 4000)  # verify_timeout_ms
        self.assertEqual(seen[7], 350)   # confirm_pause_ms


class TestCollectHistoryScaling(unittest.TestCase):
    def test_chunk_pause_scales(self):
        import actions.collect_history as block_mod
        seen = {}

        async def fake_sync(*args, **kwargs):
            seen.update(kwargs)
            return types.SimpleNamespace(ok=True, stopped=False, gap=False,
                                         added=0, total=0, reason="")

        engine = Recorder(speed_multiplier=0.5)
        block = block_mod.CollectHistory(chunk_pause_ms=40)
        journey = block_mod._CollectRun(block, engine)
        journey.parser = types.SimpleNamespace(chunk_size=0, chunk_pause_ms=0)
        journey.repo = types.SimpleNamespace(media=None)
        journey.nick = "Zoe"
        journey.state = {"count": 0}
        with mock.patch.object(block_mod, "sync_conversation",
                               new=fake_sync):
            run(journey.collect())
        self.assertEqual(seen["chunk_pause_ms"], 20)
        self.assertEqual(journey.parser.chunk_pause_ms, 20)


# ══════════════════════════════════════════════════════════════════
# end to end: a real coordinator run
# ══════════════════════════════════════════════════════════════════
class SpeedRunCase(unittest.TestCase):
    def setUp(self):
        import tempfile
        from services.run import RunCoordinator
        self._cwd = os.getcwd()
        self._tmp = tempfile.TemporaryDirectory()
        os.chdir(self._tmp.name)
        self.engine = RunCoordinator(cdp=None, memory=None, criteria=None)
        self.engine._tracer = types.SimpleNamespace(
            note=lambda *a, **k: None)
        self.debug = []
        self.engine.debug_msg.connect(
            lambda m, lv: self.debug.append((m, lv)))

    def tearDown(self):
        os.chdir(self._cwd)
        self._tmp.cleanup()

    def debug_text(self):
        return "\n".join(m for m, _ in self.debug)


class TestRunStartResolution(SpeedRunCase):
    def test_last_speed_block_wins_at_run_start(self):
        self.engine.load_stack([
            {"block_id": "SPEED_MULTIPLIER", "multiplier": 0.5},
            {"block_id": "PAUSE", "duration_ms": 1000},
            {"block_id": "SPEED_MULTIPLIER", "multiplier": 2.0},
        ])
        self.engine._begin_run()
        self.assertEqual(self.engine.speed_multiplier, 2.0)
        self.assertIn("×2.0 (2× slower)", self.debug_text())

    def test_no_speed_block_stays_silent_at_normal_speed(self):
        self.engine.load_stack([{"block_id": "PAUSE", "duration_ms": 10}])
        self.engine._begin_run()
        self.assertEqual(self.engine.speed_multiplier, 1.0)
        self.assertNotIn("Global wait speed", self.debug_text())

    def test_rate_resets_between_runs(self):
        self.engine.load_stack([
            {"block_id": "SPEED_MULTIPLIER", "multiplier": 0.5}])
        self.engine._begin_run()
        self.assertEqual(self.engine.speed_multiplier, 0.5)
        self.engine.load_stack([{"block_id": "PAUSE", "duration_ms": 10}])
        self.engine._begin_run()
        self.assertEqual(self.engine.speed_multiplier, 1.0)


class TestSpeedEndToEnd(SpeedRunCase):
    def test_speed_then_pause_sleeps_half(self):
        from stores.user_memory import UserRecord
        self.engine.load_stack([
            {"block_id": "SPEED_MULTIPLIER", "multiplier": 0.5},
            {"block_id": "PAUSE", "duration_ms": 1000},
        ])
        self.engine._begin_run()
        with mock.patch("asyncio.sleep", new=mock.AsyncMock()) as nap:
            out = run(self.engine._execute_for_user(UserRecord(nick="Zoe"),
                                                    has_skip=False))
        self.assertEqual(out, "ok")
        nap.assert_called_once_with(0.5)
        self.assertIn("×0.5 (2× faster)", self.debug_text())
        self.assertIn("Pausing for 500 ms", self.debug_text())


if __name__ == "__main__":
    unittest.main()
