"""Backend persistence shims — one canonical implementation in stores/.

Design ref: docs/BLOCKERS_FIX_DESIGN_2026-09-09.md §2 (SHM-01–06).

`backend/history_db.py` etc. are re-export shims over `stores/` (BUG-02:
the <150-LOC regroup split lost the schema constants block). These tests
pin the single-source direction; the healed suites (19 modules) are the
real behavioral coverage.

Run with:  python3 tests/test_backend_shims.py
"""

import os
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import backend.history_db as b_db  # noqa: E402
import backend.history_models as b_models  # noqa: E402
import backend.history_repo as b_repo  # noqa: E402
import backend.label_store as b_labels  # noqa: E402
import backend.media_store as b_media  # noqa: E402
import backend.user_memory as b_memory  # noqa: E402
import stores.history_db as s_db  # noqa: E402
import stores.history_models as s_models  # noqa: E402
import stores.history_repo as s_repo  # noqa: E402
import stores.label_store as s_labels  # noqa: E402
import stores.media_store as s_media  # noqa: E402
import stores.user_memory as s_memory  # noqa: E402


PAIRS = [
    (b_db, s_db),
    (b_repo, s_repo),
    (b_models, s_models),
    (b_media, s_media),
    (b_labels, s_labels),
    (b_memory, s_memory),
]


class TestShimIdentity(unittest.TestCase):
    def test_shim_names_are_the_stores_objects(self):  # SHM-01
        for back, canon in PAIRS:
            self.assertTrue(back.__all__, back.__name__)
            for name in back.__all__:
                self.assertIs(getattr(back, name), getattr(canon, name),
                              f"{back.__name__}.{name} is not "
                              f"{canon.__name__}.{name}")

    def test_every_exported_name_is_importable(self):  # SHM-02
        import importlib
        for back, _canon in PAIRS:
            mod = importlib.import_module(back.__name__)
            for name in mod.__all__:
                self.assertTrue(hasattr(mod, name), name)

    def test_split_debris_is_gone(self):  # SHM-03
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for debris in ("backend/history_db_parts",
                       "backend/history_repo_parts"):
            self.assertFalse(os.path.exists(os.path.join(root, debris)),
                             f"{debris} still on disk")

    def test_private_schema_is_reexported(self):  # SHM-06
        # tests/test_db_migration.py imports _SCHEMA from backend.user_memory
        self.assertIs(b_memory._SCHEMA, s_memory._SCHEMA)


class TestShimBehavior(unittest.TestCase):
    def test_history_db_inits_through_the_shim(self):  # SHM-04
        import asyncio

        async def go():
            path = os.path.join(tempfile.mkdtemp(), "shim.db")
            db = b_db.HistoryDB(path)
            await db.init()
            await db.close()
            return path

        path = asyncio.run(go())
        conn = sqlite3.connect(path)
        try:
            tables = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
        finally:
            conn.close()
        for table in b_db.TABLE_ORDER:
            self.assertIn(table, tables)

    def test_previously_red_importers_import(self):  # SHM-05
        import importlib
        importlib.import_module("backend.history_query")
        importlib.import_module("backend.chat_parser")
        try:
            importlib.import_module("actions.collect_history")
        except ImportError as exc:
            self.skipTest(f"actions chain needs third-party modules: {exc}")


if __name__ == "__main__":
    unittest.main()
