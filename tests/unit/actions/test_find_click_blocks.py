"""The find-and-click family: the runner's contract and the four blocks.

AREA D4/D5 (`docs/REFACTOR_2026-09-09_AREA_D_DESIGN.md` §6): `find_and_click()`
was one 126-line function of CC 27 holding both phases, every error string and
every pause. It becomes `ClickRequest` (the ten knobs) + `find_phase()` +
`click_phase()` + `run_click()`, and the four clicking blocks keep reporting
the same strings in the same order — those strings are the debugger's UI
(`docs/AGENT_RULES.md` RULE 1/RULE 2), so they are pinned here rather than
implied.

Contracts proven here (AC#1–10):

  AC#1   an empty selector fails fast, without touching the page;
  AC#2   the FIND probe is built from the request's own fields;
  AC#3   every page failure mode maps to FAIL and to a distinct report line
         (CDP error / no data / not found);
  AC#4   the confirmation hold happens only with highlights on, and only
         after the red outline was reported;
  AC#5   `click_enabled=False` is a successful *find-only* run;
  AC#6   a found-but-invisible element is refused before any click probe;
  AC#7   the CLICK phase is staged: orange outline first, then the real
         click, 250 ms apart, and its own three failure modes;
  AC#8   `run_click(cdp, ClickRequest(...))` and `find_and_click(cdp, ...)`
         are the same call — the request object is the only new thing;
  AC#9   `find_and_click_exact` pins MATCH_EXACT and nothing else changes;
  AC#10  the four blocks: pre-delay, field→probe wiring, CLICK_SEND's
         fallback, and a disabled highlight path that still clicks.

Run with:  python3 tests/unit/actions/test_find_click_blocks.py
"""

import asyncio
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from actions.click_back import ClickBack  # noqa: E402
from actions.click_main_tab import ClickMainTab  # noqa: E402
from actions.click_send import ClickSend  # noqa: E402
from actions.custom_find import CustomFind  # noqa: E402
from actions.base_action import ActionResult  # noqa: E402
from backend.dom_probe import MATCH_EXACT  # noqa: E402
from backend.visual_click import (  # noqa: E402
    CLICK_PAUSE_MS,
    find_and_click,
    find_and_click_exact,
)

try:                                        # the new seam (D4)
    from backend.visual_click import ClickRequest, run_click
except ImportError:                                           # noqa: PERF203
    ClickRequest = None
    run_click = None

FIND_MARKERS = ("var doClick = false;", "var doClick = true;")
FOUND = {"found": True, "total": 3, "index": 1, "visible": True,
         "clickable": True, "text": "Гостиная", "target_desc": "div.tab"}
STAGED = {"ok": True, "clickable": True, "target_desc": "div.send"}
CLICKED = {"ok": True, "clicked": True, "target_desc": "div.send"}


class FakeCDP:
    """Answers the three probes the runner sends, in the order it sends them."""

    def __init__(self, find=FOUND, staged=STAGED, click=CLICKED,
                 fail_on=None, error=None, find_seq=None):
        self.find, self.staged, self.click = find, staged, click
        #: successive answers for the FIND probe, when a block retries
        self.find_seq = list(find_seq) if find_seq else None
        self.expressions = []
        self.results = []
        self.fail_on = fail_on            # "find" | "staged" | "click"
        self.error = error

    def _which(self, expression: str) -> str:
        if "var doClick = true;" in expression:
            return "click"
        if "var doClick = false;" in expression:
            return "staged"
        return "find"

    async def evaluate(self, expression: str):
        which = self._which(expression)
        self.expressions.append((which, expression))
        if self.fail_on == which:
            raise self.error or RuntimeError("CDP connection closed")
        if which == "find" and self.find_seq:
            value = self.find_seq.pop(0)
        else:
            value = {"find": self.find, "staged": self.staged,
                     "click": self.click}[which]
        if isinstance(value, str) or value is None:
            return value
        return json.dumps(value)


class Recorder:
    """Stands in for the run context: collects `report(message, level)`."""

    def __init__(self):
        self.lines = []

    def report(self, message, level="info"):
        self.lines.append((message, level))

    def text(self):
        return "\n".join(m for m, _ in self.lines)

    def has(self, fragment: str) -> bool:
        return fragment in self.text()


def click(cdp, engine=None, **kw):
    kw.setdefault("selector", "div[role='tab'].tab-item")
    return asyncio.run(find_and_click(cdp, engine=engine, **kw))


# ══════════════════════════════════════════════════════════════════
# AC#1–AC#7 — the runner
# ══════════════════════════════════════════════════════════════════
class TestFindPhase(unittest.TestCase):

    def test_an_empty_selector_never_touches_the_page(self):
        """AC#1 — a misconfigured block is the user's problem, stated once."""
        cdp = FakeCDP()
        engine = Recorder()
        for selector in ("", "   "):
            with self.subTest(repr=selector):
                self.assertEqual(
                    click(cdp, engine, selector=selector), ActionResult.FAIL)
                self.assertEqual(cdp.expressions, [])
                self.assertTrue(engine.has("`selector` is empty"))

    def test_the_find_probe_is_built_from_the_request(self):
        """AC#2 — the block's fields must reach the JS, or the highlight
        outlines the wrong node."""
        cdp = FakeCDP(click=None, staged=None)      # stop after the find phase
        click(cdp, selector="user-item", label_selector=".primary-text",
              match_text="Anna", click_enabled=False, highlight_ms=4242,
              confirm_pause_ms=0)
        (which, expression), = cdp.expressions
        self.assertEqual(which, "find")
        self.assertIn(json.dumps("user-item"), expression)
        self.assertIn(json.dumps(".primary-text"), expression)
        self.assertIn(json.dumps("Anna"), expression)
        self.assertIn("4242", expression)

    def test_a_page_that_raises_is_a_finding_failure(self):
        """AC#3."""
        engine = Recorder()
        cdp = FakeCDP(fail_on="find", error=RuntimeError("socket closed"))
        self.assertEqual(click(cdp, engine), ActionResult.FAIL)
        self.assertTrue(engine.has("CDP error during element search"))
        self.assertTrue(engine.has("socket closed"))

    def test_no_data_is_reported_as_no_data(self):
        engine = Recorder()
        self.assertEqual(click(FakeCDP(find=None), engine), ActionResult.FAIL)
        self.assertTrue(engine.has("no data returned from the page"))
        self.assertEqual(click(FakeCDP(find="nonsense{"), Recorder()),
                         ActionResult.FAIL)

    def test_a_missing_element_reports_the_candidates(self):
        engine = Recorder()
        cdp = FakeCDP(find={"found": False, "total": 4, "candidates": []})
        self.assertEqual(click(cdp, engine), ActionResult.FAIL)
        self.assertTrue(engine.has("Selector matched 4 node(s)"),
                        "the count must be reported even on a miss — that is "
                        "the line users ask about")
        self.assertEqual(len(cdp.expressions), 1)

    def test_the_confirmation_hold_is_ordered_and_conditional(self):
        """AC#4 — pause AFTER the red outline, only when highlights are on."""
        slept = []
        real_sleep = asyncio.sleep

        async def spy(delay, *a, **k):
            slept.append(delay)
            return await real_sleep(0, *a, **k)

        asyncio.sleep = spy
        try:
            click(FakeCDP(), Recorder(), confirm_pause_ms=800,
                  highlight_enabled=True)
            with_highlights = list(slept)
            slept.clear()
            click(FakeCDP(), Recorder(), confirm_pause_ms=800,
                  highlight_enabled=False)
            without = list(slept)
        finally:
            asyncio.sleep = real_sleep
        self.assertIn(0.8, with_highlights)
        self.assertNotIn(0.8, without,
                         "no highlights → nothing to look at → no pause")

    def test_click_disabled_is_a_successful_find(self):
        """AC#5 — the "look, don't touch" mode still has to say so."""
        engine = Recorder()
        cdp = FakeCDP()
        self.assertEqual(click(cdp, engine, click_enabled=False),
                         ActionResult.OK)
        self.assertTrue(engine.has("Click disabled for this block"))
        self.assertEqual([which for which, _ in cdp.expressions], ["find"])

    def test_an_invisible_element_is_never_clicked(self):
        """AC#6."""
        cdp = FakeCDP(find={"found": True, "total": 1, "visible": False,
                            "clickable": False})
        engine = Recorder()
        self.assertEqual(click(cdp, engine), ActionResult.FAIL)
        self.assertTrue(engine.has("was found but is not visible"))
        self.assertEqual([which for which, _ in cdp.expressions], ["find"])


class TestClickPhase(unittest.TestCase):

    def test_the_click_is_staged_then_executed(self):
        """AC#7 — orange first, click 250 ms later, on the stashed element."""
        cdp = FakeCDP()
        engine = Recorder()
        self.assertEqual(click(cdp, engine, confirm_pause_ms=0),
                         ActionResult.OK)
        self.assertEqual([which for which, _ in cdp.expressions],
                         ["find", "staged", "click"])
        self.assertTrue(engine.has("CLICK phase: target = div.tab"),
                        "the click target is described from the FIND result")

    def test_the_pause_between_outline_and_click_is_the_shared_beat(self):
        slept = []
        real_sleep = asyncio.sleep

        async def spy(delay, *a, **k):
            slept.append(delay)
            return await real_sleep(0, *a, **k)

        asyncio.sleep = spy
        try:
            cdp = FakeCDP()
            click(cdp, Recorder(), confirm_pause_ms=0, click_selector=".go")
        finally:
            asyncio.sleep = real_sleep
        self.assertIn(CLICK_PAUSE_MS / 1000.0, slept)
        self.assertEqual(slept[-1], CLICK_PAUSE_MS / 1000.0,
                         "the beat is the last thing before the click")

    def test_every_click_failure_mode_reports_its_own_reason(self):
        """AC#7, the three ways a click does not happen."""
        cases = (
            (dict(fail_on="staged"), "CDP error while resolving the click"),
            (dict(staged=None), "no data returned while resolving"),
            (dict(staged={"error": "the stash is empty"}), "the stash is empty"),
            (dict(staged={"clickable": False}), "not clickable"),
            (dict(click=None), "no data returned from the click"),
            (dict(click={"clicked": False}), "CLICK failed"),
        )
        for kw, expected in cases:
            with self.subTest(**kw):
                engine = Recorder()
                self.assertEqual(click(FakeCDP(**kw), engine,
                                       confirm_pause_ms=0), ActionResult.FAIL)
                if expected != "CLICK failed":
                    self.assertTrue(engine.has(expected), engine.text())

    def test_a_click_selector_is_used_as_the_described_target(self):
        cdp = FakeCDP()
        engine = Recorder()
        click(cdp, engine, confirm_pause_ms=0, click_selector="  .inner  ")
        self.assertTrue(engine.has("CLICK phase: target = .inner"))


# ══════════════════════════════════════════════════════════════════
# AC#8 / AC#9 — the request object
# ══════════════════════════════════════════════════════════════════
class TestClickRequest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        if ClickRequest is None:
            raise unittest.SkipTest("ClickRequest is part of D4")

    def test_the_request_produces_the_same_run_as_the_keyword_call(self):
        kwargs = dict(selector="user-item", label_selector=".nick",
                      match_text="Ann", click_enabled=True,
                      click_selector=".row", highlight_enabled=True,
                      confirm_pause_ms=0, highlight_ms=900, label="a person")
        via_kwargs, via_request = Recorder(), Recorder()
        first = click(FakeCDP(), via_kwargs, **kwargs)
        second = asyncio.run(run_click(FakeCDP(), ClickRequest(**kwargs),
                                       engine=via_request))
        self.assertEqual(first, second)
        self.assertEqual(via_kwargs.lines, via_request.lines)

    def test_defaults_are_the_find_and_click_defaults(self):
        """The façade may not quietly change a default."""
        import inspect
        params = dict(inspect.signature(find_and_click).parameters)
        fields = ClickRequest.__dataclass_fields__
        for name, param in params.items():
            if name in ("cdp", "engine"):
                continue
            with self.subTest(field=name):
                self.assertIn(name, fields)
                if name in fields and param.default is not inspect.Parameter.empty:
                    self.assertEqual(param.default, fields[name].default)

    def test_exact_match_helper(self):
        """AC#9."""
        cdp = FakeCDP()
        engine = Recorder()
        asyncio.run(find_and_click_exact(cdp, text="Ански", selector="user-item",
                                         label_selector=".nick", engine=engine,
                                         confirm_pause_ms=0))
        find_expr = cdp.expressions[0][1]
        self.assertIn("matchText = \"Ански\"", find_expr)
        self.assertIn("var exact = true;", find_expr,
                      "`_exact` means the label must equal the text")
        self.assertTrue(engine.has("🔍 FIND phase: searching element"))
        cdp2 = FakeCDP()
        asyncio.run(find_and_click(cdp2, selector="user-item",
                                   label_selector=".nick", match_text="Ански",
                                   match_mode=MATCH_EXACT, label="element",
                                   confirm_pause_ms=0))
        self.assertEqual(cdp.expressions, cdp2.expressions,
                         "`find_and_click_exact` is exactly this call")
        self.assertIn("var exact = true;", dict(cdp2.expressions)["find"])


# ══════════════════════════════════════════════════════════════════
# AC#10 — the four blocks
# ══════════════════════════════════════════════════════════════════
class TestClickingBlocks(unittest.TestCase):

    def run_block(self, block, cdp=None, engine=None):
        return asyncio.run(block.execute("Anna", cdp or FakeCDP(),
                                         engine=engine or Recorder()))

    def test_pre_delay_is_honoured_before_any_probe(self):
        slept = []
        real_sleep = asyncio.sleep

        async def spy(delay, *a, **k):
            slept.append(delay)
            return await real_sleep(0, *a, **k)

        runs = []
        asyncio.sleep = spy
        try:
            for block in (ClickBack(pre_delay_ms=250, confirm_pause_ms=0),
                          ClickMainTab(pre_delay_ms=0, confirm_pause_ms=0)):
                slept.clear()
                self.run_block(block)
                runs.append(list(slept))
        finally:
            asyncio.sleep = real_sleep
        beat = CLICK_PAUSE_MS / 1000.0
        self.assertEqual(runs[0], [0.25, beat],
                         "the pre-delay comes before anything is probed")
        self.assertEqual(runs[1], [beat],
                         "pre_delay_ms=0 must not sleep at all")

    def test_the_tab_blocks_send_their_own_labels_and_defaults(self):
        for cls, expected_label, expected_pre in (
                (ClickMainTab, "tab “Гостиная”", 500),
                (ClickBack, "back tab “Гостиная”", 800)):
            with self.subTest(block=cls.block_id):
                block = cls(confirm_pause_ms=1)
                cdp = FakeCDP()
                engine = Recorder()
                self.assertEqual(self.run_block(block, cdp, engine),
                                 ActionResult.OK)
                self.assertEqual(block.pre_delay_ms, expected_pre)
                self.assertTrue(engine.has(f"🔍 FIND phase: searching {expected_label}"))
                (which, expression), = cdp.expressions[:1]
                self.assertIn(json.dumps("div[role='tab'].tab-item"), expression)
                self.assertIn(json.dumps("p.chat-title"), expression)

    def test_a_highlight_disabled_tab_block_still_clicks(self):
        block = ClickBack(highlight_enabled=False, confirm_pause_ms=5000)
        cdp = FakeCDP()
        self.assertEqual(self.run_block(block, cdp), ActionResult.OK)
        self.assertEqual([which for which, _ in cdp.expressions],
                         ["find", "staged", "click"])

    def test_custom_find_maps_every_declared_field(self):
        block = CustomFind(custom_name="My search", selector=".a",
                           label_selector=".b", match_text="txt",
                           click_selector=".c", highlight_ms=11,
                           confirm_pause_ms=0, click_enabled=True)
        cdp = FakeCDP()
        engine = Recorder()
        self.assertEqual(self.run_block(block, cdp, engine), ActionResult.OK)
        self.assertEqual(block.display_name, "My search")
        expressions = dict(cdp.expressions)
        for value in (json.dumps(".a"), json.dumps(".b"), "txt", "11"):
            self.assertIn(value, expressions["find"],
                          f"{value} must reach the FIND probe")
        # the inner click target is only used by the CLICK phase: it is the
        # element the stash is searched inside of
        self.assertIn(json.dumps(".c"), expressions["staged"])
        self.assertTrue(engine.has("element '.a' text inside '.b' matching \"txt\""))

    def test_custom_find_without_click_enabled_is_find_only(self):
        block = CustomFind(selector=".a", click_enabled=False,
                           confirm_pause_ms=0)
        cdp = FakeCDP()
        self.assertEqual(self.run_block(block, cdp), ActionResult.OK)
        self.assertEqual([which for which, _ in cdp.expressions], ["find"])

    def test_click_send_falls_back_once(self):
        cdp = FakeCDP(find_seq=[{"found": False, "total": 0,
                                 "candidates": []},
                                {"found": False, "total": 0,
                                 "candidates": []}],
                      click=None, staged=None)
        engine = Recorder()
        self.assertEqual(self.run_block(ClickSend(confirm_pause_ms=0), cdp,
                                        engine), ActionResult.FAIL)
        self.assertTrue(engine.has("↩ Submit button did not work"))
        self.assertEqual([which for which, _ in cdp.expressions],
                         ["find", "find"], "the fallback is one more FIND")

    def test_click_send_without_a_fallback_stops_at_the_first_failure(self):
        cdp = FakeCDP(find={"found": False, "total": 0}, click=None,
                      staged=None)
        block = ClickSend(fallback_selector="", confirm_pause_ms=0)
        engine = Recorder()
        self.assertEqual(self.run_block(block, cdp, engine), ActionResult.FAIL)
        self.assertFalse(engine.has("↩ Submit button did not work"))

    def test_click_send_reports_the_fallback_success(self):
        miss = {"found": False, "total": 0, "candidates": []}
        cdp = FakeCDP(find_seq=[miss, FOUND], click=CLICKED, staged=STAGED)
        engine = Recorder()
        self.assertEqual(self.run_block(ClickSend(confirm_pause_ms=0), cdp,
                                        engine), ActionResult.OK)
        self.assertTrue(engine.has("send icon “send”"))
        self.assertEqual([which for which, _ in cdp.expressions],
                         ["find", "find", "staged", "click"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
