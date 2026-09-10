"""`ClickUser`'s half of STEP 4: which nick, and did a tab actually appear?

`tests/test_click_user_memory.py` and `tests/test_click_user_order.py` cover the
queue/memory selection and the ordering column; this file covers the rest of
`execute()` — the tab-verification ladder, which is the only thing that turns a
click nobody saw into a failure. The wording is pinned because the run console is
the only place a user learns why a step stopped.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from actions.base_action import ActionResult
from actions.click_user import ClickUser, build_tab_count_js

TABS_MARK = "count: tabs.length"
#: the FIND probe is the only one without a `doClick` switch
FOUND = {"found": True, "total": 1, "index": 0, "visible": True,
         "clickable": True, "text": "Nick name", "target_desc": "user-item"}
STAGED = {"ok": True, "clickable": True, "target_desc": ".user-container"}
CLICKED = {"ok": True, "clicked": True, "target_desc": ".user-container"}


class FakeCDP:
    """Answers the three visual probes plus ClickUser's own tab probe."""

    def __init__(self, *, before=1, after=2, titles=("other", "Nick name"),
                 tabs_unreadable=False, find=FOUND, click=CLICKED):
        self.find = find if find is not None else dict(FOUND)
        self.find["found"] = find is not None
        self.staged, self.click = STAGED, click
        self.tabs = {1: {"count": before, "titles": list(titles[:before])},
                     2: {"count": after, "titles": list(titles)}}
        self.tabs_unreadable = tabs_unreadable
        self.evals, self.tab_reads = [], 0

    def _which(self, js: str) -> str:
        if TABS_MARK in js:
            return "tabs"
        if "var doClick = true;" in js:
            return "click"
        if "var doClick = false;" in js:
            return "staged"
        return "find"

    async def evaluate(self, js):
        which = self._which(js)
        self.evals.append(js)
        if which == "tabs":
            if self.tabs_unreadable:
                return "not json at all"
            self.tab_reads += 1
            # first read = the snapshot before the click, second = after
            return json.dumps(self.tabs[1 if self.tab_reads == 1 else 2])
        value = {"find": self.find, "staged": self.staged,
                 "click": self.click}[which]
        return json.dumps(value)



class FakeEngine:
    """Stands in for the run context: `report`, {{nick}} memory, `note_selected`."""

    def __init__(self, selected_nick=None):
        self.lines = []
        self.selected_nick = selected_nick
        self.noted = []
        self.is_stopping = None

    def report(self, message, level="info"):
        self.lines.append(message)

    def note_selected(self, nick):
        self.noted.append(nick)


def run(block, cdp, engine, nick="Nick name"):
    return asyncio.run(block.execute(nick, cdp, engine))


def make(**kw):
    kw.setdefault("tab_pause_ms", 0)
    kw.setdefault("confirm_pause_ms", 0)
    kw.setdefault("pre_delay_ms", 0)
    return ClickUser(**kw)


# ── which person gets clicked ────────────────────────────────────────
def test_queue_mode_clicks_the_queued_user():
    cdp, block = FakeCDP(), make()
    assert run(block, cdp, FakeEngine(selected_nick="Someone Else"),
               nick="Nick name") == ActionResult.OK
    assert any('"Nick name"' in js for js in cdp.evals)


def test_memory_mode_uses_the_saved_nick():
    cdp, block = FakeCDP(), make(use_person_from_memory=True)
    assert run(block, cdp, FakeEngine(selected_nick="Nick name"),
               nick="ignored") == ActionResult.OK
    assert any('"Nick name"' in js for js in cdp.evals)
    assert not any('"ignored"' in js for js in cdp.evals)


def test_memory_mode_without_a_saved_nick_refuses_and_touches_nothing():
    cdp, engine = FakeCDP(), FakeEngine(selected_nick=None)
    block = make(use_person_from_memory=True)
    assert run(block, cdp, engine) == ActionResult.FAIL
    assert cdp.evals == []
    assert "❌ Use Person from Memory: no person is saved in memory this run — " \
           "add a Pick Person block before it (or let an earlier Click User " \
           "click someone) so {{nick}} has a value" in engine.lines
    assert engine.noted == []


def test_memory_mode_refuses_even_without_an_engine():
    cdp = FakeCDP()
    assert run(make(use_person_from_memory=True), cdp, None) == \
        ActionResult.FAIL
    assert cdp.evals == []


# ── the tab probe around the click ───────────────────────────────────
def test_before_snapshot_is_reported_and_uses_the_configured_selectors():
    cdp, engine = FakeCDP(), FakeEngine()
    run(make(tab_selector="div.tabs", tab_title_selector="p.t"), cdp, engine)
    assert "🗂 1 chat tab(s) open before the click" in engine.lines
    tabs_js = [js for js in cdp.evals if TABS_MARK in js][0]
    assert tabs_js == build_tab_count_js("div.tabs", "p.t")
    assert '"div.tabs"' in tabs_js and '"p.t"' in tabs_js


def test_verification_off_skips_both_tab_probes_and_the_wait():
    cdp, engine = FakeCDP(), FakeEngine()
    block = make(verify_new_tab=False, tab_pause_ms=5000)
    assert run(block, cdp, engine) == ActionResult.OK
    assert [js for js in cdp.evals if TABS_MARK in js] == []
    assert not any("chat tab(s) open before" in line for line in engine.lines)
    assert not any("Waiting" in line for line in engine.lines)


def test_click_failure_never_reaches_the_tab_check():
    cdp, engine = FakeCDP(click={"ok": True, "clicked": False,
                                 "target_desc": ".user-container"}), FakeEngine()
    assert run(make(), cdp, engine) == ActionResult.FAIL
    assert [js for js in cdp.evals if TABS_MARK in js] == [cdp.evals[0]]
    assert cdp.tab_reads == 1
    assert engine.noted == []
    assert not any("New tab" in line or "Waiting" in line
                   for line in engine.lines)


# ── the verdict on the new tab ───────────────────────────────────────
def test_more_tabs_after_the_click_is_a_success():
    cdp, engine = FakeCDP(before=1, after=2), FakeEngine()
    assert run(make(), cdp, engine) == ActionResult.OK
    assert '✅ New tab confirmed for person “Nick name” (tab count 1 → 2)' \
        in engine.lines
    assert engine.noted == ["Nick name"]


def test_same_count_but_a_matching_title_still_counts():
    cdp, engine = FakeCDP(before=2, after=2,
                          titles=("first", "Nick name")), FakeEngine()
    assert run(make(), cdp, engine) == ActionResult.OK
    assert '✅ New tab confirmed for person “Nick name” (a tab titled ' \
           '“Nick name” is open)' in engine.lines


def test_no_change_at_all_fails_and_lists_what_is_open():
    cdp, engine = FakeCDP(before=2, after=2, titles=("a", "b")), FakeEngine()
    assert run(make(), cdp, engine) == ActionResult.FAIL
    # the click itself succeeded, so the nick stays remembered even though no
    # tab appeared — that is the shipped order and presets rely on it
    assert engine.noted == ["Nick name"]
    assert '❌ No new tab appeared for person “Nick name” — still 2 tab(s): ' \
           '“a”, “b”' in engine.lines


def test_at_most_five_titles_are_listed_and_each_is_shortened():
    long = "x" * 40
    cdp, engine = FakeCDP(before=9, after=9,
                          titles=(long,) * 9), FakeEngine()
    run(make(), cdp, engine)
    line = [l for l in engine.lines if "No new tab appeared" in l][0]
    assert line.count("“") == 6                   # the label plus 5 titles
    assert "x" * 24 in line and "x" * 25 not in line


def test_unreadable_tab_list_trusts_the_click():
    cdp, engine = FakeCDP(tabs_unreadable=True), FakeEngine()
    assert run(make(), cdp, engine) == ActionResult.OK
    assert "⚠ Could not read the tab list to confirm the new tab — assuming " \
           "the click worked" in engine.lines
    assert engine.noted == ["Nick name"]


def test_the_wait_happens_before_the_after_probe_and_reports_itself():
    """The block waits `tab_pause_ms` and says so, before reading the tabs again."""
    cdp, engine = FakeCDP(), FakeEngine()
    slept = []

    async def fake_sleep(seconds):
        slept.append(seconds)

    orig, asyncio.sleep = asyncio.sleep, fake_sleep
    try:
        run(make(tab_pause_ms=1500, verify_new_tab=True), cdp, engine)
    finally:
        asyncio.sleep = orig
    assert slept[-1] == 1.5                       # after the runner's own beat
    assert "⏸ Waiting 1500 ms for the new tab…" in engine.lines
    assert cdp.tab_reads == 2


def test_no_wait_line_and_no_sleep_when_the_pause_is_zero():
    cdp, engine = FakeCDP(), FakeEngine()
    slept = []

    async def fake_sleep(seconds):
        slept.append(seconds)

    orig, asyncio.sleep = asyncio.sleep, fake_sleep
    try:
        run(make(tab_pause_ms=0), cdp, engine)
    finally:
        asyncio.sleep = orig
    assert 0.0 not in slept
    assert not any("Waiting" in line for line in engine.lines)


@pytest.mark.parametrize("raw,expected", [
    (None, None), ("", None), ("{}", {}), ('{"count": 2, "titles": ["a"]}',
                                            {"count": 2, "titles": ["a"]}),
    ("[1,2]", None), ("nonsense", None),
])
def test_read_tabs_only_accepts_a_json_object(raw, expected):
    cdp = FakeCDP()
    cdp.tabs_unreadable = True
    monkey = pytest.MonkeyPatch()
    monkey.setattr(cdp, "evaluate", lambda js, _r=raw: asyncio.sleep(0, _r))
    got = asyncio.run(ClickUser()._read_tabs(cdp))
    monkey.undo()
    assert got == expected
