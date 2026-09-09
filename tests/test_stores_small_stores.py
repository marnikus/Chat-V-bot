"""The small stores — block/bookmark/session/settings/undo/labels-file.

Design refs: docs/STORES_TEST_DESIGN_2026-09-09.md §3–§8
(BLK-01–10, BMK-01–08, SES-01–07, SET-01–08, UND-01–07, LBF-01–06)
and docs/BLOCKERS_FIX_DESIGN_2026-09-09.md §3 (split-file shapes).

Each store owns one file (bare list / flat dict / overlay); constructors
take the file path. test_stores_migration.py covers one happy path per
store; this file pins the edges that would corrupt a user's config in
production: hostile names, strip asymmetries, bool-vs-loud refusal rules,
the undo index invariant, and corrupt-file tolerance.

Run with:  python3 tests/test_stores_small_stores.py
"""

import os
import sys
import tempfile
import unittest
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from stores.block_store import BlockStore  # noqa: E402
from stores.bookmark_store import BookmarkStore, DEFAULT_BOOKMARKS  # noqa: E402
from stores.labels_file_store import LabelsFileStore  # noqa: E402
from stores.session_store import SessionStore  # noqa: E402
from stores.settings_store import SettingsStore  # noqa: E402
from stores.undo_store import MAX_STACK_HISTORY, UndoStore  # noqa: E402


class StoreCase(unittest.TestCase):
    fname = "store.json"

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, self.fname)


# ── block store ──────────────────────────────────────────────────
class TestBlockStore(StoreCase):
    fname = "blocks.json"

    def test_save_then_list(self):  # BLK-01
        store = BlockStore(self.path)
        self.assertTrue(store.save_block("b1", {"k": 1}))
        blocks = store.all()
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0]["name"], "b1")
        self.assertEqual(blocks[0]["block"], {"k": 1})
        # updated_at is stamped and parseable
        datetime.fromisoformat(blocks[0]["updated_at"])

    def test_overwrite_replaces_in_place(self):  # BLK-02
        store = BlockStore(self.path)
        store.save_block("b1", {"k": 1})
        store.save_block("b2", {"k": 2})
        self.assertTrue(store.save_block("b1", {"k": 3}))
        blocks = store.all()
        self.assertEqual(len(blocks), 2)
        self.assertEqual(blocks[0]["name"], "b1")
        self.assertEqual(blocks[0]["block"], {"k": 3})

    def test_delete_present_and_missing(self):  # BLK-03 (+05b strip)
        store = BlockStore(self.path)
        store.save_block("  padded  ", {"k": 1})
        self.assertEqual([b["name"] for b in store.all()], ["padded"])
        # delete must find what save stored, padding or not
        self.assertTrue(store.delete("  padded  "))
        self.assertEqual(store.all(), [])
        self.assertFalse(store.delete("ghost"))

    def test_set_all_replaces_wholesale(self):  # BLK-04
        store = BlockStore(self.path)
        saved = [{"name": "a", "block": {}, "updated_at": "t"}]
        self.assertTrue(store.set_all(saved))
        self.assertEqual(store.all(), saved)
        with self.assertRaises(TypeError):
            store.set_all(None)
        self.assertEqual(store.all(), saved)

    def test_all_hands_out_copies(self):  # BLK-05
        store = BlockStore(self.path)
        store.save_block("b1", {"nested": {"x": [1]}})
        store.all()[0]["block"]["nested"]["x"].append(2)
        self.assertEqual(store.all()[0]["block"], {"nested": {"x": [1]}})

    def test_non_dict_block_is_refused_loudly(self):  # BLK-06
        store = BlockStore(self.path)
        for bad in (None, [], "str", 5):
            with self.assertRaises(TypeError, msg=repr(bad)):
                store.save_block("b", bad)
        self.assertEqual(store.all(), [])
        self.assertTrue(store.save_block("ok", {}))  # store usable

    def test_blank_name_is_refused_softly(self):  # BLK-07
        store = BlockStore(self.path)
        self.assertFalse(store.save_block("", {"k": 1}))
        self.assertFalse(store.save_block("   ", {"k": 1}))
        self.assertEqual(store.all(), [])

    def test_blocks_survive_a_reopen(self):  # BLK-08
        BlockStore(self.path).save_block("b1", {"k": 1})
        again = BlockStore(self.path)
        self.assertEqual(len(again.all()), 1)
        self.assertEqual(again.all()[0]["block"], {"k": 1})

    def test_hostile_names_are_plain_keys(self):  # BLK-09
        store = BlockStore(self.path)
        names = ["a/b", "../../x", "x" * 500, "Привет 🎉"]
        for name in names:
            self.assertTrue(store.save_block(name, {"n": name}))
        for name in names:
            self.assertTrue(store.delete(name))
        self.assertEqual(store.all(), [])
        # nothing escaped the single file
        self.assertEqual(sorted(os.listdir(self.dir)), ["blocks.json"])

    def test_corrupt_file_reads_empty_and_recovers(self):  # BLK-10
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write("{truncated")
        store = BlockStore(self.path)
        self.assertEqual(store.all(), [])
        self.assertTrue(store.save_block("b1", {"k": 1}))
        self.assertEqual(len(BlockStore(self.path).all()), 1)


# ── bookmark store ───────────────────────────────────────────────
class TestBookmarkStore(StoreCase):
    fname = "bookmarks.json"

    def test_add_then_list(self):  # BMK-01
        store = BookmarkStore(self.path)
        store.add("https://example.com/x")
        self.assertEqual(store.all().count("https://example.com/x"), 1)

    def test_double_add_keeps_first_position(self):  # BMK-02
        store = BookmarkStore(self.path)
        store.add("https://a.example/")
        store.add("https://b.example/")
        store.add("https://a.example/")
        urls = store.all()
        self.assertEqual(urls.count("https://a.example/"), 1)
        self.assertLess(urls.index("https://a.example/"),
                        urls.index("https://b.example/"))

    def test_remove_unknown_is_a_noop(self):  # BMK-03
        store = BookmarkStore(self.path)
        before = store.all()
        self.assertFalse(store.remove("https://ghost.invalid/"))
        self.assertEqual(store.all(), before)

    def test_remove_strips_like_add(self):  # BMK-03b
        store = BookmarkStore(self.path)
        store.add("  https://spaced.example/  ")
        self.assertIn("https://spaced.example/", store.all())
        store.remove("  https://spaced.example/  ")
        self.assertNotIn("https://spaced.example/", store.all())

    def test_set_all_replaces_wholesale(self):  # BMK-04
        store = BookmarkStore(self.path)
        store.set_all(["https://1.example/", "https://2.example/"])
        self.assertEqual(store.all(), ["https://1.example/", "https://2.example/"])

    def test_set_all_empty_empties(self):  # BMK-05
        store = BookmarkStore(self.path)
        store.set_all([])
        self.assertEqual(store.all(), [])

    def test_fresh_store_shows_the_shipped_defaults(self):  # BMK-01b
        self.assertEqual(BookmarkStore(self.path).all(),
                         list(DEFAULT_BOOKMARKS))

    def test_hostile_urls(self):  # BMK-06
        store = BookmarkStore(self.path)
        self.assertFalse(store.add(""))
        self.assertFalse(store.add("   "))
        odd = ["x" * 2000, "https://пример.рф/путь?q=🎉", "javascript:alert(1)"]
        for url in odd:
            self.assertTrue(store.add(url))
            self.assertIn(url, store.all())
        again = BookmarkStore(self.path)
        for url in odd:
            self.assertIn(url, again.all())

    def test_set_all_with_non_list_is_loud_and_keeps_old_list(self):  # BMK-07
        store = BookmarkStore(self.path)
        store.set_all(["https://keep.example/"])
        with self.assertRaises(TypeError):
            store.set_all(None)
        self.assertEqual(store.all(), ["https://keep.example/"])

    def test_bookmarks_survive_a_reopen(self):  # BMK-08
        store = BookmarkStore(self.path)
        store.set_all(["https://1.example/"])
        self.assertEqual(BookmarkStore(self.path).all(),
                         ["https://1.example/"])


# ── session store ────────────────────────────────────────────────
class TestSessionStore(StoreCase):
    fname = "session.json"

    def test_set_then_get(self):  # SES-01
        store = SessionStore(self.path)
        store.set(cur_user="Ann")
        self.assertEqual(store.get("cur_user"), "Ann")

    def test_unknown_key_returns_default(self):  # SES-02
        self.assertEqual(SessionStore(self.path).get("ghost", default="d"),
                         "d")

    def test_set_merges_keys(self):  # SES-03
        store = SessionStore(self.path)
        store.set(a=1)
        store.set(b=2)
        self.assertEqual((store.get("a"), store.get("b")), (1, 2))

    def test_save_now_false_stays_in_memory_only(self):  # SES-04
        store = SessionStore(self.path)
        store.set(save_now=False, temp=1)
        self.assertEqual(store.get("temp"), 1)
        self.assertIsNone(SessionStore(self.path).get("temp"))

    def test_data_is_a_copy(self):  # SES-05
        store = SessionStore(self.path)
        store.set(nested={"x": [1]})
        store.data()["nested"]["x"].append(2)
        self.assertEqual(store.get("nested"), {"x": [1]})

    def test_no_expire_api_stale_keys_only_overwritten(self):  # SES-06 (pin)
        store = SessionStore(self.path)
        self.assertFalse(hasattr(store, "expire"))
        self.assertFalse(hasattr(store, "clear"))
        store.set(stale=1)
        self.assertEqual(SessionStore(self.path).get("stale"),
                         1)

    def test_hostile_keys_and_values_round_trip(self):  # SES-07
        store = SessionStore(self.path)
        store.set(**{"ключ 🎉": {"deep": [None, 1]}})
        again = SessionStore(self.path)
        self.assertEqual(again.get("ключ 🎉"), {"deep": [None, 1]})


# ── settings store ───────────────────────────────────────────────
class TestSettingsStore(StoreCase):
    fname = "settings.json"

    def test_documented_slices_read_without_keyerror(self):  # SET-01
        store = SettingsStore(self.path)
        for keys in (("chrome",), ("scroll",), ("delays",), ("ui",),
                     ("history",), ("collector",)):
            self.assertIsNotNone(store.get(*keys))

    def test_set_deep_merges_with_default_fallback(self):  # SET-02
        store = SettingsStore(self.path)
        store.set("ui", "theme", "light")
        self.assertEqual(store.get("ui", "theme"), "light")
        # siblings absent from the file fall back to shipped defaults
        self.assertEqual(store.get("ui", "language"), "ru")

    def test_get_copy_is_deep(self):  # SET-03
        store = SettingsStore(self.path)
        store.set("ui", {"theme": "dark"})
        copied = store.get_copy("ui")
        copied["theme"] = "hacked"
        self.assertEqual(store.get("ui", "theme"), "dark")

    def test_data_is_the_persisted_overlay(self):  # SET-04 (SPEC pin)
        store = SettingsStore(self.path)
        # data() is what was written, NOT the merged view: get() resolves
        # shipped defaults, data() shows the overlay only.
        self.assertEqual(store.data(), {})
        store.set("ui", "theme", "light")
        self.assertEqual(store.data(), {"ui": {"theme": "light"}})

    def test_validate_passes_on_defaults(self):  # SET-05
        self.assertEqual(SettingsStore(self.path).validate(), [])

    def test_validate_flags_a_bad_chrome_port(self):  # SET-06
        store = SettingsStore(self.path)
        store.set("chrome", "port", "xx")
        errors = store.validate()
        self.assertTrue(errors)
        self.assertIn("chrome.port", errors[0])

    def test_validate_only_watches_the_port(self):  # SET-06b (SPEC pin)
        store = SettingsStore(self.path)
        store.set("ui", "theme", 12345)
        # the shipped validator is deliberately narrow: only chrome.port
        # is checked, anything else passes through silently.
        self.assertEqual(store.validate(), [])

    def test_foreign_sections_are_not_namespaced(self):  # SET-07 (SPEC pin)
        store = SettingsStore(self.path)
        store.set("presets", {"x": 1})
        # set() is generic: nothing refuses or namespaces foreign keys.
        # Harmless in practice (PresetStore owns a separate file), pinned
        # so a future namespacing change shows up here first.
        self.assertEqual(store.get("presets"), {"x": 1})

    def test_settings_survive_a_reopen(self):  # SET-08
        store = SettingsStore(self.path)
        store.set("ui", "theme", "light")
        self.assertEqual(SettingsStore(self.path)
                         .get("ui", "theme"), "light")


# ── undo store ───────────────────────────────────────────────────
class TestUndoStore(StoreCase):
    fname = "undo.json"

    def test_fresh_store_is_empty_at_nothing(self):  # UND-01
        self.assertEqual(UndoStore(self.path).get(), ([], -1))

    def test_set_round_trip(self):  # UND-02
        store = UndoStore(self.path)
        store.set([{"k": 1}, {"k": 2}], 1)
        self.assertEqual(store.get(), ([{"k": 1}, {"k": 2}], 1))

    def test_push_appends_and_points_at_tip(self):  # UND-03
        store = UndoStore(self.path)
        res = store.push("people", {"n": 1})
        self.assertTrue(res.is_ok)
        hist, idx = store.get()
        self.assertEqual(len(hist), 1)
        self.assertEqual(idx, 0)
        self.assertEqual(hist[0]["kind"], "people")

    def test_push_after_undo_drops_the_redo_tail(self):  # UND-04
        store = UndoStore(self.path)
        store.push("a", 1)
        store.push("b", 2)
        hist, _ = store.get()
        store.set(hist, 0)  # undo once
        store.push("c", 3)
        hist, idx = store.get()
        self.assertEqual([e["kind"] for e in hist], ["a", "c"])
        self.assertEqual(idx, 1)

    def test_out_of_range_index_is_clamped(self):  # UND-05
        store = UndoStore(self.path)
        store.set([{"k": 1}, {"k": 2}], 99)
        hist, idx = store.get()
        self.assertEqual((len(hist), idx), (2, 1))
        store.set([{"k": 1}], -5)
        _, idx = store.get()
        self.assertEqual(idx, -1)

    def test_history_is_capped(self):  # UND-05b
        store = UndoStore(self.path)
        big = [{"i": i} for i in range(MAX_STACK_HISTORY + 5)]
        store.set(big, len(big) - 1)
        hist, idx = store.get()
        self.assertEqual(len(hist), MAX_STACK_HISTORY)
        self.assertEqual(idx, MAX_STACK_HISTORY - 1)
        self.assertEqual(hist[0], {"i": 5})  # oldest trimmed first

    def test_hostile_values_round_trip(self):  # UND-06
        store = UndoStore(self.path)
        store.push("x", {"uni": "🎉", "none": None, "deep": [1, {"a": 2}]})
        again = UndoStore(self.path)
        hist, idx = again.get()
        self.assertEqual(idx, 0)
        self.assertEqual(hist[0]["value"]["uni"], "🎉")

    def test_undo_state_survives_a_reopen(self):  # UND-07
        store = UndoStore(self.path)
        store.set([{"k": 1}], 0)
        self.assertEqual(UndoStore(self.path).get(),
                         ([{"k": 1}], 0))


# ── labels file store ────────────────────────────────────────────
class TestLabelsFileStore(StoreCase):
    def _file_store(self, name="labels.json"):
        return LabelsFileStore(os.path.join(self.dir, name))

    def test_missing_file_reloads_to_default(self):  # LBF-01
        store = self._file_store()
        store.reload()
        data = store.data()
        self.assertEqual(data["defs"], [])
        self.assertEqual(data["assign"], {})

    def test_corrupt_file_reloads_to_default(self):  # LBF-02
        path = os.path.join(self.dir, "labels.json")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("nope{{{")
        store = LabelsFileStore(path)
        self.assertEqual(store.data()["defs"], [])

    def test_set_marks_dirty_flush_clears(self):  # LBF-03
        store = self._file_store()
        self.assertFalse(store.dirty)
        store.set_data({"defs": [], "assign": {}, "filter": {},
                        "next_id": 1})
        self.assertTrue(store.dirty)
        self.assertTrue(store.flush())
        self.assertFalse(store.dirty)

    def test_flush_without_changes_writes_nothing(self):  # LBF-04
        path = os.path.join(self.dir, "labels.json")
        store = LabelsFileStore(path)
        self.assertFalse(os.path.exists(path))
        self.assertTrue(store.flush())
        self.assertFalse(os.path.exists(path))

    def test_garbage_shape_coerces_to_default(self):  # LBF-05
        store = self._file_store()
        for bad in (None, [], "str", 5):
            store.set_data(bad)
            self.assertEqual(store.data()["defs"], [])
        self.assertTrue(store.flush())

    def test_round_trip_through_a_new_instance(self):  # LBF-06
        path = os.path.join(self.dir, "labels.json")
        store = LabelsFileStore(path)
        payload = {"defs": [{"id": "lbl_1", "name": "R"}], "assign": {},
                   "filter": {"include": [], "exclude": []}, "next_id": 1}
        store.set_data(payload)
        store.flush()
        again = LabelsFileStore(path)
        self.assertEqual(again.data(), payload)

    def test_data_is_a_copy(self):  # LBF-06b
        store = self._file_store()
        store.set_data({"defs": [], "assign": {"A": ["l"]}, "filter": {},
                        "next_id": 0})
        store.data()["assign"]["A"].append("hacked")
        self.assertEqual(store.data()["assign"], {"A": ["l"]})


if __name__ == "__main__":
    unittest.main()
