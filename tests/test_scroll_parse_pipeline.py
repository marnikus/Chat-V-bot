"""Tests for the redesigned Scroll & Parse pipeline (STEPS 1-3) and STEP 4.

The fake CDP client below behaves like the real page: the users list is
lazy-loaded (new rows only appear after a number of polls) and the viewport
reports real scroll geometry, so "still loading" vs "end of list" is exercised
for real rather than mocked away.

Run with:  python3 tests/test_scroll_parse_pipeline.py
"""

import asyncio
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from actions.base_action import ActionResult  # noqa: E402
from actions.click_user import ClickUser, build_tab_count_js  # noqa: E402
from actions.scroll_parse import ScrollParse  # noqa: E402
from backend.person_filter import (  # noqa: E402
    ANY,
    NO,
    YES,
    PersonFilter,
    normalize,
    sort_people,
)
from backend.scroll_parser import ScrollParser  # noqa: E402


def person(nick, female=True, registered=False, guest=True, anonymous=False):
    return {"nick": nick, "female": female, "male": not female,
            "guest": guest, "registered": registered, "anonymous": anonymous}


class FakeCDP:
    """A users list that reveals rows gradually, like a lazy-loaded viewport.

    :param pages: list of lists — each scroll reveals the next page, but only
        after ``load_delay`` extract calls (simulating the network round trip).
    """

    def __init__(self, pages, load_delay=0, viewport=True, page_height=100):
        self.pages = pages
        self.load_delay = load_delay
        self.viewport = viewport
        self.page_height = page_height
        self.revealed = 1              # first page is rendered immediately
        self.scrolls = 0
        self._pending = 0
        self.scroll_top = 0

    @property
    def _visible(self):
        out = []
        for pg in self.pages[:self.revealed]:
            out.extend(pg)
        return out

    async def evaluate(self, expression: str):
        if "user-item" in expression and "scrollTop" in expression:
            if self._pending > 0:
                self._pending -= 1
                if self._pending == 0 and self.revealed < len(self.pages):
                    self.revealed += 1
            users = self._visible
            total_h = self.page_height * len(self.pages)
            client = self.page_height
            return json.dumps({
                "users": users, "count": len(users), "viewport": self.viewport,
                "scrollTop": self.scroll_top, "scrollHeight": total_h,
                "clientHeight": client,
                "atBottom": self.scroll_top + client >= total_h - 4,
            })
        return None

    async def get_element_rect(self, selector):
        if not self.viewport:
            return None
        return {"x": 0, "y": 0, "width": 200, "height": self.page_height}

    async def mouse_wheel(self, dx, dy, x, y):
        self.scrolls += 1
        max_top = max(0, self.page_height * (len(self.pages) - 1))
        self.scroll_top = min(max_top, self.scroll_top + self.page_height)
        self._pending = self.load_delay if self.revealed < len(self.pages) else 0
        if self.load_delay == 0 and self.revealed < len(self.pages):
            self.revealed += 1


def run(coro):
    return asyncio.run(coro)


def collect(cdp, **kw):
    kw.setdefault("pause_ms", 0)
    kw.setdefault("poll_ms", 1)
    kw.setdefault("load_timeout_ms", 60)
    parser = ScrollParser(cdp=cdp, **kw)
    return run(parser.collect(min_new_users=kw.pop("min_new", 0)))


# ── STEP 1 ───────────────────────────────────────────────────────
class TestStep1ScrollAndDetect(unittest.TestCase):
    def test_collects_across_pages_until_the_end(self):
        cdp = FakeCDP([[person("Anna")], [person("Bella")], [person("Cara")]])
        res = collect(cdp)
        self.assertEqual([p.nick for p in res.all_people],
                         ["Anna", "Bella", "Cara"])
        self.assertTrue(res.reached_end)

    def test_waits_for_lazy_loaded_people_instead_of_stopping(self):
        """A slow page must not be mistaken for the end of the list."""
        cdp = FakeCDP([[person("Anna")], [person("Bella")]], load_delay=3)
        res = collect(cdp)
        self.assertEqual([p.nick for p in res.all_people], ["Anna", "Bella"],
                         "the slow second page must still be collected")

    def test_end_of_list_detected_by_scroll_geometry(self):
        cdp = FakeCDP([[person("Anna")], [person("Bella")]])
        res = collect(cdp)
        self.assertTrue(res.reached_end)
        # must not burn the whole safety cap once the bottom is reached
        self.assertLess(res.scrolls, 10)

    def test_max_scrolls_caps_an_endless_list(self):
        pages = [[person(f"P{i}")] for i in range(100)]
        cdp = FakeCDP(pages, page_height=10)
        res = collect(cdp, max_scrolls=4)
        self.assertEqual(res.scrolls, 4)

    def test_missing_viewport_is_reported_but_still_parses(self):
        cdp = FakeCDP([[person("Anna")]], viewport=False)
        msgs = []
        parser = ScrollParser(cdp=cdp, pause_ms=0, poll_ms=1,
                              load_timeout_ms=20,
                              log_cb=lambda m, l: msgs.append((m, l)))
        res = run(parser.collect())
        self.assertEqual([p.nick for p in res.all_people], ["Anna"])
        self.assertTrue(any(l == "warn" for _, l in msgs))

    def test_no_data_from_page_is_an_error(self):
        class Dead:
            async def evaluate(self, e): return None
            async def get_element_rect(self, s): return None
            async def mouse_wheel(self, *a): pass
        msgs = []
        parser = ScrollParser(cdp=Dead(), log_cb=lambda m, l: msgs.append((m, l)))
        res = run(parser.collect())
        self.assertEqual(res.all_people, [])
        self.assertTrue(any(l == "error" for _, l in msgs))


# ── STEP 2 ───────────────────────────────────────────────────────
class TestStep2Filter(unittest.TestCase):
    def test_default_profile_from_the_request(self):
        """female + not registered + guest + not anonymous."""
        f = PersonFilter()
        self.assertTrue(f(person("ok")))
        self.assertFalse(f(person("male", female=False)))
        self.assertFalse(f(person("reg", registered=True)))
        self.assertFalse(f(person("noguest", guest=False)))
        self.assertFalse(f(person("anon", anonymous=True)))

    def test_any_means_dont_care(self):
        f = PersonFilter(female=ANY, registered=ANY, guest=ANY, anonymous=ANY)
        self.assertTrue(f(person("x", female=False, registered=True,
                                 guest=False, anonymous=True)))
        self.assertTrue(f.is_empty)

    def test_rejection_reasons_are_explained(self):
        f = PersonFilter()
        self.assertEqual(f.check(person("m", female=False)).reason, "not female")
        self.assertEqual(f.check(person("r", registered=True)).reason,
                         "registered")

    def test_tristate_normalisation_handles_legacy_values(self):
        self.assertEqual(normalize(True), YES)
        self.assertEqual(normalize(False), ANY)
        self.assertEqual(normalize("no"), NO)
        self.assertEqual(normalize("YES"), YES)
        # legacy CriteriaEngine wording maps onto the tri-state
        self.assertEqual(normalize("MUST_NOT"), NO)
        self.assertEqual(normalize("must"), YES)
        # anything unrecognised falls back to the supplied default
        self.assertEqual(normalize("wat", YES), YES)
        self.assertEqual(normalize("", YES), YES)
        self.assertEqual(normalize(None), ANY)

    def test_panel_criteria_are_anded_in(self):
        class RejectAll:
            def evaluate_user(self, u): return False
        f = PersonFilter(female=ANY, registered=ANY, guest=ANY, anonymous=ANY,
                         panel_criteria=RejectAll())
        verdict = f.check(person("x"))
        self.assertFalse(verdict.passed)
        self.assertIn("Filter panel", verdict.reason)

    def test_only_matching_people_are_collected(self):
        cdp = FakeCDP([[person("Anna"),
                        person("Boris", female=False),
                        person("Carla", registered=True)]])
        parser = ScrollParser(cdp=cdp, pause_ms=0, poll_ms=1,
                              load_timeout_ms=20, person_filter=PersonFilter())
        res = run(parser.collect())
        self.assertEqual([p.nick for p in res.all_people],
                         ["Anna", "Boris", "Carla"])
        self.assertEqual([p.nick for p in res.collected], ["Anna"])
        self.assertEqual(res.rejected.get("not female"), 1)
        self.assertEqual(res.rejected.get("registered"), 1)

    def test_duplicates_are_skipped_across_scrolls(self):
        repeated = [person("Anna")]
        cdp = FakeCDP([repeated, repeated + [person("Bella")], repeated])
        res = collect(cdp, person_filter=PersonFilter())
        self.assertEqual([p.nick for p in res.collected], ["Anna", "Bella"])


# ── STEP 3 ───────────────────────────────────────────────────────
class TestStep3Queue(unittest.TestCase):
    def test_unmessaged_first_then_alphabetical(self):
        people = [
            {"nick": "Zoe", "messaged": False},
            {"nick": "adam", "messaged": True},
            {"nick": "Bella", "messaged": False},
            {"nick": "Yuri", "messaged": True},
        ]
        self.assertEqual([p["nick"] for p in sort_people(people)],
                         ["Bella", "Zoe", "adam", "Yuri"])

    def test_sorting_is_case_insensitive_and_handles_cyrillic(self):
        people = [{"nick": n, "messaged": False}
                  for n in ["бета", "Альфа", "apple", "Banana"]]
        self.assertEqual([p["nick"] for p in sort_people(people)],
                         ["apple", "Banana", "Альфа", "бета"])

    def test_finishes_early_once_enough_new_people_found(self):
        pages = [[person(f"P{i}")] for i in range(20)]
        cdp = FakeCDP(pages, page_height=10)
        parser = ScrollParser(cdp=cdp, pause_ms=0, poll_ms=1,
                              load_timeout_ms=20, person_filter=PersonFilter())
        res = run(parser.collect(min_new_users=2))
        self.assertTrue(res.stopped_early)
        self.assertGreaterEqual(len(res.new_unmessaged), 2)
        self.assertLess(res.scrolls, 20, "must not walk the whole list")

    def test_already_messaged_people_are_marked_and_sink(self):
        cdp = FakeCDP([[person("Anna"), person("Bella")]])
        parser = ScrollParser(cdp=cdp, pause_ms=0, poll_ms=1,
                              load_timeout_ms=20, person_filter=PersonFilter())
        res = run(parser.collect(known_messaged={"Anna"}))
        self.assertEqual([p.nick for p in res.collected], ["Bella", "Anna"])
        self.assertEqual([p.nick for p in res.new_unmessaged], ["Bella"])

    def test_min_new_users_zero_scrolls_to_the_end(self):
        pages = [[person(f"P{i}")] for i in range(5)]
        cdp = FakeCDP(pages, page_height=10)
        parser = ScrollParser(cdp=cdp, pause_ms=0, poll_ms=1,
                              load_timeout_ms=20, person_filter=PersonFilter())
        res = run(parser.collect(min_new_users=0))
        self.assertFalse(res.stopped_early)
        self.assertEqual(len(res.collected), 5)


# ── the block itself ─────────────────────────────────────────────
class TestScrollParseBlock(unittest.TestCase):
    def test_block_runs_the_pipeline_and_reports(self):
        cdp = FakeCDP([[person("Anna"), person("Boris", female=False)]])
        block = ScrollParse(scroll_pause_ms=0, load_timeout_ms=20,
                            min_new_users=0, pre_delay_ms=0)
        msgs = []

        class Eng:
            criteria = None
            def report(self, m, l="info"): msgs.append((m, l))

        result = run(block.run_pipeline(cdp, Eng()))
        self.assertEqual([p.nick for p in result.collected], ["Anna"])
        text = " ".join(m for m, _ in msgs)
        self.assertIn("STEP 1", text)
        self.assertIn("STEP 3", text)

    def test_filters_round_trip_through_presets(self):
        block = ScrollParse(filter_female=NO, filter_registered=YES,
                            filter_guest=ANY, filter_anonymous=YES,
                            min_new_users=5, scroll_only=True)
        d = block.to_dict()
        for key in ("filter_female", "filter_registered", "filter_guest",
                    "filter_anonymous", "scroll_only", "min_new_users",
                    "viewport_selector", "load_timeout_ms"):
            self.assertIn(key, d, f"{key} must be preset-storable")
            self.assertIn(key, block.config_schema())
        clone = ScrollParse(**{k: v for k, v in d.items() if k != "block_id"})
        self.assertEqual(clone.filter_female, NO)
        self.assertEqual(clone.filter_registered, YES)
        self.assertEqual(clone.min_new_users, 5)
        self.assertTrue(clone.scroll_only)

    def test_legacy_preset_without_new_keys_still_loads(self):
        block = ScrollParse(**{"max_scrolls": 20, "scroll_pause_ms": 500,
                               "pre_delay_ms": 300})
        self.assertEqual(block.filter_female, YES)
        self.assertEqual(block.max_scrolls, 20)

    def test_panel_criteria_are_never_applied(self):
        """The "Also apply Filter panel criteria" checkbox was removed: the
        four tri-state selects are the only source of truth now."""
        block = ScrollParse()
        self.assertIsNone(block.build_filter("SOME_ENGINE").panel_criteria)
        self.assertFalse(hasattr(block, "use_panel_filters"))


# ── STEP 4 ───────────────────────────────────────────────────────
class TabCDP:
    """Fake page for the Click-User step: clicking a person opens a tab."""

    def __init__(self, nicks, opens_tab=True, tabs=1):
        self.nicks = nicks
        self.opens_tab = opens_tab
        self.tabs = tabs
        self.clicked = []
        self.opened_for = None

    async def evaluate(self, expression: str):
        if "role='tab'" in expression or "chat-title" in expression:
            titles = ["Гостиная"] + ([self.opened_for] if self.opened_for else [])
            return json.dumps({"count": self.tabs, "titles": titles})
        if "'find'" in expression or "phase = 'find'" in expression:
            match = None
            for n in self.nicks:
                if f'"{n}"' in expression or n in expression:
                    match = n
                    break
            found = match is not None
            return json.dumps({
                "phase": "find", "total": len(self.nicks), "found": found,
                "index": 0 if found else -1, "text": match or "",
                "visible": found, "disabled": False, "clickable": found,
                "clicked": False, "target_desc": "user-item",
                "highlighted": found, "candidates": [], "error": None})
        if "phase = 'click'" in expression or "'click'" in expression:
            do_click = "doClick = true" in expression
            if do_click:
                self.clicked.append("user-container")
                if self.opens_tab:
                    self.tabs += 1
                    self.opened_for = self.nicks[0] if self.nicks else None
            return json.dumps({
                "phase": "click", "found": True, "visible": True,
                "disabled": False, "clickable": True, "clicked": do_click,
                "target_desc": ".user-container", "text": "",
                "highlighted": not do_click, "error": None})
        return None


class TestStep4ClickPerson(unittest.TestCase):
    def _run(self, cdp, nick="Anna", **kw):
        block = ClickUser(pre_delay_ms=0, confirm_pause_ms=0,
                          tab_pause_ms=0, **kw)
        msgs = []

        class Eng:
            def report(self, m, l="info"): msgs.append((m, l))

        outcome = run(block.execute(nick, cdp, Eng()))
        return outcome, msgs

    def test_click_opens_tab_and_is_confirmed(self):
        cdp = TabCDP(["Anna"])
        outcome, msgs = self._run(cdp)
        self.assertEqual(outcome, ActionResult.OK)
        self.assertEqual(cdp.clicked, ["user-container"])
        text = " ".join(m for m, _ in msgs)
        self.assertIn("New tab confirmed", text)

    def test_draws_red_then_orange_overlays(self):
        """STEP 4 must use the shared visual confirmation module."""
        cdp = TabCDP(["Anna"])
        _, msgs = self._run(cdp)
        text = " ".join(m for m, _ in msgs)
        self.assertIn("FIND phase", text)
        self.assertIn("red outline", text)
        self.assertIn("CLICK phase", text)
        self.assertIn("orange outline", text)

    def test_fails_when_no_tab_appears(self):
        cdp = TabCDP(["Anna"], opens_tab=False)
        outcome, msgs = self._run(cdp)
        self.assertEqual(outcome, ActionResult.FAIL)
        self.assertIn("No new tab", " ".join(m for m, _ in msgs))

    def test_tab_verification_can_be_disabled(self):
        cdp = TabCDP(["Anna"], opens_tab=False)
        outcome, _ = self._run(cdp, verify_new_tab=False)
        self.assertEqual(outcome, ActionResult.OK)

    def test_person_not_found_fails(self):
        cdp = TabCDP([])
        outcome, msgs = self._run(cdp, nick="Ghost")
        self.assertEqual(outcome, ActionResult.FAIL)
        self.assertEqual(cdp.clicked, [])

    def test_uses_exact_nick_matching(self):
        """“Anna” must not select “Annabelle”."""
        from backend.dom_probe import MATCH_EXACT
        import backend.visual_click as vc
        seen = {}
        orig = vc.find_and_click

        async def spy(cdp, **kw):
            seen.update(kw)
            return ActionResult.FAIL
        vc.find_and_click = spy
        try:
            run(ClickUser(pre_delay_ms=0).execute("Anna", TabCDP(["Anna"]), None))
        finally:
            vc.find_and_click = orig
        self.assertEqual(seen.get("match_mode"), MATCH_EXACT)
        self.assertEqual(seen.get("match_text"), "Anna")

    def test_tab_probe_js_is_valid(self):
        js = build_tab_count_js("div[role='tab'].tab-item", "p.chat-title")
        self.assertIn("querySelectorAll", js)
        self.assertIn("chat-title", js)


class TestSharedModuleRule(unittest.TestCase):
    def test_click_blocks_use_the_shared_runner(self):
        """RULE 1: no block may hand-roll a clicking probe."""
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for name in ("custom_find", "click_user", "click_main_tab",
                     "click_back", "click_send"):
            src = open(os.path.join(root, "actions", f"{name}.py"),
                       encoding="utf-8").read()
            self.assertIn("find_and_click", src,
                          f"{name} must use the shared visual runner")
            self.assertNotIn("click=True", src,
                             f"{name} must not build its own clicking probe")

    def test_shim_still_exports_the_runner(self):
        from actions.find_click_runner import find_and_click as shim
        from backend.visual_click import find_and_click as real
        self.assertIs(shim, real)


if __name__ == "__main__":
    unittest.main(verbosity=2)
