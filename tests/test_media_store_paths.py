"""stores/media_store — slug, folder and filename contracts.

Design refs: docs/BACKEND_TESTS_DESIGN_2026-09-09.md §MS#1–3.

test_media_store.py covers downloading/eviction. This file pins the
filesystem-identity seam — where a hostile nick must never become a
path escape:

  * `slugify_nick`: traversal ("../../etc"), "..", empty, emoji-only and
    Cyrillic nicks all become ONE safe path segment; output capped;
  * `folder_for` is stable per (nick, kind) and separates images/gifs;
  * two nicks that transliterate to the same Latin name get different
    folders (the `_nick.txt` marker arbitration);
  * `_free_name` numbers files within a day (_001, _002, …) and survives
    a restart (it reads the folder, not memory).

Run with:  python3 tests/test_media_store_paths.py
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from stores.media_store import MediaStore, slugify_nick  # noqa: E402


def store(cache_dir):
    return MediaStore(db=None, cdp=None, cache_dir=cache_dir)


class TestSlugify(unittest.TestCase):

    def test_traversal_attempts_stay_one_safe_segment(self):
        for hostile in ("../../etc", "..", "../..", "a/b/c", r"a\\b",
                        "/etc/passwd", "C:\\temp"):
            slug = slugify_nick(hostile)
            self.assertNotIn("/", slug, repr(hostile))
            self.assertNotIn("\\\\", slug, repr(hostile))
            self.assertFalse(slug.startswith("."),
                             f"{hostile!r} → {slug!r} (dot segment)")
            self.assertNotEqual(slug, "..")
            self.assertTrue(slug, repr(hostile))

    def test_empty_and_symbol_only_nicks_get_a_fallback(self):
        for empty in ("", "   ", "😀", "!!?", "___"):
            slug = slugify_nick(empty)
            self.assertTrue(slug)
            self.assertNotIn("/", slug)

    def test_cyrillic_transliterates_readably(self):
        slug = slugify_nick("Хорошо Все")
        self.assertTrue(slug and slug.isascii())
        self.assertNotIn(" ", slug)
        self.assertEqual(slugify_nick("Lizalo4ka"), "Lizalo4ka")

    def test_output_is_capped_and_deterministic(self):
        long_nick = "x" * 500
        self.assertLessEqual(len(slugify_nick(long_nick)), 64)
        self.assertEqual(slugify_nick("Stable Nick"),
                         slugify_nick("Stable Nick"))


class TestFolders(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.ms = store(self.tmp)

    def test_folder_for_is_stable_and_separates_kinds(self):
        a1 = self.ms.folder_for("Nick", "image")
        a2 = self.ms.folder_for("Nick", "image")
        g = self.ms.folder_for("Nick", "gif")
        plain = self.ms.folder_for("Nick")
        self.assertEqual(a1, a2)
        self.assertEqual(os.path.basename(a1), "images")
        self.assertEqual(os.path.basename(g), "gifs")
        self.assertNotEqual(a1, g)
        self.assertEqual(os.path.dirname(a1), plain)
        self.assertTrue(os.path.isabs(a1))

    def test_folders_never_leave_the_cache_root(self):
        root = os.path.abspath(self.tmp)
        for nick in ("../../evil", "..", "Оля/Мария", "😀"):
            folder = os.path.abspath(self.ms.folder_for(nick, "image"))
            self.assertTrue(folder.startswith(root + os.sep),
                            f"{nick!r} escaped the cache root: {folder}")

    def test_same_latin_name_from_two_nicks_gets_arbitrated(self):
        """`Ански` and `Anski` transliterate identically. The first
        DOWNLOAD records the owner in `_nick.txt`; after that, the
        late-comer is routed to a hashed variant folder."""
        f1 = self.ms._target_path("Ански", "image", "2026-09-09", ".gif")
        marker = os.path.join(os.path.dirname(os.path.dirname(f1)),
                              "_nick.txt")
        self.assertTrue(os.path.exists(marker),
                        "the first owner must be recorded")
        self.assertIn("Ански", open(marker, encoding="utf-8").read())
        f2 = self.ms._target_path("Anski", "image", "2026-09-09", ".gif")
        self.assertNotEqual(os.path.dirname(os.path.dirname(f1)),
                            os.path.dirname(os.path.dirname(f2)),
                            "the second nick must not land in Милка's tree")

    def test_the_owner_keeps_its_folder_after_a_restart(self):
        f1 = self.ms._target_path("Мила", "image", "2026-09-09", ".jpg")
        fresh = store(self.tmp)
        f2 = fresh._target_path("Мила", "image", "2026-09-09", ".jpg")
        self.assertEqual(os.path.dirname(f1), os.path.dirname(f2),
                         "the owner must keep the readable folder")

    def test_a_second_store_instance_honours_the_existing_marker(self):
        first = store(self.tmp).folder_for("Мила", "image")
        second = store(self.tmp).folder_for("Mila", "image")
        self.assertEqual(os.path.dirname(first), os.path.dirname(second),
                         "restart must not steal the folder")


class TestFreeName(unittest.TestCase):

    def test_sequence_within_one_day(self):
        tmp = tempfile.mkdtemp()
        folder = os.path.join(tmp, "Nick", "images")
        os.makedirs(folder)
        ms = store(tmp)
        seen = []
        for _ in range(3):
            path = ms._free_name(folder, "2026-09-09", ".gif")
            self.assertNotIn(path, seen)
            open(path, "wb").close()     # the next call reads the disk
            seen.append(path)
        self.assertEqual([os.path.basename(p) for p in seen],
                         ["2026-09-09_001.gif", "2026-09-09_002.gif",
                          "2026-09-09_003.gif"])

    def test_sequence_survives_a_restart(self):
        tmp = tempfile.mkdtemp()
        folder = os.path.join(tmp, "Nick", "images")
        os.makedirs(folder)
        open(os.path.join(folder, "2026-09-09_001.gif"), "wb").close()
        open(os.path.join(folder, "2026-09-09_007.gif"), "wb").close()
        fresh = store(tempfile.mkdtemp())     # cold memory, warm disk
        path = fresh._free_name(folder, "2026-09-09", ".gif")
        self.assertEqual(os.path.basename(path), "2026-09-09_008.gif",
                         "numbering must read the disk, not memory")

    def test_other_days_do_not_advance_the_counter(self):
        tmp = tempfile.mkdtemp()
        folder = os.path.join(tmp, "Nick", "images")
        os.makedirs(folder)
        open(os.path.join(folder, "2026-09-08_004.gif"), "wb").close()
        path = store(tmp)._free_name(folder, "2026-09-09", ".gif")
        self.assertEqual(os.path.basename(path), "2026-09-09_001.gif")


if __name__ == "__main__":
    unittest.main(verbosity=2)
