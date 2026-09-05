"""Tests for the two-phase visual-confirmation Find & Click.

The generated JavaScript probes are executed for real through a small Node
harness (tests/js_harness.js) backed by a minimal DOM stub, so these tests
verify actual probe behaviour — matching, highlighting, stashing and clicking —
not just string shapes.

Run with:  python3 tests/test_find_click_visual.py
"""

import json
import os
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.dom_highlight import (  # noqa: E402
    COLOR_CLICK,
    COLOR_FIND,
    build_click_probe,
    build_find_probe,
    interpret_click,
    interpret_click_target,
    interpret_find,
)

HARNESS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "js_harness.js")


def run_js(exprs, nodes):
    """Execute probe expressions in one shared DOM; return (results, effects)."""
    payload = json.dumps({"exprs": exprs, "nodes": nodes})
    proc = subprocess.run(["node", HARNESS], input=payload, capture_output=True,
                          text=True, timeout=30)
    if proc.returncode != 0:
        raise AssertionError(f"harness failed: {proc.stderr}")
    out = json.loads(proc.stdout)
    for r in out["results"]:
        assert "harness_error" not in r, r["harness_error"]
    return out["results"], out["effects"]


def tab(text, x):
    """One chat tab exactly as the real page renders it."""
    return {"tag": "div", "className": "tab-item", "attrs": {"role": "tab"},
            "x": x, "y": 0, "width": 120,
            "children": [{"tag": "p", "className": "chat-title", "text": text}]}


def tabs(active_text="Гостиная"):
    """Three chat tabs, like the real page."""
    return [tab("Приват 1", 0), tab(active_text, 120), tab("Приват 2", 240)]


class TestFindPhase(unittest.TestCase):
    def test_finds_matching_tab_and_draws_red_outline(self):
        expr = build_find_probe("div.tab-item", "p.chat-title", "Гостиная")
        (res,), eff = run_js([expr], tabs())
        self.assertTrue(res["found"])
        self.assertEqual(res["total"], 3)
        self.assertEqual(res["index"], 1)          # the middle tab
        self.assertEqual(res["text"], "Гостиная")
        self.assertTrue(res["visible"])
        self.assertTrue(res["clickable"])
        self.assertTrue(res["highlighted"])
        # exactly one RED, outline-only, non-interactive overlay
        overlays = eff["overlays"][0]
        self.assertEqual(len(overlays), 1)
        css = overlays[0]["css"]
        self.assertIn(f"outline:2px solid {COLOR_FIND}", css)
        self.assertIn("background:transparent", css)
        self.assertIn("pointer-events:none", css)
        self.assertEqual(overlays[0]["caption"], "FOUND")
        # no click happened during the find phase
        self.assertEqual(eff["clicks"], [])
        self.assertFalse(res["clicked"])

    def test_highlight_geometry_matches_element(self):
        expr = build_find_probe("div.tab-item", "p.chat-title", "Гостиная")
        (res,), _ = run_js([expr], tabs())
        self.assertEqual(res["rect"]["x"], 120)
        self.assertEqual(res["rect"]["width"], 120)

    def test_not_found_reports_candidates_and_no_overlay(self):
        expr = build_find_probe("div.tab-item", "p.chat-title", "Нет такой")
        (res,), eff = run_js([expr], tabs())
        self.assertFalse(res["found"])
        self.assertEqual(res["total"], 3)
        self.assertEqual(eff["overlays"][0], [])
        msg, level = interpret_find(res, "tab")
        self.assertEqual(level, "error")
        self.assertIn("FIND failed", msg)

    def test_hidden_element_is_found_but_not_clickable(self):
        nodes = [{"tag": "div", "className": "tab-item", "hidden": True,
                  "children": [{"tag": "p", "className": "chat-title",
                                "text": "Гостиная"}]}]
        expr = build_find_probe("div.tab-item", "p.chat-title", "Гостиная")
        (res,), _ = run_js([expr], nodes)
        self.assertTrue(res["found"])
        self.assertFalse(res["visible"])
        self.assertFalse(res["clickable"])
        _, level = interpret_find(res, "tab")
        self.assertEqual(level, "warn")

    def test_highlight_can_be_disabled(self):
        expr = build_find_probe("div.tab-item", "p.chat-title", "Гостиная",
                                highlight=False)
        (res,), eff = run_js([expr], tabs())
        self.assertTrue(res["found"])
        self.assertFalse(res["highlighted"])
        self.assertEqual(eff["overlays"][0], [])

    def test_empty_match_text_takes_first_node(self):
        expr = build_find_probe("div.tab-item")
        (res,), _ = run_js([expr], tabs())
        self.assertTrue(res["found"])
        self.assertEqual(res["index"], 0)

    def test_overlays_do_not_accumulate_between_runs(self):
        expr = build_find_probe("div.tab-item", "p.chat-title", "Гостиная")
        _, eff = run_js([expr, expr, expr], tabs())
        # each new find clears the previous overlays first
        for phase_overlays in eff["overlays"]:
            self.assertEqual(len(phase_overlays), 1)

    def test_outline_auto_expires(self):
        expr = build_find_probe("div.tab-item", "p.chat-title", "Гостиная",
                                highlight_ms=900)
        _, eff = run_js([expr], tabs())
        self.assertIn(900, eff["timers"])


class TestClickPhase(unittest.TestCase):
    def _find(self, **kw):
        return build_find_probe("div.tab-item", "p.chat-title", "Гостиная", **kw)

    def test_orange_outline_then_click_on_stashed_element(self):
        exprs = [self._find(),
                 build_click_probe(do_click=False),      # highlight only
                 build_click_probe(highlight=False, do_click=True)]
        (found, pre, done), eff = run_js(exprs, tabs())
        self.assertTrue(found["found"])
        # phase 2a: orange outline, no click yet
        self.assertTrue(pre["clickable"])
        self.assertTrue(pre["highlighted"])
        self.assertFalse(pre["clicked"])
        # the red FIND outline is still up; the orange one is added alongside it
        click_overlays = [o for o in eff["overlays"][1] if o["caption"] == "CLICK"]
        self.assertEqual(len(click_overlays), 1)
        css = click_overlays[0]["css"]
        self.assertIn(f"outline:2px solid {COLOR_CLICK}", css)
        self.assertIn("pointer-events:none", css)
        # phase 2b: the click actually lands, exactly once, on the right node
        self.assertTrue(done["clicked"])
        self.assertEqual(eff["clicks"], ["div.tab-item"])

    def test_click_targets_the_element_the_find_phase_highlighted(self):
        """Regression: the click must not re-query and hit a different node."""
        exprs = [self._find(), build_click_probe(highlight=False)]
        (found, done), eff = run_js(exprs, tabs())
        self.assertEqual(found["index"], 1)
        self.assertTrue(done["clicked"])
        self.assertEqual(len(eff["clicks"]), 1)

    def test_click_selector_targets_inner_element(self):
        exprs = [self._find(), build_click_probe(click_selector="p.chat-title")]
        (_, done), eff = run_js(exprs, tabs())
        self.assertTrue(done["clicked"])
        self.assertEqual(eff["clicks"], ["p.chat-title"])
        self.assertEqual(done["target_desc"], "p.chat-title")

    def test_click_selector_equal_to_the_root_selector_still_clicks(self):
        """Regression (the saved “Tab Main” block).

        Its click_selector is the SAME selector used to find the element. A CSS
        selector only matches descendants, so root.querySelector() returned
        null and the block silently never clicked. The root itself must be used
        when it is what the selector describes.
        """
        exprs = [build_find_probe("div[role='tab'].tab-item", "p.chat-title",
                                  "Гостиная"),
                 build_click_probe(click_selector="div[role='tab'].tab-item")]
        (found, done), eff = run_js(exprs, tabs())
        self.assertTrue(found["found"])
        self.assertTrue(done["clicked"], done.get("error"))
        self.assertEqual(eff["clicks"], ["div.tab-item"])
        self.assertIn("itself", done.get("note") or "")

    def test_missing_click_selector_is_an_error_not_a_wrong_click(self):
        exprs = [self._find(), build_click_probe(click_selector="button.nope")]
        (_, done), eff = run_js(exprs, tabs())
        self.assertFalse(done["clicked"])
        self.assertIn("not found inside", done["error"])
        self.assertEqual(eff["clicks"], [])
        msg, level = interpret_click(done, "tab")
        self.assertEqual(level, "error")

    def test_click_without_a_find_phase_errors_clearly(self):
        (done,), eff = run_js([build_click_probe()], tabs())
        self.assertFalse(done["clicked"])
        self.assertIn("no element stashed", done["error"])
        self.assertEqual(eff["clicks"], [])

    def test_detached_element_reported(self):
        nodes = [{"tag": "div", "className": "tab-item", "detached": True,
                  "children": [{"tag": "p", "className": "chat-title",
                                "text": "Гостиная"}]}]
        exprs = [self._find(), build_click_probe()]
        (_, done), eff = run_js(exprs, nodes)
        self.assertFalse(done["clicked"])
        self.assertIn("no longer attached", done["error"])
        self.assertEqual(eff["clicks"], [])

    def test_pointer_events_none_blocks_the_click(self):
        nodes = [{"tag": "div", "className": "tab-item", "pointerEventsNone": True,
                  "children": [{"tag": "p", "className": "chat-title",
                                "text": "Гостиная"}]}]
        exprs = [self._find(), build_click_probe()]
        (_, done), eff = run_js(exprs, nodes)
        self.assertFalse(done["clicked"])
        self.assertFalse(done["clickable"])
        self.assertEqual(eff["clicks"], [])
        msg, level = interpret_click(done, "tab")
        self.assertEqual(level, "error")
        self.assertIn("NOT clickable", msg)

    def test_click_exception_is_captured(self):
        nodes = [{"tag": "div", "className": "tab-item", "throwOnClick": True,
                  "children": [{"tag": "p", "className": "chat-title",
                                "text": "Гостиная"}]}]
        exprs = [self._find(), build_click_probe()]
        (_, done), _ = run_js(exprs, nodes)
        self.assertFalse(done["clicked"])
        self.assertIn("blew up", done["error"])


class TestInterpret(unittest.TestCase):
    def test_find_success_message_mentions_the_red_outline(self):
        msg, level = interpret_find(
            {"found": True, "total": 3, "index": 1, "text": "Гостиная",
             "visible": True, "clickable": True, "highlighted": True,
             "rect": {"x": 1, "y": 2, "width": 3, "height": 4}}, "tab")
        self.assertEqual(level, "success")
        self.assertIn("FIND success", msg)
        self.assertIn("red outline", msg)

    def test_click_target_message_mentions_the_orange_outline(self):
        msg, level = interpret_click_target(
            {"clickable": True, "highlighted": True, "target_desc": "div.tab-item"})
        self.assertEqual(level, "success")
        self.assertIn("orange outline", msg)

    def test_no_data_is_an_error_not_silence(self):
        for fn in (interpret_find, interpret_click):
            msg, level = fn(None, "tab")
            self.assertEqual(level, "error")
            self.assertTrue(msg)


class TestBlockConfig(unittest.TestCase):
    def test_custom_find_defaults_and_roundtrip(self):
        from actions.custom_find import CustomFind
        b = CustomFind(custom_name="Tab Main", selector="div[role='tab'].tab-item",
                       label_selector="p.chat-title", match_text="Гостиная")
        self.assertTrue(b.highlight_enabled)
        self.assertEqual(b.confirm_pause_ms, 700)
        d = b.to_dict()
        for key in ("highlight_enabled", "confirm_pause_ms", "highlight_ms"):
            self.assertIn(key, d)
            self.assertIn(key, b.config_schema())
        # a legacy preset (no new keys) still constructs and gains the feature
        legacy = {k: v for k, v in d.items()
                  if k not in ("highlight_enabled", "confirm_pause_ms",
                               "highlight_ms", "block_id")}
        self.assertTrue(CustomFind(**legacy).highlight_enabled)

    def test_tab_blocks_expose_the_same_settings(self):
        from actions.click_back import ClickBack
        from actions.click_main_tab import ClickMainTab
        for cls in (ClickMainTab, ClickBack):
            b = cls()
            self.assertTrue(b.highlight_enabled)
            self.assertIn("highlight_enabled", b.config_schema())


if __name__ == "__main__":
    unittest.main(verbosity=2)
