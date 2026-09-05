"""Regression tests for the two Scroll & Parse bugs.

BUG A — a person that matched the filter was added silently: no highlight
        overlay and no pause, so the user could not see who was detected.
BUG B — the list only refreshed when the whole scroll cycle finished, because
        ``_refresh_users()`` was called on connect/delete/clear only and the
        engine upserted people after the pipeline returned.

Run with:  python3 tests/test_collect_visual_and_live_refresh.py
"""

import asyncio
import json
import os
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.dom_highlight import COLOR_COLLECT, build_highlight_probe  # noqa: E402
from backend.person_filter import PersonFilter  # noqa: E402
from backend.scroll_parser import ScrollParser  # noqa: E402
from tests.test_scroll_parse_pipeline import FakeCDP, person  # noqa: E402

HARNESS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "js_harness.js")


def run(coro):
    return asyncio.run(coro)


def run_js(exprs, nodes):
    payload = json.dumps({"exprs": exprs, "nodes": nodes})
    proc = subprocess.run(["node", HARNESS], input=payload, capture_output=True,
                          text=True, timeout=30)
    if proc.returncode != 0:
        raise AssertionError(f"harness failed: {proc.stderr}")
    out = json.loads(proc.stdout)
    for r in out["results"]:
        assert "harness_error" not in r, r["harness_error"]
    return out["results"], out["effects"]


def rows(*nicks):
    return [{"tag": "user-item", "className": "",
             "children": [{"tag": "div", "className": "primary-text",
                           "text": n}]} for n in nicks]


class HighlightCDP(FakeCDP):
    """Records every highlight probe issued during collection."""

    def __init__(self, pages, **kw):
        super().__init__(pages, **kw)
        self.highlights = []

    async def evaluate(self, expression: str):
        if "phase = 'highlight'" in expression:
            nick = None
            for pg in self.pages:
                for p in pg:
                    if f'"{p["nick"]}"' in expression:
                        nick = p["nick"]
                        break
            self.highlights.append(nick)
            return json.dumps({"phase": "highlight", "found": True,
                               "highlighted": True, "text": nick or "",
                               "visible": True, "clickable": True,
                               "target_desc": "user-item", "error": None})
        return await super().evaluate(expression)


# ── BUG A: visual confirmation + pause ───────────────────────────
class TestCollectHighlightProbe(unittest.TestCase):
    def test_draws_a_green_outline_on_the_matched_person(self):
        expr = build_highlight_probe("user-item", ".primary-text", "Anna")
        (res,), eff = run_js([expr], rows("Zoe", "Anna", "Mia"))
        self.assertTrue(res["found"])
        self.assertEqual(res["text"], "Anna")
        self.assertTrue(res["highlighted"])
        overlays = eff["overlays"][0]
        self.assertEqual(len(overlays), 1)
        self.assertIn(f"outline:2px solid {COLOR_COLLECT}", overlays[0]["css"])
        self.assertIn("pointer-events:none", overlays[0]["css"])
        self.assertEqual(overlays[0]["caption"], "MATCH")

    def test_highlighting_never_clicks_or_scrolls(self):
        """Scrolling mid-parse would corrupt the parser's position tracking."""
        expr = build_highlight_probe("user-item", ".primary-text", "Anna")
        _, eff = run_js([expr], rows("Anna"))
        self.assertEqual(eff["clicks"], [])
        self.assertEqual(eff["scrolled"], [])

    def test_uses_exact_matching(self):
        expr = build_highlight_probe("user-item", ".primary-text", "Anna")
        (res,), _ = run_js([expr], rows("Annabelle", "Anna"))
        self.assertEqual(res["text"], "Anna")
        self.assertEqual(res["index"], 1)

    def test_missing_person_reports_not_found(self):
        expr = build_highlight_probe("user-item", ".primary-text", "Ghost")
        (res,), eff = run_js([expr], rows("Anna"))
        self.assertFalse(res["found"])
        self.assertEqual(eff["overlays"][0], [])


class TestCollectPauseAndOrder(unittest.TestCase):
    def _collect(self, cdp, **kw):
        kw.setdefault("pause_ms", 0)
        kw.setdefault("poll_ms", 1)
        kw.setdefault("load_timeout_ms", 20)
        kw.setdefault("person_filter", PersonFilter())
        parser = ScrollParser(cdp=cdp, **kw)
        return parser, run(parser.collect())

    def test_each_matching_person_is_highlighted(self):
        cdp = HighlightCDP([[person("Anna"), person("Bella")]])
        _, res = self._collect(cdp)
        self.assertEqual([p.nick for p in res.collected], ["Anna", "Bella"])
        self.assertEqual(cdp.highlights, ["Anna", "Bella"])

    def test_rejected_people_are_not_highlighted(self):
        cdp = HighlightCDP([[person("Anna"), person("Boris", female=False)]])
        _, res = self._collect(cdp)
        self.assertEqual(cdp.highlights, ["Anna"],
                         "only people that pass the filter get an overlay")

    def test_pause_happens_before_the_person_is_added(self):
        """The hold must be visible, i.e. actually delay the collection."""
        cdp = HighlightCDP([[person("Anna"), person("Bella")]])
        order = []
        real_sleep = asyncio.sleep

        async def spy(delay):
            if delay:
                order.append(("sleep", round(delay, 3)))
            await real_sleep(0)

        import backend.scroll_parser as sp
        sp.asyncio.sleep = spy
        try:
            parser = ScrollParser(cdp=cdp, pause_ms=0, poll_ms=1,
                                  load_timeout_ms=20,
                                  person_filter=PersonFilter(),
                                  confirm_pause_ms=250,
                                  on_collect=lambda r, c: order.append(
                                      ("added", r.nick)))
            run(parser.collect())
        finally:
            sp.asyncio.sleep = real_sleep
        # a 250 ms hold must precede each "added" event
        self.assertEqual(order[0], ("sleep", 0.25))
        self.assertEqual(order[1], ("added", "Anna"))
        self.assertIn(("added", "Bella"), order)

    def test_pause_is_configurable_and_can_be_disabled(self):
        cdp = HighlightCDP([[person("Anna")]])
        parser = ScrollParser(cdp=cdp, pause_ms=0, poll_ms=1, load_timeout_ms=20,
                              person_filter=PersonFilter(),
                              highlight_enabled=False)
        res = run(parser.collect())
        self.assertEqual([p.nick for p in res.collected], ["Anna"])
        self.assertEqual(cdp.highlights, [], "highlighting was disabled")

    def test_a_failing_highlight_never_breaks_collection(self):
        class Broken(FakeCDP):
            async def evaluate(self, expression):
                if "phase = 'highlight'" in expression:
                    raise RuntimeError("CDP exploded")
                return await super().evaluate(expression)

        cdp = Broken([[person("Anna")]])
        _, res = self._collect(cdp)
        self.assertEqual([p.nick for p in res.collected], ["Anna"])


# ── BUG B: the list refreshes immediately ────────────────────────
class TestLiveRefresh(unittest.TestCase):
    def test_callback_fires_per_person_during_the_scroll(self):
        cdp = HighlightCDP([[person("Anna")], [person("Bella")]])
        events = []
        parser = ScrollParser(
            cdp=cdp, pause_ms=0, poll_ms=1, load_timeout_ms=20,
            person_filter=PersonFilter(), confirm_pause_ms=0,
            on_collect=lambda rec, coll: events.append((rec.nick, len(coll))))
        res = run(parser.collect())
        # one event per person, each carrying the running total
        self.assertEqual(events, [("Anna", 1), ("Bella", 2)])
        self.assertEqual(len(res.collected), 2)

    def test_callback_fires_before_the_pipeline_returns(self):
        """The whole point: do not wait for the scroll cycle to finish."""
        pages = [[person(f"P{i}")] for i in range(6)]
        cdp = HighlightCDP(pages, page_height=10)
        seen_at = []
        parser = ScrollParser(
            cdp=cdp, pause_ms=0, poll_ms=1, load_timeout_ms=20,
            person_filter=PersonFilter(), confirm_pause_ms=0,
            on_collect=lambda rec, coll: seen_at.append(cdp.scrolls))
        run(parser.collect())
        self.assertTrue(seen_at)
        self.assertLess(min(seen_at), max(seen_at),
                        "people must be reported as scrolling progresses")

    def test_async_callbacks_are_awaited(self):
        cdp = HighlightCDP([[person("Anna")]])
        seen = []

        async def on_collect(rec, coll):
            await asyncio.sleep(0)
            seen.append(rec.nick)

        parser = ScrollParser(cdp=cdp, pause_ms=0, poll_ms=1,
                              load_timeout_ms=20, person_filter=PersonFilter(),
                              confirm_pause_ms=0, on_collect=on_collect)
        run(parser.collect())
        self.assertEqual(seen, ["Anna"])

    def test_a_broken_callback_never_kills_the_parse(self):
        def boom(rec, coll):
            raise RuntimeError("UI exploded")

        cdp = HighlightCDP([[person("Anna"), person("Bella")]])
        parser = ScrollParser(cdp=cdp, pause_ms=0, poll_ms=1,
                              load_timeout_ms=20, person_filter=PersonFilter(),
                              confirm_pause_ms=0, on_collect=boom)
        res = run(parser.collect())
        self.assertEqual([p.nick for p in res.collected], ["Anna", "Bella"])


class TestEngineLiveHook(unittest.TestCase):
    def test_engine_persists_and_emits_per_person(self):
        from backend.action_engine import ActionEngine
        from backend.user_memory import UserRecord

        class Mem:
            def __init__(self): self.saved = []
            async def upsert_user(self, u): self.saved.append(u.nick)

        mem = Mem()
        engine = ActionEngine(cdp=None, memory=mem, criteria=None)
        emitted = []
        engine.person_found.connect(lambda p: emitted.append(json.loads(p)))

        rec = UserRecord(nick="Anna", gender="female", guest=True)
        run(engine.person_collected(rec, [rec]))

        self.assertEqual(mem.saved, ["Anna"], "person saved immediately")
        self.assertEqual(len(emitted), 1)
        self.assertEqual(emitted[0]["nick"], "Anna")
        self.assertEqual(emitted[0]["collected"], 1)

    def test_hook_survives_a_storage_failure(self):
        from backend.action_engine import ActionEngine
        from backend.user_memory import UserRecord

        class Broken:
            async def upsert_user(self, u): raise RuntimeError("db down")

        engine = ActionEngine(cdp=None, memory=Broken(), criteria=None)
        emitted = []
        engine.person_found.connect(lambda p: emitted.append(p))
        run(engine.person_collected(UserRecord(nick="Anna"), []))
        self.assertEqual(len(emitted), 1, "UI is still told about the person")

    def test_block_wires_the_engine_hook_automatically(self):
        from actions.scroll_parse import ScrollParse

        cdp = HighlightCDP([[person("Anna")]])
        got = []

        class Eng:
            criteria = None
            def report(self, m, l="info"): pass
            async def person_collected(self, rec, coll): got.append(rec.nick)

        block = ScrollParse(scroll_pause_ms=0, load_timeout_ms=20,
                            min_new_users=0, pre_delay_ms=0,
                            confirm_pause_ms=0)
        run(block.run_pipeline(cdp, Eng()))
        self.assertEqual(got, ["Anna"],
                         "the block must use the engine's live hook")


class TestSettingsRoundTrip(unittest.TestCase):
    def test_new_settings_are_preset_storable(self):
        from actions.scroll_parse import ScrollParse

        block = ScrollParse(highlight_enabled=False, highlight_ms=1500,
                            confirm_pause_ms=250, person_selector="li.person",
                            nick_selector=".name")
        d = block.to_dict()
        schema = block.config_schema()
        for key in ("highlight_enabled", "highlight_ms", "confirm_pause_ms",
                    "person_selector", "nick_selector"):
            self.assertIn(key, d, f"{key} must round-trip through presets")
            self.assertIn(key, schema, f"{key} must be editable in the UI")
        clone = ScrollParse(**{k: v for k, v in d.items() if k != "block_id"})
        self.assertFalse(clone.highlight_enabled)
        self.assertEqual(clone.confirm_pause_ms, 250)
        self.assertEqual(clone.person_selector, "li.person")

    def test_defaults_are_sensible_and_legacy_presets_still_load(self):
        from actions.scroll_parse import ScrollParse

        block = ScrollParse(**{"max_scrolls": 20, "scroll_pause_ms": 500})
        self.assertTrue(block.highlight_enabled)
        self.assertEqual(block.confirm_pause_ms, 500)
        self.assertEqual(block.person_selector, "user-item")


if __name__ == "__main__":
    unittest.main(verbosity=2)
