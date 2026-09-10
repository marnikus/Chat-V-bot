"""AREA B contracts — small-store unification + god-class decomposition gates.

Design ref: docs/AREA_B_NEW_STRUCTURE.md §7

Run:  python3 -m pytest tests/test_area_b_contracts.py -v

This file is written BEFORE any production edit (TDD).  On the baseline
checkout it has 10+ failures:

  * SessionStore / SettingsStore / LabelsFileStore / PresetStore do not
    accept AtomicJsonStore → TypeError
  * LabelsFileStore has no save() → AttributeError
  * stores/history_repo.py et al. exceed 400 SLOC → structural assertion fails
  * HistoryRepo has 44 public methods (>30) → structural assertion fails

After B1+B2 they all pass, and no other test in the suite regresses.
"""

import inspect
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from stores.atomic import AtomicJsonStore  # noqa: E402


def _tmp():
    return tempfile.mkdtemp()


# ── B1: small-store constructor unification ──────────────────────
class TestSessionStoreAtomicPath(unittest.TestCase):
    def test_accepts_atomic(self):
        from stores.session_store import SessionStore
        d = _tmp()
        path = os.path.join(d, "session.json")
        atomic = AtomicJsonStore(path)
        store = SessionStore(atomic)  # must not raise
        store.set(cur_user="Ann")
        self.assertEqual(store.get("cur_user"), "Ann")
        # persisted?
        self.assertTrue(store.save() or os.path.exists(path))
        again = SessionStore(AtomicJsonStore(path))
        self.assertEqual(again.get("cur_user"), "Ann")

    def test_accepts_plain_string_positional(self):
        from stores.session_store import SessionStore
        d = _tmp()
        path = os.path.join(d, "session.json")
        store = SessionStore(path)
        store.set(a=1)
        self.assertEqual(store.get("a"), 1)

    def test_accepts_path_keyword(self):
        from stores.session_store import SessionStore
        d = _tmp()
        path = os.path.join(d, "session.json")
        store = SessionStore(path=path)
        store.set(b=2)
        self.assertEqual(store.get("b"), 2)

    def test_save_persists_and_reopen_sees_it(self):
        from stores.session_store import SessionStore
        d = _tmp()
        path = os.path.join(d, "session.json")
        store = SessionStore(AtomicJsonStore(path))
        store.set(save_now=False, temp=99)
        # not yet on disk if save_now=False
        # but save() must flush
        self.assertTrue(store.save())
        again = SessionStore(path)
        self.assertEqual(again.get("temp"), 99)

    def test_has_save_method(self):
        from stores.session_store import SessionStore
        self.assertTrue(hasattr(SessionStore(AtomicJsonStore(os.path.join(_tmp(), "x.json"))), "save"))
        self.assertTrue(callable(getattr(SessionStore, "save", None)))


class TestSettingsStoreAtomicPath(unittest.TestCase):
    def test_accepts_atomic(self):
        from stores.settings_store import SettingsStore
        d = _tmp()
        path = os.path.join(d, "settings.json")
        atomic = AtomicJsonStore(path)
        store = SettingsStore(atomic)
        store.set("ui", "theme", "light")
        self.assertEqual(store.get("ui", "theme"), "light")

    def test_accepts_plain_string(self):
        from stores.settings_store import SettingsStore
        d = _tmp()
        path = os.path.join(d, "settings.json")
        store = SettingsStore(path)
        store.set("ui", "theme", "dark")
        self.assertEqual(store.get("ui", "theme"), "dark")

    def test_save_and_reopen(self):
        from stores.settings_store import SettingsStore
        d = _tmp()
        path = os.path.join(d, "settings.json")
        store = SettingsStore(AtomicJsonStore(path))
        store.set("ui", "theme", "light")
        store.save()
        again = SettingsStore(path)
        self.assertEqual(again.get("ui", "theme"), "light")

    def test_validate_still_works(self):
        from stores.settings_store import SettingsStore
        d = _tmp()
        path = os.path.join(d, "settings.json")
        store = SettingsStore(AtomicJsonStore(path))
        self.assertEqual(store.validate(), [])
        store.set("chrome", "port", "xx")
        self.assertTrue(store.validate())


class TestLabelsFileStoreAtomicPath(unittest.TestCase):
    def test_accepts_atomic(self):
        from stores.labels_file_store import LabelsFileStore
        d = _tmp()
        path = os.path.join(d, "labels.json")
        atomic = AtomicJsonStore(path)
        store = LabelsFileStore(atomic)
        payload = {"defs": [], "assign": {}, "filter": {"include": [], "exclude": []}, "next_id": 1}
        store.set_data(payload)
        self.assertTrue(store.dirty)
        # save() must exist and be alias of flush()
        self.assertTrue(hasattr(store, "save"))
        self.assertTrue(store.save())
        again = LabelsFileStore(path)
        self.assertEqual(again.data(), payload)

    def test_accepts_plain_string(self):
        from stores.labels_file_store import LabelsFileStore
        d = _tmp()
        path = os.path.join(d, "labels.json")
        store = LabelsFileStore(path)
        store.set_data({"defs": [], "assign": {}, "filter": {}, "next_id": 0})
        self.assertTrue(store.flush())
        self.assertEqual(LabelsFileStore(path).data()["next_id"], 0)

    def test_save_is_alias_of_flush(self):
        from stores.labels_file_store import LabelsFileStore
        d = _tmp()
        path = os.path.join(d, "labels.json")
        store = LabelsFileStore(path)
        # both must exist and behave the same
        self.assertTrue(hasattr(store, "save"))
        self.assertTrue(hasattr(store, "flush"))
        store.set_data({"defs": [{"id": "lbl_1", "name": "R"}], "assign": {}, "filter": {}, "next_id": 1})
        # save should clear dirty like flush
        store.save()
        self.assertFalse(store.dirty)


class TestPresetStoreAtomicPath(unittest.TestCase):
    def setUp(self):
        from stores.preset_store import PresetStore
        PresetStore._by_path.clear()

    def tearDown(self):
        from stores.preset_store import PresetStore
        PresetStore._by_path.clear()

    def test_accepts_atomic(self):
        from stores.preset_store import PresetStore
        d = _tmp()
        path = os.path.join(d, "presets.json")
        atomic = AtomicJsonStore(path)
        store = PresetStore(atomic)
        store.save_stack("s1", [{"block_id": "PAUSE"}])
        self.assertEqual(store.load_stack("s1"), [{"block_id": "PAUSE"}])
        # reopen via string path must see same data (cache key = abspath)
        again = PresetStore(path=path)
        self.assertEqual(again.load_stack("s1"), [{"block_id": "PAUSE"}])

    def test_accepts_string_as_first_arg(self):
        from stores.preset_store import PresetStore
        d = _tmp()
        path = os.path.join(d, "presets.json")
        store = PresetStore(path)  # string as config param
        store.save_stack("s2", [])
        self.assertIsNotNone(store.load_stack("s2"))

    def test_has_save(self):
        from stores.preset_store import PresetStore
        d = _tmp()
        path = os.path.join(d, "presets.json")
        store = PresetStore(path=path)
        self.assertTrue(hasattr(store, "save"))
        self.assertTrue(callable(getattr(store, "save")))


# ── structural gates (B2) ────────────────────────────────────────
class TestStructuralSloc(unittest.TestCase):
    """No file in stores/ over 400 SLOC; HistoryRepo under 30 public methods.

    Before B2 this fails (history_repo 1070, media_store 664, history_db 605,
    label_store 472). After B2 it passes — each facade is <400 and helpers
    are <400.

    This test is the executable form of FOUR_AREA_PLAN §6.2 exit criterion #2.
    """

    def _sloc(self, path: str) -> int:
        # SLOC = non-blank, non-comment lines (same as metrics.py)
        count = 0
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                stripped = line.strip()
                if not stripped:
                    continue
                if stripped.startswith("#"):
                    continue
                count += 1
        return count

    def test_no_file_over_400_sloc(self):
        stores_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "stores")
        over = []
        for fname in os.listdir(stores_dir):
            if not fname.endswith(".py"):
                continue
            # helpers are allowed to be under 400 too — this checks all files
            fpath = os.path.join(stores_dir, fname)
            sloc = self._sloc(fpath)
            if sloc > 400:
                over.append((fname, sloc))
        self.assertEqual(over, [], f"files over 400 SLOC: {over} — split them per docs/AREA_B_NEW_STRUCTURE.md §5")

    def test_history_repo_under_30_public_methods(self):
        from stores.history_repo import HistoryRepo
        # count public methods (not _private, not dunder)
        methods = [m for m, _ in inspect.getmembers(HistoryRepo, predicate=inspect.isfunction) if not m.startswith("_")]
        # also count async def as function in py3.11 inspect
        # include methods defined as async too (inspect.isfunction covers them)
        # also check for coroutine detection
        self.assertLess(len(methods), 30, f"HistoryRepo has {len(methods)} public methods: {methods} — extract collaborators per §5.1")

    def test_label_store_helpers_exist(self):
        # after B2, helper modules must exist
        base = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "stores")
        expected = ["_history_repo_alignment.py", "_history_repo_writer.py",
                    "_history_repo_recovery.py", "_history_repo_person.py",
                    "_history_db_schema.py", "_media_fetch.py", "_media_cache.py",
                    "_label_defs.py", "_label_assign.py", "_label_filter.py"]
        missing = [f for f in expected if not os.path.exists(os.path.join(base, f))]
        # Before B2, this will list many missing — expected failure before refactor
        self.assertEqual(missing, [], f"missing helper modules (B2 not yet done): {missing}")

    def test_public_imports_still_work(self):
        # byte-identical public import paths must survive the split
        from stores.history_repo import HistoryRepo, align_batch, resolve_days  # noqa: F401
        from stores.history_db import HistoryDB  # noqa: F401
        from stores.media_store import MediaStore, slugify_nick, infer_kind  # noqa: F401
        from stores.label_store import LabelStore  # noqa: F401
        from stores.user_memory import UserMemory  # noqa: F401
        from stores.preset_store import PresetStore  # noqa: F401
        # if any import fails, B2 broke the public surface


if __name__ == "__main__":
    unittest.main()
