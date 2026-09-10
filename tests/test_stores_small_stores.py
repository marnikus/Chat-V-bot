"""The small stores — block/bookmark/session/settings/undo/labels-file.

Design refs: docs/archive/2026-09-09-test-suite/STORES_TEST_DESIGN_2026-09-09.md §3–§8
(BLK-01–10, BMK-01–08, SES-01–07, SET-01–08, UND-01–07, LBF-01–06).

test_stores_migration.py covers one happy path per store; this file pins the
edges that would corrupt a user's config in production: unknown sections,
hostile names, strip/unstrip asymmetries between add and remove, the undo
index invariant, and the dirty/clean lifecycle of the labels fallback file.

Run with:  python3 tests/test_stores_small_stores.py
"""

import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from stores.atomic import AtomicJsonStore  # noqa: E402
from stores.block_store import BlockStore  # noqa: E402
from stores.bookmark_store import BookmarkStore, DEFAULT_URLS  # noqa: E402
from stores.labels_file_store import LabelsFileStore  # noqa: E402
from stores.session_store import SessionStore  # noqa: E402
from stores.settings_store import SettingsStore  # noqa: E402
from stores.undo_store import MAX_STACK_HISTORY, UndoStore  # noqa: E402


class StoreCase(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "config.json")
        self.atomic = AtomicJsonStore(self.path)


# ── block store ──────────────────────────────────────────────────
class TestBlockStore(StoreCase):
    def test_named_round_trip(self):  # BLK-01
        store = BlockStore(self.atomic)
        self.assertTrue(store.named_set("stack_presets", "a", {"x": 1}).is_ok)
        self.assertEqual(store.named_get("stack_presets", "a"), {"x": 1})
        self.assertTrue(store.named_delete("stack_presets", "a").value)
        self.assertIsNone(store.named_get("stack_presets", "a"))

    def test_unknown_section_and_name_are_empty_safe(self):  # BLK-02/03
        store = BlockStore(self.atomic)
        self.assertEqual(store.named_all("no_such_section"), {})
        self.assertEqual(store.named_get("stack_presets", "ghost", default="d"),
                         "d")
        self.assertFalse(store.named_delete("stack_presets", "ghost").value)

    def test_sections_are_isolated(self):  # BLK-04
        store = BlockStore(self.atomic)
        store.named_set("stack_presets", "same", 1)
        store.named_set("template_presets", "same", 2)
        self.assertEqual(store.named_get("stack_presets", "same"), 1)
        self.assertEqual(store.named_get("template_presets", "same"), 2)

    def test_custom_block_save_overwrite_delete(self):  # BLK-05/06/07
        store = BlockStore(self.atomic)
        self.assertTrue(store.save_custom_block("b1", {"k": 1}).is_ok)
        self.assertTrue(store.save_custom_block("b1", {"k": 2}).is_ok)
        blocks = store.custom_blocks()
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0]["block"], {"k": 2})
        self.assertTrue(store.delete_custom_block("b1").value)
        self.assertEqual(store.custom_blocks(), [])
        self.assertFalse(store.delete_custom_block("ghost").value)

    def test_custom_block_names_are_stripped_symmetrically(self):  # BLK-05b
        store = BlockStore(self.atomic)
        store.save_custom_block("  padded  ", {"k": 1})
        self.assertEqual(
            [b["name"] for b in store.custom_blocks()], ["padded"])
        # delete must find what save stored, padding or not
        self.assertTrue(store.delete_custom_block("  padded  ").value)
        self.assertEqual(store.custom_blocks(), [])

    def test_named_and_custom_blocks_survive_a_reopen(self):  # BLK-08
        store = BlockStore(self.atomic)
        store.named_set("stack_presets", "a", {"x": 1})
        store.save_custom_block("b1", {"k": 1})
        again = BlockStore(AtomicJsonStore(self.path))
        self.assertEqual(again.named_get("stack_presets", "a"), {"x": 1})
        self.assertEqual(len(again.custom_blocks()), 1)

    def test_hostile_names_are_plain_dict_keys(self):  # BLK-09
        store = BlockStore(self.atomic)
        names = ["", "  ", "a/b", "../../x", "x" * 500, "Привет 🎉"]
        for name in names:
            store.named_set("stack_presets", name, {"n": name})
        for name in names:
            self.assertEqual(store.named_get("stack_presets", name),
                             {"n": name})
        # nothing escaped the single file
        self.assertEqual(sorted(os.listdir(self.dir)), ["config.json"])

    def test_non_dict_custom_block_is_refused_loudly(self):  # BLK-10
        store = BlockStore(self.atomic)
        for bad in (None, [], "str", 5):
            res = store.save_custom_block("b", bad)
            self.assertTrue(res.is_err, bad)
        self.assertEqual(store.custom_blocks(), [])
        self.assertTrue(store.named_delete("x", "y").is_ok)  # store usable
        self.assertEqual(BlockStore(AtomicJsonStore(self.path))
                         .custom_blocks(), [])


# ── bookmark store ───────────────────────────────────────────────
class TestBookmarkStore(StoreCase):
    def test_add_then_list(self):  # BMK-01
        store = BookmarkStore(self.atomic)
        store.add("https://example.com/x")
        self.assertEqual(store.all().count("https://example.com/x"), 1)

    def test_double_add_keeps_first_position(self):  # BMK-02
        store = BookmarkStore(self.atomic)
        store.add("https://a.example/")
        store.add("https://b.example/")
        store.add("https://a.example/")
        urls = store.all()
        self.assertEqual(urls.count("https://a.example/"), 1)
        self.assertLess(urls.index("https://a.example/"),
                        urls.index("https://b.example/"))

    def test_remove_unknown_is_a_noop(self):  # BMK-03
        store = BookmarkStore(self.atomic)
        before = store.all()
        self.assertTrue(store.remove("https://ghost.invalid/").is_ok)
        self.assertEqual(store.all(), before)

    def test_remove_strips_like_add(self):  # BMK-03b
        store = BookmarkStore(self.atomic)
        store.add("  https://spaced.example/  ")
        self.assertIn("https://spaced.example/", store.all())
        store.remove("  https://spaced.example/  ")
        self.assertNotIn("https://spaced.example/", store.all())

    def test_set_all_replaces_wholesale(self):  # BMK-04
        store = BookmarkStore(self.atomic)
        store.set_all(["https://1.example/", "https://2.example/"])
        self.assertEqual(store.all(), ["https://1.example/", "https://2.example/"])

    def test_set_all_empty_empties(self):  # BMK-05
        store = BookmarkStore(self.atomic)
        store.set_all([])
        self.assertEqual(store.all(), [])

    def test_fresh_store_shows_the_shipped_defaults(self):  # BMK-01b
        self.assertEqual(BookmarkStore(self.atomic).all(), list(DEFAULT_URLS))

    def test_hostile_urls(self):  # BMK-06
        store = BookmarkStore(self.atomic)
        self.assertTrue(store.add("").is_err)
        self.assertTrue(store.add("   ").is_err)
        odd = ["x" * 2000, "https://пример.рф/путь?q=🎉", "javascript:alert(1)"]
        for url in odd:
            self.assertTrue(store.add(url).is_ok)
            self.assertIn(url, store.all())
        again = BookmarkStore(AtomicJsonStore(self.path))
        for url in odd:
            self.assertIn(url, again.all())

    def test_set_all_with_non_list_is_loud_and_keeps_old_list(self):  # BMK-07
        store = BookmarkStore(self.atomic)
        store.set_all(["https://keep.example/"])
        with self.assertRaises(TypeError):
            store.set_all(None)
        self.assertEqual(store.all(), ["https://keep.example/"])

    def test_bookmarks_survive_a_reopen(self):  # BMK-08
        store = BookmarkStore(self.atomic)
        store.set_all(["https://1.example/"])
        self.assertEqual(BookmarkStore(AtomicJsonStore(self.path)).all(),
                         ["https://1.example/"])


# ── session store ────────────────────────────────────────────────
class TestSessionStore(StoreCase):
    def test_set_then_get(self):  # SES-01
        store = SessionStore(self.atomic)
        store.set(cur_user="Ann")
        self.assertEqual(store.get("cur_user"), "Ann")

    def test_unknown_key_returns_default(self):  # SES-02
        self.assertEqual(SessionStore(self.atomic).get("ghost", default="d"),
                         "d")

    def test_set_merges_keys(self):  # SES-03
        store = SessionStore(self.atomic)
        store.set(a=1)
        store.set(b=2)
        self.assertEqual((store.get("a"), store.get("b")), (1, 2))

    def test_save_false_stays_in_memory_only(self):  # SES-04
        store = SessionStore(self.atomic)
        store.set(save=False, temp=1)
        self.assertEqual(store.get("temp"), 1)
        self.assertIsNone(SessionStore(AtomicJsonStore(self.path))
                          .get("temp"))

    def test_data_is_a_copy(self):  # SES-05
        store = SessionStore(self.atomic)
        store.set(nested={"x": [1]})
        store.data()["nested"]["x"].append(2)
        self.assertEqual(store.get("nested"), {"x": [1]})

    def test_no_expire_api_stale_keys_only_overwritten(self):  # SES-06 (pin)
        store = SessionStore(self.atomic)
        self.assertFalse(hasattr(store, "expire"))
        self.assertFalse(hasattr(store, "clear"))
        store.set(stale=1)
        self.assertEqual(SessionStore(AtomicJsonStore(self.path)).get("stale"),
                         1)

    def test_hostile_keys_and_values_round_trip(self):  # SES-07
        store = SessionStore(self.atomic)
        store.set(**{"ключ 🎉": {"deep": [None, 1]}})
        again = SessionStore(AtomicJsonStore(self.path))
        self.assertEqual(again.get("ключ 🎉"), {"deep": [None, 1]})


# ── settings store ───────────────────────────────────────────────
class TestSettingsStore(StoreCase):
    def test_documented_slices_read_without_keyerror(self):  # SET-01
        store = SettingsStore(self.atomic)
        for keys in (("chrome",), ("scroll",), ("delays",), ("ui",),
                     ("history",), ("collector",)):
            self.assertIsNotNone(store.get(*keys))

    def test_set_deep_merges_with_default_fallback(self):  # SET-02
        store = SettingsStore(self.atomic)
        store.set("ui", "theme", "light")
        self.assertEqual(store.get("ui", "theme"), "light")
        # siblings absent from the file fall back to shipped defaults
        self.assertEqual(store.get("ui", "language"), "ru")

    def test_get_copy_is_deep(self):  # SET-03
        store = SettingsStore(self.atomic)
        store.set("ui", {"theme": "dark"})
        copied = store.get_copy("ui")
        copied["theme"] = "hacked"
        self.assertEqual(store.get("ui", "theme"), "dark")

    def test_data_is_the_persisted_overlay(self):  # SET-04 (SPEC pin)
        store = SettingsStore(self.atomic)
        # data() is what was written, NOT the merged view: get() resolves
        # shipped defaults, data() shows the overlay only.
        self.assertEqual(store.data(), {})
        store.set("ui", "theme", "light")
        self.assertEqual(store.data(), {"ui": {"theme": "light"}})

    def test_validate_passes_on_defaults(self):  # SET-05
        self.assertEqual(SettingsStore(self.atomic).validate(), [])

    def test_validate_flags_a_bad_chrome_port(self):  # SET-06
        store = SettingsStore(self.atomic)
        store.set("chrome", "port", "xx")
        errors = store.validate()
        self.assertTrue(errors)
        self.assertIn("chrome.port", errors[0])

    def test_validate_only_watches_the_port(self):  # SET-06b (SPEC pin)
        store = SettingsStore(self.atomic)
        store.set("ui", "theme", 12345)
        # the shipped validator is deliberately narrow: only chrome.port
        # is checked, anything else passes through silently.
        self.assertEqual(store.validate(), [])

    def test_foreign_sections_are_not_namespaced(self):  # SET-07 (SPEC pin)
        store = SettingsStore(self.atomic)
        store.set("presets", {"x": 1})
        # set() is generic: nothing refuses or namespaces foreign keys.
        # Harmless in practice (PresetStore owns a separate file), pinned
        # so a future namespacing change shows up here first.
        self.assertEqual(store.get("presets"), {"x": 1})

    def test_settings_survive_a_reopen(self):  # SET-08
        # The contract is "memory first, `save()` persists" (the default the
        # ConfigManager facade batches with, AREA B1 design §6.3): a reopen
        # sees the write only once the store was told to put it on disk.
        store = SettingsStore(self.atomic)
        store.set("ui", "theme", "light")
        self.assertEqual(SettingsStore(AtomicJsonStore(self.path))
                         .get("ui", "theme"), "dark", "nothing is on disk yet")
        self.assertTrue(store.save())
        self.assertEqual(SettingsStore(AtomicJsonStore(self.path))
                         .get("ui", "theme"), "light")

    def test_settings_save_flag_writes_immediately(self):  # SET-08b
        store = SettingsStore(self.atomic)
        store.set("ui", "theme", "light", save=True)
        self.assertFalse(store.dirty)
        self.assertEqual(SettingsStore(AtomicJsonStore(self.path))
                         .get("ui", "theme"), "light")


# ── undo store ───────────────────────────────────────────────────
class TestUndoStore(StoreCase):
    def test_fresh_store_is_empty_at_nothing(self):  # UND-01
        self.assertEqual(UndoStore(self.atomic).get(), ([], -1))

    def test_set_round_trip(self):  # UND-02
        store = UndoStore(self.atomic)
        store.set([{"k": 1}, {"k": 2}], 1)
        self.assertEqual(store.get(), ([{"k": 1}, {"k": 2}], 1))

    def test_push_appends_and_points_at_tip(self):  # UND-03
        store = UndoStore(self.atomic)
        res = store.push("people", {"n": 1})
        self.assertTrue(res.is_ok)
        hist, idx = store.get()
        self.assertEqual(len(hist), 1)
        self.assertEqual(idx, 0)
        self.assertEqual(hist[0]["kind"], "people")

    def test_push_after_undo_drops_the_redo_tail(self):  # UND-04
        store = UndoStore(self.atomic)
        store.push("a", 1)
        store.push("b", 2)
        hist, _ = store.get()
        store.set(hist, 0)  # undo once
        store.push("c", 3)
        hist, idx = store.get()
        self.assertEqual([e["kind"] for e in hist], ["a", "c"])
        self.assertEqual(idx, 1)

    def test_out_of_range_index_is_clamped(self):  # UND-05
        store = UndoStore(self.atomic)
        store.set([{"k": 1}, {"k": 2}], 99)
        hist, idx = store.get()
        self.assertEqual((len(hist), idx), (2, 1))
        store.set([{"k": 1}], -5)
        _, idx = store.get()
        self.assertEqual(idx, -1)

    def test_history_is_capped(self):  # UND-05b
        store = UndoStore(self.atomic)
        big = [{"i": i} for i in range(MAX_STACK_HISTORY + 5)]
        store.set(big, len(big) - 1)
        hist, idx = store.get()
        self.assertEqual(len(hist), MAX_STACK_HISTORY)
        self.assertEqual(idx, MAX_STACK_HISTORY - 1)
        self.assertEqual(hist[0], {"i": 5})  # oldest trimmed first

    def test_hostile_values_round_trip(self):  # UND-06
        store = UndoStore(self.atomic)
        store.push("x", {"uni": "🎉", "none": None, "deep": [1, {"a": 2}]})
        again = UndoStore(AtomicJsonStore(self.path))
        hist, idx = again.get()
        self.assertEqual(idx, 0)
        self.assertEqual(hist[0]["value"]["uni"], "🎉")

    def test_undo_state_survives_a_reopen(self):  # UND-07
        store = UndoStore(self.atomic)
        store.set([{"k": 1}], 0)
        self.assertEqual(UndoStore(AtomicJsonStore(self.path)).get(),
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
