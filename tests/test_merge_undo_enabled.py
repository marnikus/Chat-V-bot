"""Merge guard: undo/redo + enable-disable must coexist with the new pipeline.

The undo/redo + enable/disable branch was written against the OLD collect
pipeline (``_run_parse_phase`` and a bridge-built ``ScrollParser``), which the
Scroll & Parse redesign had already replaced. Merging the two needed manual
conflict resolution, so these tests pin the combined contract:

  * a DISABLED Scroll & Parse block must skip the whole new pipeline
    (no scrolling, nothing collected) — the enabled check has to sit on the
    block the engine actually runs;
  * ``enabled`` and the newer settings (``scroll_only``, the filters) must
    round-trip together through presets;
  * the tri-state filter dropdowns are ``<select>`` elements, and the merged
    config-form handler must still bind them — the incoming branch bound only
    ``input[data-key]``, which would have silently dropped every filter edit;
  * the retired settings must not come back from the other branch.

Run with:  python3 tests/test_merge_undo_enabled.py
"""

import asyncio
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from actions.scroll_parse import ScrollParse  # noqa: E402
from backend.action_engine import ActionEngine  # noqa: E402
from backend.user_memory import UserMemory, UserRecord  # noqa: E402
from tests.test_collect_visual_and_live_refresh import HighlightCDP  # noqa: E402
from tests.test_scroll_parse_pipeline import person  # noqa: E402

PAGES = [[person("Anna"), person("Bella")], [person("Cara")]]

UI_DIR = os.path.join(os.path.dirname(__file__), "..", "ui")


def cfg(**kw):
    d = {"block_id": "SCROLL_PARSE", "scroll_pause_ms": 0, "load_timeout_ms": 20,
         "pre_delay_ms": 0, "confirm_pause_ms": 0, "highlight_ms": 0,
         "min_new_users": 0}
    d.update(kw)
    return d


def run_stack(blocks, seed=()):
    async def go():
        d = tempfile.mkdtemp()
        mem = UserMemory(os.path.join(d, "t.db"))
        await mem.init()
        for nick in seed:
            await mem.upsert_user(UserRecord(nick=nick, gender="female",
                                             guest=True))
        cdp = HighlightCDP(PAGES, page_height=100)
        eng = ActionEngine(cdp=cdp, memory=mem, criteria=None)
        eng.load_stack(blocks)
        await eng.execute()
        names = sorted(u.nick for u in await mem.get_all())
        await mem.close()
        return names, cdp.scrolls

    cwd = os.getcwd()
    os.chdir(tempfile.mkdtemp())
    try:
        return asyncio.run(go())
    finally:
        os.chdir(cwd)


# ── enable/disable against the NEW pipeline ──────────────────────
class TestDisabledBlockSkipsTheNewPipeline(unittest.TestCase):
    def test_enabled_block_collects(self):
        names, scrolls = run_stack([cfg(enabled=True)])
        self.assertEqual(names, ["Anna", "Bella", "Cara"])
        self.assertGreater(scrolls, 0)

    def test_disabled_block_does_nothing_at_all(self):
        """The whole point: no scrolling, no collecting, no writes."""
        names, scrolls = run_stack([cfg(enabled=False)])
        self.assertEqual(names, [], "a disabled block must collect nobody")
        self.assertEqual(scrolls, 0, "a disabled block must not even scroll")

    def test_missing_enabled_key_defaults_to_on(self):
        """Legacy presets predate the toggle and must keep working."""
        names, scrolls = run_stack([cfg()])
        self.assertEqual(names, ["Anna", "Bella", "Cara"])
        self.assertGreater(scrolls, 0)

    def test_disabled_scroll_only_block_also_does_nothing(self):
        names, scrolls = run_stack([cfg(scroll_only=True, enabled=False)],
                                   seed=("Cara",))
        self.assertEqual(names, ["Cara"], "seeded person untouched")
        self.assertEqual(scrolls, 0)


# ── the two feature sets round-trip together ─────────────────────
class TestSettingsCoexist(unittest.TestCase):
    def test_enabled_and_scroll_only_round_trip(self):
        blk = ScrollParse(scroll_only=True, enabled=False,
                          filter_female="no")
        d = blk.to_dict()
        self.assertFalse(d["enabled"])
        self.assertTrue(d["scroll_only"])
        clone = ScrollParse(**{k: v for k, v in d.items() if k != "block_id"})
        self.assertFalse(clone.enabled)
        self.assertTrue(clone.scroll_only)
        self.assertEqual(clone.filter_female, "no")

    def test_enabled_defaults_true_and_is_serialised(self):
        self.assertTrue(ScrollParse().enabled)
        self.assertIn("enabled", ScrollParse().to_dict())

    def test_retired_settings_did_not_come_back(self):
        blk = ScrollParse()
        for dead in ("use_panel_filters", "skip_if_backlog",
                     "backlog_threshold"):
            self.assertFalse(hasattr(blk, dead), dead)
            self.assertNotIn(dead, blk.to_dict(), dead)
            self.assertNotIn(dead, blk.config_schema(), dead)


# ── the merged UI must not lose either side ──────────────────────
class TestMergedUI(unittest.TestCase):
    def setUp(self):
        with open(os.path.join(UI_DIR, "js", "stack-dnd.js"),
                  encoding="utf-8") as fh:
            self.js = fh.read()

    def test_no_conflict_markers_anywhere(self):
        for name in ("js/stack-dnd.js", "js/app.js", "js/presets-ui.js",
                     "css/stack.css", "index.html"):
            with open(os.path.join(UI_DIR, name), encoding="utf-8") as fh:
                text = fh.read()
            for marker in ("<<<<<<<", ">>>>>>>", "=======\n<<<"):
                self.assertNotIn(marker, text, f"{name} has {marker}")

    def test_select_dropdowns_are_still_bound(self):
        """The incoming branch bound only input[data-key], which would have
        silently dropped every tri-state filter edit."""
        self.assertIn("form.querySelectorAll('input[data-key], select[data-key]')",
                      self.js)
        self.assertIn("inp.tagName === 'SELECT'", self.js)

    def test_enabled_toggle_survived(self):
        self.assertIn("toggle-switch", self.js)
        self.assertIn("form-row-enabled", self.js)
        self.assertIn("pushHistory", self.js)

    def test_our_block_settings_survived(self):
        for key in ("scroll_only", "purge_rejected", "filter_female",
                    "min_new_users", "viewport_selector", "nick_selector"):
            self.assertIn(key, self.js, key)

    def test_every_block_has_an_enabled_default(self):
        import re
        blocks = re.findall(r"block_id:'([A-Z_]+)'[^\n]*\n?(?:[^{]*)"
                            r"defaults:\{(.*?)\},\s*\n?\s*(?:options|labels):",
                            self.js, re.S)
        self.assertGreater(len(blocks), 5, "block table not parsed")
        for bid, defaults in blocks:
            self.assertIn("enabled:true", defaults.replace(" ", ""),
                          f"{bid} is missing the enable/disable toggle")

    def test_undo_redo_buttons_exist(self):
        with open(os.path.join(UI_DIR, "index.html"), encoding="utf-8") as fh:
            html = fh.read()
        self.assertIn('id="undoBtn"', html)
        self.assertIn('id="redoBtn"', html)
        self.assertIn("Ctrl", html, "keyboard shortcut hint")


# ── bridge keeps both APIs ───────────────────────────────────────
class TestBridgeSurface(unittest.TestCase):
    def test_history_slots_exist(self):
        from backend.bridge import Bridge
        for slot in ("undo_stack", "redo_stack", "get_stack_history",
                     "push_stack_history", "save_stack_history"):
            self.assertTrue(hasattr(Bridge, slot), slot)

    def test_bridge_no_longer_builds_a_scroll_parser(self):
        """The block owns its own parser now; the bridge must not rebuild one."""
        import inspect
        from backend.bridge import Bridge
        src = inspect.getsource(Bridge.run_stack)
        self.assertNotIn("ScrollParser(", src)
        self.assertIn("self._engine.execute()", src)

    def test_engine_execute_is_called_without_a_parser(self):
        import inspect
        from backend.action_engine import ActionEngine
        src = inspect.getsource(ActionEngine.execute)
        self.assertIn("_run_collect_phase", src)
        self.assertNotIn("_run_parse_phase", src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
