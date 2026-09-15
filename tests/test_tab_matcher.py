"""backend/tab_matcher — URL → tab scoring (pure logic, first direct tests).

Design refs: docs/archive/2026-09-09-test-suite/BACKEND_TESTS_DESIGN_2026-09-09.md §TM#1–5.

The module docstring defines the exact scoring ladder:
    url_exact +500 · url_path +300 · host +200 · keyword +60 · none 0
and the site-key rule: every *.virt-chat.com host folds onto the same
registered site. URL presets (auto-connect) select tabs by these
numbers, so a regression here silently connects to the wrong tab.

Run with:  python3 tests/test_tab_matcher.py
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.tab_matcher import (  # noqa: E402
    _normalize_url,
    _site_key,
    best_matches,
    score_tab,
)


class TestNormalize(unittest.TestCase):

    def test_scheme_www_case_fragment_trailing_slash_are_dropped(self):
        self.assertEqual(_normalize_url("HTTPS://Example.com/"), "example.com")
        self.assertEqual(_normalize_url("https://x.io/a/#frag"), "x.io/a")
        self.assertEqual(_normalize_url("http://X.io/A"), "x.io/a")
        self.assertEqual(_normalize_url(""), "")
        self.assertEqual(_normalize_url(None), "")


class TestSiteKey(unittest.TestCase):

    def test_subhosts_of_a_registered_site_fold_together(self):
        self.assertEqual(_site_key("virt-chat.com"), "virt-chat.com")
        self.assertEqual(_site_key("www.virt-chat.com"), "virt-chat.com")
        self.assertEqual(_site_key("ru.virt-chat.com"), "virt-chat.com")
        self.assertEqual(_site_key("notvirt-chat.com"), "notvirt-chat.com",
                         "a suffix must not match without the dot")
        self.assertEqual(_site_key("example.org"), "example.org")


class TestScoringTiers(unittest.TestCase):

    def test_exact_url_beats_everything(self):
        score, kind = score_tab("https://ru.virt-chat.com/chat",
                                "https://ru.virt-chat.com/chat/",
                                "Вирт чат")
        self.assertEqual((score, kind), (500, "url_exact"))

    def test_path_prefix_on_the_same_site(self):
        score, kind = score_tab("ru.virt-chat.com/ch",
                                "https://ru.virt-chat.com/chat", "")
        self.assertEqual((score, kind), (300, "url_path"))

    def test_bare_host_query_is_a_host_match(self):
        score, kind = score_tab("virt-chat.com",
                                "https://ru.virt-chat.com/chat", "")
        self.assertEqual((score, kind), (200, "host"))

    def test_same_site_different_path_is_a_weak_keyword(self):
        score, kind = score_tab("ru.virt-chat.com/other",
                                "https://ru.virt-chat.com/chat", "")
        self.assertEqual((score, kind), (60, "keyword"))

    def test_keyword_falls_back_to_the_title(self):
        score, kind = score_tab("гостиная", "https://ru.virt-chat.com/room",
                                "Гостиная — Вирт чат")
        self.assertEqual((score, kind), (60, "keyword"))

    def test_unrelated_tab_scores_zero(self):
        self.assertEqual(score_tab("virt-chat.com", "https://example.org/x",
                                   "Example"), (0, ""))
        self.assertEqual(score_tab("", "https://virt-chat.com", ""), (0, ""))
        self.assertEqual(score_tab("virt-chat.com", "", ""), (0, ""))

    def test_percent_encoded_paths_still_match(self):
        # _normalize_url unquotes BOTH sides, so the page's %D0%BF and
        # the user's П normalize to the same string → url_exact
        score, kind = score_tab("virt-chat.com/%D0%BF",
                                "https://virt-chat.com/п", "")
        self.assertEqual((score, kind), (500, "url_exact"))


class TestBestMatches(unittest.TestCase):

    TABS = [
        {"id": 1, "title": "Вирт чат", "url": "https://ru.virt-chat.com/chat"},
        {"id": 2, "title": "Example", "url": "https://example.org/"},
        {"id": 3, "title": "Вирт чат приват",
         "url": "https://ru.virt-chat.com/chat/privat"},
    ]

    def test_best_first_and_zero_scores_excluded(self):
        out = best_matches("virt-chat.com", self.TABS)
        self.assertEqual([t["id"] for t in out], [1, 3],
                         "example.org must not appear at all")
        self.assertGreaterEqual(out[0]["score"], out[1]["score"])

    def test_top_n_caps_the_result(self):
        out = best_matches("virt-chat.com", self.TABS, top_n=1)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["id"], 1)

    def test_empty_tab_list_is_empty(self):
        self.assertEqual(best_matches("virt-chat.com", []), [])
        self.assertEqual(best_matches("virt-chat.com", None), [])

    def test_match_dicts_carry_the_wire_fields(self):
        out = best_matches("virt-chat.com", self.TABS, top_n=1)
        item = out[0]
        for key in ("id", "title", "url", "ws_url", "score", "kind"):
            self.assertIn(key, item)


if __name__ == "__main__":
    unittest.main(verbosity=2)
