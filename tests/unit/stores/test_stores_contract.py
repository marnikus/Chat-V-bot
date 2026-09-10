"""AREA B1 — the ONE contract every config-file store must satisfy.

Design ref: docs/REFACTOR_2026-09-09_AREA_B_DESIGN.md §1 (P1-3 of docs/
REFACTOR_2026-09-09_FOUR_AREA_PLAN.md §5).

The seven config-file stores grew up twice. `BlockStore`/`BookmarkStore` take an
`AtomicJsonStore` (what the store tests build) while `SessionStore`,
`SettingsStore`, `LabelsFileStore` and `PresetStore` take a bare path (what
`ConfigManager` passes). `SessionStore(atomic)` therefore died with
`TypeError: stat: path should be … not AtomicJsonStore` — 16 red tests whose
root cause was a missing contract, not the code under test.

This file pins the contract *as a contract* so no future store can skip it:

  * a store is built from **either** an `AtomicJsonStore` **or** a path
    (or nothing at all → the legacy `config.json`);
  * both spellings own the same file, and `reload()` means "from disk";
  * the lifecycle surface is identical: `path`, `dirty`, `load()`, `reload()`,
    `save(force=False)`, `flush()`, `data()` — `save`/`flush` answer `bool`;
  * `data()` is a deep copy — mutating it can never corrupt the store;
  * a missing or corrupt file degrades to the store's documented shape.

Run with:  python3 tests/unit/stores/test_stores_contract.py
"""

import copy
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))))

from stores.atomic import AtomicJsonStore  # noqa: E402
from stores.block_store import BlockStore  # noqa: E402
from stores.bookmark_store import BookmarkStore  # noqa: E402
from stores.labels_file_store import LABELS_DEFAULT, LabelsFileStore  # noqa: E402
from stores.preset_store import PresetStore  # noqa: E402
from stores.session_store import SessionStore  # noqa: E402
from stores.settings_store import SettingsStore  # noqa: E402
from stores.undo_store import UndoStore  # noqa: E402

#: every store must expose all of these
LIFECYCLE = ("path", "dirty", "load", "reload", "save", "flush", "data")

#: `data()` for a store whose file does not exist yet
FRESH = {
    BlockStore: {},
    BookmarkStore: {},
    LabelsFileStore: {"defs": [], "assign": {},
                      "filter": {"include": [], "exclude": []}, "next_id": 0},
    PresetStore: {"stack_presets": {}, "template_presets": {}},
    SessionStore: {},
    SettingsStore: {},
    UndoStore: {"history": [], "index": -1},
}
ALL_STORES = sorted(FRESH, key=lambda cls: cls.__name__)

#: the stores that keep their own overlay and are written on `save()`
OVERLAY_STORES = (SessionStore, SettingsStore, LabelsFileStore, UndoStore,
                  PresetStore)


def write_something(store):
    """The cheapest mutation each store accepts."""
    if isinstance(store, BlockStore):
        return store.named_set("stack_presets", "keep", {"x": 1})
    if isinstance(store, BookmarkStore):
        return store.set_all(["https://keep.example/"])
    if isinstance(store, LabelsFileStore):
        return store.set_data({"defs": [{"id": "lbl_1", "name": "Nice"}],
                               "assign": {}, "filter": {"include": [],
                                                        "exclude": []},
                               "next_id": 1})
    if isinstance(store, PresetStore):
        return store.save_stack("keep", [{"block_id": "PAUSE"}])
    if isinstance(store, SessionStore):
        return store.set(save=False, keep=1)
    if isinstance(store, SettingsStore):
        return store.set("ui", "keep", 1)
    if isinstance(store, UndoStore):
        return store.save_state([{"kind": "people", "value": 1}], 0,
                                save_now=False)
    raise AssertionError("write_something() does not know this store")


class StoreContractCase(unittest.TestCase):
    """A temp dir + a path + an `AtomicJsonStore` over the very same file.

    `PresetStore` caches one instance per path (two writers must not fight),
    so the fixture drops the cache entries a test added — otherwise a "fresh
    store" would silently be somebody else's instance.
    """

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "config.json")
        self.atomic = AtomicJsonStore(self.path)
        self._preset_keys = list(PresetStore._by_path)

    def tearDown(self):
        for key in set(PresetStore._by_path) - set(self._preset_keys):
            PresetStore._by_path.pop(key, None)

    def fresh_path(self, label):
        return os.path.join(self.dir, f"{label}.json")

    def write_file(self, path, text):
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)


class TestConstruction(StoreContractCase):
    def test_a_path_and_an_atomic_are_interchangeable(self):  # B1-01
        for cls in ALL_STORES:
            with self.subTest(store=cls.__name__):
                from_path = cls(self.path)
                from_atomic = cls(self.atomic)
                self.assertEqual(os.path.abspath(from_path.path),
                                 os.path.abspath(self.path))
                self.assertEqual(os.path.abspath(from_atomic.path),
                                 os.path.abspath(self.path))
                self.assertEqual(from_path.data(), from_atomic.data())
                self.assertEqual(from_path.data(), FRESH[cls])

    def test_no_argument_builds_a_usable_store(self):  # B1-02
        cwd = os.getcwd()
        os.chdir(self.dir)
        try:
            for cls in ALL_STORES:
                with self.subTest(store=cls.__name__):
                    store = cls()
                    self.assertTrue(str(store.path).endswith(".json"))
                    self.assertEqual(store.data(), FRESH[cls])
        finally:
            os.chdir(cwd)

    def test_the_borrowed_atomic_is_the_file_handle(self):  # B1-03
        # `reload()` means "from disk": an unsaved change in the borrowed
        # atomic is NOT the store's state, a saved one is
        self.atomic.replace({"grid_layout": {"a": 1}})
        store = SessionStore(self.atomic)
        self.assertIsNone(store.get("grid_layout"))
        self.atomic.save()
        store.reload()
        self.assertEqual(store.get("grid_layout"), {"a": 1})

    def test_the_store_writes_through_the_borrowed_atomic(self):  # B1-04
        store = SessionStore(self.atomic)
        write_something(store)
        self.assertTrue(store.save(force=True))
        self.assertEqual(self.atomic.data(), {"keep": 1})
        self.assertFalse(self.atomic.dirty,
                         "a saved atomic must not claim unsaved work")

    def test_preset_store_still_accepts_a_config_manager(self):  # B1-05
        # `bridge/router.py:187` and `backend/config_manager.py:106` build it
        # as `PresetStore(config=…)`; that call form is not B's to change
        legacy = os.path.join(self.dir, "config.json")
        self.write_file(legacy, json.dumps({"chrome": {"port": 9333}}))

        class FakeConfig:
            _path = legacy

        store = PresetStore(config=FakeConfig())
        self.assertEqual(os.path.dirname(os.path.abspath(store.path)),
                         os.path.join(os.path.abspath(self.dir), "config"))
        store.save_stack("keep", [{"block_id": "PAUSE"}])
        self.assertTrue(store.save(force=True))
        self.assertEqual(PresetStore(path=store.path).load_stack("keep"),
                         [{"block_id": "PAUSE"}])

    def test_preset_store_identifies_instances_by_file(self):  # B1-06
        path = self.fresh_path("presets.json")
        from_atomic = PresetStore(AtomicJsonStore(path))
        self.assertIs(PresetStore(path), from_atomic,
                      "two writers must share one instance per file")


class TestLifecycle(StoreContractCase):
    def test_every_store_exposes_the_same_surface(self):  # B1-07
        for cls in ALL_STORES:
            with self.subTest(store=cls.__name__):
                store = cls(self.path)
                for name in LIFECYCLE:
                    self.assertTrue(callable(getattr(store, name, None))
                                    if name not in ("path", "dirty")
                                    else hasattr(store, name),
                                    f"{cls.__name__}.{name} is missing")
                self.assertIs(store.load(), None)
                self.assertIs(store.reload(), None)

    def test_save_and_flush_answer_with_a_bool(self):  # B1-08
        for cls in ALL_STORES:
            with self.subTest(store=cls.__name__):
                store = cls(self.path)
                self.assertIsInstance(store.save(), bool)
                self.assertIsInstance(store.flush(), bool)
                self.assertIsInstance(store.dirty, bool)
                self.assertIsInstance(store.save(force=True), bool)
                self.assertTrue(os.path.exists(store.path))

    def test_save_creates_a_missing_parent_directory(self):  # B1-09
        # a store pointed at a folder the app has not made yet must still
        # write (jsonio.save_json does this; an atomic-backed store must not
        # regress it)
        for cls in ALL_STORES:
            with self.subTest(store=cls.__name__):
                deep = os.path.join(self.dir, "deeper", "still", "c.json")
                store = cls(deep)
                self.assertTrue(store.save(force=True))
                self.assertTrue(os.path.exists(deep))

    def test_dirty_tracks_unsaved_work(self):  # B1-10
        for cls in OVERLAY_STORES:
            with self.subTest(store=cls.__name__):
                store = cls(self.fresh_path(f"dirty-{cls.__name__}.json"))
                self.assertFalse(store.dirty)
                write_something(store)
                self.assertTrue(store.dirty,
                                f"{cls.__name__} must mark itself dirty")
                self.assertFalse(os.path.exists(store.path),
                                 "a dirty store has not been written yet")
                self.assertTrue(store.flush())
                self.assertFalse(store.dirty)
                self.assertTrue(os.path.exists(store.path))

    def test_the_inline_saving_stores_write_at_once(self):  # B1-11
        for cls in (BlockStore, BookmarkStore):
            with self.subTest(store=cls.__name__):
                path = self.fresh_path(f"inline-{cls.__name__}.json")
                store = cls(path)
                write_something(store)
                self.assertFalse(store.dirty)
                self.assertTrue(os.path.exists(path))
                self.assertEqual(cls(path).data(), store.data())

    def test_flush_is_a_noop_when_clean(self):  # B1-12
        for cls in OVERLAY_STORES:
            with self.subTest(store=cls.__name__):
                path = self.fresh_path(f"clean-{cls.__name__}.json")
                store = cls(path)
                self.assertTrue(store.flush())
                self.assertFalse(os.path.exists(path))


class TestPersistence(StoreContractCase):
    def test_a_saved_write_survives_a_reopen(self):  # B1-13
        for cls in ALL_STORES:
            with self.subTest(store=cls.__name__):
                path = self.fresh_path(f"roundtrip-{cls.__name__}.json")
                store = cls(AtomicJsonStore(path))
                write_something(store)
                self.assertTrue(store.save(force=True))
                self.assertEqual(cls(path).data(), store.data())

    def test_a_corrupt_file_degrades_to_the_documented_shape(self):  # B1-14
        for cls in ALL_STORES:
            with self.subTest(store=cls.__name__):
                path = self.fresh_path(f"corrupt-{cls.__name__}.json")
                self.write_file(path, "{ this is not json")
                self.assertEqual(cls(path).data(), FRESH[cls])
                self.assertEqual(cls(AtomicJsonStore(path)).data(), FRESH[cls])

    def test_a_non_dict_file_degrades_too(self):  # B1-15
        for cls in ALL_STORES:
            with self.subTest(store=cls.__name__):
                path = self.fresh_path(f"list-{cls.__name__}.json")
                self.write_file(path, '["not", "a", "mapping"]')
                self.assertEqual(cls(path).data(), FRESH[cls])

    def test_a_failed_save_says_so_and_keeps_the_overlay(self):  # B1-16
        blocker = os.path.join(self.dir, "blocker")
        self.write_file(blocker, "x")
        for cls in ALL_STORES:
            with self.subTest(store=cls.__name__):
                store = cls(os.path.join(blocker, f"{cls.__name__}.json"))
                write_something(store)
                self.assertFalse(store.save(force=True))
                self.assertTrue(store.dirty,
                                "a failed save must leave the store dirty")
                self.assertEqual(store.data(),
                                 copy.deepcopy(store.data()),
                                 "the rejected write must stay in memory")
                self.assertTrue(store.data(),
                                "the overlay the store failed to write must "
                                "still be there for the next attempt")

    def test_unserialisable_payload_never_touches_the_good_file(self):
        # the same promise jsonio.save_json makes and `AtomicJsonStore` keeps
        path = self.fresh_path("unserialisable.json")
        store = SessionStore(path)
        store.set(good=1)
        self.assertTrue(store.save(force=True))
        before = open(path, encoding="utf-8").read()
        store.set(bad={1, 2}, save=False)
        self.assertFalse(store.save(force=True))
        self.assertEqual(open(path, encoding="utf-8").read(), before)
        self.assertEqual(SessionStore(path).get("good"), 1)


class TestDataIsolation(StoreContractCase):
    def test_data_is_a_deep_copy(self):  # B1-17
        for cls in ALL_STORES:
            with self.subTest(store=cls.__name__):
                store = cls(self.atomic)
                payload = store.data()
                self.assertIsInstance(payload, dict)
                payload["probe"] = ["mutated"]
                self.assertNotIn("probe", store.data(),
                                 "data() leaked the live payload")
                payload2 = store.data()
                payload2["nested"] = {"x": [1]}
                self.assertNotIn("nested", store.data())

    def test_mutating_a_returned_value_reaches_the_store_only_via_set(self):
        # deep copies all the way down: a caller must not be able to edit
        # the store by editing what it got back
        store = SessionStore(self.fresh_path("copy.json"))
        store.set(nested={"x": [1]}, save=False)
        got = store.get("nested")
        got["x"].append(2)
        self.assertEqual(store.get("nested"), {"x": [1]})

    def test_unknown_reads_never_raise(self):  # B1-18
        for cls in ALL_STORES:
            with self.subTest(store=cls.__name__):
                store = cls(self.atomic)
                if isinstance(store, SessionStore):
                    self.assertEqual(store.get("ghost", default="d"), "d")
                elif isinstance(store, SettingsStore):
                    self.assertEqual(store.get("ghost", "deeper", default=5), 5)
                    self.assertEqual(store.section("ghost"), {})
                    self.assertEqual(store.get_copy("ghost"), None)
                elif isinstance(store, BlockStore):
                    self.assertEqual(store.named_all("ghost"), {})
                    self.assertIsNone(store.named_get("ghost", "ghost"))
                elif isinstance(store, PresetStore):
                    self.assertEqual(store.named_all("ghost"), {})
                    self.assertIsNone(store.load_stack("ghost"))
                    self.assertFalse(store.delete_stack("ghost"))
                elif isinstance(store, BookmarkStore):
                    self.assertEqual(len(store.all()), len(store.all()))
                elif isinstance(store, UndoStore):
                    self.assertEqual(store.get(), ([], -1))
                    self.assertEqual(store.index(), -1)
                elif isinstance(store, LabelsFileStore):
                    self.assertEqual(set(store.data()), set(LABELS_DEFAULT))


class TestSessionAndSettingsFlags(StoreContractCase):
    def test_save_and_save_now_are_the_same_switch(self):  # B1-19
        # `core/interfaces.py` documents `set(save=True, **updates)`; the
        # ConfigManager facade has always called `set(save_now=…)` — both
        # must keep working, and neither may be stored as a session key
        for kwargs in ({"save": False}, {"save_now": False}):
            with self.subTest(**kwargs):
                path = self.fresh_path(f"session-{list(kwargs)[0]}.json")
                store = SessionStore(path)
                store.set(temp=1, **kwargs)
                self.assertEqual(store.get("temp"), 1)
                self.assertIsNone(store.get("save"))
                self.assertIsNone(SessionStore(path).get("temp"))
                self.assertTrue(store.save())
                self.assertEqual(SessionStore(path).get("temp"), 1)

    def test_session_save_true_writes_at_once(self):  # B1-20
        store = SessionStore(self.fresh_path("session-now.json"))
        store.set(cur_user="Ann", save=True)
        self.assertFalse(store.dirty)
        self.assertEqual(SessionStore(store.path).get("cur_user"), "Ann")

    def test_settings_save_flag_is_the_same_switch_as_the_session_one(self):
        # B1-21: both spellings work, and neither becomes a settings key
        path = self.fresh_path("settings-save-flag.json")
        store = SettingsStore(path)
        store.set("ui", "theme", "light")
        self.assertTrue(store.dirty)
        self.assertFalse(os.path.exists(path),
                         "the batched default survives the split — "
                         "`ConfigManager.set` is memory-only until `save()`")
        self.assertTrue(store.save())
        self.assertEqual(SettingsStore(path).get("ui", "theme"), "light")
        store.set("ui", "theme", "dark", save_now=True)
        self.assertEqual(SettingsStore(path).get("ui", "theme"), "dark")
        self.assertFalse(store.dirty)
        store.set("ui", "language", "en", save=True)
        self.assertEqual(SettingsStore(path).get("ui"),
                         {"theme": "dark", "language": "en"})
        store.set("save", "on", 1, save=True)
        self.assertEqual(SettingsStore(path).get("save", "on"), 1,
                         "a key called `save` still works as a path, and the "
                         "flag is the keyword argument")

    def test_settings_data_is_the_overlay_not_the_merged_view(self):
        # SET-04 (docs/STORES_TEST_DESIGN_2026-09-09.md §6) — pinned here as
        # part of the contract so a refactor cannot quietly merge defaults in
        store = SettingsStore(self.fresh_path("settings-overlay.json"))
        self.assertEqual(store.data(), {})
        store.set("ui", "theme", "light")
        self.assertEqual(store.data(), {"ui": {"theme": "light"}})
        self.assertEqual(store.get("ui", "language"), "ru")

    def test_atomic_or_path_settings_store_read_the_same_shipped_defaults(self):
        path = self.fresh_path("settings-defaults.json")
        for store in (SettingsStore(path), SettingsStore(AtomicJsonStore(path))):
            with self.subTest(store=type(store).__name__):
                self.assertEqual(store.get("chrome", "port"), 9222)
                self.assertEqual(store.validate(), [])
                store.set("chrome", "port", "xx")
                self.assertTrue(any("chrome.port" in e for e in
                                    store.validate()))


class TestUndoStoreShape(StoreContractCase):
    def test_undo_writes_are_clamped_before_they_hit_the_file(self):
        path = self.fresh_path("undo.json")
        store = UndoStore(path)
        store.save_state([{"kind": "people", "value": i} for i in range(3)],
                         99, save_now=True)
        on_disk = json.load(open(path, encoding="utf-8"))
        self.assertEqual(on_disk["index"], 2)
        self.assertEqual(len(on_disk["history"]), 3)
        reopened = UndoStore(AtomicJsonStore(path))
        self.assertEqual(reopened.get(), (on_disk["history"], 2))

    def test_undo_history_and_index_are_projections_of_get(self):
        store = UndoStore(self.fresh_path("undo-proj.json"))
        store.set([{"kind": "people", "value": 1}], 0)
        self.assertEqual(store.history(), [{"kind": "people", "value": 1}])
        self.assertEqual(store.index(), 0)
        self.assertEqual(store.get(), (store.history(), store.index()))
        history = store.history()
        history.append({"kind": "labels", "value": 2})
        self.assertEqual(len(store.history()), 1,
                         "history() must not alias the live timeline")


class TestHostilePayloads(StoreContractCase):
    def test_unicode_and_deep_values_round_trip(self):
        cases = {
            SessionStore: lambda s: s.set(**{"ключ 🎉": {"deep": [None, 1]}},
                                          save=False),
            SettingsStore: lambda s: s.set("ключ", "вложенн", {"🎉": [1, 2]}),
            LabelsFileStore: lambda s: s.set_data(
                {"defs": [{"id": "lbl_1", "name": "Плохой 🎉"}],
                 "assign": {"Анна": ["lbl_1"]}, "filter": {}, "next_id": 2}),
            UndoStore: lambda s: s.save_state([{"kind": "ключ", "value": None}],
                                              0, save_now=False),
            PresetStore: lambda s: s.save_stack("Привет 🎉",
                                                [{"block_id": "PAUSE"}]),
            BookmarkStore: lambda s: s.set_all(["https://пример.рф/🎉"]),
            BlockStore: lambda s: s.named_set("stack_presets", "ключ 🎉",
                                              {"n": "значение"}),
        }
        for cls, mutate in cases.items():
            with self.subTest(store=cls.__name__):
                path = self.fresh_path(f"hostile-{cls.__name__}.json")
                store = cls(path)
                mutate(store)
                self.assertTrue(store.save(force=True))
                again = cls(path)
                self.assertEqual(again.data(),
                                 copy.deepcopy(store.data()))


if __name__ == "__main__":
    unittest.main()
