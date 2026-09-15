"""backend/media_handler — pattern and path contracts (no browser).

Design refs: docs/archive/2026-09-09-test-suite/BACKEND_TESTS_DESIGN_2026-09-09.md §MH#1–3.

The download/recovery flows live in test_attach_image.py and
test_media_recovery*.py. This file pins the pure seam every attach run
starts from:

  * `parse_patterns` — "gif", ".PNG", "*.JPG", free globs, comma /
    semicolon / space lists, empty → the documented default set;
  * `list_image_files` — case-insensitive extensions, no directories,
    deterministic order, missing folder → [] (never raises);
  * a folder the user typed wrong (missing / empty) is a clean failure
    surface, not a traceback.

Run with:  python3 tests/test_media_handler_paths.py
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.media_handler import (  # noqa: E402
    DEFAULT_FILE_PATTERN,
    list_image_files,
    parse_patterns,
)


class TestParsePatterns(unittest.TestCase):

    def test_bare_extension_becomes_a_glob(self):
        self.assertEqual(parse_patterns("gif"), ["*.gif"])
        self.assertEqual(parse_patterns(".png"), ["*.png"])
        self.assertEqual(parse_patterns("*.JPG"), ["*.jpg"])

    def test_separators_are_comma_semicolon_and_whitespace(self):
        self.assertEqual(parse_patterns("jpg; png, gif webp"),
                         ["*.jpg", "*.png", "*.gif", "*.webp"])

    def test_free_globs_are_kept_verbatim(self):
        self.assertEqual(parse_patterns("vacation-*.jp*"), ["vacation-*.jp*"])
        self.assertEqual(parse_patterns("img??.png"), ["img??.png"])

    def test_empty_falls_back_to_the_documented_defaults(self):
        for empty in ("", "   ", ",,,", None):
            self.assertEqual(parse_patterns(empty),
                             [p.strip() for p in
                              DEFAULT_FILE_PATTERN.split(",")])

    def test_everything_is_lowercase(self):
        for p in parse_patterns("GIF, WebP, .TiFF"):
            self.assertEqual(p, p.lower())


class TestListImageFiles(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        for name in ("a.jpg", "B.PNG", "c.GiF", "d.txt", "e.jpeg"):
            with open(os.path.join(self.dir, name), "wb") as fh:
                fh.write(b"x")
        os.mkdir(os.path.join(self.dir, "subdir.jpg"))     # a directory!

    def test_case_insensitive_and_deterministic(self):
        files = list_image_files(self.dir, "*.jpg")
        names = [os.path.basename(f) for f in files]
        self.assertEqual(names, ["a.jpg"], "*.jpg must not match .jpeg")
        every = list_image_files(self.dir, DEFAULT_FILE_PATTERN)
        names = [os.path.basename(f).lower() for f in every]
        self.assertEqual(sorted(names),
                         ["a.jpg", "b.png", "c.gif", "e.jpeg"])
        self.assertEqual(names, [n.lower() for n in names])
        self.assertTrue(all(os.path.isabs(f) for f in every),
                        "absolute paths so the CDP file dialog can use them")

    def test_directories_are_never_listed(self):
        files = list_image_files(self.dir, "*.jpg")
        self.assertNotIn(os.path.join(self.dir, "subdir.jpg"), files)

    def test_free_glob_narrows_the_selection(self):
        files = list_image_files(self.dir, "*.gif")
        self.assertEqual([os.path.basename(f) for f in files], ["c.GiF"])

    def test_missing_or_unreadable_folder_is_empty(self):
        self.assertEqual(list_image_files(
            os.path.join(self.dir, "nope"), "*.jpg"), [])
        self.assertEqual(list_image_files("", "*.jpg"), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
